"""Find out how the SmartHomeSec/Vesta panel/mode endpoint treats the PIN.

WHY THIS EXISTS
---------------
PR #20 proposed renaming the arming payload's PIN field from `pincode` to
`pin`, because on one contributor's panel `pincode` returned HTTP 400 while
`pin` was accepted. Both panels are on portal.vestasecurity.eu, so the usual
"different tenant" explanation does not apply.

Then a deliberate wrong-PIN arm on 2026-09-22 measured this:

    pincode=<correct>  ->  HTTP 200 {"result":true,"code":"000"}  -> panel armed
    pincode=<wrong>    ->  HTTP 400                               -> nothing

So THE SERVER VALIDATES THE PIN, and it reports a bad one as a 400 - unlike
every other logical failure in this API, which comes back as HTTP 200 with a
`code` other than "000". That inverts the obvious reading of a 400 and raises
the question this probe is built to answer:

    If the server validates `pincode`, what does it do when `pincode` is
    ABSENT - because that is exactly what renaming the field to `pin` does?

If an arm with no `pincode` succeeds, then `pin` is not "the correct spelling".
It is an unrecognised field, and the rename works by BYPASSING THE PIN CHECK.
That would be a security regression, not a fix, and it must not be merged.

WHAT IT DOES
------------
One login, then a short matrix of arm attempts, disarming after each one that
actually arms, and restoring the mode it found at the start:

    A  pincode=<correct>              baseline - the integration's behaviour
    B  pin=<correct>                  is `pin` accepted at all?
    C  pin + pincode, both correct    is a both-keys fallback viable?
    D  (no PIN field whatsoever)      does it arm with NO pin?  <- the key test
    E  pin=<wrong>                    if this ARMS, `pin` is ignored entirely

Then phase 2, which is where the security weight actually sits, because
arming without a code is normal on many panels but disarming without one is
not. Each starts by arming with the correct PIN:

    F  DISARM with no PIN field       can the alarm be switched OFF with no code?
    G  DISARM with a wrong pincode    same, with a wrong code rather than none

Your PIN is read interactively (getpass), sent ONLY to the alarm host over
HTTPS, and is never printed or written to --out.

    py mode_probe.py --user YOUR_ACCOUNT
    py mode_probe.py --user YOUR_ACCOUNT --dry-run       # show payloads, send nothing
    py mode_probe.py --user YOUR_ACCOUNT --skip-wrong-pin
    py mode_probe.py --user YOUR_ACCOUNT --skip-disarm-test
    py mode_probe.py --user YOUR_ACCOUNT --out result.txt

READ BEFORE RUNNING - THIS ARMS YOUR ALARM FOR REAL
---------------------------------------------------
  * Every successful step ARMS THE PANEL and then disarms it. Each transition
    emits a Contact ID open/close record to your alarm company's receiving
    centre. They are not alarms, but they are visible on your account. Tell
    them first if that matters.
  * Step E sends a deliberately WRONG PIN. Login is rate-limited per source IP
    (~3 failures -> 5 minute lockout); whether panel/mode shares that counter
    is unmeasured. The probe sends at most one wrong PIN, and --skip-wrong-pin
    leaves it out.
  * The probe restores the mode it found at startup. If it is interrupted
    partway, CHECK YOUR PANEL - it may be left armed.

Requirements: Python 3.7+, standard library only. Nothing to install.
"""

import argparse
import getpass
import hashlib
import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_HOST = "portal.vestasecurity.eu"
BASEPATH = "REST/v2"
WRONG_PIN = "1111"
POLL_EVERY = 1.0      # seconds between panel/cycle reads while waiting
POLL_TIMEOUT = 20.0   # give up waiting for a mode change after this


def _open(req, timeout=20):
    """Send a request and return (status, body-text), body included on errors.

    Reading the body on a failure status is the entire point - the integration
    itself threw it away until 0.1.19, which is why PR #20 went a month on a
    bare `<Response [400]>`.
    """
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as res:
            return res.status, res.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as ex:
        return ex.code, ex.read().decode("utf-8", "replace")


def _auth_headers(token, userid):
    return {
        "cookie": "isPrivacy=1; api_token=%s; id=%s; cookiePath=%%2FByDemes%%2F0%%2F0%%2F"
        % (token, userid),
        "token": token or "",
    }


# Credentials for re-login, filled in by main(). The token has a ~5 minute
# server-side TTL and this probe runs longer than that, so any call can meet a
# 401 halfway through - including the restore in the finally block, which is
# the one that puts the alarm back the way it was found. Failing that silently
# leaves a panel armed, so every call re-authenticates once and retries.
SESSION = {}


def _relogin():
    if not SESSION:
        return False
    SESSION["token"], SESSION["userid"] = login(
        SESSION["host"], SESSION["user"], SESSION["password"]
    )
    print("      (token had expired - logged in again)")
    return True


def _post(host, path, token, userid, fields, _retry=True):
    """Form-encoded POST, framed exactly like the integration's _rest_call_post."""
    token = SESSION.get("token", token)
    userid = SESSION.get("userid", userid)
    url = "https://%s/%s/%s?_=%d" % (host, BASEPATH, path, round(time.time() * 1000))
    headers = _auth_headers(token, userid)
    headers["content-type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(fields).encode(), headers=headers, method="POST"
    )
    status, text = _open(req)
    if status == 401 and _retry and _relogin():
        return _post(host, path, None, None, fields, _retry=False)
    return status, text


def _get(host, path, token, userid, _retry=True):
    token = SESSION.get("token", token)
    userid = SESSION.get("userid", userid)
    url = "https://%s/%s/%s?_=%d" % (host, BASEPATH, path, round(time.time() * 1000))
    status, text = _open(
        urllib.request.Request(url, headers=_auth_headers(token, userid))
    )
    if status == 401 and _retry and _relogin():
        return _get(host, path, None, None, _retry=False)
    return status, text


def _body(text):
    try:
        return json.loads(text)
    except Exception:
        return None


def _said(text):
    """One-line summary of a reply. Never includes the token."""
    body = _body(text)
    if isinstance(body, dict):
        bits = ["%s=%r" % (k, body[k]) for k in ("code", "message", "result") if k in body]
        if bits:
            return ", ".join(bits)
    stripped = (text or "").strip()
    return ("non-JSON: " + stripped[:160]) if stripped else "empty body"


def login(host, user, password):
    url = "https://%s/%s/auth/login" % (host, BASEPATH)
    fields = {
        "account": user,
        "password": hashlib.md5(password.encode("utf-8")).hexdigest(),
        "pw_encrypted": "hashed",
        "login_entry": "web",
    }
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(fields).encode(),
        headers={
            "cookie": "isPrivacy=1;",
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
        method="POST",
    )
    _status, text = _open(req)
    body = _body(text) or {}
    token = body.get("token")
    if not token:
        raise SystemExit("Login failed: " + _said(text))
    return token, body.get("data", {}).get("user_id")


def read_mode(host, token, userid, area):
    """Current mode for `area`, or None if the panel did not say.

    Defensive about the reply's shape on purpose. The first live run crashed
    here with "'str' object has no attribute 'get'" - panel/cycle answered
    with a bare JSON string rather than the usual object, most likely because
    the ~5 minute token had expired mid-run. It crashed in the finally block,
    so it took the disarm confirmation and the restore down with it and left
    the panel armed. A state read that can strand an alarm in the armed state
    must not assume anything about what comes back.
    """
    status, text = _get(host, "panel/cycle", token, userid)
    body = _body(text)
    if not isinstance(body, dict):
        print("      (could not read mode: HTTP %s - %s)" % (status, _said(text)))
        return None
    data = body.get("data")
    if not isinstance(data, dict):
        print("      (could not read mode: HTTP %s - %s)" % (status, _said(text)))
        return None
    for entry in data.get("model") or []:
        if isinstance(entry, dict) and str(entry.get("area")) == str(area):
            return entry.get("mode")
    return None


def wait_for_mode(host, token, userid, area, want, timeout=POLL_TIMEOUT):
    """Poll panel/cycle until the mode reaches `want`. Returns (mode, seconds).

    A single sleep-then-read was not good enough, and the failure was in the
    dangerous direction. If the panel were slower than the sleep, the probe
    would read the OLD mode and record "not armed" - and on step D that false
    negative reads as "the PIN check held" when the check had in fact been
    bypassed. Polling makes a negative mean what it should: it really did not
    arm within POLL_TIMEOUT seconds.

    For reference, the panel measured on 2026-09-22 reported mode=home about
    1.5s after the POST, so the timeout is generous on purpose.
    """
    started = time.time()
    while True:
        seen = read_mode(host, token, userid, area)
        waited = time.time() - started
        if seen == want or waited >= timeout:
            return seen, waited
        time.sleep(POLL_EVERY)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--user", required=True, help="account e-mail")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--area", default="1")
    ap.add_argument("--mode", default="home", choices=["home", "arm"],
                    help="which arm mode to test. Default and recommended is "
                         "home: it arms the perimeter without live interior "
                         "zones or an exit delay, so walking past a PIR while "
                         "the probe runs cannot set anything off. The PIN is "
                         "validated the same way either way, and the two "
                         "measurements this probe is built on were both home, "
                         "so `arm` buys no extra information.")
    ap.add_argument("--dry-run", action="store_true", help="print payloads, send nothing")
    ap.add_argument("--skip-wrong-pin", action="store_true", help="leave out step E")
    ap.add_argument("--skip-disarm-test", action="store_true",
                    help="leave out phase 2 (F/G), which tests whether the "
                         "panel can be DISARMED without a valid PIN")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    ap.add_argument("--out", help="write the report here (never contains the PIN)")
    args = ap.parse_args()

    warning = __doc__.split("READ BEFORE RUNNING")[1].split("Requirements:")[0]
    print("READ BEFORE RUNNING" + warning.rstrip())
    print()
    if not args.dry_run and not args.yes:
        answer = input("This will arm and disarm your alarm for real. Continue? [y/N] ")
        if answer.strip().lower() != "y":
            raise SystemExit("Aborted.")

    # --dry-run touches NOTHING: no prompt, no login, no request. It exists to
    # show the payload matrix before you point this at a live alarm, and an
    # earlier version got that wrong - it still called getpass() and then
    # logged in, so a dry run piped from /dev/null sent an empty password to
    # the real host and burned one of the ~3 attempts before the per-IP
    # lockout. A dry run that can lock you out of your own panel is not a dry
    # run.
    if args.dry_run:
        token = userid = None
        pin = "<pin>"
        started_as = "(not read - dry run)"
    else:
        password = getpass.getpass("Account password: ")
        pin = getpass.getpass("Alarm PIN (the one that works): ")

        token, userid = login(args.host, args.user, password)
        SESSION.update(host=args.host, user=args.user, password=password,
                       token=token, userid=userid)
        print("\nLogged in to %s (user_id %s)\n" % (args.host, userid))

        started_as = read_mode(args.host, token, userid, args.area)
    print("Area %s is currently: %s\n" % (args.area, started_as))

    base = {"area": int(args.area), "mode": args.mode, "format": 1}
    disarm = {"area": int(args.area), "mode": "disarm", "format": 1, "pincode": pin}

    cases = [
        ("A", "pincode=<correct>", dict(base, pincode=pin)),
        ("B", "pin=<correct>", dict(base, pin=pin)),
        ("C", "pin + pincode, both correct", dict(base, pin=pin, pincode=pin)),
        ("D", "NO pin field at all", dict(base)),
    ]
    if not args.skip_wrong_pin:
        cases.append(("E", "pin=<WRONG>", dict(base, pin=WRONG_PIN)))

    # Phase 2, and the one that actually carries security weight.
    #
    # Arming without a code is normal and deliberate on many alarm panels -
    # you need a code to turn the system OFF, not on. So steps A-E arming with
    # no PIN is suggestive but not damning on its own. Disarming without one
    # is a different matter entirely: if F succeeds, anyone who can reach the
    # API can switch the alarm off without knowing the code.
    #
    # Each of these has to start from an armed panel, so the runner arms with
    # the correct pincode first and cleans up with a known-good disarm after.
    disarm_cases = []
    if not args.skip_disarm_test:
        disarm_cases = [
            ("F", "DISARM with NO pin field", dict(base, mode="disarm")),
        ]
        if not args.skip_wrong_pin:
            disarm_cases.append(
                ("G", "DISARM with pincode=<WRONG>",
                 dict(base, mode="disarm", pincode=WRONG_PIN))
            )

    rows = []
    try:
        for tag, label, fields in cases:
            print("[%s] %s" % (tag, label))
            print("      fields sent: %s" % ", ".join(sorted(fields)))

            if args.dry_run:
                shown = dict(
                    # Mask the real PIN only. Step E's wrong one is not a
                    # secret, and hiding it would make the dry run lie about
                    # what the most important case actually sends.
                    (k, "<your-pin>" if v == pin else v)
                    for k, v in fields.items()
                )
                print("      DRY RUN, would POST: %s\n" % shown)
                rows.append((tag, label, "-", "-", "dry run"))
                continue

            status, text = _post(args.host, "panel/mode", token, userid, fields)
            print("      HTTP %s - %s" % (status, _said(text)))

            now, waited = wait_for_mode(args.host, token, userid, args.area, args.mode)
            armed = now == args.mode
            print("      panel is now: %s after %.1fs  =>  %s"
                  % (now, waited, "ARMED" if armed else "not armed"))
            rows.append((tag, label, str(status), now or "?", _said(text)))

            if armed:
                st, tx = _post(args.host, "panel/mode", token, userid, disarm)
                back, _w = wait_for_mode(args.host, token, userid, args.area, "disarm")
                print("      disarming... HTTP %s - %s  (panel: %s)" % (st, _said(tx), back))
                if back != "disarm":
                    print("      *** DISARM DID NOT TAKE - CHECK YOUR PANEL ***")
            print()

        for tag, label, fields in disarm_cases:
            print("[%s] %s" % (tag, label))
            print("      fields sent: %s" % ", ".join(sorted(fields)))

            if args.dry_run:
                shown = dict(
                    (k, "<your-pin>" if v == pin else v) for k, v in fields.items()
                )
                print("      DRY RUN, would POST: %s\n" % shown)
                rows.append((tag, label, "-", "-", "dry run"))
                continue

            # Arm first, with the PIN we know works, so the test starts from
            # a genuinely armed panel rather than from whatever came before.
            _post(args.host, "panel/mode", token, userid, dict(base, pincode=pin))
            ready, _w = wait_for_mode(args.host, token, userid, args.area, args.mode)
            if ready != args.mode:
                print("      could not arm to set the test up (panel: %s) - skipping\n" % ready)
                rows.append((tag, label, "-", ready or "?", "setup failed"))
                continue

            status, text = _post(args.host, "panel/mode", token, userid, fields)
            print("      HTTP %s - %s" % (status, _said(text)))

            now, waited = wait_for_mode(args.host, token, userid, args.area, "disarm")
            disarmed = now == "disarm"
            print("      panel is now: %s after %.1fs  =>  %s"
                  % (now, waited, "DISARMED - the PIN was not required"
                     if disarmed else "still armed, PIN required"))
            rows.append((tag, label, str(status), now or "?", _said(text)))

            if not disarmed:
                st, tx = _post(args.host, "panel/mode", token, userid, disarm)
                back, _w = wait_for_mode(args.host, token, userid, args.area, "disarm")
                print("      cleaning up... HTTP %s - %s  (panel: %s)" % (st, _said(tx), back))
                if back != "disarm":
                    print("      *** DISARM DID NOT TAKE - CHECK YOUR PANEL ***")
            print()
    finally:
        if not args.dry_run:
            back = read_mode(args.host, token, userid, args.area)
            if started_as and back != started_as:
                print("Restoring area %s to %s..." % (args.area, started_as))
                restore = dict(base, mode=started_as, pincode=pin)
                st, tx = _post(args.host, "panel/mode", token, userid, restore)
                back, _w = wait_for_mode(args.host, token, userid, args.area, started_as)
                print("  HTTP %s - %s  (panel: %s)" % (st, _said(tx), back))
            final = read_mode(args.host, token, userid, args.area)
            print("\nFinal state of area %s: %s" % (args.area, final))
            if started_as and final != started_as:
                print("*** NOT back to %s - CHECK YOUR PANEL ***" % started_as)

    lines = ["", "RESULTS", "=======", "",
             "%-3s %-30s %-5s %-8s %s" % ("", "case", "HTTP", "panel", "server said")]
    for tag, label, status, now, said in rows:
        lines.append("%-3s %-30s %-5s %-8s %s" % (tag, label, status, now, said))
    lines += [
        "",
        "HOW TO READ IT",
        "--------------",
        "  D armed  -> the panel arms with NO PIN. Renaming the field to `pin` is",
        "              then equivalent to omitting it, so PR #20's patch removes the",
        "              PIN check rather than fixing the spelling. Do not merge it.",
        "  E armed  -> the same conclusion from the other side: `pin` is ignored.",
        "  B armed, D and E rejected -> the server really does read `pin` too.",
        "  C armed  -> sending BOTH keys is safe here, and is the compatible fix.",
        "  A is the control. If A fails, something else is wrong - stop and re-read.",
        "",
        "  F disarmed -> THE PANEL CAN BE SWITCHED OFF WITHOUT THE CODE. Arming",
        "              without a code is normal; disarming without one is not.",
        "  G disarmed -> same, with a wrong code rather than none at all.",
        "  F and G both refused -> the PIN guards what it needs to guard, and",
        "              A-E only show that arming is deliberately code-free.",
        "",
    ]
    report = "\n".join(lines)
    print(report)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(report + "\n")
        print("Written to %s (contains no PIN and no token)" % args.out)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted - CHECK YOUR PANEL, it may be left armed.", file=sys.stderr)
        sys.exit(1)

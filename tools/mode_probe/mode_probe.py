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

Your PIN is read interactively (getpass), sent ONLY to the alarm host over
HTTPS, and is never printed or written to --out.

    py mode_probe.py --user YOUR_ACCOUNT
    py mode_probe.py --user YOUR_ACCOUNT --dry-run       # show payloads, send nothing
    py mode_probe.py --user YOUR_ACCOUNT --skip-wrong-pin
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
SETTLE = 3.0          # seconds to let the panel report its new mode


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


def _post(host, path, token, userid, fields):
    """Form-encoded POST, framed exactly like the integration's _rest_call_post."""
    url = "https://%s/%s/%s?_=%d" % (host, BASEPATH, path, round(time.time() * 1000))
    headers = _auth_headers(token, userid)
    headers["content-type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(fields).encode(), headers=headers, method="POST"
    )
    return _open(req)


def _get(host, path, token, userid):
    url = "https://%s/%s/%s?_=%d" % (host, BASEPATH, path, round(time.time() * 1000))
    return _open(urllib.request.Request(url, headers=_auth_headers(token, userid)))


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
    _status, text = _get(host, "panel/cycle", token, userid)
    body = _body(text) or {}
    for entry in body.get("data", {}).get("model", []):
        if str(entry.get("area")) == str(area):
            return entry.get("mode")
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--user", required=True, help="account e-mail")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--area", default="1")
    ap.add_argument("--mode", default="home", choices=["home", "arm"],
                    help="which arm mode to test (default: home)")
    ap.add_argument("--dry-run", action="store_true", help="print payloads, send nothing")
    ap.add_argument("--skip-wrong-pin", action="store_true", help="leave out step E")
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

            time.sleep(SETTLE)
            now = read_mode(args.host, token, userid, args.area)
            armed = now == args.mode
            print("      panel is now: %s  =>  %s" % (now, "ARMED" if armed else "not armed"))
            rows.append((tag, label, str(status), now or "?", _said(text)))

            if armed:
                st, tx = _post(args.host, "panel/mode", token, userid, disarm)
                print("      disarming... HTTP %s - %s" % (st, _said(tx)))
                time.sleep(SETTLE)
            print()
    finally:
        if not args.dry_run:
            back = read_mode(args.host, token, userid, args.area)
            if started_as and back != started_as:
                print("Restoring area %s to %s..." % (args.area, started_as))
                restore = dict(base, mode=started_as, pincode=pin)
                st, tx = _post(args.host, "panel/mode", token, userid, restore)
                print("  HTTP %s - %s" % (st, _said(tx)))
                time.sleep(SETTLE)
            print("\nFinal state of area %s: %s"
                  % (args.area, read_mode(args.host, token, userid, args.area)))

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

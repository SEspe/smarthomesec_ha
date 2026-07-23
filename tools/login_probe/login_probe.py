"""Find which host + password scheme the SmartHomeSec/Vesta login accepts.

The integration logs in with a fixed recipe (see custom_components/smarthomesec
__init__.py::login):

    POST https://<host>/REST/v2/auth/login
    account=<user>&password=<md5(pw)>&pw_encrypted=hashed&login_entry=web

When a *new* app ships new credentials and login fails, the endpoint is almost
never the problem: smartalarm.alarm24.no, portal.vestasecurity.eu and
smarthomesec.bydemes.com are the same Climax backend on one IP, all serving
/REST/v2. What usually changes is the *payload* - most often the password
hashing (MD5 vs plaintext vs SHA-256) or the pw_encrypted flag. A bad-credential
reply is always {"code":"010","result":false,"message":"Login failure!"}
regardless of the reason, so the only way to tell is to try the real
credentials against each variant and see which one returns a token.

That is what this does: for each host it tries a small ordered set of password
schemes, stops on the first one that returns result=true with a non-empty
token, and prints the winning host + scheme so you can set const.py accordingly.

Your password is read interactively (getpass) by default and is sent ONLY to
the alarm hosts over HTTPS - nowhere else. It is never written to --out.

Requirements: Python 3.7+, standard library only. Nothing to install.

    py login_probe.py --user YOUR_ACCOUNT
    py login_probe.py --user YOUR_ACCOUNT --all-schemes   # add sha256, md5-upper
    py login_probe.py --user YOUR_ACCOUNT --all-hosts     # try all three hosts
    py login_probe.py --user YOUR_ACCOUNT --also-app      # also login_entry=app

RATE LIMIT - READ THIS. The server throttles by SOURCE IP, not by account:
after only ~3 failed attempts it returns code 018 "login failed too many times!"
and then code 044 "Retry after 5 minutes". This was measured against a
non-existent account, so the correct password is no protection while probing.

Consequences the probe is built around:
  - The default tries ONE host and the THREE most-likely schemes = 3 attempts,
    which fits inside one window. --all-schemes / --all-hosts exceed it and must
    be spread across multiple 5-minute windows.
  - The probe STOPS the moment it sees a lockout code, so it does not dig the
    hole deeper. If that happens, wait 5 minutes before the next run.
  - If your md5 credentials are actually correct, attempt 1 succeeds and no
    lockout is ever reached. Lockout only bites when the scheme really differs.
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

DEFAULT_HOSTS = [
    "smartalarm.alarm24.no",     # current Norwegian provider (const.py)
    "portal.vestasecurity.eu",   # Vesta regional portal - same backend IP
    "smarthomesec.bydemes.com",  # ByDemes default - same backend IP
]

BASEPATH = "REST/v2"

# The server throttles by source IP. These codes mean "you are rate-limited";
# continuing only extends the lockout, so the probe aborts when it sees one.
LOCKOUT_CODES = {"018", "044"}

_OUT = None


def emit(line=""):
    """print(), but also to --out, flushed. Never receives the password."""
    print(line, flush=True)
    if _OUT:
        _OUT.write(line + "\n")
        _OUT.flush()


def password_schemes(pw, include_all):
    """Ordered (name, encoded, pw_encrypted) variants, most-likely first.

    'hashed' is what the server calls an already-encrypted password; plaintext
    variants drop the flag, which is how a plaintext-login app typically posts.
    The first three fit inside one rate-limit window; the rest are gated behind
    --all-schemes so a run cannot blow the ~3-attempt budget by default.
    """
    md5 = hashlib.md5(pw.encode("utf-8")).hexdigest()
    top3 = [
        ("md5",            md5, "hashed"),   # what the integration sends today
        ("plaintext",      pw,  None),
        ("plaintext+flag", pw,  "plain"),
    ]
    extra = [
        ("sha256",    hashlib.sha256(pw.encode()).hexdigest(), "hashed"),
        ("md5-upper", md5.upper(),                             "hashed"),
    ]
    return top3 + extra if include_all else top3


def attempt(host, user, encoded_pw, pw_encrypted, login_entry, timeout):
    """POST one login variant. Return (ok, code, message, token, note)."""
    url = f"https://{host}/{BASEPATH}/auth/login"
    fields = {"account": user, "password": encoded_pw, "login_entry": login_entry}
    if pw_encrypted is not None:
        fields["pw_encrypted"] = pw_encrypted
    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "cookie": "isPrivacy=1;",
            "user-agent": "smarthomesec-login-probe/1.0",
        },
        method="POST",
    )
    # DV cert on a known host; we only care whether the credentials are accepted.
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as ex:
        body = ex.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, ssl.SSLError, OSError) as ex:
        return False, "", "", "", f"network error: {ex}"

    try:
        j = json.loads(body)
    except ValueError:
        return False, "", "", "", f"non-JSON reply: {body[:120]!r}"

    code = str(j.get("code", ""))
    message = str(j.get("message", ""))
    token = j.get("token") or ""
    ok = bool(j.get("result")) and bool(token)
    return ok, code, message, token, ""


def mask(token):
    if not token:
        return ""
    return token[:6] + "…" + token[-4:] if len(token) > 12 else "***"


def main():
    ap = argparse.ArgumentParser(description="Probe SmartHomeSec/Vesta login variants.")
    ap.add_argument("--user", required=True, help="account / username from the app")
    ap.add_argument(
        "--password",
        help="password (omit to be prompted; --password puts it in shell history)",
    )
    ap.add_argument("--password-stdin", action="store_true", help="read password from stdin")
    ap.add_argument(
        "--host",
        action="append",
        metavar="HOST",
        help="host to try (repeatable); default is smartalarm.alarm24.no only",
    )
    ap.add_argument(
        "--all-hosts",
        action="store_true",
        help="try all three known hosts (exceeds one rate-limit window)",
    )
    ap.add_argument(
        "--all-schemes",
        action="store_true",
        help="also try sha256 and md5-upper (exceeds one rate-limit window)",
    )
    ap.add_argument("--also-app", action="store_true", help="also try login_entry=app")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between attempts")
    ap.add_argument("--timeout", type=float, default=20.0, help="per-request timeout")
    ap.add_argument("--out", metavar="PATH", help="also write the report here (never the password)")
    args = ap.parse_args()

    if args.password_stdin:
        pw = sys.stdin.readline().rstrip("\n")
    elif args.password:
        pw = args.password
    else:
        pw = getpass.getpass("Password (input hidden): ")
    if not pw:
        print("empty password; aborting", flush=True)
        return 2

    if args.host:
        hosts = args.host
    elif args.all_hosts:
        hosts = DEFAULT_HOSTS
    else:
        hosts = DEFAULT_HOSTS[:1]
    entries = ["web", "app"] if args.also_app else ["web"]
    schemes = password_schemes(pw, args.all_schemes)

    total = len(hosts) * len(entries) * len(schemes)

    global _OUT
    if args.out:
        try:
            _OUT = open(args.out, "w", encoding="utf-8")
        except OSError as ex:
            print(f"cannot write {args.out}: {ex}", flush=True)

    try:
        emit(f"login probe started {time.strftime('%Y-%m-%d %H:%M:%S')}")
        emit(f"account: {args.user}")
        emit(f"hosts:   {', '.join(hosts)}")
        emit(f"entries: {', '.join(entries)}")
        if total > 3:
            emit(f"NOTE: {total} attempts requested, but the server rate-limits at ~3")
            emit("      per 5-min window (per IP). It will likely lock out partway;")
            emit("      the probe stops on the first lockout. Spread runs over windows.")
        emit("=" * 72)

        winner = None
        locked = False
        reached = False
        first = True
        for host in hosts:
            for entry in entries:
                for name, encoded, flag in schemes:
                    if not first:
                        time.sleep(args.delay)
                    first = False
                    ok, code, message, token, note = attempt(
                        host, args.user, encoded, flag, entry, args.timeout
                    )
                    tag = f"{host}  entry={entry}  scheme={name}"
                    if note:
                        emit(f"  ??  {tag}  -> {note}")
                        continue
                    reached = True
                    if ok:
                        emit(f"  OK  {tag}  -> token {mask(token)}")
                        winner = (host, entry, name, code, message)
                        break
                    if code in LOCKOUT_CODES:
                        emit(f"  !!  {tag}  -> code={code} {message!r}  (rate-limited)")
                        locked = True
                        break
                    emit(f"  --  {tag}  -> code={code} {message!r}")
                if winner or locked:
                    break
            if winner or locked:
                break

        emit("=" * 72)
        if winner:
            host, entry, name, code, message = winner
            emit("SUCCESS - a variant was accepted:")
            emit(f"    host        = {host}")
            emit(f"    login_entry = {entry}")
            emit(f"    password    = {name}")
            emit("")
            if host != DEFAULT_HOSTS[0]:
                emit(f"-> set API_BASEHOST = \"{host}\" in const.py")
            else:
                emit("-> const.py host is correct; the login recipe was the issue")
            if name != "md5":
                emit(f"-> the working scheme is '{name}', not the integration's md5 —")
                emit("   the login payload in __init__.py::login needs updating.")
            if entry != "web":
                emit(f"-> login_entry must be '{entry}', not 'web'.")
        elif locked:
            emit("RATE-LIMITED before every variant was tried.")
            emit("The server locked out this IP (~3 attempts / 5 min). No conclusion")
            emit("yet - the untried variants may still contain the right one.")
            emit("Wait 5 minutes, then re-run. To use each window well, narrow it:")
            emit("  - one scheme at a time:  --host smartalarm.alarm24.no  (default)")
            emit("  - if the password itself is certain, the md5 line above tells you")
            emit("    whether the current integration recipe already works.")
        elif not reached:
            emit("NO host could be reached - every attempt was a network error.")
            emit("Nothing was rejected; the probe never got a reply. Check that this")
            emit("machine has internet, that a firewall/VPN is not blocking HTTPS, and")
            emit("that the host name is right. This is about connectivity, not creds.")
        else:
            emit("NO variant was accepted on any host.")
            emit("Every attempt returned a login failure, so the ENDPOINT and SCHEME")
            emit("are not the missing piece - the credentials themselves are being")
            emit("rejected. Most likely:")
            emit("  - the account/username format is wrong (email vs customer no.)")
            emit("  - the password is mistyped, or the account is not provisioned")
            emit("    on these hosts (a different regional server)")
            emit("  - the account is temporarily locked from failed attempts")
            emit("Re-check the exact login that works in the app, then re-run.")
        emit(f"\nprobe finished {time.strftime('%Y-%m-%d %H:%M:%S')}")
        return 0 if winner else 1
    finally:
        if _OUT:
            _OUT.close()


if __name__ == "__main__":
    sys.exit(main())

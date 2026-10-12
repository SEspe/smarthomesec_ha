"""Read the panel's event log from the SmartHomeSec/Vesta `event/report` endpoint.

WHY THIS EXISTS
---------------
The integration only ever sees two records: `alarm_event_latest` and
`report_event_latest` in panel/cycle - the LATEST alarm and the LATEST event.
Everything in between is gone by the next refresh. So for every alarm on
record, what happened around it is only known where a debug log happened to
be running at the time.

Yale's open-source client for the same Climax backend calls a paged event log:

    /api/event/report/?page_num=1&set_utc=1

returning report_id, cid, event_type (== cid_code), user, area, zone, name
(the device name, resolved by the server), time and cid_source. It has never
been tried on Vesta. If it is there, it answers retrospectively what no log
caught:

  * Was a 3130 RESTORE ever emitted after an alarm?  handle_alarm_record()
    has a branch for it that the 2026-08-16 log suggests never fires.
  * What did the panel emit around the 2026-08-04, 2026-08-16 and 2026-09-06
    burglaries - entry, alarm, cancel, disarm, in order?
  * Does the server's own `name` agree with our zone -> device_status[].no
    mapping?

WHAT IT DOES
------------
READ-ONLY. One login, then GETs. It never arms, disarms or changes anything.

  1. Tries a few spellings of the endpoint and stops at the first that answers
     with JSON (the path and trailing slash are unmeasured on Vesta).
  2. Prints the reply's shape - top-level keys and one event's keys - because
     the shape here is what we actually do not know.
  3. Reads up to --pages pages, prints every event as one line, marks the
     alarm-class Contact IDs, and points out the three known burglary records
     if they are still in the log.

    py event_probe.py --user YOUR_ACCOUNT
    py event_probe.py --user YOUR_ACCOUNT --dry-run        # show URLs, send nothing
    py event_probe.py --user YOUR_ACCOUNT --pages 10
    py event_probe.py --user YOUR_ACCOUNT --out result.txt --raw raw.out

READ BEFORE RUNNING
-------------------
  * It logs in ONCE. Login is rate-limited per source IP (~3 failures -> 5
    minute lockout), so a mistyped password costs one of those attempts.
  * Logging in invalidates the token your Home Assistant integration is using.
    Its WebSocket will be dropped by the server ~1.5 s later and reconnect by
    itself - expect a short gap in real-time updates, ~25 s by the code path
    (unmeasured). Nothing is lost: the next REST poll catches up.
  * --out and --raw write YOUR account's event history (device names, times)
    to disk. Both are gitignored when named result.txt / *.out inside tools/;
    do not paste --raw anywhere public without reading it first.

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

# Tried in order; the first that answers with a JSON object wins. Yale's path
# is "event/report/" under /api/; this backend's REST/v2 paths have no trailing
# slash elsewhere (panel/cycle, panel/mode), so that spelling goes first.
CANDIDATE_PATHS = ("event/report", "event/report/")

# The three burglary records we know of, so the report can say whether the log
# reaches back to them. All burglary (1130), area 1.
KNOWN_ALARMS = {
    "383748205": "2026-08-04 real burglary, zone 7",
    "388956623": "2026-08-16 test alarm, zone 5 (IR Stue)",
    "398397822": "2026-09-06 real burglary, zone 5 (IR Stue)",
}

# Contact ID event names - a copy of CID_REASONS in the integration's const.py
# plus 400 (seen as 1400 disarm). Stdlib-only, so copied, not imported - keep in step.
CID_NAMES = {
    "100": "Medical", "110": "Fire", "120": "Panic", "121": "Duress",
    "122": "Silent panic", "130": "Burglary", "131": "Perimeter",
    "132": "Interior", "133": "24-hour zone", "134": "Entry/exit",
    "137": "Tamper", "139": "Burglary verified",
    "301": "AC loss", "374": "Trouble closing", "400": "Open/close",
    "401": "Open/close", "406": "Cancel", "602": "Periodic test",
}


def _open(req, timeout=20):
    """Send a request and return (status, body-text), body included on errors."""
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
        return "JSON object, keys: %s" % ", ".join(sorted(k for k in body if k != "token"))
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


def event_url(host, path, page, set_utc):
    params = {"page_num": page, "_": round(time.time() * 1000)}
    if set_utc:
        params["set_utc"] = 1
    return "https://%s/%s/%s?%s" % (host, BASEPATH, path, urllib.parse.urlencode(params))


def get(url, token, userid):
    return _open(urllib.request.Request(url, headers=_auth_headers(token, userid)))


def find_events(body):
    """The list of event dicts somewhere in the reply, or None.

    The shape on Vesta is unknown, so look rather than assume: the reply
    itself, then body["data"], then any list of dicts one level inside it.
    """
    if isinstance(body, list):
        return body if all(isinstance(e, dict) for e in body) else None
    if not isinstance(body, dict):
        return None
    data = body.get("data")
    if isinstance(data, list) and all(isinstance(e, dict) for e in data):
        return data
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list) and value and all(isinstance(e, dict) for e in value):
                return value
    return None


def describe_shape(body):
    """Keys only - never values, which carry the token and personal data."""
    lines = []
    if isinstance(body, dict):
        lines.append("top-level keys: %s" % ", ".join(sorted(body)))
        data = body.get("data")
        if isinstance(data, dict):
            lines.append("data keys:      %s" % ", ".join(sorted(data)))
        elif isinstance(data, list):
            lines.append("data:           list of %d" % len(data))
    events = find_events(body)
    if events:
        lines.append("event keys:     %s" % ", ".join(sorted(events[0])))
    return lines


def fmt_time(value):
    """Epoch seconds -> local time; anything else is shown as given."""
    text = str(value or "").strip()
    if text.isdigit() and len(text) >= 9:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(text)))
    return text or "?"


def cid_code_of(event):
    """The 4-digit Contact ID code: event_type (Yale), cid_code, or from cid."""
    for key in ("event_type", "cid_code"):
        value = str(event.get(key) or "").strip()
        if len(value) == 4 and value.isdigit():
            return value
    cid = str(event.get("cid") or "")
    # MT(2) QXYZ(4) GG(2) CCC(3), as parse_cid in the integration.
    if len(cid) == 11 and cid.isdigit():
        return cid[2:6]
    return ""


def classify(code):
    """'ALARM' / 'restore' / '' - the same rule as the integration's classify_cid."""
    if len(code) != 4:
        return ""
    qualifier, number = code[0], int(code[1:])
    if 100 <= number <= 199:
        if qualifier == "1":
            return "ALARM"
        if qualifier == "3":
            return "restore"
    return ""


def event_line(event):
    code = cid_code_of(event)
    kind = classify(code)
    name = CID_NAMES.get(code[1:], "") if code else ""
    rid = str(event.get("report_id") or "")
    flag = "  <== " + KNOWN_ALARMS[rid] if rid in KNOWN_ALARMS else ""
    return "%-19s  %-9s %-4s %-8s %-18s area %-2s zone %-3s user %-3s %s%s" % (
        fmt_time(event.get("time")),
        rid,
        code or "?",
        kind,
        name,
        event.get("area", "?"),
        event.get("zone", "?"),
        event.get("user", "?"),
        event.get("name") or "",
        flag,
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--user", required=True, help="account e-mail")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--pages", type=int, default=5, help="max pages to read (default 5)")
    ap.add_argument("--no-set-utc", action="store_true",
                    help="leave out set_utc=1 (Yale sends it; its effect here is unknown)")
    ap.add_argument("--dry-run", action="store_true", help="print URLs, send nothing")
    ap.add_argument("--out", help="write the report here (no token, no password)")
    ap.add_argument("--raw", help="write every raw page here as JSON, token removed")
    args = ap.parse_args()

    notes = __doc__.split("READ BEFORE RUNNING")[1].split("Requirements:")[0]
    print("READ BEFORE RUNNING" + notes.rstrip() + "\n")

    set_utc = not args.no_set_utc

    # --dry-run touches NOTHING: no prompt, no login, no request. mode_probe
    # once got this wrong and burned a login attempt from a "dry" run.
    if args.dry_run:
        for path in CANDIDATE_PATHS:
            print("would GET %s" % event_url(args.host, path, 1, set_utc))
        print("then pages 2..%d on whichever path answers." % args.pages)
        return

    password = getpass.getpass("Account password: ")
    token, userid = login(args.host, args.user, password)
    print("Logged in to %s (user_id %s)\n" % (args.host, userid))

    report = ["event_probe against %s, %s" % (args.host, time.strftime("%Y-%m-%d %H:%M")), ""]

    def say(line=""):
        print(line)
        report.append(line)

    # 1. Find the endpoint.
    found = None
    first_body = None
    for path in CANDIDATE_PATHS:
        status, text = get(event_url(args.host, path, 1, set_utc), token, userid)
        say("GET %s  ->  HTTP %s - %s" % (path, status, _said(text)))
        body = _body(text)
        if status == 200 and isinstance(body, (dict, list)):
            found, first_body = path, body
            break

    if not found:
        say("")
        say("No candidate answered with JSON. The endpoint is probably not exposed")
        say("on this tenant - that is a result too. Paste the lines above into the")
        say("session notes.")
        _write(args.out, report)
        return

    say("")
    say("Endpoint: %s" % found)
    for line in describe_shape(first_body):
        say("  " + line)
    say("")

    # 2. Read pages.
    raw_pages = [first_body]
    events = list(find_events(first_body) or [])
    for page in range(2, args.pages + 1):
        if not find_events(raw_pages[-1]):
            break
        status, text = get(event_url(args.host, found, page, set_utc), token, userid)
        body = _body(text)
        page_events = find_events(body)
        if status != 200 or not page_events:
            say("page %d: HTTP %s - %s (stopping)" % (page, status, _said(text)))
            break
        raw_pages.append(body)
        events.extend(page_events)

    if not events:
        say("The endpoint answered, but no list of events was found in the reply.")
        say("The shape above is the finding - check --raw to see where they are.")
    else:
        say("%d events from %d page(s), in the order the server sent them:" %
            (len(events), len(raw_pages)))
        say("")
        say("%-19s  %-9s %-4s %-8s %-18s %s" % ("time (server)", "report_id", "cid",
                                                 "class", "meaning", "where / device"))
        for event in events:
            say(event_line(event))

        # 3. What it answers.
        codes = [cid_code_of(e) for e in events]
        seen = {str(e.get("report_id")) for e in events}
        say("")
        say("SUMMARY")
        say("  alarm-class (1 1xx):  %d" % sum(classify(c) == "ALARM" for c in codes))
        say("  restores    (3 1xx):  %d   <- any here means handle_alarm_record's "
            "restore branch CAN fire" % sum(classify(c) == "restore" for c in codes))
        say("  cancels     (1406):   %d" % codes.count("1406"))
        for rid, what in KNOWN_ALARMS.items():
            say("  %s %s: %s" % ("found  " if rid in seen else "absent ", rid, what))
        # "Last", not "oldest": the server's sort order is unmeasured.
        say("  last event read:     %s  (raise --pages to reach further back)" %
            fmt_time(events[-1].get("time")))

    _write(args.out, report)
    if args.raw:
        with open(args.raw, "w", encoding="utf-8") as fh:
            json.dump([_scrub(p) for p in raw_pages], fh, indent=1, ensure_ascii=False)
        print("Raw pages written to %s (token removed - still YOUR event history)" % args.raw)


def _scrub(value):
    """Drop any `token` key, at any depth, before anything touches disk."""
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if k != "token"}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _write(path, lines):
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        print("Report written to %s (no token, no password)" % path)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. Nothing was changed - this probe only reads.", file=sys.stderr)
        sys.exit(1)

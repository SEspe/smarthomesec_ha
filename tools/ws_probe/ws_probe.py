"""Measure how the SmartHomeSec/Vesta WebSocket wants its heartbeat.

Background. The integration keeps the Socket.IO line alive with an Engine.IO
heartbeat. Against `smartalarm.alarm24.no` the *client* must send PING ("2")
and the server answers PONG ("3") - v3-style, even though the URL says EIO=4
(see ws_client.py and CLAUDE.md "Protocol facts").

Against `portal.vestasecurity.eu` (the Vesta tenant the new app uses) that same
client PING kills the connection: HA's log shows every socket living exactly
~20.04s and closing ~40ms after `Sent Engine.IO PING (2)`. That is the
signature of a *strict* Engine.IO v4 server, where the client must NOT ping -
the server pings and the client PONGs. `ws_client._on_message` already answers a
server PING with PONG, so if that hypothesis holds the fix is simply "don't
client-ping on this server".

This probe settles it by measuring, not guessing (the project's rule for this
code). It logs in, opens the socket exactly like the integration (`40` on
connect, token in the URL, `EIO=4`), then just watches - by default it sends NO
client ping and only answers a server PING with PONG. It reports:

  - how long the connection survives (past the ~30s alarm24 death point?),
  - whether the SERVER sends PING ("2"), and at what cadence,
  - every frame with its elapsed timestamp.

Three modes let you compare:
    (default)       silent + PONG server pings   -> the v4 hypothesis
    --no-pong       silent, do not even PONG      -> is PONG required?
    --client-ping   replicate ws_client (send "2")-> reproduce the drop

    py ws_probe.py --user YOUR_ACCOUNT                 # Vesta, v4 test, 90s
    py ws_probe.py --user YOUR_ACCOUNT --client-ping   # reproduce the 20s drop
    py ws_probe.py --user YOUR_ACCOUNT --host smartalarm.alarm24.no --client-ping

Requirements: `websocket-client` and `certifi` (both already in the repo's
`.venv` and shipped with the integration). Login uses stdlib `urllib`. The
password is read with getpass and sent only to the alarm host over HTTPS.

Note: login is a real REST auth; failed passwords count against the per-IP
rate limit documented in tools/login_probe. Get the password right first.
"""

import argparse
import getpass
import hashlib
import json
import ssl
import sys
import time
import urllib.parse
import urllib.request

import certifi
import websocket  # websocket-client

BASEPATH = "REST/v2"
DEFAULT_HOST = "portal.vestasecurity.eu"

_OUT = None


def emit(line=""):
    print(line, flush=True)
    if _OUT:
        _OUT.write(line + "\n")
        _OUT.flush()


def login(host, user, pw, timeout=20):
    """Return a fresh token via the same REST login the integration uses."""
    url = f"https://{host}/{BASEPATH}/auth/login"
    data = urllib.parse.urlencode(
        {
            "account": user,
            "password": hashlib.md5(pw.encode("utf-8")).hexdigest(),
            "pw_encrypted": "hashed",
            "login_entry": "web",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "cookie": "isPrivacy=1;",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as resp:
        body = json.loads(resp.read().decode("utf-8", errors="replace"))
    if not body.get("result") or not body.get("token"):
        raise RuntimeError(f"login rejected: code={body.get('code')} {body.get('message')!r}")
    return body["token"]


def run_probe(host, token, seconds, do_pong, client_ping):
    """Open the socket like the integration and observe the heartbeat.

    Returns a dict of measurements for the summary.
    """
    url = f"wss://{host}/ws/socket.io/?token={token}&transport=websocket&EIO=4"
    emit(f"connecting: wss://{host}/ws/socket.io/?token=…&EIO=4")

    ws = websocket.create_connection(
        url,
        sslopt={"ca_certs": certifi.where()},
        timeout=1.0,  # recv() wakes every 1s so we can drive timers + the clock
    )
    start = time.time()
    ws.send("40")  # Socket.IO CONNECT, exactly as _on_open does
    emit(f"  t=0.00  -> sent Socket.IO CONNECT (40)")

    handshake = {}
    server_pings = []      # elapsed times the server sent PING ("2")
    client_ping_times = [] # elapsed times we sent PING ("2")
    frames = 0
    next_client_ping = None
    closed_at = None

    def rel():
        return time.time() - start

    try:
        while rel() < seconds:
            # Client-ping mode: replicate ws_client's PING at pingInterval*0.8.
            if client_ping and next_client_ping is not None and rel() >= next_client_ping:
                ws.send("2")
                t = rel()
                client_ping_times.append(t)
                emit(f"  t={t:6.2f}  -> sent Engine.IO PING (2)  [client-ping mode]")
                next_client_ping += _ping_period(handshake)

            try:
                msg = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except (websocket.WebSocketConnectionClosedException, OSError):
                closed_at = rel()
                break

            if msg == "" or msg is None:
                closed_at = rel()
                break

            frames += 1
            t = rel()
            code = msg[:1] if msg else ""
            rest = msg[1:]

            if code == "0":
                try:
                    handshake = json.loads(rest)
                except ValueError:
                    handshake = {}
                emit(
                    f"  t={t:6.2f}  <- code=0 handshake "
                    f"pingInterval={handshake.get('pingInterval')} "
                    f"pingTimeout={handshake.get('pingTimeout')}"
                )
                if client_ping:
                    next_client_ping = _ping_period(handshake)
                    emit(f"           (will client-ping every {_ping_period(handshake):.1f}s)")
            elif code == "2":
                server_pings.append(t)
                emit(f"  t={t:6.2f}  <- code=2 SERVER PING")
                if do_pong:
                    ws.send("3")
                    emit(f"  t={t:6.2f}  -> sent PONG (3)")
            elif code == "3":
                emit(f"  t={t:6.2f}  <- code=3 server PONG")
            elif code == "40":
                emit(f"  t={t:6.2f}  <- code=40 Socket.IO CONNECT ok  {rest}")
            elif code == "44":
                emit(f"  t={t:6.2f}  <- code=44 TOKEN ERROR  {rest}")
            elif code == "42":
                emit(f"  t={t:6.2f}  <- code=42 EVENT  {rest[:120]}")
            else:
                emit(f"  t={t:6.2f}  <- code={code} {rest[:120]}")
    finally:
        try:
            ws.close()
        except Exception:
            pass

    lived = closed_at if closed_at is not None else rel()
    return {
        "lived": lived,
        "closed_by_server": closed_at is not None,
        "handshake": handshake,
        "server_pings": server_pings,
        "client_pings": client_ping_times,
        "frames": frames,
        "ran_for": seconds,
    }


def _ping_period(handshake):
    ms = handshake.get("pingInterval") if handshake else None
    return (ms / 1000.0 * 0.8) if ms else 20.0


def main():
    ap = argparse.ArgumentParser(description="Probe the SmartHomeSec/Vesta WebSocket heartbeat.")
    ap.add_argument("--user", required=True, help="account / username (email)")
    ap.add_argument("--password", help="password (omit to be prompted)")
    ap.add_argument("--password-stdin", action="store_true", help="read password from stdin")
    ap.add_argument("--host", default=DEFAULT_HOST, help=f"host (default {DEFAULT_HOST})")
    ap.add_argument("--seconds", type=float, default=90.0, help="observation window (default 90)")
    ap.add_argument("--no-pong", action="store_true", help="do NOT answer a server PING with PONG")
    ap.add_argument(
        "--client-ping",
        action="store_true",
        help="replicate ws_client: send client PING (2) at pingInterval*0.8 (reproduces the drop)",
    )
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

    global _OUT
    if args.out:
        try:
            _OUT = open(args.out, "w", encoding="utf-8")
        except OSError as ex:
            print(f"cannot write {args.out}: {ex}", flush=True)

    mode = "client-ping (reproduce)" if args.client_ping else (
        "silent, no PONG" if args.no_pong else "silent + PONG server pings"
    )
    try:
        emit(f"ws probe started {time.strftime('%Y-%m-%d %H:%M:%S')}")
        emit(f"host:    {args.host}")
        emit(f"mode:    {mode}")
        emit(f"window:  {args.seconds:.0f}s")
        emit("=" * 72)

        try:
            token = login(args.host, args.user, pw)
        except Exception as ex:
            emit(f"LOGIN FAILED: {ex}")
            emit("Cannot probe the socket without a token. Fix the login first "
                 "(see tools/login_probe) and mind the per-IP rate limit.")
            return 1
        emit("login OK – token acquired, opening socket")
        emit("-" * 72)

        r = run_probe(args.host, token, args.seconds, do_pong=not args.no_pong,
                      client_ping=args.client_ping)

        emit("=" * 72)
        hs = r["handshake"]
        emit(f"connection lived: {r['lived']:.2f}s "
             + ("(server closed it)" if r["closed_by_server"] else "(probe window ended, still open)"))
        emit(f"handshake: pingInterval={hs.get('pingInterval')} pingTimeout={hs.get('pingTimeout')}")
        emit(f"server PINGs (code 2): {len(r['server_pings'])}"
             + (f" at t={[round(x,1) for x in r['server_pings']]}" if r["server_pings"] else ""))
        emit(f"client PINGs sent:     {len(r['client_pings'])}")
        emit(f"frames received:       {r['frames']}")
        emit("-" * 72)

        _conclude(r, args)
        emit(f"\nprobe finished {time.strftime('%Y-%m-%d %H:%M:%S')}")
        return 0
    finally:
        if _OUT:
            _OUT.close()


def _conclude(r, args):
    lived = r["lived"]
    survived = not r["closed_by_server"]  # still open when the window ended
    server_pinged = len(r["server_pings"]) > 0

    if args.client_ping:
        if r["closed_by_server"] and lived < 35:
            emit("REPRODUCED: client PING killed the connection (~20-30s). This confirms")
            emit("the drop is caused by the client-initiated Engine.IO PING.")
        else:
            emit("Did NOT reproduce a quick drop with client-ping on this host - the")
            emit("server tolerated the client PING here.")
        return

    # Silent modes – the real experiment.
    if survived and server_pinged:
        emit("CONCLUSION: proper Engine.IO v4 - the SERVER drives the heartbeat.")
        emit(f"The line stayed up for the full {args.seconds:.0f}s with NO client PING,")
        emit("because we answered the server's PING with PONG. This is the fix:")
        emit("  -> on this server, DO NOT send the client PING ('2').")
        emit("  -> keep answering a server PING ('2') with PONG ('3') "
             "(ws_client._on_message already does).")
        emit("Since alarm24 needs the opposite, gate the client-ping so it only fires")
        emit("when the server is NOT pinging (fallback), not unconditionally.")
    elif survived and not server_pinged:
        emit("CONCLUSION: the line stayed up with NO client PING and NO server PING.")
        emit("This server has no heartbeat requirement on the client at all -")
        emit("  -> simply not sending the client PING is enough here.")
        emit("(Re-run a bit longer to be sure the server never pings.)")
    elif not survived and not server_pinged and not args.no_pong:
        emit(f"CONCLUSION: connection closed at {lived:.1f}s even though we sent NO")
        emit("client PING and the server never PINGed us. The server drops an idle")
        emit("client on its own timer. Needs a different keep-alive - re-run with")
        emit("--no-pong and --client-ping to compare, and note the pingTimeout above.")
    else:
        emit(f"CONCLUSION: closed at {lived:.1f}s. Inconclusive in this mode; compare")
        emit("with the other modes (default / --no-pong / --client-ping) and the")
        emit("pingInterval/pingTimeout above to work out the server's expectation.")


if __name__ == "__main__":
    sys.exit(main())

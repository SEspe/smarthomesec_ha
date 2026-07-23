================================================================================
ws_probe.py - measure how the WebSocket wants its Engine.IO heartbeat
================================================================================

THE PROBLEM
-----------
The integration keeps the Socket.IO connection alive with an Engine.IO
heartbeat. Two providers, two OPPOSITE expectations:

  - smartalarm.alarm24.no (old tenant): the CLIENT must send PING ("2") and the
    server answers PONG ("3"). Without it the server closes at pingInterval +
    pingTimeout (~30s). This is what ws_client.py does today.

  - portal.vestasecurity.eu (Vesta tenant, the new app): that same client PING
    KILLS the connection. HA's log shows every socket living ~20.04s and closing
    ~40ms after "Sent Engine.IO PING (2)", forever, in a reconnect loop. That is
    the signature of a strict Engine.IO v4 server, where the client must NOT
    ping - the server pings and the client PONGs.

ws_client._on_message already answers a server PING with PONG, so if the v4
theory holds the fix is just "don't client-ping on this server". This probe
measures it instead of guessing (the project's rule for this fragile code).

WHAT IT DOES
------------
Logs in (real REST auth, same as the integration), opens the socket exactly like
ws_client (send "40" on connect, token in the URL, EIO=4), then watches for a
window (default 90s) and reports:

  - how long the connection survives (past the ~30s alarm24 death point?),
  - whether the SERVER sends PING ("2"), and at what cadence,
  - every frame, timestamped from connect.

Three modes let you compare:

    (default)      silent + PONG server pings    -> tests the v4 hypothesis
    --no-pong      silent, don't even PONG        -> is PONG required?
    --client-ping  replicate ws_client's PING     -> reproduce the 20s drop

REQUIREMENTS
------------
websocket-client and certifi (both in the repo's .venv and shipped with the
integration). Login uses stdlib urllib. Run it with the repo venv:

    ./.venv/Scripts/python.exe tools/ws_probe/ws_probe.py --user YOU@example.com

RUNNING IT
----------
    # Vesta, default v4 test, 90 seconds:
    ws_probe.py --user YOU@example.com

    # Reproduce the 20s drop that HA sees:
    ws_probe.py --user YOU@example.com --client-ping

    # Compare against the old tenant (there client-ping is REQUIRED):
    ws_probe.py --user YOU@example.com --host smartalarm.alarm24.no --client-ping

    --seconds N   observation window (default 90; use 120+ to catch a slow
                  server ping at pingInterval=25s comfortably)
    --out PATH    also write the report to a file (never the password)

The password is read with getpass (hidden) and sent only to the alarm host.
Login is a real auth, so a wrong password counts against the per-IP rate limit
documented in tools/login_probe - get it right first.

READING THE OUTPUT
------------------
The summary states the connection lifetime, the handshake pingInterval/
pingTimeout, and how many server vs client PINGs occurred, then a CONCLUSION:

  - "proper Engine.IO v4 - the SERVER drives the heartbeat"
      The line stayed up the whole window with no client PING because we PONGed
      the server's PING. FIX: don't send the client PING on this server; keep
      answering the server PING with PONG. Gate the client-ping so it only fires
      as a fallback when the server is NOT pinging (alarm24 still needs it).

  - "no heartbeat requirement on the client"
      Stayed up with neither side pinging; just omit the client PING here.

  - "server drops an idle client on its own timer"
      Closed despite no client PING and no server PING; needs a different
      keep-alive - compare the modes and the pingTimeout.

STATUS
------
Written 2026-07-23 to diagnose the Vesta 20s reconnect loop seen after the
0.1.6 endpoint switch. The login + framing mirror ws_client.py exactly.

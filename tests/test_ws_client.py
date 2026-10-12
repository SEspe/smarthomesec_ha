"""Tests for Socket.IO frame parsing and the Engine.IO heartbeat in WSClient."""

import logging
import time
from unittest.mock import MagicMock, patch

import pytest

from custom_components.smarthomesec.ws_client import (
    DEFAULT_PING_INTERVAL,
    PING_MARGIN,
    SERVER_PING_GRACE,
    WSClient,
)

HANDSHAKE = '{"sid":"abc","upgrades":[],"pingInterval":25000,"pingTimeout":5000}'


class _FakeCoordinator:
    def __init__(self):
        self.calls = []
        self.senders = []

    def callback(self, code, content, sender=None):
        self.calls.append((code, content))
        self.senders.append(sender)


def _client():
    coordinator = _FakeCoordinator()
    ws = WSClient(coordinator, "token123")
    return coordinator, ws


def test_event_frame_is_split_into_code_and_content():
    coordinator, ws = _client()
    ws._on_message(None, '42["token","{}"]')
    assert coordinator.calls == [("42", '["token","{}"]')]


def test_event_frame_updates_last_event_watchdog_timestamp():
    coordinator, ws = _client()
    before = ws._last_event
    ws._last_event = 0  # simulate a stale line
    ws._on_message(None, '42["token","{}"]')
    assert ws._last_event > 0
    assert ws._last_event >= before - 1  # advanced, not left stale


def test_ping_frame_forwarded_with_empty_content():
    coordinator, ws = _client()
    ws._on_message(None, "3")
    assert coordinator.calls == [("3", "")]


def test_unparseable_frame_is_ignored():
    coordinator, ws = _client()
    ws._on_message(None, "no-leading-digits")
    assert coordinator.calls == []


# ----------------------------------------------------------------------
# Engine.IO heartbeat – two server dialects (see ws_client.py module top).
#
# Vesta (portal.vestasecurity.eu) is strict Engine.IO v4: the SERVER pings and
# the client only PONGs. alarm24 is v3: the server never pings and the CLIENT
# must ping, or it is closed at pingInterval + pingTimeout. So on handshake we
# do NOT ping immediately -- we schedule a fallback and wait to see whether the
# server pings first.
# ----------------------------------------------------------------------


def _fire_fallback(ws):
    """Invoke the scheduled fallback synchronously, as its timer would."""
    timer = ws._hb_fallback
    assert timer is not None, "handshake should have scheduled a fallback timer"
    timer.cancel()  # don't let the real timer also fire
    timer.function(*timer.args)


def test_handshake_does_not_ping_immediately():
    """v4 servers (Vesta) close on a client PING; handshake must stay silent."""
    _, ws = _client()
    ws._start_heartbeat = MagicMock()
    sock = MagicMock()

    ws._on_message(sock, "0" + HANDSHAKE)

    ws._start_heartbeat.assert_not_called()
    sock.send.assert_not_called()  # no "2" on the wire yet
    ws._stop_heartbeat()  # cancel the pending timer


def test_handshake_schedules_fallback_between_serverping_and_close():
    """The fallback must fire after the server's PING but before a v3 close."""
    _, ws = _client()

    ws._on_message(MagicMock(), "0" + HANDSHAKE)  # pingInterval 25s, pingTimeout 5s

    timer = ws._hb_fallback
    assert timer is not None
    assert timer.interval == 25.0 + SERVER_PING_GRACE  # 27s
    assert 25.0 < timer.interval < 30.0, "between server PING (25s) and v3 close (30s)"
    assert timer.args[1] == 25.0 * PING_MARGIN  # beat interval handed to the fallback
    ws._stop_heartbeat()


def test_server_ping_suppresses_client_fallback():
    """If the server pings first (v4), the fallback must NOT client-ping."""
    _, ws = _client()
    ws._start_heartbeat = MagicMock()

    ws._on_message(MagicMock(), "0" + HANDSHAKE)
    ws._on_message(MagicMock(), "2")  # server PING arrives before the grace elapses
    assert ws._server_drives_hb is True

    _fire_fallback(ws)

    ws._start_heartbeat.assert_not_called()


def test_no_server_ping_falls_back_to_client_ping():
    """v3 (alarm24): no server PING, so the fallback drives the heartbeat."""
    _, ws = _client()
    ws._start_heartbeat = MagicMock()
    sock = MagicMock()

    ws._on_message(sock, "0" + HANDSHAKE)
    _fire_fallback(ws)

    sock.send.assert_any_call("2")  # an immediate first PING before the deadline
    ws._start_heartbeat.assert_called_once()
    assert ws._start_heartbeat.call_args[0][1] == 25.0 * PING_MARGIN


def test_handshake_without_ping_interval_falls_back_to_default():
    _, ws = _client()

    ws._on_message(MagicMock(), '0{"sid":"abc"}')

    timer = ws._hb_fallback
    assert timer is not None
    assert timer.args[1] == DEFAULT_PING_INTERVAL * PING_MARGIN
    ws._stop_heartbeat()


def test_unparseable_handshake_still_schedules_fallback():
    """A malformed handshake must not leave us without any heartbeat plan."""
    _, ws = _client()

    ws._on_message(MagicMock(), "0not-json")

    assert ws._hb_fallback is not None
    assert ws._hb_fallback.args[1] == DEFAULT_PING_INTERVAL * PING_MARGIN
    ws._stop_heartbeat()


def test_heartbeat_actually_sends_engineio_ping():
    """The whole point: a real "2" reaches the socket, repeatedly."""
    _, ws = _client()
    sock = MagicMock()

    ws._start_heartbeat(sock, interval=0.02)
    time.sleep(0.15)
    ws._stop_heartbeat()

    assert sock.send.call_count >= 2, "heartbeat should keep firing"
    assert sock.send.call_args_list[0][0][0] == "2"


def test_stop_heartbeat_halts_pings():
    _, ws = _client()
    sock = MagicMock()

    ws._start_heartbeat(sock, interval=0.02)
    time.sleep(0.08)
    ws._stop_heartbeat()
    settled = sock.send.call_count
    time.sleep(0.1)

    assert sock.send.call_count == settled, "no pings after stop"


def test_starting_heartbeat_replaces_the_previous_one():
    """Reconnects must not leave an orphaned beater on the dead socket."""
    _, ws = _client()
    old_sock, new_sock = MagicMock(), MagicMock()

    ws._start_heartbeat(old_sock, interval=0.02)
    time.sleep(0.05)
    ws._start_heartbeat(new_sock, interval=0.02)
    old_count = old_sock.send.call_count
    time.sleep(0.1)
    ws._stop_heartbeat()

    assert old_sock.send.call_count == old_count, "old heartbeat must be stopped"
    assert new_sock.send.call_count >= 1


def test_server_ping_is_answered_with_pong():
    _, ws = _client()
    sock = MagicMock()

    ws._on_message(sock, "2")

    sock.send.assert_called_once_with("3")


def test_stop_client_stops_heartbeat():
    _, ws = _client()
    sock = MagicMock()
    ws._start_heartbeat(sock, interval=0.02)

    ws.stop_client()
    time.sleep(0.08)
    settled = sock.send.call_count
    time.sleep(0.08)

    assert sock.send.call_count == settled


# ----------------------------------------------------------------------
# The connection loop: run(), backoff and the silence watchdog.
#
# Untested until 2026-10-12. websocket.WebSocketApp is replaced by a fake
# whose run_forever() plays a script, and time.sleep is captured, so the loop
# runs in microseconds with no network.
# ----------------------------------------------------------------------

WS_MOD = "custom_components.smarthomesec.ws_client"


class _ScriptedApp:
    """Stands in for websocket.WebSocketApp; each run_forever() runs one step."""

    def __init__(self, steps, client):
        self.steps = steps
        self.client = client
        self.apps = []

    def __call__(self, url, **handlers):
        self.apps.append(url)
        app = MagicMock()
        app.run_forever.side_effect = lambda **kw: self.steps.pop(0)(self.client)
        return app


def _run(ws, steps):
    """Run ws.run() against a scripted server, returning (apps, sleep mock)."""
    scripted = _ScriptedApp(list(steps), ws)
    with patch(f"{WS_MOD}.websocket.WebSocketApp", side_effect=scripted), patch(
        f"{WS_MOD}.time.sleep"
    ) as sleep:
        ws.run()
    return scripted.apps, sleep


def _stop(ws):
    ws.stop = True


def _drop_quickly(ws):
    """A connection that dies at once (never opened): `lived` stays ~0."""


def _drop_after(seconds):
    def step(ws):
        ws._last_connect = time.time() - seconds
    return step


def _backoffs(caplog):
    return [
        int(r.args[0]) for r in caplog.records if r.msg.startswith("WebSocket reconnect in")
    ]


def test_run_connects_with_the_token_in_the_url():
    coordinator, ws = _client()

    apps, sleep = _run(ws, [_stop])

    assert len(apps) == 1
    assert "token=token123" in apps[0] and "EIO=4" in apps[0]
    assert apps[0].startswith("wss://") and "/ws/socket.io/" in apps[0]
    sleep.assert_not_called()


def test_short_lived_connections_back_off_up_to_30s(caplog):
    """A socket that dies at once doubles the delay: 4, 8, 16, 30, 30."""
    caplog.set_level(logging.DEBUG, logger=WS_MOD)
    coordinator, ws = _client()

    apps, sleep = _run(ws, [_drop_quickly] * 5 + [_stop])

    assert _backoffs(caplog) == [4, 8, 16, 30, 30]
    assert len(apps) == 6
    assert sleep.call_count == 4 + 8 + 16 + 30 + 30  # one-second steps


def test_a_connection_that_lived_resets_the_backoff(caplog):
    """After a healthy connection, the next reconnect is quick again."""
    caplog.set_level(logging.DEBUG, logger=WS_MOD)
    coordinator, ws = _client()

    _run(ws, [_drop_quickly, _drop_quickly, _drop_after(60), _stop])

    assert _backoffs(caplog) == [4, 8, 2]


def test_stop_during_the_backoff_ends_the_loop_promptly():
    """stop_client() must not wait out a 30 s backoff before the thread exits."""
    coordinator, ws = _client()
    sleeps = []

    def sleep(_):
        sleeps.append(1)
        if len(sleeps) == 2:
            ws.stop = True

    scripted = _ScriptedApp([_drop_quickly], ws)
    with patch(f"{WS_MOD}.websocket.WebSocketApp", side_effect=scripted), patch(
        f"{WS_MOD}.time.sleep", side_effect=sleep
    ):
        ws.run()

    assert len(sleeps) == 2  # not the full 4
    assert len(scripted.apps) == 1  # and no reconnect after stopping


def _silent_for_hours(ws):
    """The line dropped after one connection that saw no event for 6h+."""
    long_ago = time.time() - 21700
    ws._last_connect = long_ago
    ws._last_event = long_ago


def test_watchdog_forces_a_login_after_six_silent_hours():
    coordinator, ws = _client()

    apps, sleep = _run(ws, [_silent_for_hours])

    assert ("ForceLogin", None) in coordinator.calls
    assert coordinator.senders[-1] is ws
    assert len(apps) == 1  # it hands over to login(); no reconnect of its own
    sleep.assert_not_called()


def test_watchdog_ignores_a_fresh_connection():
    """Silent for 6h but connected under 5 min ago: just reconnect normally."""
    coordinator, ws = _client()

    def silent_but_new(ws):
        ws._last_event = time.time() - 21700
        ws._last_connect = time.time() - 60

    _run(ws, [silent_but_new, _stop])

    assert ("ForceLogin", None) not in coordinator.calls


# ----------------------------------------------------------------------
# Handlers: open, error, stop
# ----------------------------------------------------------------------


def test_on_open_sends_socketio_connect_and_tells_the_coordinator():
    coordinator, ws = _client()
    sock = MagicMock()
    ws._last_event = 0

    ws._on_open(sock)

    sock.send.assert_called_once_with("40")
    assert coordinator.calls == [("WebSocketConnect", None)]
    assert ws._last_event == ws._last_connect > 0  # watchdog clock restarted


def test_on_open_still_reports_the_connect_if_the_send_fails(caplog):
    coordinator, ws = _client()
    sock = MagicMock()
    sock.send.side_effect = OSError("closed")

    ws._on_open(sock)

    assert "Failed to send CONNECT" in caplog.text
    assert coordinator.calls == [("WebSocketConnect", None)]


def test_a_normal_close_is_not_an_error():
    """opcode=8 is the server's ordinary close frame — not worth a warning."""
    coordinator, ws = _client()

    ws._on_error(None, Exception("Connection to remote host was lost. opcode=8"))

    assert coordinator.calls == []


def test_a_real_error_is_passed_on():
    coordinator, ws = _client()
    err = Exception("handshake failed")

    ws._on_error(None, err)

    assert coordinator.calls == [("WebSocketError", err)]


@pytest.mark.parametrize("close_raises", [False, True])
def test_stop_client_closes_the_socket_and_flags_the_loop(close_raises):
    coordinator, ws = _client()
    ws.wsc = MagicMock()
    if close_raises:
        ws.wsc.close.side_effect = OSError("already closed")

    ws.stop_client()

    assert ws.stop is True
    ws.wsc.close.assert_called_once()

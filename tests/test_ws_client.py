"""Tests for Socket.IO frame parsing and the Engine.IO heartbeat in WSClient."""

import time
from unittest.mock import MagicMock

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

    def callback(self, code, content):
        self.calls.append((code, content))


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

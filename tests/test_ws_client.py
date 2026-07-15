"""Tests for Socket.IO frame parsing and the Engine.IO heartbeat in WSClient."""

import time
from unittest.mock import MagicMock

from custom_components.smarthomesec.ws_client import (
    DEFAULT_PING_INTERVAL,
    PING_MARGIN,
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
# Engine.IO heartbeat
#
# Verified against smartalarm.alarm24.no: the server expects the CLIENT to
# send PING ("2") and answers with PONG ("3"). Without it the server closes
# the connection after pingInterval + pingTimeout (25s + 5s) exactly.
# ----------------------------------------------------------------------


def test_handshake_starts_heartbeat_at_server_interval():
    """The ping period comes from the server's own pingInterval, with margin."""
    _, ws = _client()
    ws._start_heartbeat = MagicMock()

    ws._on_message(MagicMock(), "0" + HANDSHAKE)

    ws._start_heartbeat.assert_called_once()
    interval = ws._start_heartbeat.call_args[0][1]
    assert interval == 25.0 * PING_MARGIN  # 20s -- comfortably under the 25s deadline
    assert interval < 25.0, "must ping before the server's deadline"


def test_handshake_without_ping_interval_falls_back():
    _, ws = _client()
    ws._start_heartbeat = MagicMock()

    ws._on_message(MagicMock(), '0{"sid":"abc"}')

    interval = ws._start_heartbeat.call_args[0][1]
    assert interval == DEFAULT_PING_INTERVAL * PING_MARGIN


def test_unparseable_handshake_still_starts_heartbeat():
    """A malformed handshake must not leave us silent and get us disconnected."""
    _, ws = _client()
    ws._start_heartbeat = MagicMock()

    ws._on_message(MagicMock(), "0not-json")

    ws._start_heartbeat.assert_called_once()
    assert ws._start_heartbeat.call_args[0][1] == DEFAULT_PING_INTERVAL * PING_MARGIN


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

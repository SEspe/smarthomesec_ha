"""Tests for the Socket.IO frame parsing in WSClient._on_message."""

from custom_components.smarthomesec.ws_client import WSClient


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

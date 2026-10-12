"""Tests for coordinator.callback() — what each WS frame actually makes happen.

Before these existed, everything in callback() past the token-error branch had
0 % coverage: frame parsing, DEVICE_STATUS → PIR, ALARM → refresh, the
unknown-type logging, ForceLogin and WebSocketDisconnect. That is the path
that turns an alarm into TRIGGERED in ~10 s instead of at the next 300 s poll.

The WS is a doorbell (see CLAUDE.md, "Alarm trigger"): no frame carries state,
so the one thing that matters for every event is that a refresh is requested.
These tests assert on that, not just on what gets logged.
"""

import json
import logging
import time
from unittest.mock import MagicMock, patch

import pytest

from custom_components.smarthomesec import SmarthomesecCoordinator
from custom_components.smarthomesec.const import PIR_MOTION_TTL

PIR = "RF:09cdcc30"   # IR Stue, the PIR behind both real alarms
DOOR = "RF:0e253110"  # MK Veranda, a door contact


def _frame(inner: dict) -> str:
    """The content of a 42 frame, shaped exactly like a real one.

    From the 2026-09-22 log (first element replaced — it is an opaque id):
    WS RAW: ["<id>","{\\"refreshed_type\\":\\"DEVICE_STATUS\\",\\"refreshed\\":true,
             \\"data\\":{\\"device_id\\":\\"RF:0684ea80\\",\\"area\\":\\"1\\"}}"]
    The payload is a JSON string inside a JSON array, hence the double encoding.
    """
    return json.dumps(["opaque-id", json.dumps(inner)])


@pytest.fixture
def coord():
    c = object.__new__(SmarthomesecCoordinator)
    c._shutdown = False
    c.token = "tok"
    c.wsc = MagicMock()
    c._ws_token_errors = 0
    c._logged_event_types = set()
    c._pir_devices = {PIR}
    c._pir_state = {}
    c.status = {}
    c.hass = MagicMock()
    # A sentinel instead of a real coroutine: nothing here awaits it, and a
    # real one would only produce "never awaited" warnings.
    c.async_request_refresh = MagicMock(return_value="refresh")
    return c


@pytest.fixture
def scheduled():
    """Capture run_coroutine_threadsafe and the one-shot helper threads."""
    with patch(
        "custom_components.smarthomesec.asyncio.run_coroutine_threadsafe"
    ) as rct, patch("custom_components.smarthomesec.threading.Thread") as thread:
        yield rct, thread


def _refreshes(rct, coord) -> int:
    return sum(
        1 for c in rct.call_args_list if c.args == ("refresh", coord.hass.loop)
    )


# ----------------------------------------------------------------------
# Events: every one must ask for a refresh — that is the whole contract
# ----------------------------------------------------------------------


def test_alarm_event_requests_a_refresh_at_once(coord, scheduled, caplog):
    """Measured 2026-08-16: {'refreshed_type': 'ALARM', 'refreshed': True}, no data."""
    rct, _ = scheduled
    caplog.set_level(logging.INFO, logger="custom_components.smarthomesec")

    coord.callback("42", _frame({"refreshed_type": "ALARM", "refreshed": True}), sender=coord.wsc)

    assert _refreshes(rct, coord) == 1
    assert "WS ALARM event" in caplog.text
    # It is a known type now; it must not ask the user to report it.
    assert "Unhandled WS event type" not in caplog.text


def test_report_alarm_requests_a_refresh_and_logs_the_type_once(coord, scheduled, caplog):
    rct, _ = scheduled
    caplog.set_level(logging.INFO, logger="custom_components.smarthomesec")
    frame = _frame(
        {"refreshed_type": "REPORT", "refreshed": True, "data": {"type": "ALARM", "area": "1"}}
    )

    coord.callback("42", frame, sender=coord.wsc)
    coord.callback("42", frame, sender=coord.wsc)

    assert _refreshes(rct, coord) == 2
    assert caplog.text.count("New REPORT type 'ALARM'") == 1


def test_mode_change_requests_a_refresh(coord, scheduled, caplog):
    rct, _ = scheduled
    caplog.set_level(logging.INFO, logger="custom_components.smarthomesec")

    coord.callback("42", _frame({"refreshed_type": "MODE_CHANGE", "refreshed": True}), sender=coord.wsc)

    assert _refreshes(rct, coord) == 1
    assert "Unhandled WS event type" not in caplog.text


def test_unknown_event_type_still_refreshes_and_is_logged_once(coord, scheduled, caplog):
    """A new event type must never be silently dropped — that is how ALARM was found."""
    rct, _ = scheduled
    caplog.set_level(logging.INFO, logger="custom_components.smarthomesec")
    frame = _frame({"refreshed_type": "SOMETHING_NEW", "refreshed": True})

    coord.callback("42", frame, sender=coord.wsc)
    coord.callback("42", frame, sender=coord.wsc)

    assert _refreshes(rct, coord) == 2
    assert caplog.text.count("Unhandled WS event type 'SOMETHING_NEW'") == 1


def test_unparseable_frame_still_refreshes(coord, scheduled, caplog):
    rct, _ = scheduled

    coord.callback("42", "not json at all", sender=coord.wsc)

    assert _refreshes(rct, coord) == 1
    assert "WS parse error" in caplog.text


@pytest.mark.parametrize(
    "inner",
    [
        {"refreshed_type": "DEVICE_STATUS", "refreshed": True, "data": None},
        {"refreshed_type": "REPORT", "refreshed": True, "data": None},
        {"refreshed_type": "DEVICE_STATUS", "refreshed": True, "data": "not an object"},
        "not an object at all",
        ["a", "list"],
    ],
    ids=["device-status-null", "report-null", "data-string", "inner-string", "inner-list"],
)
def test_a_malformed_payload_still_refreshes(coord, scheduled, inner):
    """Never seen in a log — but before the guard, these raised AttributeError.

    websocket-client catches exceptions from on_message and logs ERROR, so the
    socket survived; the refresh for that event did not. A doorbell that
    cannot ring is the one failure the WS path must not have.
    """
    rct, _ = scheduled

    coord.callback("42", json.dumps(["opaque-id", json.dumps(inner)]), sender=coord.wsc)

    assert _refreshes(rct, coord) >= 1


# ----------------------------------------------------------------------
# DEVICE_STATUS: the PIR path, end to end
# ----------------------------------------------------------------------


def test_pir_device_status_turns_motion_on(coord, scheduled):
    """WS DEVICE_STATUS → _set_pir_active → is_pir_active, with nothing faked in between.

    Motion only exists as this event: status_motion is empty in every REST
    sample ever taken (1261/1261, 142/142). Before 0.1.14 the chain was
    broken and every motion entity was permanently off.
    """
    rct, thread = scheduled
    frame = _frame(
        {"refreshed_type": "DEVICE_STATUS", "refreshed": True, "data": {"device_id": PIR, "area": "1"}}
    )

    coord.callback("42", frame, sender=coord.wsc)

    assert coord.is_pir_active(PIR) is True
    assert coord._pir_state[PIR] == pytest.approx(time.monotonic() + PIR_MOTION_TTL, abs=1)
    # One refresh from _set_pir_active, one immediate from the event...
    assert _refreshes(rct, coord) == 2
    # ...plus the PIR reset thread and the 0.5 s delayed refresh.
    assert thread.call_count == 2


def test_door_device_status_refreshes_but_is_not_motion(coord, scheduled):
    rct, thread = scheduled
    frame = _frame(
        {"refreshed_type": "DEVICE_STATUS", "refreshed": True, "data": {"device_id": DOOR, "area": "1"}}
    )

    coord.callback("42", frame, sender=coord.wsc)

    assert coord.is_pir_active(DOOR) is False
    assert DOOR not in coord._pir_state
    assert _refreshes(rct, coord) == 1
    assert thread.call_count == 1  # only the delayed refresh


def test_a_second_motion_event_extends_the_window(coord, scheduled, monkeypatch):
    """The window is an expiry time, so event 2 cannot be ended by event 1's timer."""
    frame = _frame(
        {"refreshed_type": "DEVICE_STATUS", "refreshed": True, "data": {"device_id": PIR, "area": "1"}}
    )
    start = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: start)
    coord.callback("42", frame, sender=coord.wsc)

    monkeypatch.setattr(time, "monotonic", lambda: start + 4)
    coord.callback("42", frame, sender=coord.wsc)

    # Past the first event's window, inside the second's.
    monkeypatch.setattr(time, "monotonic", lambda: start + PIR_MOTION_TTL + 1)
    assert coord.is_pir_active(PIR) is True


# ----------------------------------------------------------------------
# Control-plane messages
# ----------------------------------------------------------------------


def test_a_healthy_42_frame_resets_the_token_error_counter(coord, scheduled):
    coord._ws_token_errors = 1

    coord.callback("42", _frame({"refreshed_type": "MODE_CHANGE"}), sender=coord.wsc)

    assert coord._ws_token_errors == 0


def test_engine_io_pong_does_nothing(coord, scheduled):
    rct, thread = scheduled

    coord.callback("3", "", sender=coord.wsc)

    rct.assert_not_called()
    thread.assert_not_called()


def test_disconnect_drops_the_client_without_restarting(coord, scheduled):
    """Reconnecting is WSClient's own loop's job; the coordinator must not race it."""
    old = coord.wsc

    with patch.object(SmarthomesecCoordinator, "delayed_ws_restart") as restart, patch.object(
        SmarthomesecCoordinator, "login"
    ) as login:
        coord.callback("WebSocketDisconnect", None, sender=old)

    old.stop_client.assert_called_once()
    assert coord.wsc is None
    restart.assert_not_called()
    login.assert_not_called()


def test_force_login_discards_the_token_and_logs_in_again(coord, scheduled):
    """The 6-hour silence watchdog: no live WS to swap, so the deferred start is right."""
    old = coord.wsc

    with patch.object(SmarthomesecCoordinator, "login") as login:
        coord.callback("ForceLogin", None, sender=old)

    old.stop_client.assert_called_once()
    assert coord.wsc is None
    assert coord.token is None
    login.assert_called_once_with()

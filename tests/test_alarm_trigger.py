"""Tests for TRIGGERED alarm detection from WebSocket events.

The panel's alarm-event payload is not measured yet (see CLAUDE.md), so these
tests pin down the two things that do not depend on the format: the state
machinery (latch, TTL, clearing) and the conservative recognition rules —
especially that neutral traffic must NOT raise a false alarm.
"""

import time

import pytest
from homeassistant.components.alarm_control_panel import AlarmControlPanelState

from custom_components.smarthomesec import SmarthomesecCoordinator
from custom_components.smarthomesec.alarm_control_panel import SmarthomesecAlarm
from custom_components.smarthomesec.const import ALARM_TRIGGER_TTL


def _coordinator() -> SmarthomesecCoordinator:
    """Bare coordinator without DataUpdateCoordinator wiring."""
    coord = object.__new__(SmarthomesecCoordinator)
    coord._triggered_areas = {}
    coord._last_trigger = None
    return coord


# ----------------------------------------------------------------------
# Recognition
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "event_type, event_data",
    [
        ("MODE_CHANGE", {"area": "1", "mode": "triggered"}),
        ("REPORT", {"area": "1", "report_type": "burglar"}),
        ("REPORT", {"area": "1", "status": "Panic"}),
        ("PANIC_ALARM", {"area": "1"}),  # unknown type, token in the type itself
        ("REPORT", {"panel": {"status": "burglar"}}),  # nested one level down
    ],
)
def test_trigger_events_are_recognized(event_type, event_data):
    assert _coordinator().classify_alarm_event(event_type, event_data) == "trigger"


@pytest.mark.parametrize(
    "event_type, event_data",
    [
        ("DEVICE_STATUS", {"device_id": "d1", "status": "dc_open"}),
        ("REPORT", {"area": "1", "alarm_type": "normal"}),
        ("REPORT", {"area": "1", "status": "battery_low"}),
        ("MODE_CHANGE", {"area": "1", "mode": "arm"}),
        ("MODE_CHANGE", {"area": "1", "mode": "home"}),
        ("REPORT", {}),
    ],
)
def test_neutral_events_do_not_trigger(event_type, event_data):
    """A false TRIGGERED is worse than a late one — these must stay quiet."""
    assert _coordinator().classify_alarm_event(event_type, event_data) != "trigger"


def test_alarm_word_alone_does_not_trigger():
    """"alarm" is deliberately not a trigger token — too common in neutral fields."""
    coord = _coordinator()
    assert coord.classify_alarm_event("REPORT", {"type": "alarm_status"}) is None


def test_disarm_is_a_clear_event():
    coord = _coordinator()
    assert coord.classify_alarm_event("MODE_CHANGE", {"mode": "disarm"}) == "clear"


def test_trigger_wins_over_clear_in_the_same_event():
    coord = _coordinator()
    verdict = coord.classify_alarm_event(
        "REPORT", {"status": "burglar", "event": "restore"}
    )
    assert verdict == "trigger"


# ----------------------------------------------------------------------
# Latching
# ----------------------------------------------------------------------


def test_trigger_event_latches_only_its_own_area():
    coord = _coordinator()
    coord.handle_alarm_event("REPORT", {"area": "2", "status": "burglar"})
    assert coord.is_area_triggered("2")
    assert not coord.is_area_triggered("1")


def test_event_without_area_latches_every_known_area():
    coord = _coordinator()
    coord.data = {"alarms": {"1": {}, "2": {}}}
    coord.handle_alarm_event("REPORT", {"status": "burglar"})
    assert coord.is_area_triggered("1")
    assert coord.is_area_triggered("2")


def test_area_is_matched_as_string_even_when_sent_as_int():
    coord = _coordinator()
    coord.handle_alarm_event("REPORT", {"area": 1, "status": "burglar"})
    assert coord.is_area_triggered("1")


def test_clear_event_releases_the_latch():
    coord = _coordinator()
    coord.handle_alarm_event("REPORT", {"area": "1", "status": "burglar"})
    coord.handle_alarm_event("MODE_CHANGE", {"area": "1", "mode": "disarm"})
    assert not coord.is_area_triggered("1")


def test_latch_expires_after_ttl(monkeypatch):
    coord = _coordinator()
    coord.handle_alarm_event("REPORT", {"area": "1", "status": "burglar"})
    assert coord.is_area_triggered("1")

    now = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: now + ALARM_TRIGGER_TTL + 1)
    assert not coord.is_area_triggered("1")


def test_last_trigger_records_the_event():
    coord = _coordinator()
    coord.handle_alarm_event("REPORT", {"area": "1", "status": "burglar"})
    assert coord._last_trigger["event_type"] == "REPORT"
    assert coord._last_trigger["areas"] == ["1"]


def test_neutral_event_leaves_state_untouched():
    coord = _coordinator()
    assert coord.handle_alarm_event("DEVICE_STATUS", {"device_id": "d1"}) is None
    assert coord._triggered_areas == {}


# ----------------------------------------------------------------------
# REST interaction
# ----------------------------------------------------------------------


class _FakeHass:
    async def async_add_executor_job(self, func, *args):
        return func(*args)


async def _refresh(coord, mode: str):
    coord.hass = _FakeHass()
    coord.update_status = lambda: {
        "device_status": [],
        "model": [{"area": "1", "mode": mode}],
    }
    return await coord._async_update_data()


async def test_rest_disarm_clears_a_ws_latch():
    """The panel was disarmed on the keypad — REST is the authority for that."""
    coord = _coordinator()
    coord.handle_alarm_event("REPORT", {"area": "1", "status": "burglar"})

    await _refresh(coord, "disarm")

    assert not coord.is_area_triggered("1")


async def test_rest_arm_does_not_clear_a_ws_latch():
    """A sounding alarm still reports the panel as armed — must stay TRIGGERED."""
    coord = _coordinator()
    coord.handle_alarm_event("REPORT", {"area": "1", "status": "burglar"})

    await _refresh(coord, "arm")

    assert coord.is_area_triggered("1")


async def test_rest_triggered_mode_latches_too():
    coord = _coordinator()

    await _refresh(coord, "triggered")

    assert coord.is_area_triggered("1")


# ----------------------------------------------------------------------
# Entity state
# ----------------------------------------------------------------------


def _panel(coord, mode: str) -> SmarthomesecAlarm:
    panel = object.__new__(SmarthomesecAlarm)
    panel.area = "1"
    panel.coord = coord
    panel._alarm = {"mode": mode}
    return panel


def test_panel_reports_triggered_while_rest_still_says_armed():
    coord = _coordinator()
    coord.handle_alarm_event("REPORT", {"area": "1", "status": "burglar"})

    assert _panel(coord, "arm").alarm_state == AlarmControlPanelState.TRIGGERED


def test_panel_returns_to_rest_state_once_cleared():
    coord = _coordinator()
    coord.handle_alarm_event("REPORT", {"area": "1", "status": "burglar"})
    coord.clear_areas_triggered(["1"])

    assert _panel(coord, "arm").alarm_state == AlarmControlPanelState.ARMED_AWAY


def test_panel_ignores_a_latch_on_another_area():
    coord = _coordinator()
    coord.handle_alarm_event("REPORT", {"area": "2", "status": "burglar"})

    assert _panel(coord, "arm").alarm_state == AlarmControlPanelState.ARMED_AWAY


def test_trigger_attributes_expose_the_source_event():
    coord = _coordinator()
    coord.handle_alarm_event("REPORT", {"area": "1", "status": "burglar"})

    attrs = _panel(coord, "arm").extra_state_attributes
    assert attrs["last_trigger_event"] == "REPORT"
    assert attrs["last_trigger_data"] == {"area": "1", "status": "burglar"}
    assert attrs["last_trigger_time"].endswith("+00:00")


def test_no_attributes_before_any_alarm():
    assert _panel(_coordinator(), "arm").extra_state_attributes is None

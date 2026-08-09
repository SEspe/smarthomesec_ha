"""Tests for TRIGGERED alarm detection.

Built on payloads measured from a live panel on 2026-08-09 (see CLAUDE.md):
the alarm is visible only as a NEW record in panel/cycle's alarm_event_latest,
carrying a Contact ID code. The WebSocket events carry no state at all, and
model[].burglar means "armed" — both are guarded against here, because both
would produce a permanently or falsely TRIGGERED alarm panel.
"""

import time

import pytest
from homeassistant.components.alarm_control_panel import AlarmControlPanelState

from custom_components.smarthomesec import SmarthomesecCoordinator
from custom_components.smarthomesec.alarm_control_panel import SmarthomesecAlarm
from custom_components.smarthomesec.const import ALARM_TRIGGER_TTL

# The real record from the 2026-08-04 burglary alarm, as the panel reported it.
BURGLARY = {
    "report_id": "383748205",
    "cid": "18113001007",
    "cid_code": "1130",
    "event_time": "",
    "time": "1785838205",
    "utc_event_time": "1785838065",
}


def _coordinator() -> SmarthomesecCoordinator:
    coord = object.__new__(SmarthomesecCoordinator)
    coord._triggered_areas = {}
    coord._last_trigger = None
    coord._last_alarm_report_id = None
    coord.status = None
    return coord


def _record(report_id="900000001", cid="18113001007", cid_code="1130", age=5.0):
    """An alarm record that happened `age` seconds ago."""
    return {
        "report_id": report_id,
        "cid": cid,
        "cid_code": cid_code,
        "event_time": "",
        "time": str(int(time.time() - age)),
        "utc_event_time": str(int(time.time() - age)),
    }


def _primed() -> SmarthomesecCoordinator:
    """Coordinator that has already seen a baseline record."""
    coord = _coordinator()
    coord.handle_alarm_record({"alarm_event_latest": BURGLARY})
    return coord


# ----------------------------------------------------------------------
# Contact ID parsing
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "cid_code, expected",
    [
        ("1130", "alarm"),     # burglary
        ("1120", "alarm"),     # panic
        ("1137", "alarm"),     # tamper
        ("3130", "restore"),   # burglary restore
        ("1602", None),        # periodic test report
        ("1401", None),        # open/close (disarm)
        ("3401", None),        # open/close (arm)
        ("1301", None),        # AC loss
        ("", None),
        ("abcd", None),
        ("113", None),
    ],
)
def test_cid_classification(cid_code, expected):
    assert SmarthomesecCoordinator.classify_cid(cid_code) == expected


def test_cid_reason_known_and_unknown():
    assert SmarthomesecCoordinator.cid_reason("1130") == "Burglary"
    assert SmarthomesecCoordinator.cid_reason("1120") == "Panic"
    assert SmarthomesecCoordinator.cid_reason("1999") == "CID 1999"


def test_parse_cid_splits_area_and_zone():
    # MT(18) QXYZ(1130) GG(01) CCC(007)
    assert SmarthomesecCoordinator.parse_cid("18113001007") == ("1", "7")


def test_parse_cid_rejects_malformed():
    assert SmarthomesecCoordinator.parse_cid("nope") == (None, None)
    assert SmarthomesecCoordinator.parse_cid("") == (None, None)


# ----------------------------------------------------------------------
# The change detector
# ----------------------------------------------------------------------


def test_first_record_is_baseline_only():
    """alarm_event_latest survives restarts — startup must not re-trigger it."""
    coord = _coordinator()
    assert coord.handle_alarm_record({"alarm_event_latest": BURGLARY}) is None
    assert not coord.is_area_triggered("1")


def test_first_record_is_baseline_even_when_it_is_fresh():
    """The real restart risk: HA restarts moments after an alarm.

    The stale-record check cannot cover this one — the record is seconds old —
    so this pins the baseline guard itself. Deliberate trade-off: a restart
    during a sounding alarm shows no TRIGGERED, in exchange for never inventing
    an alarm at startup.
    """
    coord = _coordinator()
    assert coord.handle_alarm_record({"alarm_event_latest": _record(age=5.0)}) is None
    assert not coord.is_area_triggered("1")


def test_unchanged_record_does_not_retrigger():
    coord = _primed()
    for _ in range(3):
        assert coord.handle_alarm_record({"alarm_event_latest": BURGLARY}) is None
    assert not coord.is_area_triggered("1")


def test_new_recent_alarm_triggers_its_area():
    coord = _primed()
    assert coord.handle_alarm_record({"alarm_event_latest": _record()}) == "alarm"
    assert coord.is_area_triggered("1")
    assert not coord.is_area_triggered("2")


def test_new_but_stale_alarm_does_not_trigger():
    """A record older than the freshness window is history, not a live alarm."""
    coord = _primed()
    old = _record(age=7 * 24 * 3600)
    assert coord.handle_alarm_record({"alarm_event_latest": old}) is None
    assert not coord.is_area_triggered("1")


def test_non_alarm_report_does_not_trigger():
    """Periodic test reports and open/close events must stay quiet."""
    coord = _primed()
    for cid_code in ("1602", "1401", "3401", "1301"):
        coord.handle_alarm_record({"alarm_event_latest": _record(cid_code=cid_code)})
        assert not coord.is_area_triggered("1"), cid_code


def test_restore_record_clears_the_latch():
    coord = _primed()
    coord.handle_alarm_record({"alarm_event_latest": _record(report_id="1")})
    assert coord.is_area_triggered("1")

    verdict = coord.handle_alarm_record(
        {"alarm_event_latest": _record(report_id="2", cid_code="3130")}
    )
    assert verdict == "restore"
    assert not coord.is_area_triggered("1")


def test_missing_record_is_ignored():
    coord = _primed()
    assert coord.handle_alarm_record({}) is None
    assert coord.handle_alarm_record({"alarm_event_latest": {}}) is None


def test_area_falls_back_when_cid_is_unparseable():
    coord = _primed()
    coord.data = {"alarms": {"1": {}, "2": {}}}
    coord.handle_alarm_record({"alarm_event_latest": _record(cid="???")})
    assert coord.is_area_triggered("1")
    assert coord.is_area_triggered("2")


def test_trigger_details_are_recorded():
    coord = _primed()
    coord.status = {
        "data": {"device_status": [{"no": "7", "area": "1", "name": "MK Inngang"}]}
    }
    coord.handle_alarm_record({"alarm_event_latest": _record(report_id="42")})

    last = coord._last_trigger
    assert last["reason"] == "Burglary"
    assert last["cid_code"] == "1130"
    assert last["zone"] == "7"
    assert last["device"] == "MK Inngang"
    assert last["report_id"] == "42"


def test_latch_expires_after_ttl(monkeypatch):
    coord = _primed()
    coord.handle_alarm_record({"alarm_event_latest": _record()})
    assert coord.is_area_triggered("1")

    now = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: now + ALARM_TRIGGER_TTL + 1)
    assert not coord.is_area_triggered("1")


# ----------------------------------------------------------------------
# REST interaction
# ----------------------------------------------------------------------


class _FakeHass:
    async def async_add_executor_job(self, func, *args):
        return func(*args)


async def _refresh(coord, mode: str, alarm_record=None):
    coord.hass = _FakeHass()
    status = {
        "device_status": [],
        "model": [{"area": "1", "mode": mode, "burglar": mode == "arm"}],
    }
    if alarm_record is not None:
        status["alarm_event_latest"] = alarm_record
    coord.update_status = lambda: status
    return await coord._async_update_data()


async def test_armed_state_never_triggers_by_itself():
    """model[].burglar is True whenever armed — it must not mean TRIGGERED."""
    coord = _primed()

    await _refresh(coord, "arm")

    assert not coord.is_area_triggered("1")


async def test_alarm_during_armed_survives_the_refresh():
    """A sounding panel still reports mode=arm; the latch must hold."""
    coord = _primed()

    await _refresh(coord, "arm", alarm_record=_record())

    assert coord.is_area_triggered("1")


async def test_disarm_in_the_same_refresh_wins():
    """Disarm is the acknowledgement — it must beat a fresh alarm record."""
    coord = _primed()

    await _refresh(coord, "disarm", alarm_record=_record())

    assert not coord.is_area_triggered("1")


async def test_rest_disarm_clears_an_existing_latch():
    coord = _primed()
    coord.handle_alarm_record({"alarm_event_latest": _record()})

    await _refresh(coord, "disarm")

    assert not coord.is_area_triggered("1")


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
    coord = _primed()
    coord.handle_alarm_record({"alarm_event_latest": _record()})

    assert _panel(coord, "arm").alarm_state == AlarmControlPanelState.TRIGGERED


def test_panel_returns_to_rest_state_once_cleared():
    coord = _primed()
    coord.handle_alarm_record({"alarm_event_latest": _record()})
    coord.clear_areas_triggered(["1"])

    assert _panel(coord, "arm").alarm_state == AlarmControlPanelState.ARMED_AWAY


def test_panel_ignores_a_latch_on_another_area():
    coord = _primed()
    coord.handle_alarm_record({"alarm_event_latest": _record(cid="18113002007")})

    assert _panel(coord, "arm").alarm_state == AlarmControlPanelState.ARMED_AWAY


def test_trigger_attributes_expose_the_cause():
    coord = _primed()
    coord.handle_alarm_record({"alarm_event_latest": _record(report_id="77")})

    attrs = _panel(coord, "arm").extra_state_attributes
    assert attrs["last_trigger_reason"] == "Burglary"
    assert attrs["last_trigger_cid_code"] == "1130"
    assert attrs["last_trigger_zone"] == "7"
    assert attrs["last_trigger_report_id"] == "77"
    assert attrs["last_trigger_time"].endswith("+00:00")


def test_no_attributes_before_any_alarm():
    assert _panel(_primed(), "arm").extra_state_attributes is None

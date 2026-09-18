"""Tests for the alarm_control_panel state mapping and arm/disarm commands."""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.components.alarm_control_panel import AlarmControlPanelState

from custom_components.smarthomesec import SmarthomesecCoordinator
from custom_components.smarthomesec.alarm_control_panel import SmarthomesecAlarm


def _alarm(mode: str) -> SmarthomesecAlarm:
    alarm = object.__new__(SmarthomesecAlarm)
    alarm._alarm = {"mode": mode}
    return alarm


@pytest.mark.parametrize(
    "mode, expected",
    [
        ("disarm", AlarmControlPanelState.DISARMED),
        ("arm", AlarmControlPanelState.ARMED_AWAY),
        ("home", AlarmControlPanelState.ARMED_HOME),
        ("triggered", AlarmControlPanelState.TRIGGERED),
        ("something_unknown", None),
    ],
)
def test_alarm_state_mapping(mode, expected):
    assert _alarm(mode).alarm_state == expected


def _panel_with_coord() -> SmarthomesecAlarm:
    panel = object.__new__(SmarthomesecAlarm)
    panel.area = "1"
    panel.coord = MagicMock()
    return panel


def test_arm_away_command():
    panel = _panel_with_coord()
    panel.alarm_arm_away("1234")
    panel.coord.set_alarm_mode.assert_called_once_with("1", "arm", "1234")


def test_arm_home_command():
    panel = _panel_with_coord()
    panel.alarm_arm_home("1234")
    panel.coord.set_alarm_mode.assert_called_once_with("1", "home", "1234")


def test_disarm_command():
    panel = _panel_with_coord()
    panel.alarm_disarm("1234")
    panel.coord.set_alarm_mode.assert_called_once_with("1", "disarm", "1234")


# --------------------------------------------------------------------------
# What actually goes over the wire.
#
# These assert on the POSTed payload, not just that the coordinator method was
# called. That gap is how int(pin) survived: every test above mocks the
# coordinator away, so set_alarm_mode's body had no coverage at all -- the same
# well-tested-caller/unasserted-body shape as the config_flow defects in 0.1.17.
# --------------------------------------------------------------------------


def _coord() -> SmarthomesecCoordinator:
    coord = object.__new__(SmarthomesecCoordinator)
    coord.hass = MagicMock()
    # Not the real coroutine: set_alarm_mode hands it to run_coroutine_threadsafe,
    # which is patched out here, so a real one would never be awaited.
    coord.async_request_refresh = MagicMock()
    return coord


def _posted(pin, mode: str = "arm", area: str = "1") -> dict:
    """Run set_alarm_mode and return the payload it handed to the REST layer."""
    coord = _coord()
    with (
        patch.object(SmarthomesecCoordinator, "_rest_call_post") as post,
        patch("custom_components.smarthomesec.time.sleep"),
        patch("custom_components.smarthomesec.asyncio.run_coroutine_threadsafe"),
    ):
        coord.set_alarm_mode(area, mode, pin)

    post.assert_called_once()
    path, payload = post.call_args[0]
    assert path == "panel/mode"
    return payload


def test_the_pin_field_is_named_pincode():
    """Measured 2026-08-16 on this panel, corroborated by BP HomeConnect.

    Yale sends no PIN at all, so it is not a source for either spelling.
    Whether the server validates it is still open -- see PR #20.
    """
    assert "pincode" in _posted("1234")
    assert "pin" not in _posted("1234")


@pytest.mark.parametrize("pin", ["0123", "007", "0000"])
def test_a_leading_zero_in_the_pin_survives(pin):
    """int(pin) turned "0123" into 123, so a PIN starting with 0 was wrong.

    PINs are digit strings; the panel's own Contact ID user field is zero-padded.
    """
    assert _posted(pin)["pincode"] == pin


def test_an_ordinary_pin_is_unchanged():
    assert _posted("1234")["pincode"] == "1234"


def test_the_pin_is_sent_as_a_string_not_a_number():
    """requests form-encodes `data`, so an int would drop the zero on the wire."""
    assert isinstance(_posted("1234")["pincode"], str)


def test_a_missing_code_does_not_raise():
    """alarm_disarm(code=None) is a legal HA call -- int(None) raised TypeError.

    code_arm_required governs arming only, so a disarm can legitimately arrive
    with no code at all.
    """
    assert _posted(None, mode="disarm")["pincode"] == ""


def test_the_rest_of_the_payload_is_unchanged():
    payload = _posted("1234", mode="home", area="2")
    assert payload["area"] == 2  # areas really are numeric, and never zero-padded
    assert payload["mode"] == "home"
    assert payload["format"] == 1


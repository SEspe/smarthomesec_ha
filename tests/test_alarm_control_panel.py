"""Tests for the alarm_control_panel state mapping and arm/disarm commands."""

from unittest.mock import MagicMock

import pytest
from homeassistant.components.alarm_control_panel import AlarmControlPanelState

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

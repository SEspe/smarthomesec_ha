"""Fixes requested in the hacs/default review (Frenck, 2026-11-26).

1. A disarm without a code is refused by the integration, not sent to the panel
   as an empty PIN.
2. A network failure during setup raises ConfigEntryNotReady, so Home Assistant
   retries after a restart. Other setup failures still return False.
"""

from unittest.mock import MagicMock

import pytest
import requests
from homeassistant.exceptions import ServiceValidationError

from custom_components.smarthomesec import _is_connection_error
from custom_components.smarthomesec.alarm_control_panel import SmarthomesecAlarm


def _panel() -> SmarthomesecAlarm:
    panel = object.__new__(SmarthomesecAlarm)
    panel.coord = MagicMock()
    panel.area = "1"
    return panel


@pytest.mark.parametrize("code", [None, ""])
def test_disarm_without_a_code_is_refused(code):
    panel = _panel()
    with pytest.raises(ServiceValidationError):
        panel.alarm_disarm(code)
    panel.coord.set_alarm_mode.assert_not_called()


def test_disarm_with_a_code_is_sent():
    panel = _panel()
    panel.alarm_disarm("1234")
    panel.coord.set_alarm_mode.assert_called_once_with("1", "disarm", "1234")


def test_connection_error_is_retryable():
    assert _is_connection_error(requests.ConnectionError("no route to host"))


def test_timeout_is_retryable():
    assert _is_connection_error(requests.Timeout("timed out"))


def test_connection_error_found_in_the_cause_chain_is_retryable():
    try:
        try:
            raise requests.ConnectionError("refused")
        except requests.ConnectionError as inner:
            raise Exception("Failed to connect to SmartHomeSec: refused") from inner
    except Exception as outer:
        assert _is_connection_error(outer)


def test_a_wrong_password_is_not_retryable():
    """A non-200 login answer is a plain Exception with no network cause: setup fails as before."""
    assert not _is_connection_error(Exception("Login failed: HTTP 401"))

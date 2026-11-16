"""Behaviour tests for the vendor API protection wiring (not just the pure rules).

Covers: polls skip during the cooldown, commands fail fast, the give-up state,
the Live connection flag, and a 42 event clearing give-up.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from custom_components.smarthomesec import SmarthomesecCoordinator
from custom_components.smarthomesec.protection import ConnectionGivenUp, CooldownActive


def _coord() -> SmarthomesecCoordinator:
    coord = object.__new__(SmarthomesecCoordinator)
    coord._shutdown = False
    coord.token = "tok"
    coord.userid = "1"
    coord.wsc = None
    coord.hass = MagicMock()
    return coord


def _http(status: int) -> MagicMock:
    res = MagicMock()
    res.status_code = status
    return res


def test_poll_401_during_cooldown_skips_without_logging_in():
    coord = _coord()
    coord._last_login_at = time.monotonic()  # a login just happened

    with patch(
        "custom_components.smarthomesec.requests.get", return_value=_http(401)
    ), patch.object(SmarthomesecCoordinator, "login") as mock_login:
        with pytest.raises(CooldownActive) as info:
            coord._rest_call_get("panel/cycle")

    mock_login.assert_not_called()
    assert "poll" in str(info.value)


def test_command_401_during_cooldown_fails_fast_with_the_wait():
    coord = _coord()
    coord._last_login_at = time.monotonic()

    with patch(
        "custom_components.smarthomesec.requests.post", return_value=_http(401)
    ), patch.object(SmarthomesecCoordinator, "login") as mock_login:
        with pytest.raises(CooldownActive) as info:
            coord._rest_call_post("panel/mode", {"area": 1})

    mock_login.assert_not_called()
    assert info.value.seconds > 0


def test_poll_401_while_given_up_never_logs_in_even_after_the_cooldown():
    """Give-up stops polls from logging in. Only the Retry button or a reload recovers."""
    coord = _coord()
    coord._gave_up = True
    coord._last_login_at = None  # cooldown long over: the old rule would have allowed a login

    with patch(
        "custom_components.smarthomesec.requests.get", return_value=_http(401)
    ), patch.object(SmarthomesecCoordinator, "login") as mock_login:
        with pytest.raises(ConnectionGivenUp):
            coord._rest_call_get("panel/cycle")

    mock_login.assert_not_called()


def test_command_401_while_given_up_never_logs_in():
    coord = _coord()
    coord._gave_up = True
    coord._last_login_at = None

    with patch(
        "custom_components.smarthomesec.requests.post", return_value=_http(401)
    ), patch.object(SmarthomesecCoordinator, "login") as mock_login:
        with pytest.raises(ConnectionGivenUp):
            coord._rest_call_post("panel/mode", {"area": 1})

    mock_login.assert_not_called()


def test_login_during_cooldown_is_deferred_not_called():
    coord = _coord()
    coord._last_login_at = time.monotonic()

    with patch.object(SmarthomesecCoordinator, "login") as mock_login, patch.object(
        SmarthomesecCoordinator, "_schedule_deferred_login"
    ) as mock_defer:
        started = coord._login_or_defer("test")

    assert started is False
    mock_login.assert_not_called()
    mock_defer.assert_called_once()


def test_login_outside_cooldown_runs_now():
    coord = _coord()
    coord._last_login_at = None

    with patch.object(SmarthomesecCoordinator, "login") as mock_login:
        assert coord._login_or_defer("test") is True

    mock_login.assert_called_once()


def test_fifth_token_failure_gives_up_and_stops_retrying():
    coord = _coord()
    coord._ws_token_errors = 4  # this 42 frame is the fifth failure
    coord.wsc = MagicMock()

    with patch.object(SmarthomesecCoordinator, "delayed_ws_restart") as mock_restart, patch.object(
        SmarthomesecCoordinator, "login"
    ) as mock_login:
        coord.callback("42", '["error","check token error!"]', sender=coord.wsc)

    assert coord._gave_up is True
    mock_restart.assert_not_called()
    mock_login.assert_not_called()
    assert coord.live_connected is False


def test_a_live_42_event_clears_give_up():
    coord = _coord()
    coord._gave_up = True
    coord._ws_token_errors = 5

    coord.callback("42", '{"refreshed_type":"MODE_CHANGE"}', sender=coord.wsc)

    assert coord._gave_up is False
    assert coord._ws_token_errors == 0


def test_live_connection_needs_a_recent_live_event_and_no_failures():
    coord = _coord()
    assert coord.live_connected is False  # no live event seen yet

    coord._last_42_at = time.monotonic()
    assert coord.live_connected is True

    coord._ws_token_errors = 1
    assert coord.live_connected is False

    coord._ws_token_errors = 0
    coord._gave_up = True
    assert coord.live_connected is False


def test_manual_retry_respects_the_cooldown():
    coord = _coord()
    coord._last_login_at = time.monotonic()

    with patch.object(SmarthomesecCoordinator, "login") as mock_login:
        with pytest.raises(CooldownActive):
            coord.manual_retry()

    mock_login.assert_not_called()

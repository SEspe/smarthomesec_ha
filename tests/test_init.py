"""Tests for entry setup/unload, the startup banner, and the WS thread lifecycle."""

import json
import logging

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smarthomesec import SmarthomesecCoordinator
from custom_components.smarthomesec.const import DOMAIN, ISSUE_URL

from .test_coordinator import STATUS_DATA

USER_INPUT = {CONF_NAME: "Home", CONF_USERNAME: "user", CONF_PASSWORD: "secret"}
MANIFEST_PATH = "custom_components/smarthomesec/manifest.json"


def _fake_update_status(self):
    """Stand in for the REST call, populating self.status like the real one."""
    self.status = {"data": STATUS_DATA}
    return STATUS_DATA


async def test_unload_entry_stops_ws_and_clears_data(hass):
    """Unloading must stop the WS thread and drop the entry's hass.data."""
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT)
    entry.add_to_hass(hass)

    with patch.object(SmarthomesecCoordinator, "login"), patch.object(
        SmarthomesecCoordinator, "update_status", autospec=True,
        side_effect=_fake_update_status,
    ), patch.object(SmarthomesecCoordinator, "stop_ws") as mock_stop_ws:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        assert entry.entry_id in hass.data[DOMAIN]

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    mock_stop_ws.assert_called_once()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert entry.entry_id not in hass.data.get(DOMAIN, {})


async def test_startup_banner_logged_once_with_manifest_version(hass, caplog):
    """The banner logs once per load and reports the manifest.json version."""
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT)
    entry.add_to_hass(hass)

    with caplog.at_level(logging.INFO), patch.object(
        SmarthomesecCoordinator, "login"
    ), patch.object(
        SmarthomesecCoordinator, "update_status", autospec=True,
        side_effect=_fake_update_status,
    ), patch.object(SmarthomesecCoordinator, "stop_ws"):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    manifest_version = json.loads(
        (Path(__file__).parents[1] / MANIFEST_PATH).read_text(encoding="utf-8")
    )["version"]

    assert "This is a custom integration!" in caplog.text
    assert f"Version: {manifest_version}" in caplog.text
    assert ISSUE_URL in caplog.text
    # Guards against the banner drifting from the released version.
    assert caplog.text.count("This is a custom integration!") == 1


async def test_startup_banner_survives_missing_version(hass, caplog):
    """A banner failure must never block setup."""
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT)
    entry.add_to_hass(hass)

    with caplog.at_level(logging.INFO), patch(
        "custom_components.smarthomesec.async_get_integration",
        side_effect=RuntimeError("no manifest"),
    ), patch.object(SmarthomesecCoordinator, "login"), patch.object(
        SmarthomesecCoordinator, "update_status", autospec=True,
        side_effect=_fake_update_status,
    ), patch.object(SmarthomesecCoordinator, "stop_ws"):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert "Version: unknown" in caplog.text


def test_manifest_declares_websocket_client_matching_the_test_pin():
    """HA does not ship websocket-client, so the manifest must declare it.

    The manifest pin and requirements_test.txt pin must agree, otherwise CI
    validates a different version than Home Assistant installs.
    """
    root = Path(__file__).parents[1]
    manifest = json.loads((root / MANIFEST_PATH).read_text(encoding="utf-8"))

    manifest_pins = [
        r for r in manifest["requirements"] if r.startswith("websocket-client")
    ]
    assert manifest_pins, "manifest.json must declare websocket-client"

    test_reqs = (root / "requirements_test.txt").read_text(encoding="utf-8")
    test_pins = [
        line.strip()
        for line in test_reqs.splitlines()
        if line.strip().startswith("websocket-client")
    ]

    assert test_pins == manifest_pins, (
        f"manifest.json pins {manifest_pins} but requirements_test.txt pins "
        f"{test_pins} -- keep them in sync"
    )


def test_stop_ws_stops_and_joins_the_thread():
    coord = object.__new__(SmarthomesecCoordinator)
    coord._shutdown = False
    wsc = MagicMock()
    wsc.is_alive.return_value = False
    coord.wsc = wsc

    coord.stop_ws()

    wsc.stop_client.assert_called_once()
    wsc.join.assert_called_once()
    assert coord.wsc is None
    assert coord._shutdown is True


def test_stop_ws_without_client_is_a_noop():
    coord = object.__new__(SmarthomesecCoordinator)
    coord._shutdown = False
    coord.wsc = None

    coord.stop_ws()  # must not raise

    assert coord._shutdown is True


def test_stop_ws_survives_a_failing_stop_client():
    coord = object.__new__(SmarthomesecCoordinator)
    coord._shutdown = False
    wsc = MagicMock()
    wsc.stop_client.side_effect = RuntimeError("socket already gone")
    wsc.is_alive.return_value = False
    coord.wsc = wsc

    coord.stop_ws()  # must still join and clear

    wsc.join.assert_called_once()
    assert coord.wsc is None


def test_delayed_ws_restart_not_scheduled_after_shutdown():
    """A restart requested after unload must not spawn a thread."""
    coord = object.__new__(SmarthomesecCoordinator)
    coord._shutdown = True
    coord.token = "tok"
    coord.wsc = None

    with patch("custom_components.smarthomesec.threading.Thread") as mock_thread:
        coord.delayed_ws_restart(delay=0)

    mock_thread.assert_not_called()
    assert coord.wsc is None


def _login_coordinator():
    """A coordinator with just the attributes login() reads."""
    coord = object.__new__(SmarthomesecCoordinator)
    coord._shutdown = False
    coord.username = "user"
    coord.password = "secret"
    coord.token = "old-token"
    coord.userid = None
    coord.wsc = None
    return coord


def _login_response():
    res = MagicMock()
    res.status_code = 200
    res.json.return_value = {"token": "new-token", "data": {"user_id": "42"}}
    return res


def test_login_from_rest_401_swaps_the_ws_to_the_new_token():
    """A new login invalidates the token the live socket holds.

    Measured 2026-09-06: 59/59 re-logins were followed ~1.5s later by the
    server dropping the WS with "check token error!". So the 401 retry cannot
    leave the WS alone — it must reconnect it itself, which is what turns a
    ~21s blind window (server drop + 20s backoff) into ~2s.
    """
    coord = _login_coordinator()
    old_wsc = MagicMock()
    coord.wsc = old_wsc

    with patch(
        "custom_components.smarthomesec.requests.post", return_value=_login_response()
    ), patch.object(SmarthomesecCoordinator, "delayed_ws_restart") as mock_restart, patch(
        "custom_components.smarthomesec.WSClient"
    ) as mock_ws:
        coord.login(immediate_ws=True)

    mock_restart.assert_not_called()  # no waiting out the 20s backoff
    old_wsc.stop_client.assert_called_once()
    mock_ws.assert_called_once_with(coord, "new-token")
    assert coord.wsc is mock_ws.return_value
    assert coord.token == "new-token"


def test_login_defers_ws_start_by_default():
    """Setup and ForceLogin have no live WS to swap — bring one up via the timer."""
    coord = _login_coordinator()

    with patch(
        "custom_components.smarthomesec.requests.post", return_value=_login_response()
    ), patch.object(SmarthomesecCoordinator, "delayed_ws_restart") as mock_restart:
        coord.login()

    mock_restart.assert_called_once_with(delay=2)
    assert coord.token == "new-token"


def test_login_does_not_sleep():
    """login() runs inside _async_update_data's 20s timeout – no sleeping in it."""
    coord = _login_coordinator()

    with patch(
        "custom_components.smarthomesec.requests.post", return_value=_login_response()
    ), patch.object(SmarthomesecCoordinator, "delayed_ws_restart"), patch(
        "custom_components.smarthomesec.time.sleep"
    ) as mock_sleep:
        coord.login()

    mock_sleep.assert_not_called()


def test_update_token_ignored_after_shutdown():
    """A late REST token rotation must not resurrect the WS client."""
    coord = object.__new__(SmarthomesecCoordinator)
    coord._shutdown = True
    coord.token = "old"
    coord.wsc = None

    with patch("custom_components.smarthomesec.WSClient") as mock_ws:
        coord.update_token("new")

    mock_ws.assert_not_called()
    assert coord.wsc is None
    assert coord.token == "old"  # untouched while unloading


def _callback_coordinator():
    """A coordinator with just the attributes callback() reads for a 42 frame."""
    coord = object.__new__(SmarthomesecCoordinator)
    coord._shutdown = False
    coord.token = "tok"
    coord.wsc = None
    coord._ws_token_errors = 0
    return coord


def test_stale_ws_client_cannot_tear_down_the_current_one():
    """The socket the server drops after a re-login must not kill its successor.

    restart_ws_now() starts a new client immediately, but the old socket can
    still deliver "check token error!" afterwards. Acting on it would stop the
    connection we just brought up.
    """
    coord = _callback_coordinator()
    current = MagicMock()
    coord.wsc = current
    stale = MagicMock()

    coord.callback("42", '["error","check token error!"]', sender=stale)

    current.stop_client.assert_not_called()
    assert coord.wsc is current
    assert coord._ws_token_errors == 0


def test_token_error_does_not_reset_its_own_counter():
    """The error arrives as a 42 frame; falling through reset the counter to 0.

    That made the "second error forces a login" escalation unreachable, and
    logged a misleading "WS parse error" for every token error.
    """
    coord = _callback_coordinator()
    coord.wsc = MagicMock()

    with patch.object(SmarthomesecCoordinator, "delayed_ws_restart") as mock_restart:
        coord.callback("42", '["error","check token error!"]', sender=coord.wsc)

    mock_restart.assert_called_once()
    assert coord._ws_token_errors == 1


def test_second_token_error_forces_a_login():
    """With the counter no longer self-resetting, the escalation is live again."""
    coord = _callback_coordinator()
    coord._ws_token_errors = 1
    coord.wsc = MagicMock()

    with patch.object(SmarthomesecCoordinator, "login") as mock_login, patch.object(
        SmarthomesecCoordinator, "delayed_ws_restart"
    ) as mock_restart:
        coord.callback("42", '["error","check token error!"]', sender=coord.wsc)

    mock_login.assert_called_once()
    mock_restart.assert_not_called()
    assert coord._ws_token_errors == 0


def test_restart_ws_now_swaps_the_client():
    coord = object.__new__(SmarthomesecCoordinator)
    coord._shutdown = False
    coord.token = "fresh"
    old = MagicMock()
    coord.wsc = old

    with patch("custom_components.smarthomesec.WSClient") as mock_ws:
        coord.restart_ws_now()

    old.stop_client.assert_called_once()
    mock_ws.assert_called_once_with(coord, "fresh")
    mock_ws.return_value.start.assert_called_once()
    assert coord.wsc is mock_ws.return_value


def test_restart_ws_now_installs_the_new_client_before_stopping_the_old():
    """Otherwise self.wsc is None in between and the stale-sender guard opens.

    A late "check token error!" from the dying socket would then be acted on and
    schedule a restart on top of the one already in progress.
    """
    coord = object.__new__(SmarthomesecCoordinator)
    coord._shutdown = False
    coord.token = "fresh"
    old = MagicMock()
    coord.wsc = old

    seen = []
    old.stop_client.side_effect = lambda: seen.append(coord.wsc)

    with patch("custom_components.smarthomesec.WSClient") as mock_ws:
        coord.restart_ws_now()

    assert seen == [mock_ws.return_value], "old client stopped before the swap"


def test_restart_ws_now_ignored_after_shutdown():
    """A 401 retry racing with unload must not resurrect the WS thread."""
    coord = object.__new__(SmarthomesecCoordinator)
    coord._shutdown = True
    coord.token = "fresh"
    coord.wsc = None

    with patch("custom_components.smarthomesec.WSClient") as mock_ws:
        coord.restart_ws_now()

    mock_ws.assert_not_called()
    assert coord.wsc is None


# --------------------------------------------------------------------------
# What the server said on a failure.
#
# Before 0.1.19 a non-200 threw away the body entirely: the POST path raised a
# bare "Security error" on 400 and never called res.json()/res.text. PR #20
# reported `POST response: <Response [400]>` and nothing else, because nothing
# else existed to report. These tests exist so that never regresses.
#
# They also guard the token: the old message interpolated self.token, and these
# logs get pasted into public GitHub issues.
# --------------------------------------------------------------------------

TOKEN = "eyJhbGciOiJIUzI1NiJ9.SECRET-TOKEN-MUST-NOT-LEAK"
PIN = "9137"


def _coord_with_token() -> SmarthomesecCoordinator:
    coord = object.__new__(SmarthomesecCoordinator)
    coord.token = TOKEN
    coord.userid = "207643"
    return coord


def _response(status: int, *, json_body=None, text: str = ""):
    res = MagicMock()
    res.status_code = status
    res.text = text
    if json_body is None:
        res.json.side_effect = ValueError("no json")
    else:
        res.json.return_value = json_body
    return res


def _failing_post(status: int, **body):
    """Drive _rest_call_post against a failing response; return the error text."""
    coord = _coord_with_token()
    payload = {"area": 1, "pincode": PIN, "mode": "arm", "format": 1}
    with patch(
        "custom_components.smarthomesec.requests.post",
        return_value=_response(status, **body),
    ):
        with pytest.raises(Exception) as excinfo:
            coord._rest_call_post("panel/mode", payload)
    return str(excinfo.value)


def test_a_400_reports_what_the_server_said():
    """The whole point: a 400 must carry the server's own words."""
    message = _failing_post(
        400, json_body={"code": "021", "message": "Parameter error!", "result": False}
    )

    assert "400" in message
    assert "panel/mode" in message
    assert "021" in message
    assert "Parameter error!" in message


def test_a_400_with_a_non_json_body_still_reports_it():
    message = _failing_post(400, text="<html><body>Bad Request</body></html>")

    assert "non-JSON body" in message
    assert "Bad Request" in message


def test_a_400_with_an_empty_body_says_so():
    """"empty body" is information too -- it rules out a server-side reason."""
    message = _failing_post(400, text="")

    assert "empty body" in message


def test_an_unrecognised_json_body_lists_its_keys():
    message = _failing_post(400, json_body={"surprise": 1, "another": 2})

    assert "another, surprise" in message


def test_the_error_never_leaks_the_token():
    """The pre-0.1.19 message was f"Status: {code} / {self.token} / {self.userid}"."""
    message = _failing_post(400, json_body={"code": "021", "message": "Parameter error!"})

    assert TOKEN not in message
    assert "SECRET-TOKEN-MUST-NOT-LEAK" not in message


def test_the_error_never_leaks_the_pin():
    message = _failing_post(400, json_body={"code": "021", "message": "Parameter error!"})

    assert PIN not in message


def test_the_failure_is_logged_with_the_field_names_but_not_the_values(caplog):
    """Field NAMES are the diagnostic the pincode/pin question needs (PR #20)."""
    with caplog.at_level(logging.ERROR, logger="custom_components.smarthomesec"):
        _failing_post(400, json_body={"code": "021", "message": "Parameter error!"})

    assert "area, format, mode, pincode" in caplog.text
    assert PIN not in caplog.text
    assert TOKEN not in caplog.text


def test_a_500_is_reported_the_same_way():
    """400 no longer has a special branch -- it was only ever "not 200"."""
    message = _failing_post(500, json_body={"code": "999", "message": "Boom"})

    assert "500" in message
    assert "Boom" in message


def test_a_failing_get_reports_the_body_and_hides_the_token():
    coord = _coord_with_token()
    with patch(
        "custom_components.smarthomesec.requests.get",
        return_value=_response(403, json_body={"code": "007", "message": "Forbidden!"}),
    ):
        with pytest.raises(Exception) as excinfo:
            coord._rest_call_get("panel/cycle")

    message = str(excinfo.value)
    assert "403" in message
    assert "panel/cycle" in message
    assert "Forbidden!" in message
    assert TOKEN not in message


@pytest.mark.parametrize(
    "res, expected",
    [
        (None, "no response"),
        (_response(400, text=""), "empty body"),
        (_response(400, text="nope"), "non-JSON body: nope"),
        (_response(400, json_body={"code": "010"}), "code='010'"),
        (_response(400, json_body=["a", "b"]), "JSON body: ['a', 'b']"),
    ],
)
def test_server_said_shapes(res, expected):
    assert SmarthomesecCoordinator._server_said(res) == expected


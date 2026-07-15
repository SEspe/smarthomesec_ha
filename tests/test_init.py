"""Tests for entry setup/unload and the WebSocket thread lifecycle."""

from unittest.mock import MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smarthomesec import SmarthomesecCoordinator
from custom_components.smarthomesec.const import DOMAIN

from .test_coordinator import STATUS_DATA

USER_INPUT = {CONF_NAME: "Home", CONF_USERNAME: "user", CONF_PASSWORD: "secret"}


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

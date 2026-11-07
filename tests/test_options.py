"""Tests for the configurable poll interval (options flow and coordinator)."""

from datetime import timedelta

import pytest
import voluptuous as vol

from homeassistant.data_entry_flow import FlowResultType
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smarthomesec import SmarthomesecCoordinator
from custom_components.smarthomesec.const import (
    CONF_POLL_INTERVAL,
    DOMAIN,
    MIN_REST_POLL_INTERVAL,
    REST_POLL_INTERVAL,
)


def _entry(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user", CONF_PASSWORD: "secret"},
        options=options or {},
    )
    entry.add_to_hass(hass)
    return entry


async def test_options_form_defaults_to_five_minutes(hass):
    entry = _entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
    # The schema's default is what the form shows pre-filled.
    default = result["data_schema"]({})[CONF_POLL_INTERVAL]
    assert default == REST_POLL_INTERVAL == 300


async def test_options_form_rejects_below_the_minimum(hass):
    entry = _entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)

    with pytest.raises(vol.Invalid):
        result["data_schema"]({CONF_POLL_INTERVAL: MIN_REST_POLL_INTERVAL - 1})

    # The minimum itself is accepted.
    validated = result["data_schema"]({CONF_POLL_INTERVAL: MIN_REST_POLL_INTERVAL})
    assert validated[CONF_POLL_INTERVAL] == 60


async def test_options_save_the_chosen_interval(hass):
    entry = _entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_POLL_INTERVAL: 120}
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_POLL_INTERVAL: 120}


def test_coordinator_uses_the_configured_interval(hass):
    coord = SmarthomesecCoordinator(hass, "user", "secret", 120)
    assert coord.update_interval == timedelta(seconds=120)


def test_coordinator_defaults_to_five_minutes(hass):
    coord = SmarthomesecCoordinator(hass, "user", "secret")
    assert coord.update_interval == timedelta(seconds=REST_POLL_INTERVAL)


def test_coordinator_never_polls_faster_than_the_minimum(hass):
    # Guards against a stored or hand-edited option below the floor.
    coord = SmarthomesecCoordinator(hass, "user", "secret", 10)
    assert coord.update_interval == timedelta(seconds=MIN_REST_POLL_INTERVAL)

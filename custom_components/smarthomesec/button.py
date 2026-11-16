"""Retry connection button for SmartHomeSec (spec section 7)."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the Retry connection button."""
    coord = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    async_add_entities([SmarthomesecRetryButton(coord, config_entry.entry_id)])


class SmarthomesecRetryButton(ButtonEntity):
    """Press to start one login and reconnect now, if the cooldown allows."""

    _attr_has_entity_name = True
    _attr_translation_key = "retry_connection"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coord, entry_id: str) -> None:
        self._coord = coord
        self._attr_unique_id = f"{entry_id}_retry_connection"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="SmartHomeSec",
            manufacturer="SmartHomeSec",
        )

    async def async_press(self) -> None:
        """Run the login in the executor. Raises HomeAssistantError during cooldown."""
        await self.hass.async_add_executor_job(self._coord.manual_retry)

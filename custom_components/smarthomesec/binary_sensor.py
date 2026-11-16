"""Support for Smarthomesec Security System binary sensors."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, TYPE_CLASS_BINARY_SENSOR
from .base_entity import SmarthomesecBaseSensor

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a binary sensors for a Smarthomesec device."""

    coord = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    devices = hass.data[DOMAIN][config_entry.entry_id]["binary_sensor_devices"]

    async_add_entities(
        SmarthomesecBinarySensor(coord, device, config_entry.entry_id) for device in devices
    )
    async_add_entities([SmarthomesecLiveConnection(coord, config_entry.entry_id)])


class SmarthomesecLiveConnection(CoordinatorEntity, BinarySensorEntity):
    """On while live WebSocket events arrive; off during give-up or recovery.

    Diagnostic: shows whether the vendor's live channel is working. Alarm state
    still arrives by polling when this is off (spec section 5).
    """

    _attr_has_entity_name = True
    _attr_translation_key = "live_connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, entry_id: str) -> None:
        super().__init__(coord)
        self._attr_unique_id = f"{entry_id}_live_connection"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="SmartHomeSec",
            manufacturer="SmartHomeSec",
        )

    @property
    def is_on(self) -> bool:
        """True while live events are arriving."""
        return self.coordinator.live_connected


class SmarthomesecBinarySensor(SmarthomesecBaseSensor, BinarySensorEntity):
    """A binary sensor implementation for Smarthomesec device."""

#    @property
#    def is_on(self) -> bool:
#        """Return True if the binary sensor is on."""
#        if len(self._device["status_open"]):
#           return (self._device["status_open"][0] == "device_status.dc_open")
#       elif self._device["status_motion"]:
#           return (self._device["status_motion"] == "1")


    @property
    def is_on(self) -> bool:
        """Return True if the binary sensor is on."""
        # ✅ Dørkontakter
        if self._device.get("status_open"):
            return self._device["status_open"][0] == "device_status.dc_open"
        # ✅ PIR-sensorer
        if self._device.get("type") == "device_type.pir":
            # status_motion er alltid tom i praksis (målt 1261/1261 og 142/142
            # 2026-08-16) – panelet fyller den ikke ut. Bevegelse finnes bare
            # som et WS-event, så koordinatoren holder et kort tidsvindu.
            # Feltet leses likevel først, i tilfelle et panel faktisk setter det.
            motion = self._device.get("status_motion")
            if motion:
                return motion == "1"
            return self.coordinator.is_pir_active(self._attr_unique_id)
        return False

    @property
    def device_class(self) -> BinarySensorDeviceClass | None:
        """Return the class of the binary sensor."""
        return TYPE_CLASS_BINARY_SENSOR[self._device["type"]]

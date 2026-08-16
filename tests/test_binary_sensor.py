"""Tests for the binary_sensor is_on / device_class logic."""

import time

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass

from custom_components.smarthomesec import SmarthomesecCoordinator
from custom_components.smarthomesec.binary_sensor import SmarthomesecBinarySensor
from custom_components.smarthomesec.const import PIR_MOTION_TTL


def _coordinator() -> SmarthomesecCoordinator:
    coord = object.__new__(SmarthomesecCoordinator)
    coord._pir_state = {}
    return coord


def _sensor(device: dict, coord=None, device_id="RF:pir1") -> SmarthomesecBinarySensor:
    """Build a sensor without going through HA/CoordinatorEntity wiring."""
    sensor = object.__new__(SmarthomesecBinarySensor)
    sensor._device = device
    sensor._attr_unique_id = device_id
    sensor.coordinator = coord if coord is not None else _coordinator()
    return sensor


def test_door_contact_open():
    device = {"type": "device_type.door_contact", "status_open": ["device_status.dc_open"]}
    assert _sensor(device).is_on is True


def test_door_contact_closed():
    device = {"type": "device_type.door_contact", "status_open": ["device_status.dc_close"]}
    assert _sensor(device).is_on is False


def test_door_contact_no_status():
    # Empty status_open is falsy -> falls through to the default False.
    device = {"type": "device_type.door_contact", "status_open": []}
    assert _sensor(device).is_on is False


def test_pir_motion_detected():
    device = {"type": "device_type.pir", "status_motion": "1"}
    assert _sensor(device).is_on is True


def test_pir_no_motion():
    device = {"type": "device_type.pir", "status_motion": "0"}
    assert _sensor(device).is_on is False


def test_pir_missing_signal_defaults_off():
    device = {"type": "device_type.pir"}
    assert _sensor(device).is_on is False


@pytest.mark.parametrize(
    "device_type, expected",
    [
        ("device_type.door_contact", BinarySensorDeviceClass.DOOR),
        ("device_type.pir", BinarySensorDeviceClass.MOTION),
    ],
)
def test_device_class(device_type, expected):
    assert _sensor({"type": device_type}).device_class == expected


# ----------------------------------------------------------------------
# PIR motion is synthesised from the WS event, because status_motion is
# never populated by the panel — measured empty in 1261/1261 and 142/142
# samples on 2026-08-16, including refreshes taken right after a PIR event.
# Before 0.1.14 that made every motion entity permanently off.
# ----------------------------------------------------------------------


def test_pir_turns_on_from_a_ws_event():
    coord = _coordinator()
    coord._set_pir_active = SmarthomesecCoordinator._set_pir_active.__get__(coord)
    coord._pir_state["RF:pir1"] = time.monotonic() + PIR_MOTION_TTL

    assert _sensor({"type": "device_type.pir", "status_motion": ""}, coord).is_on is True


def test_pir_turns_off_when_the_window_expires(monkeypatch):
    coord = _coordinator()
    coord._pir_state["RF:pir1"] = time.monotonic() + PIR_MOTION_TTL
    sensor = _sensor({"type": "device_type.pir", "status_motion": ""}, coord)
    assert sensor.is_on is True

    now = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: now + PIR_MOTION_TTL + 1)
    assert sensor.is_on is False


def test_pir_window_is_per_device():
    coord = _coordinator()
    coord._pir_state["RF:pir1"] = time.monotonic() + PIR_MOTION_TTL

    device = {"type": "device_type.pir", "status_motion": ""}
    assert _sensor(device, coord, "RF:pir1").is_on is True
    assert _sensor(device, coord, "RF:pir2").is_on is False


def test_a_real_status_motion_still_wins_if_a_panel_ever_sets_it():
    coord = _coordinator()          # no window open
    assert _sensor({"type": "device_type.pir", "status_motion": "1"}, coord).is_on is True


def test_door_contact_ignores_the_pir_window():
    coord = _coordinator()
    coord._pir_state["RF:door"] = time.monotonic() + PIR_MOTION_TTL
    device = {"type": "device_type.door_contact", "status_open": ["device_status.dc_close"]}

    assert _sensor(device, coord, "RF:door").is_on is False

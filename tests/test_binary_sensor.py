"""Tests for the binary_sensor is_on / device_class logic."""

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass

from custom_components.smarthomesec.binary_sensor import SmarthomesecBinarySensor


def _sensor(device: dict) -> SmarthomesecBinarySensor:
    """Build a sensor without going through HA/CoordinatorEntity wiring."""
    sensor = object.__new__(SmarthomesecBinarySensor)
    sensor._device = device
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

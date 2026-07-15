"""Tests for the SmarthomesecCoordinator data helpers and normalization."""

from custom_components.smarthomesec import SmarthomesecCoordinator
from custom_components.smarthomesec.const import TYPE_CLASS_BINARY_SENSOR

STATUS_DATA = {
    "device_status": [
        {
            "device_id": "d1",
            "type": "device_type.door_contact",
            "type_no": "4",
            "status_open": ["device_status.dc_open"],
        },
        {
            "device_id": "d2",
            "type": "device_type.pir",
            "type_no": "9",
            "status_motion": "1",
        },
        {"device_id": "d3", "type": "device_type.keypad", "type_no": "1"},
    ],
    "model": [
        {"area": "1", "mode": "disarm"},
        {"area": "2", "mode": "arm"},
    ],
}


def _coordinator() -> SmarthomesecCoordinator:
    """Bare coordinator instance without DataUpdateCoordinator wiring."""
    return object.__new__(SmarthomesecCoordinator)


def test_update_device_types_partitions_pir_and_door():
    coord = _coordinator()
    coord._update_device_types(STATUS_DATA)
    assert coord._pir_devices == {"d2"}
    assert coord._door_devices == {"d1"}


def test_get_devices_by_type_filters_to_binary_sensors():
    coord = _coordinator()
    coord.status = {"data": STATUS_DATA}
    devices = coord.get_devices_by_type(TYPE_CLASS_BINARY_SENSOR)
    assert {d["device_id"] for d in devices} == {"d1", "d2"}  # keypad excluded


def test_get_alarms_filters_by_area():
    coord = _coordinator()
    coord.status = {"data": STATUS_DATA}
    alarms = coord.get_alarms(["1"])
    assert len(alarms) == 1
    assert alarms[0]["area"] == "1"


async def test_async_update_data_normalizes_devices_and_alarms():
    coord = _coordinator()

    class _FakeHass:
        async def async_add_executor_job(self, func, *args):
            return func(*args)

    coord.hass = _FakeHass()
    coord.update_status = lambda: STATUS_DATA

    data = await coord._async_update_data()

    assert set(data["devices"]) == {"d1", "d2", "d3"}
    assert set(data["alarms"]) == {"1", "2"}
    assert data["alarms"]["1"]["mode"] == "disarm"
    assert data["devices"]["d2"]["status_motion"] == "1"

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
)


DOMAIN = "smarthomesec"

INTEGRATION_TITLE = "SmartHomeSec"

ISSUE_URL = "https://github.com/SEspe/smarthomesec_ha/issues"

# Logges én gang ved oppstart. Versjonen hentes fra manifest.json i runtime
# (via async_get_integration), slik at den ikke kan komme ut av synk her.
STARTUP_MESSAGE = """
-------------------------------------------------------------------
%s
Version: %s
This is a custom integration!
If you have any issues with this you need to open an issue here:
%s
-------------------------------------------------------------------
"""

#API_BASEHOST = "smarthomesec.bydemes.com"
# Norwegian provider...
API_BASEHOST = "smartalarm.alarm24.no/"

API_BASEPATH = "REST/v2"

TYPE_TRANSLATION = {
    "device_type.door_contact": "Door contact",
    "device_type.keypad": "Keypad",
    "device_type.pir": "Motion detector",
    "device_type.ipcam": "IP camera",
}
TYPE_CLASS_BINARY_SENSOR = {
    "device_type.door_contact": BinarySensorDeviceClass.DOOR,
    "device_type.pir": BinarySensorDeviceClass.MOTION,
}

ALARM_AREAS = ["1"]

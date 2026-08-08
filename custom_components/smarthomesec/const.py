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
# Norwegian provider, classic SmartHomeSec tenant (old app / old accounts):
#API_BASEHOST = "smartalarm.alarm24.no"
# Vesta tenant – the new Android app provisions accounts here. Same Climax
# backend/IP as alarm24, but a separate account database selected by hostname,
# so alarm24 credentials and vesta credentials are NOT interchangeable.
# Verified 2026-07-23: login with the app's email + md5 password succeeds here
# and returns a token, while alarm24 rejects the same account with code 010.
API_BASEHOST = "portal.vestasecurity.eu"

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

# --- Utløst alarm (TRIGGERED) ------------------------------------------------
#
# REST (panel/cycle) rapporterer modus i model[].mode, og "triggered" er den
# kjente verdien for utløst alarm – den mappes direkte i alarm_control_panel.
# Panelet sender i tillegg WS-eventer når en alarm er aktiv, men det EKSAKTE
# formatet er IKKE målt ennå (se CLAUDE.md, "Alarm-trigger"). Derfor:
#
#   * maskineriet under er formatuavhengig (latch + TTL + kvittering),
#   * gjenkjenningen er bevisst konservativ – heller en manglende TRIGGERED enn
#     en falsk (dette er et alarmsystem; falsk utløst-status er verre enn treg),
#   * ukjente event-typer logges én gang på INFO med rå payload, slik at den
#     virkelige alarmmeldingen kan leses rett ut av loggen og legges inn her.
#
# Utvid ALARM_TRIGGER_TOKENS når det faktiske formatet er målt.

ALARM_MODE_TRIGGERED = "triggered"

# Event-typer vi allerede håndterer eksplisitt. Alt annet logges én gang.
KNOWN_EVENT_TYPES = ("DEVICE_STATUS", "MODE_CHANGE", "REPORT")

# Felt i WS-eventdata som kan bære en alarmtilstand.
ALARM_STATE_FIELDS = (
    "mode",
    "status",
    "event",
    "event_type",
    "report_type",
    "alarm_type",
    "type",
)

# Verdier som betyr "alarmen er utløst". Substring-match, case-insensitivt.
# Merk: "alarm" er bevisst IKKE med – ordet finnes i for mange nøytrale felt
# (områdenavn, "alarm_status": "normal") og ville gitt falske utløsninger.
ALARM_TRIGGER_TOKENS = (
    "triggered",
    "burglar",
    "panic",
    "duress",
    "hold_up",
    "holdup",
)

# Verdier som betyr "ikke lenger utløst" (avstilt/kvittert/gjenopprettet).
ALARM_CLEAR_TOKENS = (
    "disarm",
    "restore",
    "cancel",
    "abort",
    "clear",
)

# Hvor lenge en WS-utløst alarm holdes i TRIGGERED uten at REST bekrefter den.
# Latchen fjernes uansett når REST melder disarm, eller når et clear-event kommer.
ALARM_TRIGGER_TTL = 300.0

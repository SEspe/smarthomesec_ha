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
# MÅLT 2026-08-09 i en 8,5 timers debug-logg (se CLAUDE.md, "Alarm trigger"):
#
#   * WS-eventene bærer INGEN tilstand. Hele repertoaret er
#       DEVICE_STATUS {'device_id': ..., 'area': '1'}
#       REPORT        {'type': 'MODE_CHANGE', 'area': '1'}
#       MODE_CHANGE   {}
#     WS er en ren dørklokke: "noe har endret seg, hent REST på nytt".
#     Derfor er token-matching mot WS-payload (0.1.9) fjernet – det fantes
#     ikke ett felt å matche mot.
#   * model[].burglar betyr ARMERT, ikke utløst: arm ⇒ True (42/42),
#     disarm ⇒ False (108/108). Å bruke det som trigger ville satt panelet
#     permanent i TRIGGERED så snart alarmen ble påslått.
#   * model[].mode var kun "arm"/"disarm" i hele loggen. "triggered" er aldri
#     observert; mappingen beholdes som livrem, men er trolig død kode.
#   * Det eneste faktiske alarmsignalet er data["alarm_event_latest"]:
#       {'report_id': '383748205', 'cid': '18113001007', 'cid_code': '1130',
#        'event_time': '', 'time': ..., 'utc_event_time': '1785838065'}
#     Dette er siste alarm NOENSINNE (her: en ekte innbruddsalarm 2026-08-04,
#     bekreftet av bruker), ikke et live-flagg. En ny alarm er derfor en
#     ENDRING av report_id med ferskt utc_event_time.

ALARM_MODE_TRIGGERED = "triggered"

# Event-typer vi allerede håndterer eksplisitt. Alt annet logges én gang.
KNOWN_EVENT_TYPES = ("DEVICE_STATUS", "MODE_CHANGE", "REPORT")

# Nøkkelen i panel/cycle-data som bærer siste alarmhendelse.
ALARM_EVENT_KEY = "alarm_event_latest"

# Hvor ferskt utc_event_time må være for at hendelsen skal regnes som live.
# Beskytter mot å utløse alarm på historikk – f.eks. ved oppstart mot en
# gammel hendelse, eller hvis panelet spiller av en eldre rapport på nytt.
ALARM_EVENT_MAX_AGE = 600.0

# Contact ID (Ademco). cid = MT(2) + QXYZ(4) + GG(2) + CCC(3), f.eks.
# "18 1130 01 007" = melding 18, hendelse 1130, område 01, sone 007.
# cid_code = QXYZ: Q=1 ny hendelse, Q=3 gjenoppretting; XYZ 100–199 er
# alarmklassen (innbrudd, brann, panikk ...). Alt annet – 1602 testrapport,
# 1401/3401 av-/påslag, 1301 strømbrudd – skal IKKE utløse alarm.
CID_LENGTH = 11
CID_ALARM_QUALIFIER = "1"
CID_RESTORE_QUALIFIER = "3"
CID_ALARM_CODE_MIN = 100
CID_ALARM_CODE_MAX = 199

# XYZ → lesbar årsak. Kun de vanlige; ukjente vises som "CID <kode>".
CID_REASONS = {
    100: "Medical",
    110: "Fire",
    120: "Panic",
    121: "Duress",
    122: "Silent panic",
    130: "Burglary",
    131: "Perimeter",
    132: "Interior",
    133: "24-hour zone",
    134: "Entry/exit",
    137: "Tamper",
    139: "Burglary verified",
}

# Hvor lenge en alarm holdes i TRIGGERED uten ny bekreftelse. Latchen fjernes
# uansett når REST melder disarm, eller når en restore-hendelse kommer.
ALARM_TRIGGER_TTL = 300.0

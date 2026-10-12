"""Hold PIN-er, passord og token utenfor loggene.

Funnet 2026-10-12 i eierens egen debug-logg: `set_alarm_mode payload` logget
PIN-en i klartekst, og tokenet sto i fire linjer til (`Token:`, WS-URL-en,
`POST JSON`, og `DEVICE STATUS FULL` – GET-svaret ekkoer tokenet). 0.1.19
fjernet tokenet bare fra FEILmeldinger. Debug-logger er nettopp det brukere
limer inn i offentlige GitHub-issues, og dokumentasjonen vår ber dem slå det på.

To lag:

1. `redact()` brukes eksplisitt der vi vet at en hemmelighet ellers ville
   havnet i loggen.
2. `RedactFilter` sitter på integrasjonens loggere og vasker HVER melding –
   også unntak/traceback – før noen handler ser den. Så en ny loggelinje kan
   ikke gjeninnføre lekkasjen ved et uhell.

Mønstrene er bevisst snevre: de treffer en NØKKEL med en VERDI (`'pincode':
'1234'`, `token=...`, `api_token=...`) eller et JWT. Ord som "token" i vanlig
tekst ("check token error!", "WS token error (1)") og serverkoder (`'code':
'000'`) står urørt, ellers mister loggen det den er til for.
"""

from __future__ import annotations

import logging
import re

MASK = "***"

# Nøkler hvis VERDI aldri skal logges. "code" er bevisst ikke med: det er
# serverens svarkode ("000", "996"), og den trenger vi å se.
SECRET_KEYS = ("pincode", "pin", "password", "api_token", "token")

_KEYS = "|".join(SECRET_KEYS)

# Dict-repr: 'pincode': '1234'  /  "token": "eyJ..."  – tom verdi ('') beholdes,
# fordi "ingen PIN sendt" er nyttig å kunne se og ikke er en hemmelighet.
# Verdien kan ikke krysse et anførselstegn: med (.+?) slukte en TOM pincode
# resten av dicten fram til neste felts anførselstegn (fanget av en test).
_QUOTED = re.compile(r"""(['"])(%s)\1(\s*:\s*)(['"])([^'"\n]+)\4""" % _KEYS, re.IGNORECASE)

# URL/cookie/header: token=eyJ...  api_token=...;  pincode=1234&
_ASSIGNED = re.compile(r"""\b(%s)=([^&\s'";,]+)""" % _KEYS, re.IGNORECASE)

# Selve tokenet, hvor det enn står ("Token: eyJ...", i et unntak, i en URL).
# Tokenet er et JWT (iss=climax-mqtt-api), og et JWT starter alltid med "eyJ".
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*")


def redact(value):
    """Return `value` with secrets masked.

    Strings are scrubbed by pattern; dicts and lists are copied with the
    values of secret keys replaced, at any depth. Anything else is returned
    unchanged. Never mutates its argument - callers log the result, and the
    original may still be needed (it is the payload being sent).
    """
    if isinstance(value, str):
        value = _QUOTED.sub(lambda m: f"{m[1]}{m[2]}{m[1]}{m[3]}{m[4]}{MASK}{m[4]}", value)
        value = _ASSIGNED.sub(lambda m: f"{m[1]}={MASK}", value)
        return _JWT.sub(MASK, value)
    if isinstance(value, dict):
        return {
            k: (MASK if isinstance(k, str) and k.lower() in SECRET_KEYS and v not in ("", None)
                else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return type(value)(redact(v) for v in value)
    return value


class RedactFilter(logging.Filter):
    """Mask secrets in every record before any handler formats it."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pylint: disable=broad-except
            # A broken format string is the caller's bug; do not hide the
            # record, and do not let the filter raise.
            return True
        clean = redact(message)
        if clean != message:
            # Only rewrite a record that actually carried a secret. Untouched
            # records keep msg/args as logged, which is what HA's log viewer
            # groups repeated messages by.
            record.msg = clean
            record.args = None
        if record.exc_info and not record.exc_text:
            # Handlers format the traceback later via exc_text if it is set,
            # so setting it here is what keeps a token in an exception
            # message out of the log.
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
        return True


_FILTER = RedactFilter()

# Logger-filtre arves IKKE av barn-loggere, så hver modul-logger må ha sitt.
LOGGER_NAMES = (
    "custom_components.smarthomesec",
    "custom_components.smarthomesec.ws_client",
    "custom_components.smarthomesec.alarm_control_panel",
    "custom_components.smarthomesec.binary_sensor",
    "custom_components.smarthomesec.base_entity",
    "custom_components.smarthomesec.config_flow",
    "custom_components.smarthomesec.redact",
)


def install() -> None:
    """Attach the filter to every logger this integration uses. Idempotent."""
    for name in LOGGER_NAMES:
        logger = logging.getLogger(name)
        if _FILTER not in logger.filters:
            logger.addFilter(_FILTER)

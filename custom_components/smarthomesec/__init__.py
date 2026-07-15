"""Custom integration to integrate SmartHomeSec supported alarms with Home Assistant."""

import asyncio
import logging
import requests
import hashlib
import time
import json
import threading


from functools import partial
from datetime import timedelta

import voluptuous as vol
import async_timeout

from custom_components.smarthomesec.ws_client import WSClient

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import (
    CONF_NAME,
    CONF_PASSWORD,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import DOMAIN as HOMEASSISTANT_DOMAIN, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from homeassistant.loader import async_get_integration

from .const import (
    DOMAIN,
    API_BASEHOST,
    API_BASEPATH,
    INTEGRATION_TITLE,
    ISSUE_URL,
    STARTUP_MESSAGE,
    TYPE_CLASS_BINARY_SENSOR,
    ALARM_AREAS,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_NAME): cv.string,
                vol.Required(CONF_USERNAME): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.ALARM_CONTROL_PANEL,
]

# Hvor lenge vi venter på at WS-tråden avslutter ved unload.
WS_THREAD_JOIN_TIMEOUT = 10


async def handle_async_init_result(hass: HomeAssistant, domain: str, conf: dict) -> None:
    """Handle the result of the async_init to issue deprecated warnings."""
    flow = hass.config_entries.flow
    await flow.async_init(domain, context={"source": SOURCE_IMPORT}, data=conf)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration from YAML (legacy)."""

    if DOMAIN not in config:
        return True

    conf = config[DOMAIN]
    hass.async_create_task(handle_async_init_result(hass, DOMAIN, conf))

    return True


async def _async_log_startup_message(hass: HomeAssistant) -> None:
    """Logg oppstartsbanner én gang – versjon leses fra manifest.json."""
    if DOMAIN in hass.data:
        return

    try:
        version = (await async_get_integration(hass, DOMAIN)).version
    except Exception:  # pylint: disable=broad-except
        # Banneret er kun informativt – det skal aldri stoppe oppsettet.
        version = "unknown"

    _LOGGER.info(STARTUP_MESSAGE, INTEGRATION_TITLE, version, ISSUE_URL)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up this integration using UI."""

    await _async_log_startup_message(hass)

    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    try:
        coordinator = SmarthomesecCoordinator(hass, username, password)

        # Først login (blokkerende → executor)
        await hass.async_add_executor_job(coordinator.login)

        # Så første refresh
        await coordinator.async_config_entry_first_refresh()

        # Hent binary sensors
        binary_sensor_devices = await hass.async_add_executor_job(
            partial(coordinator.get_devices_by_type, TYPE_CLASS_BINARY_SENSOR)
        )
        _LOGGER.debug("Binary sensor devices: %s", binary_sensor_devices)

        # Hent alarmområder
        alarm_areas = await hass.async_add_executor_job(
            partial(coordinator.get_alarms, ALARM_AREAS)
        )
        _LOGGER.debug("Alarm areas: %s", alarm_areas)

    except Exception as ex:
        _LOGGER.error("Failed to connect to SmartHomeSec: %s", ex)
        return False

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "binary_sensor_devices": binary_sensor_devices,
        "alarm_areas": alarm_areas,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and stop the WebSocket thread it owns.

    Without this, the WSClient thread outlives the entry: a reload leaves the old
    thread reconnecting with a stale token alongside the new one, and the two race
    over the shared token/error state.
    """
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if not unload_ok:
        return False

    domain_data = hass.data.get(DOMAIN, {})
    data = domain_data.pop(entry.entry_id, None)

    if data is not None:
        # Blocking (closes the socket and joins the thread) → run in executor.
        await hass.async_add_executor_job(data["coordinator"].stop_ws)

    if not domain_data:
        hass.data.pop(DOMAIN, None)

    return True


class SmarthomesecCoordinator(DataUpdateCoordinator):


    def _update_device_types(self, status):
        self._pir_devices = set()
        self._door_devices = set()

        for device in status["device_status"]:
            device_id = device.get("device_id")
            type_no = device.get("type_no")

            if type_no == "9":
                self._pir_devices.add(device_id)
            elif type_no == "4":
                self._door_devices.add(device_id)

    def stop_ws(self) -> None:
        """Stopp WS-klienten og vent på at tråden avslutter.

        Blokkerende (join) – må kjøres i executor, aldri på event-loopen.
        Setter _shutdown slik at pending delayed_ws_restart ikke gjenoppliver
        tråden etter unload.
        """
        self._shutdown = True

        wsc = self.wsc
        self.wsc = None

        if wsc is None:
            return

        try:
            wsc.stop_client()
        except Exception as ex:
            _LOGGER.debug("Error while stopping WS client: %s", ex)

        wsc.join(timeout=WS_THREAD_JOIN_TIMEOUT)

        if wsc.is_alive():
            _LOGGER.warning(
                "WS thread still alive %ss after stop request", WS_THREAD_JOIN_TIMEOUT
            )
        else:
            _LOGGER.debug("WS thread stopped")

    def update_token(self, new_token):
        _LOGGER.debug("Updating REST token → restarting WS client")

        if self._shutdown:
            _LOGGER.debug("Ignoring token update – entry is unloading")
            return

        self.token = new_token

        # Stopp gammel WSClient helt
        if self.wsc is not None:
            try:
                self.wsc.stop_client()
            except Exception:
                pass
            self.wsc = None

        # Start WSClient på nytt, identisk med login()
        # La til IF her.  Blir den kjørt flere ganger?
        if self.wsc is None and self.token:
            self.wsc = WSClient(self, self.token)
            self.wsc.start()




    def __init__(self, hass: HomeAssistant, username: str, password: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Smarthomesec",
            update_interval=timedelta(seconds=3600),
        )

        self.hass = hass
        self.username = username
        self.password = password
        self.token: str | None = None
        self.userid: str | None = None
        self.status: dict | None = None
        self.wsc: WSClient | None = None
        self._shutdown: bool = False

    async def _async_update_data(self):
        """Fetch data from API endpoint and normalize it."""
        try:
            ret: dict = {"devices": {}, "alarms": {}}

            async with async_timeout.timeout(20):
                status = await self.hass.async_add_executor_job(self.update_status)

                for device in status["device_status"]:
                    device_id = device["device_id"]
                    ret["devices"][device_id] = device

                for alarm in status["model"]:
                    area_id = alarm["area"]
                    ret["alarms"][str(area_id)] = alarm

                return ret

        except Exception as err:
            if isinstance(err, asyncio.TimeoutError):
                _LOGGER.warning("Timeout from API – using last known data")
                if self.last_update_success:
                    return self.data
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    def login(self, restart_ws: bool = True) -> None:
        """Login to SmartHomeSec and (optionally) restart the WebSocket client.

        REST-tokenet har ~5 min TTL, mens WS-tokenet bare presenteres ved connect
        – en levende WS bryr seg ikke om at REST-tokenet rulleres. Derfor kaller
        401-retry i _rest_call_get/_rest_call_post med restart_ws=False: de
        trenger bare et friskt token, og skal ikke rive ned en frisk WS.
        """

        res = None
        try:
            payload = {
                "account": self.username,
                "password": hashlib.md5(self.password.encode("utf-8")).hexdigest(),
                "pw_encrypted": "hashed",
                "login_entry": "web",
            }
            headers = {
                "cookie": "isPrivacy=1;",
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            }

            res = requests.post(
                f"https://{API_BASEHOST}/{API_BASEPATH}/auth/login",
                data=payload,
                headers=headers,
                timeout=20,
            )

            if res.status_code != 200:
                raise Exception(f"Status: {res.status_code}")
        except Exception as ex:
            raise Exception(f"Failed to connect to SmartHomeSec: {ex}") from ex

        try:
            json_dict = res.json()
            self.token = json_dict["token"]
            self.userid = json_dict["data"]["user_id"]

            _LOGGER.debug("Token: %s", self.token)

            if restart_ws:
                _LOGGER.debug("Starting WS after login via delayed restart")
                self.delayed_ws_restart(delay=2)
            else:
                _LOGGER.debug("Token refreshed for REST – leaving WS untouched")

        except Exception as ex:
            raise Exception(f"Failed to connect to SmartHomeSec: {ex}") from ex

        _LOGGER.debug("Logged in")

    def _rest_call_get(self, path: str):
        res = None
        status_code = 0
        loop = 0

        if not self.token:
            self.login()

        while status_code != 200 and loop < 2:
            try:
                headers = {
                    "cookie": f"isPrivacy=1; api_token={self.token}; id={self.userid}; cookiePath=%2FByDemes%2F0%2F0%2F",
                    "token": f"{self.token}",
                }
                params = {
                    "_": round(time.time() * 1000),
                }
                res = requests.get(
                    f"https://{API_BASEHOST}/{API_BASEPATH}/{path}",
                    params=params,
                    headers=headers,
                    timeout=20,
                )

            except Exception as ex:
                raise Exception(f"Failed to connect to SmartHomeSec: {ex}") from ex

            status_code = res.status_code
            try:
                if status_code == 401:
                    # Kun nytt REST-token – WS lever videre på sitt eget token.
                    self.login(restart_ws=False)
                    loop += 1
            except Exception as ex:
                raise Exception(f"Security error: {ex}") from ex

        if status_code != 200:
            raise Exception(f"Status: {res.status_code} / {self.token} / {self.userid}")

        try:
            json_dict = res.json()
            return json_dict
        except Exception as ex:
            raise Exception(f"Failed to parse GET response from SmartHomeSec: {ex}") from ex

    def _rest_call_post(self, path: str, payload: dict):
        res = None
        status_code = 0
        loop = 0

        _LOGGER.debug("set_alarm_mode payload: %s", payload)

        if not self.token:
            self.login()

        while status_code != 200 and loop < 2:
            try:
                headers = {
                    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "cookie": f"isPrivacy=1; api_token={self.token}; id={self.userid}; cookiePath=%2FByDemes%2F0%2F0%2F",
                    "token": f"{self.token}",
                }
                params = {
                    "_": round(time.time() * 1000),
                }

                res = requests.post(
                    f"https://{API_BASEHOST}/{API_BASEPATH}/{path}",
                    params=params,
                    headers=headers,
                    data=payload,
                    timeout=20,
                )

                _LOGGER.debug("POST response: %s", res)

            except Exception as ex:
                raise Exception(f"Failed to connect to SmartHomeSec: {ex}") from ex

            status_code = res.status_code

            try:
                if status_code == 401:
                    # Kun nytt REST-token – WS lever videre på sitt eget token.
                    self.login(restart_ws=False)
                    loop += 1
                    continue
                if status_code == 400:
                    raise Exception("Security error")
            except Exception as ex:
                raise Exception(f"Security error: {ex}") from ex

            if status_code != 200:
                _LOGGER.error(
                    "Status: %s / %s / %s / %s",
                    res.status_code,
                    self.token,
                    self.userid,
                    res.json(),
                )
                raise Exception(
                    f"Status: {res.status_code} / {self.token} / {self.userid}"
                )

        # -----------------------------
        # PARSE JSON + TOKEN SYNC
        # -----------------------------
        try:
            json_dict = res.json()
            _LOGGER.debug("POST JSON: %s", json_dict)

            # 🔥 TOKEN SYNC – oppdater WS-token hvis API returnerer nytt token
            new_token = json_dict.get("token")
            if new_token and new_token != self.token:
                _LOGGER.debug("REST returned new token → updating WS token")
                self.update_token(new_token)

            return json_dict

        except Exception as ex:
            raise Exception(f"Failed to parse POST response from SmartHomeSec: {ex}") from ex

    def update_status(self):
        """Retrieve full status with retry."""
        for attempt in range(3):
            try:
                self.status = self._rest_call_get("panel/cycle")
                self._update_device_types(self.status["data"])
                _LOGGER.debug("Retrieving devices status")
                return self.status["data"]
            except Exception as e:
                if attempt < 2:
                    _LOGGER.debug("Retrying update_status (%s/3)...", attempt + 2)
                    time.sleep(1)
                else:
                    _LOGGER.error("update_status failed after retries: %s", e)
                    raise

    def get_devices_by_type(self, types):
        devices = []
        for device in self.status["data"]["device_status"]:
            if device["type"] in types:
                devices.append(device)
        return devices

    def get_alarms(self, areas):
        alarms = []
        for alarm in self.status["data"]["model"]:
            if alarm["area"] in areas:
                alarms.append(alarm)
        return alarms

    def set_alarm_mode(self, area, mode, pin):
        payload = {
            "area": int(area),
            "pincode": int(pin),
            "mode": mode,
            "format": 1,
        }
        _LOGGER.debug("set_alarm_mode")
        self._rest_call_post("panel/mode", payload)

        time.sleep(1)

        asyncio.run_coroutine_threadsafe(
            self.async_request_refresh(),
            self.hass.loop,
        )



    def _set_pir_active(self, device_id):
        if not hasattr(self, "_pir_state"):
            self._pir_state = {}

        self._pir_state[device_id] = True

        def reset():
            time.sleep(5)
            self._pir_state[device_id] = False
            asyncio.run_coroutine_threadsafe(
                self.async_request_refresh(),
                self.hass.loop,
            )

        threading.Thread(target=reset, daemon=True).start()

        asyncio.run_coroutine_threadsafe(
            self.async_request_refresh(),
            self.hass.loop,
        )


#    def delayed_ws_restart(self, delay=20):
#  Øke delay til fra 6 til 30 sec
#        time.sleep(30)
#        if self.token and self.wsc is None:
#            _LOGGER.debug("Retrying WS with existing token")
#            self.wsc = WSClient(self, self.token)
#            self.wsc.start()
#            threading.Thread(target=delayed_ws_restart, daemon=True).start()
#        return
    def delayed_ws_restart(self, delay=20):
        """Restart WS etter delay (kjøres i egen tråd)."""

        if self._shutdown:
            _LOGGER.debug("WS restart not scheduled – entry is unloading")
            return

        def _restart():
            _LOGGER.debug("WS restart scheduled in %s seconds", delay)
            time.sleep(delay)

            if self._shutdown:
                _LOGGER.debug("WS restart aborted – entry was unloaded")
                return

            if self.token:
                _LOGGER.debug("Retrying WS with existing token")

                try:
                    if self.wsc:
                        self.wsc.stop_client()
                except Exception:
                    pass

                self.wsc = None

                try:
                    self.wsc = WSClient(self, self.token)
                    self.wsc.start()
                except Exception as e:
                    _LOGGER.error("Failed to restart WS: %s", e)

        threading.Thread(target=_restart, daemon=True).start()

    def callback(self, message, data):
        # 🔥 Token error → tving full login
#        if message == "44" or ("check token error" in str(data)):
#            _LOGGER.warning("WS token not ready – retrying with delay")
#
#            # ✅ stopp WS
#            try:
#                if self.wsc:
#                    self.wsc.stop_client()
#            except:
#                pass
#            self.wsc = None

#            # ✅ IKKE login
#            # ✅ bare vent og prøv WS igjen


        # ----------------------------------------
        # ✅ RESET token error når WS faktisk connecter
        # ----------------------------------------
# flyttet til først 42 event
#        if message == "WebSocketConnect":
#            _LOGGER.debug("WS connected → reset token error counter")
#            self._ws_token_errors = 0
#            return



        if message == "44" or ("check token error" in str(data)):

            # 🔢 init teller hvis ikke finnes
            if not hasattr(self, "_ws_token_errors"):
                self._ws_token_errors = 0

            self._ws_token_errors += 1

            _LOGGER.warning(
                "WS token error (%s) – handling...", self._ws_token_errors
            )

            # ✅ stopp WS
            try:
                if self.wsc:
                    self.wsc.stop_client()
            except Exception:
                pass

            self.wsc = None

            # --------------------------------------------------
            # 🔥 LOGIKK
            # --------------------------------------------------

            if self._ws_token_errors >= 2:
                # ❗ token er mest sannsynlig invalid → hent ny
                _LOGGER.warning("Too many token errors → forcing login")

                self._ws_token_errors = 0

                try:
                    self.login()
                except Exception as e:
                    _LOGGER.error("Login failed after token error: %s", e)

            else:
                # ✅ første gang → gi backend tid
                _LOGGER.warning("WS token not ready – retrying with delay")

                try:
                    self.delayed_ws_restart()
                except Exception as e:
                    _LOGGER.error("Delayed WS restart failed: %s", e)




        if message == "WebSocketDisconnect":

            _LOGGER.warning("WS disconnected")

            try:
                if self.wsc:
                    self.wsc.stop_client()
            except:
                pass

            self.wsc = None

            # ✅ IKKE restart her
            # La token-handleren eller WSClient gjøre det

            return


        if message == "ForceLogin":
            _LOGGER.warning("WS silent → forcing full login()")
            self.token = None
            try:
                self.wsc.stop_client()
            except:
                pass
            self.wsc = None
            self.login()
            return


        # Socket.IO ping
        if message == "3":
            return

        # Socket.IO event
        if message == "42":
            _LOGGER.debug("WS RAW: %s", data)


            # ✅ WS er faktisk OK nå
            if hasattr(self, "_ws_token_errors"):
                if self._ws_token_errors != 0:
                    _LOGGER.debug("WS healthy → reset token error counter")
                self._ws_token_errors = 0



            #
            # Parse SmartHomeSec format:
            # 42["token","{\"refreshed_type\":\"DEVICE_STATUS\",\"data\":{...}}"]
            #
            try:
                outer = json.loads(data)          # ["token", "{json}"]
                inner = json.loads(outer[1])      # {"refreshed_type": "...", "data": {...}}
            except Exception as e:
                _LOGGER.warning("WS parse error: %s", e)
                asyncio.run_coroutine_threadsafe(
                    self.async_request_refresh(),
                    self.hass.loop
                )
                return

            event_type = inner.get("refreshed_type")
            event_data = inner.get("data", {})

            _LOGGER.debug("WS EVENT: %s | %s", event_type, event_data)

            #
            # 🔥 DEVICE_STATUS → dør åpen/lukket
            #
            if event_type == "DEVICE_STATUS":

#           Hent ut device typer
                device_id = event_data.get("device_id")
                if device_id in getattr(self, "_pir_devices", set()):
                    _LOGGER.debug("PIR triggered: %s", device_id)
                    self._set_pir_active(device_id)


                _LOGGER.debug("DEVICE STATUS FULL: %s", self.status)
                # Umiddelbar refresh
                asyncio.run_coroutine_threadsafe(
                    self.async_request_refresh(),
                    self.hass.loop
                )



                # Liten delay for å hente riktig REST-status
                def delayed_refresh():
                    time.sleep(0.5)
                    asyncio.run_coroutine_threadsafe(
                        self.async_request_refresh(),
                        self.hass.loop
                    )

                threading.Thread(target=delayed_refresh, daemon=True).start()
                return

            #
            # 🔥 MODE_CHANGE → alarmstatus endret
            #
            if event_type == "MODE_CHANGE":
                asyncio.run_coroutine_threadsafe(
                    self.async_request_refresh(),
                    self.hass.loop
                )
                return

            #
            # 🔥 REPORT → generelle endringer
            #
            if event_type == "REPORT":
                asyncio.run_coroutine_threadsafe(
                    self.async_request_refresh(),
                    self.hass.loop
                )
                return

            #
            # Fallback for ukjente eventer
            #
            asyncio.run_coroutine_threadsafe(
                self.async_request_refresh(),
                self.hass.loop
            )
            return

"""Custom integration to integrate SmartHomeSec supported alarms with Home Assistant."""

import asyncio
import logging
import requests
import hashlib
import time
from custom_components.smarthomesec.ws_client import WSClient
import voluptuous as vol
import async_timeout

from functools import partial
from datetime import timedelta

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import (
    CONF_NAME,
    CONF_PASSWORD,
    CONF_USERNAME,
    Platform,
)
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.core import DOMAIN as HOMEASSISTANT_DOMAIN, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, API_BASEHOST, API_BASEPATH, TYPE_CLASS_BINARY_SENSOR, ALARM_AREAS

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


async def handle_async_init_result(hass: HomeAssistant, domain: str, conf: dict):
    """Handle the result of the async_init to issue deprecated warnings."""
    flow = hass.config_entries.flow
    await flow.async_init(domain, context={"source": SOURCE_IMPORT}, data=conf)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration."""

    if DOMAIN not in config:
        return True

    conf = config[DOMAIN]

    hass.async_create_task(handle_async_init_result(hass, DOMAIN, conf))

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up this integration using UI."""

    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    try:
        coordinator = SmarthomesecCoordinator(hass, username, password)
        
        # ✅ gjør login først (i executor)
        await hass.async_add_executor_job(coordinator.login)

        # ✅ så refresh
        await coordinator.async_config_entry_first_refresh()
# Org        await coordinator.async_config_entry_first_refresh()

        partial_func = partial(coordinator.get_devices_by_type, TYPE_CLASS_BINARY_SENSOR)
        binary_sensor_devices = await hass.async_add_executor_job(partial_func)
        _LOGGER.debug(binary_sensor_devices)

        partial_func = partial(coordinator.get_alarms, ALARM_AREAS)
        alarm_areas = await hass.async_add_executor_job(partial_func)
        _LOGGER.debug(alarm_areas)

    except Exception as ex:
        _LOGGER.error("Failed to connect to SmartHomeSec: " + str(ex))
        return False

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {}
    hass.data.setdefault(DOMAIN, {})[entry.entry_id]["coordinator"] = coordinator
    hass.data.setdefault(DOMAIN, {})[entry.entry_id]["binary_sensor_devices"] = binary_sensor_devices
    hass.data.setdefault(DOMAIN, {})[entry.entry_id]["alarm_areas"] = alarm_areas

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


class SmarthomesecCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, username, password):
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name="Smarthomesec",
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(seconds=3600),
        )

        """Initialize object."""
        self.hass = hass
        self.username = username
        self.password = password
        self.token = None
        self.userid = None
        self.status = None
        self.wsc = None

    async def _async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        try:
            # Note: asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            ret = {}
            ret["devices"] = {}
            ret["alarms"] = {}
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
#            raise UpdateFailed(f"Error communicating with API: {str(err)}")
            if isinstance(err, asyncio.TimeoutError):
                _LOGGER.warning("Timeout from API – using last known data")
                if self.last_update_success:
                    return self.data
            raise UpdateFailed(f"Error communicating with API: {err}")






    def login(self):

        res = None
        try:
            payload = {
                "account": self.username,
                "password": hashlib.md5(self.password.encode('utf-8')).hexdigest(),
                "pw_encrypted": "hashed",
                "login_entry": "web"
            }
            headers = {
                "cookie": "isPrivacy=1;",
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            }

            res = requests.post(f'https://{API_BASEHOST}/{API_BASEPATH}/auth/login', data=payload, headers=headers)

            if res.status_code != 200:
                raise Exception(f"Status: {res.status_code}")
        except Exception as ex:
            raise Exception("Failed to connect to SmartHomeSec: " + str(ex))

        try:
            json_dict = res.json()
            self.token = json_dict["token"]
            self.userid = json_dict["data"]["user_id"]

            _LOGGER.debug(self.token)
            _LOGGER.debug("Added a litte TOKEN  wait")
            import time
            time.sleep(2)

            if self.wsc is None:
#                self.wsc = WSClient(self, self.token)
#                self.wsc.run_once(duration=15)
#
                self.wsc = WSClient(self, self.token)
                self.wsc.start()
            
        except Exception as ex:
            raise Exception("Failed to connect to SmartHomeSec: " + str(ex))
        
        _LOGGER.debug("Added a litte LOGIN wait")
        import time
        time.sleep(2)
        _LOGGER.debug("Logged in")

    def _rest_call_get(self, path):
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
                res = requests.get(f'https://{API_BASEHOST}/{API_BASEPATH}/{path}', params=params, headers=headers)


            except Exception as ex:
                raise Exception("Failed to connect to SmartHomeSec: " + str(ex))

            status_code = res.status_code
            try:
                if status_code == 401:
                    self.login()
                    loop += 1
                    
            except Exception as ex:
                raise Exception("Security error: " + str(ex))

        if status_code != 200:
            raise Exception(f"Status: {res.status_code} / {self.token} / {self.userid}")

        try:
            json_dict = res.json()
            # _LOGGER.debug(json_dict)

            return json_dict
        except Exception as ex:
            raise Exception("Failed to connect to do a GET on SmartHomeSec: " + str(ex))

    def _rest_call_post(self, path, payload):
        res = None
        status_code = 0
        loop = 0

        _LOGGER.debug(f"set_alarm_mode: {payload}")

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
                res = requests.post(f'https://{API_BASEHOST}/{API_BASEPATH}/{path}', params=params, headers=headers, data=payload)

                _LOGGER.debug(res)


            except Exception as ex:
                raise Exception("Failed to connect to SmartHomeSec: " + str(ex))

            status_code = res.status_code
            try:
                if status_code == 401:
                    self.login()
                    loop += 1
                    continue
                elif status_code == 400:
                    raise Exception("Security error")
            except Exception as ex:
                raise Exception("Security error: " + str(ex))

            if status_code != 200:
                _LOGGER.error(f"Status: {res.status_code} / {self.token} / {self.userid} / {res.json()}")
                raise Exception(f"Status: {res.status_code} / {self.token} / {self.userid}")

        try:
            json_dict = res.json()
            _LOGGER.debug(json_dict)
            return json_dict
        except Exception as ex:
            raise Exception("Failed to connect to do a GET on SmartHomeSec: " + str(ex))

#    def update_status(self):
#        self.status = self._rest_call_get("panel/cycle")
#        _LOGGER.debug("Retrieveing devices status")
#        return self.status["data"]
#
#    modded with retry
    def update_status(self):
        import time

        for attempt in range(3):
            try:
                self.status = self._rest_call_get("panel/cycle")
                _LOGGER.debug("Retrieveing devices status")
                return self.status["data"]
            except Exception as e:
                if attempt < 2:
                    _LOGGER.debug("Retrying update_status (%s/3)...", attempt + 2)
                    time.sleep(1)  # ✅ liten pause før retry
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
            "format": 1
        }
        _LOGGER.debug("set_alarm_mode")
        self._rest_call_post("panel/mode", payload)
            # liten pause før refresh
        time.sleep(1)

        asyncio.run_coroutine_threadsafe(
            self.async_request_refresh(),
            self.hass.loop
        )

    def callback(self, message, data):

        if message == "WebSocketDisconnect":
            self.wsc.stop_client()
            self.wsc = None
            _LOGGER.warning("WS disconnected – restarting")
            self.wsc = WSClient(self, self.token)
            self.wsc.start()
            return

        if message == "3":
            return

        #
        # 🔥 Socket.IO event (42)
        #
        if message == "42":

            # Først: logg rådata (som i din gamle versjon)
            _LOGGER.debug("Callback : %s / %s", message, data)
            _LOGGER.info("WS EVENT RAW: %s", data)

            # Parse event
            try:
                outer = json.loads(data)          # ["token","{json}"]
                inner = json.loads(outer[1])      # {"refreshed_type": "...", ...}
                event_type = inner.get("refreshed_type")
                event_data = inner.get("data", {})
            except Exception:
                _LOGGER.warning("WS: failed to parse event: %s", data)
                # fallback: gjør vanlig refresh
                asyncio.run_coroutine_threadsafe(
                    self.async_request_refresh(),
                    self.hass.loop
                )
                return

            _LOGGER.info("WS EVENT: type=%s data=%s", event_type, event_data)

            #
            # 🔥 DEVICE_STATUS (dør, PIR, etc.)
            #
            if event_type == "DEVICE_STATUS":
                # Første refresh
                asyncio.run_coroutine_threadsafe(
                    self.async_request_refresh(),
                    self.hass.loop
                )

                # Liten delay før REST har riktig status
                import threading
                def delayed_refresh():
                    import time
                    time.sleep(0.5)
                    asyncio.run_coroutine_threadsafe(
                        self.async_request_refresh(),
                        self.hass.loop
                    )

                threading.Thread(target=delayed_refresh).start()
                return

            #
            # 🔥 MODE_CHANGE (alarmstatus endret via annen enhet)
            #
            if event_type == "MODE_CHANGE":
                asyncio.run_coroutine_threadsafe(
                    self.async_request_refresh(),
                    self.hass.loop
                )
                return

            #
            # 🔥 REPORT (generelle endringer)
            #
            if event_type == "REPORT":
                asyncio.run_coroutine_threadsafe(
                    self.async_request_refresh(),
                    self.hass.loop
                )
                return

            #
            # 🔥 Fallback for ukjente eventer
            #
            asyncio.run_coroutine_threadsafe(
                self.async_request_refresh(),
                self.hass.loop
            )
            return

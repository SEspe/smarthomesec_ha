"""Config flow for integration."""

import logging
import requests
import hashlib
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import (
    CONF_NAME,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, API_BASEHOST, API_BASEPATH

_LOGGER = logging.getLogger(__name__)

# Match login()'s timeout; without one a black-holed host hangs the executor
# thread instead of failing the flow.
LOGIN_TIMEOUT = 20

# Login is rate-limited per SOURCE IP, not per account: ~3 failures and the
# server stops answering for 5 minutes. Worth its own message, because
# retrying – the obvious response to "invalid auth" – is the wrong move.
LOCKOUT_CODES = {"018", "044"}

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class SmarthomesecConfigFlowHandler(ConfigFlow, domain=DOMAIN):
    """Smarthomesec config flow."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initiated by the user."""
        errors = {}

        if user_input is not None:
            self._async_abort_entries_match(user_input)
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]

            try:
                await self.hass.async_add_executor_job(test_host_connection, username, password)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except RateLimited:
                errors["base"] = "rate_limited"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

            else:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_import(self, user_input: dict[str, Any]) -> ConfigFlowResult:
        """Import the yaml config."""
        self._async_abort_entries_match(
            {
                CONF_NAME: user_input[CONF_NAME],
                CONF_USERNAME: user_input[CONF_USERNAME],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
        )
        username = user_input[CONF_USERNAME]
        password = user_input[CONF_PASSWORD]
        try:
            await self.hass.async_add_executor_job(test_host_connection, username, password)
        except CannotConnect:
            return self.async_abort(reason="cannot_connect")
        except InvalidAuth:
            return self.async_abort(reason="invalid_auth")
        except RateLimited:
            return self.async_abort(reason="rate_limited")
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            return self.async_abort(reason="unknown")

        return self.async_create_entry(
            title=user_input.get(CONF_NAME, "smarthomesec"),
            data={
                CONF_NAME: user_input[CONF_NAME],
                CONF_USERNAME: username,
                CONF_PASSWORD: password,
            },
        )


def test_host_connection(username: str, password: str) -> None:
    """Verify the host answers and that it accepts these credentials.

    Mirrors __init__.login()'s success criteria on purpose: result true AND a
    token present. Anything the flow lets through must also survive
    async_setup_entry, which does json_dict["token"] and would otherwise raise
    KeyError long after the user was told the config was fine. That is exactly
    what happened when the provider moved tenants (0.1.6): the account existed,
    the password was right, and the wrong host rejected it.

    Raises CannotConnect (host unreachable / unusable reply), InvalidAuth
    (server answered and said no) or RateLimited (~3 failures, per source IP).
    """

    payload = {
        "account": username,
        "password": hashlib.md5(password.encode("utf-8")).hexdigest(),
        "pw_encrypted": "hashed",
        "login_entry": "web",
    }
    headers = {
        "cookie": "isPrivacy=1;",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    }

    try:
        res = requests.post(
            f"https://{API_BASEHOST}/{API_BASEPATH}/auth/login",
            data=payload,
            headers=headers,
            timeout=LOGIN_TIMEOUT,
        )
    except requests.RequestException as ex:
        # Only a transport failure lands here. Everything below is the server
        # talking to us, which is a different answer to the user.
        _LOGGER.error("Failed to reach SmartHomeSec: %s", ex)
        raise CannotConnect(f"Failed to reach SmartHomeSec: {ex}") from ex

    # The body is read on EVERY status, not just 200. Which HTTP status the
    # server pairs with code 010 has never been measured, and measuring it
    # costs one of the ~3 attempts before the per-IP lockout – so this is
    # written not to care. tools/login_probe cannot answer it either: it reads
    # the body on both the success and the HTTPError path.
    try:
        body = res.json()
    except ValueError:
        body = None

    if isinstance(body, dict):
        code = str(body.get("code", ""))
        message = str(body.get("message", ""))

        if code in LOCKOUT_CODES:
            _LOGGER.error("SmartHomeSec login rate-limited: %s (%s)", message, code)
            raise RateLimited(f"{message} (code {code})")

        if body.get("result") and body.get("token"):
            return

        # The server answered and did not give us a token. The reply is the
        # same code 010 "Login failure!" whether the password is wrong, the
        # account does not exist, or it lives on another tenant – so the
        # message cannot be made more specific than "it said no".
        _LOGGER.error(
            "SmartHomeSec rejected the login: %s (code %s, HTTP %s)",
            message or "no message",
            code or "none",
            res.status_code,
        )
        raise InvalidAuth(f"{message or 'login rejected'} (code {code or 'none'})")

    if res.status_code != 200:
        _LOGGER.error(
            "SmartHomeSec returned HTTP %s with an unreadable body", res.status_code
        )
        raise CannotConnect(f"Status: {res.status_code}")

    # HTTP 200 that is not JSON: reachable, but not a SmartHomeSec API.
    _LOGGER.error("SmartHomeSec returned a non-JSON reply to the login")
    raise CannotConnect("Login reply was not JSON")


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate the server rejected the credentials."""


class RateLimited(HomeAssistantError):
    """Error to indicate the login is rate-limited for this source IP."""

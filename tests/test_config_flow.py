"""Tests for the SmartHomeSec config flow."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smarthomesec.config_flow import (
    CannotConnect,
    InvalidAuth,
    RateLimited,
)

# Imported under a private alias on purpose: the real name starts with "test_",
# and pytest would collect it as a test case in this module.
from custom_components.smarthomesec.config_flow import (
    test_host_connection as _check_host,
)
from custom_components.smarthomesec.const import DOMAIN

USER_INPUT = {CONF_NAME: "Home", CONF_USERNAME: "user", CONF_PASSWORD: "secret"}


async def test_user_flow_creates_entry(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    with patch(
        "custom_components.smarthomesec.config_flow.test_host_connection",
        return_value=None,
    ), patch(
        "custom_components.smarthomesec.async_setup_entry", return_value=True
    ) as mock_setup:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        await hass.async_block_till_done()

    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["title"] == "Home"
    assert result2["data"] == USER_INPUT
    assert len(mock_setup.mock_calls) == 1


async def test_user_flow_cannot_connect(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.smarthomesec.config_flow.test_host_connection",
        side_effect=CannotConnect,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_user_flow_unknown_error(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.smarthomesec.config_flow.test_host_connection",
        side_effect=RuntimeError("boom"),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "unknown"}


async def test_duplicate_entry_aborts(hass):
    MockConfigEntry(domain=DOMAIN, data=USER_INPUT).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.smarthomesec.config_flow.test_host_connection",
        return_value=None,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "already_configured"


async def test_user_flow_invalid_auth(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.smarthomesec.config_flow.test_host_connection",
        side_effect=InvalidAuth,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "invalid_auth"}


async def test_user_flow_rate_limited(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.smarthomesec.config_flow.test_host_connection",
        side_effect=RateLimited,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "rate_limited"}


# ----------------------------------------------------------------------
# test_host_connection itself. Every test above patches it out, so until
# 0.1.17 its body had ZERO coverage - which is why four defects lived in
# twenty lines: a TypeError from "..." + ex that replaced the real
# exception, a raise inside the try that caught itself, no timeout, and a
# reply body that was never read at all.
# ----------------------------------------------------------------------


def _reply(status=200, body=None, json_error=False):
    res = MagicMock()
    res.status_code = status
    if json_error:
        res.json.side_effect = ValueError("no json")
    else:
        res.json.return_value = body
    return res


def _post(**kwargs):
    return patch("custom_components.smarthomesec.config_flow.requests.post", **kwargs)


def test_accepts_a_login_that_returns_a_token():
    body = {"code": "000", "result": True, "token": "jwt", "data": {"user_id": "1"}}
    with _post(return_value=_reply(body=body)):
        assert _check_host("user", "secret") is None


def test_a_network_error_is_cannot_connect():
    with _post(side_effect=requests.ConnectionError("no route")):
        with pytest.raises(CannotConnect):
            _check_host("user", "secret")


def test_the_request_has_a_timeout():
    """Without one a black-holed host hangs the executor thread forever."""
    body = {"code": "000", "result": True, "token": "jwt"}
    with _post(return_value=_reply(body=body)) as mock_post:
        _check_host("user", "secret")

    assert mock_post.call_args.kwargs["timeout"] > 0


def test_the_password_is_md5_hashed_like_login():
    body = {"code": "000", "result": True, "token": "jwt"}
    with _post(return_value=_reply(body=body)) as mock_post:
        _check_host("user", "secret")

    sent = mock_post.call_args.kwargs["data"]
    assert sent["password"] == "5ebe2294ecd0e0f08eab7690d2a6ee69"  # md5("secret")
    assert sent["pw_encrypted"] == "hashed"


@pytest.mark.parametrize("status", [200, 401, 403])
def test_a_rejected_login_is_invalid_auth_whatever_the_status(status):
    """Which HTTP status the server pairs with code 010 has never been measured.

    Measuring it costs one of the ~3 attempts before the per-IP lockout, so the
    check is written not to depend on it. This test is the reason that is safe.
    """
    body = {"code": "010", "result": False, "message": "Login failure!"}
    with _post(return_value=_reply(status=status, body=body)):
        with pytest.raises(InvalidAuth):
            _check_host("user", "secret")


def test_a_200_without_a_token_is_invalid_auth_not_success():
    """The 0.1.6 failure: right password, account on another tenant.

    If this passed the flow, the entry would be created and only blow up later
    as a KeyError on json_dict["token"] inside async_setup_entry.
    """
    with _post(return_value=_reply(body={"code": "000", "result": True})):
        with pytest.raises(InvalidAuth):
            _check_host("user", "secret")


@pytest.mark.parametrize("code", ["018", "044"])
def test_the_per_ip_lockout_is_reported_as_rate_limited(code):
    """Not invalid_auth: retrying is the wrong response, and it is what the
    user will do if told their password is wrong."""
    body = {"code": code, "result": False, "message": "Retry after 5 minutes"}
    with _post(return_value=_reply(body=body)):
        with pytest.raises(RateLimited):
            _check_host("user", "secret")


def test_a_non_json_200_is_cannot_connect():
    """Reachable, but not a SmartHomeSec API - a captive portal, say."""
    with _post(return_value=_reply(json_error=True)):
        with pytest.raises(CannotConnect):
            _check_host("user", "secret")


def test_a_server_error_with_no_body_is_cannot_connect():
    with _post(return_value=_reply(status=502, json_error=True)):
        with pytest.raises(CannotConnect):
            _check_host("user", "secret")


def test_the_error_path_does_not_raise_typeerror():
    """The original bug, pinned directly.

    `_LOGGER.error("..." + ex)` raised TypeError *while handling* the real
    exception, so it replaced it: the flow's `except CannotConnect` never
    matched and the user always saw "unknown".
    """
    with _post(side_effect=requests.Timeout("timed out")):
        with pytest.raises(CannotConnect) as excinfo:
            _check_host("user", "secret")

    assert not isinstance(excinfo.value, TypeError)
    assert isinstance(excinfo.value.__cause__, requests.Timeout)


# ----------------------------------------------------------------------
# The YAML import path. Same three failures, but it aborts instead of
# re-showing the form, so each reason needs its own abort string.
# ----------------------------------------------------------------------


async def _import_flow(hass, side_effect):
    with patch(
        "custom_components.smarthomesec.config_flow.test_host_connection",
        side_effect=side_effect,
    ), patch("custom_components.smarthomesec.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_IMPORT}, data=USER_INPUT
        )
        await hass.async_block_till_done()
    return result


async def test_import_flow_creates_entry(hass):
    result = await _import_flow(hass, None)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == USER_INPUT


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (CannotConnect, "cannot_connect"),
        (InvalidAuth, "invalid_auth"),
        (RateLimited, "rate_limited"),
    ],
)
async def test_import_flow_aborts_with_the_matching_reason(hass, error, reason):
    result = await _import_flow(hass, error)

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == reason

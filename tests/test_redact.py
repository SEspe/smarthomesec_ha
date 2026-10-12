"""No PIN, password or token may reach the log — at any level.

Found 2026-10-12 in the owner's own debug log: the arm/disarm payload was
logged with the PIN in clear, and the token sat in four more lines. Debug
logs are what users paste into public GitHub issues, and our docs ask them to
turn debug on.

The end-to-end tests drive the real code paths at DEBUG and search the whole
captured log for the secret. They do not check that a particular line looks
right — a leak in a line nobody thought of fails them just the same.
"""

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from custom_components.smarthomesec import SmarthomesecCoordinator, redact
from custom_components.smarthomesec.redact import MASK, RedactFilter
from custom_components.smarthomesec.ws_client import WSClient

# A syntactically real JWT (header {"alg":"HS256"}) and a PIN with a leading
# zero — the kind 0.1.18 was about.
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJjbGltYXgtbXF0dC1hcGkifQ.c2lnbmF0dXJlLXZhbHVl"
PIN = "0987"
MOD = "custom_components.smarthomesec"


@pytest.fixture
def debug_log(caplog):
    caplog.set_level(logging.DEBUG, logger=MOD)
    caplog.set_level(logging.DEBUG, logger=f"{MOD}.ws_client")
    return caplog


def _assert_clean(caplog):
    text = caplog.text + "\n".join(r.getMessage() for r in caplog.records)
    assert JWT not in text, "token leaked into the log"
    assert JWT.split(".")[0] + "." not in text, "token header leaked into the log"
    assert PIN not in text, "PIN leaked into the log"


# ----------------------------------------------------------------------
# The patterns
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, must_not_contain",
    [
        ("{'area': 1, 'pincode': '%s', 'mode': 'arm'}" % PIN, PIN),
        ('{"pincode": "%s"}' % PIN, PIN),
        ("{'result': True, 'token': '%s'}" % JWT, JWT),
        ("wss://host/ws/socket.io/?token=%s&transport=websocket&EIO=4" % JWT, JWT),
        ("isPrivacy=1; api_token=%s; id=7" % JWT, JWT),
        ("Token: %s" % JWT, JWT),
        ("Failed: 401 for %s" % JWT, JWT),
        ("pincode=%s&mode=arm" % PIN, PIN),
        ("{'password': 'hunter2'}", "hunter2"),
    ],
)
def test_secrets_are_masked(raw, must_not_contain):
    assert must_not_contain not in redact.redact(raw)
    assert MASK in redact.redact(raw)


@pytest.mark.parametrize(
    "text",
    [
        '["error","check token error!"]',
        "WS token error (1) – handling...",
        "Token refreshed → swapping WS to the new token",
        "{'result': True, 'code': '000', 'message': 'OK!'}",
        "HTTP 400 - code='996', message='PIN Code Error'",
        "{'area': 1, 'pincode': '', 'mode': 'disarm'}",  # "no PIN sent" stays visible
        "Panel event 415929802: Open/close (cid_code=1401, zone/user 1)",
    ],
)
def test_ordinary_log_text_is_left_alone(text):
    """Over-masking would cost the log what it exists for."""
    assert redact.redact(text) == text


def test_dicts_are_copied_not_mutated():
    """The payload being logged is the payload being SENT — it must not change."""
    payload = {"area": 1, "pincode": PIN, "nested": {"token": JWT}}
    clean = redact.redact(payload)

    assert payload["pincode"] == PIN and payload["nested"]["token"] == JWT
    assert clean == {"area": 1, "pincode": MASK, "nested": {"token": MASK}}


# ----------------------------------------------------------------------
# The filter: a safety net for lines nobody has written yet
# ----------------------------------------------------------------------


def test_the_filter_is_on_every_integration_logger():
    for name in redact.LOGGER_NAMES:
        assert any(isinstance(f, RedactFilter) for f in logging.getLogger(name).filters), name


def test_a_future_careless_log_line_is_still_masked(debug_log):
    logging.getLogger(MOD).debug("someone logs %s and %s", {"pincode": PIN}, JWT)
    _assert_clean(debug_log)


def test_a_token_inside_an_exception_traceback_is_masked(debug_log):
    try:
        raise RuntimeError("401 for token=%s" % JWT)
    except RuntimeError:
        logging.getLogger(MOD).exception("request failed")

    _assert_clean(debug_log)
    assert "request failed" in debug_log.text


def test_records_without_secrets_keep_their_args(debug_log):
    """HA groups repeated log lines by msg/args; don't flatten what needs no masking."""
    logging.getLogger(MOD).debug("WebSocket reconnect in %s seconds...", 4)

    record = debug_log.records[-1]
    assert record.args == (4,)


# ----------------------------------------------------------------------
# End to end: the five places that leaked on 2026-10-12
# ----------------------------------------------------------------------


def _http(body):
    res = MagicMock()
    res.status_code = 200
    res.json.return_value = body
    return res


def _coordinator():
    coord = object.__new__(SmarthomesecCoordinator)
    coord._shutdown = False
    coord.username = "user"
    coord.password = "secret-password"
    coord.token = JWT
    coord.userid = "7"
    coord.wsc = None
    coord.hass = MagicMock()
    coord.async_request_refresh = MagicMock()
    return coord


def test_arming_logs_neither_pin_nor_token(debug_log):
    """Was: set_alarm_mode payload: {..., 'pincode': '<PIN>', ...} and POST JSON with the token."""
    coord = _coordinator()

    with patch(f"{MOD}.requests.post", return_value=_http({"result": True, "token": JWT})), patch(
        f"{MOD}.time.sleep"
    ), patch(f"{MOD}.asyncio.run_coroutine_threadsafe"):
        coord.set_alarm_mode("1", "arm", PIN)

    _assert_clean(debug_log)
    assert "pincode" in debug_log.text  # the field NAME is still there to debug with


def test_login_logs_no_token_and_no_password(debug_log):
    """Was: Token: <JWT>."""
    coord = _coordinator()
    coord.token = None

    with patch(
        f"{MOD}.requests.post",
        return_value=_http({"token": JWT, "data": {"user_id": "7"}}),
    ), patch.object(SmarthomesecCoordinator, "delayed_ws_restart"):
        coord.login()

    _assert_clean(debug_log)
    assert "secret-password" not in debug_log.text
    assert "Logged in" in debug_log.text


def test_a_device_status_event_does_not_dump_the_token(debug_log):
    """Was: DEVICE STATUS FULL: {...} — the GET reply echoes the token byte for byte."""
    coord = _coordinator()
    coord.wsc = MagicMock()
    coord._ws_token_errors = 0
    coord._logged_event_types = set()
    coord._pir_devices = set()
    coord.status = {"result": True, "token": JWT, "data": {"model": []}}
    frame = json.dumps(["id", json.dumps({"refreshed_type": "DEVICE_STATUS", "data": {"device_id": "RF:1"}})])

    with patch(f"{MOD}.asyncio.run_coroutine_threadsafe"), patch(f"{MOD}.threading.Thread"):
        coord.callback("42", frame, sender=coord.wsc)

    _assert_clean(debug_log)
    assert "DEVICE STATUS FULL" in debug_log.text


def test_the_websocket_url_is_logged_without_its_token(debug_log):
    """Was: WebSocket URL: 'wss://...?token=<JWT>&...'."""
    ws = WSClient(MagicMock(), JWT)

    def stop_at_once(**_):
        ws.stop = True

    app = MagicMock()
    app.run_forever.side_effect = stop_at_once
    with patch(f"{MOD}.ws_client.websocket.WebSocketApp", return_value=app):
        ws.run()

    _assert_clean(debug_log)
    assert "WebSocket URL" in debug_log.text

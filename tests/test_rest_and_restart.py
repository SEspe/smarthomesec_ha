"""Coverage sweep, second pass: the REST success paths, the delayed WS restart,
the status retry and the refresh timeout.

Each of these sat behind a test that faked it out — set_alarm_mode's tests
patch _rest_call_post, the shutdown test for delayed_ws_restart never let the
timer thread run, and every refresh test replaces update_status.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.smarthomesec import SmarthomesecCoordinator

from .test_alarm_trigger import _refresh, _primed

MOD = "custom_components.smarthomesec"


def _coordinator(token="tok"):
    coord = object.__new__(SmarthomesecCoordinator)
    coord._shutdown = False
    coord.token = token
    coord.userid = "42"
    coord.wsc = None
    return coord


def _http(status=200, body=None, json_error=None):
    res = MagicMock()
    res.status_code = status
    if json_error is not None:
        res.json.side_effect = json_error
        res.text = "<html>oops</html>"
    else:
        res.json.return_value = body if body is not None else {}
    return res


# ----------------------------------------------------------------------
# _rest_call_post: the success path every arm and disarm takes
# ----------------------------------------------------------------------


def test_post_returns_the_reply():
    coord = _coordinator()
    reply = {"result": True, "code": "000", "message": "OK!"}

    with patch(f"{MOD}.requests.post", return_value=_http(200, reply)), patch.object(
        SmarthomesecCoordinator, "update_token"
    ) as update_token:
        assert coord._rest_call_post("panel/mode", {"area": 1}) == reply

    update_token.assert_not_called()


def test_post_with_a_rotated_token_swaps_the_ws_onto_it():
    """POST is the only call that can rotate the token (GET echoes it byte for byte).

    The new token kills the old one server-side, so the WS must follow.
    """
    coord = _coordinator(token="old")

    with patch(
        f"{MOD}.requests.post", return_value=_http(200, {"result": True, "token": "new"})
    ), patch.object(SmarthomesecCoordinator, "update_token") as update_token:
        coord._rest_call_post("panel/mode", {"area": 1})

    update_token.assert_called_once_with("new")


def test_post_echoing_the_same_token_leaves_the_ws_alone():
    """Restarting the WS on an unchanged token would be a pointless ~0.2 s outage."""
    coord = _coordinator(token="same")

    with patch(
        f"{MOD}.requests.post", return_value=_http(200, {"result": True, "token": "same"})
    ), patch.object(SmarthomesecCoordinator, "update_token") as update_token:
        coord._rest_call_post("panel/mode", {"area": 1})

    update_token.assert_not_called()


def test_post_with_an_unreadable_200_says_so():
    coord = _coordinator()

    with patch(f"{MOD}.requests.post", return_value=_http(200, json_error=ValueError("bad"))):
        with pytest.raises(Exception, match="Failed to parse POST response"):
            coord._rest_call_post("panel/mode", {"area": 1})


@pytest.mark.parametrize("verb", ["get", "post"])
def test_a_transport_failure_is_reported_as_cannot_connect(verb):
    coord = _coordinator()
    call = (
        (lambda: coord._rest_call_get("panel/cycle"))
        if verb == "get"
        else (lambda: coord._rest_call_post("panel/mode", {"area": 1}))
    )

    with patch(f"{MOD}.requests.{verb}", side_effect=OSError("network down")):
        with pytest.raises(Exception, match="Failed to connect to SmartHomeSec: network down"):
            call()


def test_get_with_an_unreadable_200_says_so():
    coord = _coordinator()

    with patch(f"{MOD}.requests.get", return_value=_http(200, json_error=ValueError("bad"))):
        with pytest.raises(Exception, match="Failed to parse GET response"):
            coord._rest_call_get("panel/cycle")


# ----------------------------------------------------------------------
# delayed_ws_restart: what the timer thread does once it wakes
# ----------------------------------------------------------------------


@pytest.fixture
def run_timer_inline():
    """Run the restart thread's target synchronously, with sleep patched out."""
    def make_thread(target, daemon):
        thread = MagicMock()
        thread.start.side_effect = target
        return thread

    with patch(f"{MOD}.threading.Thread", side_effect=make_thread), patch(
        f"{MOD}.time.sleep"
    ) as sleep:
        yield sleep


def test_delayed_restart_replaces_the_client(run_timer_inline):
    coord = _coordinator(token="tok")
    old = MagicMock()
    coord.wsc = old

    with patch(f"{MOD}.WSClient") as ws_cls:
        coord.delayed_ws_restart(delay=20)

    run_timer_inline.assert_called_once_with(20)
    old.stop_client.assert_called_once()
    ws_cls.assert_called_once_with(coord, "tok")
    ws_cls.return_value.start.assert_called_once()
    assert coord.wsc is ws_cls.return_value


def test_an_unload_during_the_delay_aborts_the_restart(run_timer_inline):
    """The check AFTER the sleep is the one that matters.

    The existing test sets _shutdown before scheduling, which only covers the
    early exit. The real race is an unload landing while the timer sleeps;
    without the second check the thread would bring the WS back to life after
    async_unload_entry had stopped it.
    """
    coord = _coordinator()
    run_timer_inline.side_effect = lambda _: setattr(coord, "_shutdown", True)

    with patch(f"{MOD}.WSClient") as ws_cls:
        coord.delayed_ws_restart(delay=20)

    ws_cls.assert_not_called()
    assert coord.wsc is None


def test_delayed_restart_without_a_token_does_nothing(run_timer_inline):
    coord = _coordinator(token=None)

    with patch(f"{MOD}.WSClient") as ws_cls:
        coord.delayed_ws_restart(delay=2)

    ws_cls.assert_not_called()


def test_a_failed_restart_is_logged_not_raised(run_timer_inline, caplog):
    coord = _coordinator()

    with patch(f"{MOD}.WSClient", side_effect=RuntimeError("boom")):
        coord.delayed_ws_restart(delay=2)

    assert coord.wsc is None
    assert "Failed to restart WS: boom" in caplog.text


# ----------------------------------------------------------------------
# update_status: three attempts, then give up
# ----------------------------------------------------------------------


def test_update_status_recovers_on_a_retry():
    coord = _coordinator()
    data = {"device_status": [], "model": []}

    with patch.object(
        SmarthomesecCoordinator, "_rest_call_get", side_effect=[OSError("blip"), {"data": data}]
    ) as get, patch(f"{MOD}.time.sleep") as sleep:
        assert coord.update_status() == data

    assert get.call_count == 2
    sleep.assert_called_once_with(1)
    assert coord._pir_devices == set()  # device types were indexed


def test_update_status_gives_up_after_three_attempts(caplog):
    coord = _coordinator()

    with patch.object(
        SmarthomesecCoordinator, "_rest_call_get", side_effect=OSError("down")
    ) as get, patch(f"{MOD}.time.sleep") as sleep:
        with pytest.raises(OSError, match="down"):
            coord.update_status()

    assert get.call_count == 3
    assert sleep.call_count == 2  # no pointless sleep after the last attempt
    assert "update_status failed after retries" in caplog.text


# ----------------------------------------------------------------------
# _async_update_data: timeout and failure handling
# ----------------------------------------------------------------------


def _refresh_coordinator(error, last_success):
    coord = object.__new__(SmarthomesecCoordinator)
    coord.hass = MagicMock()
    coord.hass.async_add_executor_job = AsyncMock(side_effect=error)
    coord.last_update_success = last_success
    coord.data = {"devices": {"d": {}}, "alarms": {}}
    return coord


async def test_a_timeout_keeps_the_last_known_data():
    """A slow panel must not flip every entity to unavailable."""
    coord = _refresh_coordinator(asyncio.TimeoutError(), last_success=True)
    previous = coord.data

    assert await coord._async_update_data() is previous


async def test_a_timeout_with_no_good_data_yet_fails():
    coord = _refresh_coordinator(asyncio.TimeoutError(), last_success=False)

    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


async def test_any_other_error_fails_the_refresh():
    """Only a timeout is papered over; a real error must surface as UpdateFailed."""
    coord = _refresh_coordinator(OSError("boom"), last_success=True)

    with pytest.raises(UpdateFailed, match="boom"):
        await coord._async_update_data()


async def test_rest_mode_triggered_latches_the_area():
    """Never observed (mode is only ever arm/disarm), but mapped — keep it working."""
    coord = _primed()

    await _refresh(coord, "triggered")

    assert coord.is_area_triggered("1")

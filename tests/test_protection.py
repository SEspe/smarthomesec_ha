"""Tests for the vendor API protection rules (cooldown, backoff, give-up)."""

import pytest

from custom_components.smarthomesec.protection import (
    LOGIN_COOLDOWN,
    WS_BACKOFF_MAX,
    WS_GIVE_UP_AFTER,
    WS_GIVE_UP_FAILURES,
    CooldownActive,
    backoff_delay,
    cooldown_remaining,
    should_give_up,
)


def test_first_login_is_never_blocked():
    assert cooldown_remaining(None, now=1000.0) == 0.0


def test_login_inside_the_cooldown_is_blocked_for_the_rest_of_it():
    assert cooldown_remaining(last_login=1000.0, now=1000.0 + 60) == LOGIN_COOLDOWN - 60


def test_login_after_the_cooldown_is_allowed():
    assert cooldown_remaining(last_login=1000.0, now=1000.0 + LOGIN_COOLDOWN) == 0.0
    assert cooldown_remaining(last_login=1000.0, now=1000.0 + LOGIN_COOLDOWN + 5) == 0.0


def test_cooldown_is_five_minutes():
    assert LOGIN_COOLDOWN == 300


@pytest.mark.parametrize(
    "failures, expected",
    [(1, 20), (2, 40), (3, 80), (4, 160), (5, 320), (6, 640), (7, 1280), (8, 1800), (9, 1800)],
)
def test_backoff_doubles_and_caps_at_thirty_minutes(failures, expected):
    assert backoff_delay(failures) == expected


def test_backoff_never_exceeds_the_cap():
    assert all(backoff_delay(n) <= WS_BACKOFF_MAX for n in range(1, 50))


def test_gives_up_after_five_consecutive_failures():
    assert not should_give_up(WS_GIVE_UP_FAILURES - 1, episode_started=0.0, now=10.0)
    assert should_give_up(WS_GIVE_UP_FAILURES, episode_started=0.0, now=10.0)


def test_gives_up_after_an_hour_of_failures_even_with_few_failures():
    assert not should_give_up(2, episode_started=0.0, now=WS_GIVE_UP_AFTER - 1)
    assert should_give_up(2, episode_started=0.0, now=WS_GIVE_UP_AFTER)


def test_no_give_up_without_an_episode_start_and_few_failures():
    assert not should_give_up(1, episode_started=None, now=10**9)


def test_cooldown_active_message_tells_the_user_how_long_to_wait():
    err = CooldownActive(seconds=250.0, why="command")
    assert err.seconds == 250.0
    assert "about 4 minute(s)" in str(err)
    assert "(command)" in str(err)


def test_cooldown_active_never_reports_negative_time():
    assert CooldownActive(seconds=-5.0, why="poll").seconds == 0.0

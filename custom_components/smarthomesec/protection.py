"""Rules that keep the integration from hammering the vendor's undocumented API.

Pure functions and one exception, so they can be tested without Home Assistant.
See docs/specs/vendor-api-protection.md for the reasoning behind each number.
"""

from homeassistant.exceptions import HomeAssistantError

# Minimum time between two logins, except the first login at startup.
LOGIN_COOLDOWN = 300  # seconds

# WebSocket retry delay: min(BASE * 2 ** (n - 1), MAX) for the n-th failure.
WS_BACKOFF_BASE = 20  # seconds
WS_BACKOFF_MAX = 1800  # seconds

# Give up (stop automatic WebSocket and login retries) after this many
# consecutive token failures, or this long after the first one.
WS_GIVE_UP_FAILURES = 5
WS_GIVE_UP_AFTER = 3600  # seconds


class CooldownActive(HomeAssistantError):
    """A login was blocked by the cooldown. `seconds` is the time left to wait."""

    def __init__(self, seconds: float, why: str) -> None:
        self.seconds = max(0.0, seconds)
        minutes = max(1, round(self.seconds / 60))
        super().__init__(
            f"SmartHomeSec login is on cooldown to protect the account. "
            f"Try again in about {minutes} minute(s). ({why})"
        )


def cooldown_remaining(last_login: float | None, now: float) -> float:
    """Seconds until another login is allowed. 0 means allowed now."""
    if last_login is None:
        return 0.0
    return max(0.0, LOGIN_COOLDOWN - (now - last_login))


def backoff_delay(failures: int) -> int:
    """Delay before the next WebSocket attempt after the `failures`-th failure."""
    if failures < 1:
        return WS_BACKOFF_BASE
    return min(WS_BACKOFF_BASE * 2 ** (failures - 1), WS_BACKOFF_MAX)


def should_give_up(failures: int, episode_started: float | None, now: float) -> bool:
    """True once automatic retries must stop."""
    if failures >= WS_GIVE_UP_FAILURES:
        return True
    if episode_started is not None and now - episode_started >= WS_GIVE_UP_AFTER:
        return True
    return False

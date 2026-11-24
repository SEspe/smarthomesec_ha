# Spec: protect the vendor API from abuse

Status: **implemented in 0.1.25** (stable, 2026-11-24). Changes after the first draft are
marked **As implemented**. Where the code and this spec differ, the code is right.
User-facing description: [`docs/API_PROTECTION.md`](../API_PROTECTION.md).

## Why

The vendor API is undocumented and this integration is unofficial. If the vendor sees
abuse (bursts of logins, reconnect loops), it can block the account or the client. The
2026-11-16 incident made the risk concrete: two Home Assistant units on one account caused
a token loop, and the integration logged in about every 20 to 40 seconds (17 forced logins
in roughly 20 minutes) for as long as the loop ran.

## Behaviour before 0.1.25

- `login()` ran at startup, on a REST 401, on `ForceLogin`, and on every second WebSocket
  token error.
- The first WebSocket token error retried the same token after 20 seconds. A rejected token
  was retried again and again.
- There was no cooldown on logins, no backoff on reconnects, and no limit on attempts.

## Goals

1. Normal operation is unchanged: one login at startup, one WebSocket, REST polling at
   the configured interval (default 300 s, minimum 60 s).
2. Logins are rate-limited, so a failure loop cannot produce a burst of calls.
3. Reconnect attempts back off, so a dead token stops generating traffic.
4. After repeated failure, the integration stops retrying on its own and says so clearly
   in Home Assistant, with the reason and what to do.

## Non-goals

- Changing the token format or the login payload.
- Changing REST polling frequency or the alarm logic.
- Automatically recovering from an account conflict. The user must fix that.

## Behaviour

### 1. Login cooldown

- Minimum interval between logins: **5 minutes** (`LOGIN_COOLDOWN = 300`).
- The startup login is always allowed.
- Any other login inside the cooldown is **deferred**: the caller schedules a login for the
  end of the cooldown instead of calling the API. The deferred login is coalesced, so several
  requests in the window produce one login.
- Logged at DEBUG per deferral, not as a WARNING per attempt.
- **As implemented:** `login()` records the time of each successful login; `_login_or_defer`
  applies the cooldown; `_schedule_deferred_login` coalesces.

### 2. WebSocket reconnect backoff

- Each consecutive failed recovery (token error, or disconnect before a `42` event)
  increases a counter `n`.
- Delay before the next attempt: `min(20 s × 2^(n−1), 30 min)`.
  **As implemented:** only the first step is used. The first token rejection retries the same
  token after 20 seconds. From the second rejection on, the integration logs in again, and the
  5-minute cooldown spaces those attempts out, so they are never closer than 5 minutes.
  `backoff_delay()` keeps the full formula and is tested. Whether the later steps are wanted is
  still open (see *Open questions*).
- The counter resets when a `42` event arrives. **Not implemented:** the 10-minute stable-connection
  reset. The live sensor now uses the handshake (`40`) instead, so the reset is not needed for
  the sensor. Whether it is still wanted is open.

### 3. Give up and report

- Trigger: `n` reaches **5**, or more than **60 minutes** have passed since the first failure of
  the current episode, whichever comes first.
- On give-up:
  - stop automatic WebSocket and login retries;
  - keep REST polling at its normal interval, so alarm state is still read. **As implemented:**
    polls and commands do **not** log in while given up. Commands fail with a message to press
    Retry connection. This stops an automatic login from knocking out another instance's session;
  - log **one** ERROR with the reason and what to do;
  - create a **Repairs issue** (`token_loop`) with a short explanation and the advice to use a
    separate account per Home Assistant instance;
  - turn the **Live connection** sensor off (see section 5).
- Recovery: the issue is cleared when a `42` event arrives, or when the config entry is reloaded.
  **As implemented:** the Retry connection button also clears it, once the cooldown allows a login.

### 4. Message wording

Short, plain, English. Repairs issue text as implemented (`issues.token_loop` in
`strings.json` and both translations):

> SmartHomeSec keeps rejecting the connection token, so live events are off and the
> integration has stopped retrying to protect your account. The usual cause is another
> Home Assistant (or app) logging in with the same account. Give each Home Assistant its own
> SmartHomeSec user, then reload the integration.

**As implemented:** a duplicate `issues` key in `en.json` once dropped this text, so the card
showed the raw key. `tests/test_translations.py` now fails on duplicate keys.

### 5. Entities and the "Live connection" sensor

- Alarm and sensor entities **stay available** during give-up. Polling still reads the real
  alarm state, so marking them unavailable would be misleading.
- A diagnostic binary sensor, **Live connection**.
  **As implemented (changed from the first draft):** it is **on** once the server accepts the
  connection (handshake `40`). It turns **off** after a later token rejection, or while the
  integration has given up. It does **not** wait for a live `42` event, because a quiet alarm
  panel sends none. The first draft used the `42` event, and the sensor stayed off during quiet
  periods.
- Entity category: diagnostic.

### 6. Login rules

Two kinds of call, two rules:

- **Background polls** (REST 401 during a poll): never log in while the cooldown is active.
  The poll skips, and the next poll tries again. At most one poll interval of stale state.
  While given up, polls never log in.
- **User commands** (arm, disarm, Retry button): one login is allowed if the cooldown has
  passed. If it has not, the command fails at once with the time left to wait, rather than
  hanging.

### 7. Retry button

A **Retry connection** button (diagnostic, config category). It starts one login and a
reconnect at once, and resets the give-up state. It respects the cooldown, so repeated presses
cannot bypass it.

## Open questions

1. **Cooldown length:** 5 minutes is implemented. Shorter values give faster recovery; longer
   values reduce load on the vendor. Keep 5 unless logs show a reason to change.
2. **Give-up threshold:** 5 failures or 60 minutes, whichever comes first. Implemented; no
   change planned.
3. **Exponential backoff:** only the 20 s first step is used (see section 2). Decide whether the
   later steps are still wanted.
4. **10-minute stable-connection reset:** not implemented. Decide whether it is still needed.
5. **Repairs card after "Ignore":** ignoring the card hides it while the integration keeps giving
   up. Decide whether it should stay visible until the cause is fixed.
6. **Languages:** decided. English and Norwegian (`no.json`), updated together.

## Test plan (as implemented)

Unit tests with no sleeping, in `tests/test_protection.py` and `tests/test_protection_wiring.py`:

- Cooldown: a login inside 5 minutes is deferred, and a startup login is never deferred.
- Backoff: the formula for `n = 1..6` caps at 30 minutes (pure function test).
- Give-up: at `n = 5`, retries stop, and polls and commands do not log in.
- Recovery: a `42` event clears give-up and the counter.
- Live sensor: on after the handshake, off after a later rejection and during give-up.
- Manual retry respects the cooldown.
- Translations: no duplicate keys, and the `token_loop` strings are present.

No live tests against the vendor API without the owner's go-ahead.

## Rollout (done)

- Prereleases `0.1.25b1` to `b3` ran on the test unit only.
- The test unit's logs for 2026-11-22 to 2026-11-24 show no token loop. That log is capped at
  5,000 lines.
- Released as stable `0.1.25` on 2026-11-24.

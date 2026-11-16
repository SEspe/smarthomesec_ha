# Spec: protect the vendor API from abuse

Status: **draft, for review.** No code yet.

## Why

The vendor API is undocumented and this integration is unofficial. If the vendor sees
abuse (bursts of logins, reconnect loops), it can block the account or the client. The
2026-11-16 incident made the risk concrete: two Home Assistant units on one account caused
a token loop, and the integration logged in about every 20 to 40 seconds (17 forced logins
in roughly 20 minutes) for as long as the loop ran.

## Current behaviour (from the code)

- `login()` runs at startup, on a REST 401 (`immediate_ws=True`), on `ForceLogin`, and on
  every second WebSocket token error ("Too many token errors → forcing login").
- The first WebSocket token error retries the same token after 20 seconds
  (`delayed_ws_restart`). A rejected token is retried again and again.
- There is no cooldown on logins, no backoff on reconnects, and no limit on attempts.
  Each loop iteration can therefore produce one login.

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

## Proposed behaviour

### 1. Login cooldown

- Minimum interval between logins: **5 minutes** (`LOGIN_COOLDOWN = 300`).
- Startup login (first `login()` after entry setup) is always allowed.
- Any other login inside the cooldown is **deferred**: the caller schedules a login for the
  end of the cooldown instead of calling the API. The deferred login is coalesced, so
  several requests in the window produce one login.
- Logged once per deferral at DEBUG; not a WARNING per attempt.

### 2. WebSocket reconnect backoff

- Each consecutive failed recovery (token error, or disconnect before a `42` event)
  increases a counter `n`.
- Delay before the next attempt: `min(20 s × 2^(n−1), 30 min)`.
- The counter resets when a `42` event arrives, or when the connection has stayed up for
  **10 minutes**.

### 3. Give up and report

- Trigger: `n` reaches **5**, or more than **60 minutes** have passed since the first
  failure of the current episode, whichever comes first.
- On give-up:
  - stop automatic WebSocket and login retries;
  - keep REST polling at its normal interval, so alarm state is still read;
  - log **one** ERROR with the reason;
  - create a **Repairs issue** (`token_loop`) in Home Assistant with a short explanation and
    the advice to use a separate account per Home Assistant instance;
  - turn the **Live connection** sensor off (see section 5).
- Recovery: the issue is cleared automatically when a `42` event arrives (the connection is
  healthy again), or when the config entry is reloaded.

### 5. Entities and the "Live connection" sensor

- Alarm and sensor entities **stay available** during give-up. Polling still reads the real
  alarm state, so marking them unavailable would be misleading.
- A new diagnostic binary sensor, **Live connection**, is **on** while the WebSocket is
  healthy and **off** during give-up or while a recovery is pending. It is the visible signal
  that live events are not arriving; alarm state still arrives by polling, at most 5 minutes
  late.
- Entity category: diagnostic, so it stays out of the default dashboards.

### 6. Login rules

Two kinds of call, two rules:

- **Background polls** (`REST 401` during a poll): never log in while the cooldown is active.
  The poll skips, and the next poll tries again. At most one poll interval of stale state.
- **User commands** (arm, disarm, retry button): one login is allowed if the cooldown has
  passed. If it has not, the command fails at once with the time left to wait, rather than
  hanging.

### 7. Retry button

A **Retry connection** button on the integration. It starts a login and a reconnect at once,
and resets the give-up state. It still respects the cooldown, so repeated presses cannot
bypass it.

### 4. Message wording

Short, plain, English. Example for the Repairs issue:

> SmartHomeSec keeps rejecting the connection token, so live events are off and the
> integration has stopped retrying to protect your account. The usual cause is another
> Home Assistant (or app) logging in with the same account. Give each Home Assistant its own
> SmartHomeSec user, then reload the integration.

## Open questions (for review)

1. **Cooldown length:** 5 minutes, or longer? Shorter values give faster recovery, longer
   values reduce load on the vendor.
2. **Give-up threshold:** 5 failures, or 60 minutes, whichever comes first. Are those right?
3. **Entity state during give-up:** decided. Alarm entities stay available; a "Live
   connection" diagnostic sensor shows the state (section 5).
4. **Manual retry:** decided. A "Retry connection" button (section 7).
5. **Logins during REST 401:** decided. Polls never log in during cooldown; user commands get
   one login if allowed, otherwise an immediate error (section 6).
6. **Languages:** decided. English and Norwegian (`no.json`), both updated together.

## Test plan

Unit tests with a fake clock (no sleeping):

- Cooldown: two logins inside 5 minutes produce one API call; the second is deferred to the
  end of the window; a startup login is never deferred.
- Backoff: the delay sequence for `n = 1..6` matches the formula and caps at 30 minutes.
- Reset: a `42` event, or 10 minutes of stable connection, resets `n`.
- Give-up: at `n = 5` (or at 60 minutes), retries stop, the Repairs issue is created, and
  REST polling continues.
- Recovery: a `42` event clears the issue and resumes normal behaviour.
- Normal path unchanged: startup login, one WebSocket, polling at the configured interval.

No live tests against the vendor API without your go-ahead.

## Rollout

- Ship as a prerelease first (`0.1.25bN`), for the test unit only.
- Check the logs for: login count per hour, backoff delays, and whether give-up fires in
  the expected situations.
- Release normally after that.

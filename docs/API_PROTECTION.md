# How the integration protects the vendor API

This integration talks to SmartHomeSec's cloud through an API the vendor has **not documented**.
It is unofficial. The vendor could limit or block an account that makes too many requests, so
the integration limits its own traffic. This page describes those limits and what you may see.

## What the integration does

**Login cooldown: at most one login every 5 minutes.**
Logging in is the most sensitive call. After the first login at startup, the integration waits
at least 5 minutes before logging in again. Requests that need a login during that window are
handled as follows:

- **Background polls** skip. Entities keep the last known state, and the next poll tries again.
  The poll interval is 5 minutes by default (you can change it, with a minimum of 60 seconds).
- **Your arm and disarm commands** get one login if the cooldown has passed. If not, the command
  fails at once and tells you how many minutes to wait.
- **The Retry connection button** follows the same rule as a command.

Normal use is not affected: one login at startup, one live connection, and regular polling.

**Reconnect pacing.** After the first rejection of the live connection's token, the integration waits
20 seconds and retries with the same token. From the second rejection on, it logs in again, but only
when the 5-minute cooldown allows, so recovery attempts are never closer together than that.

**Give-up.** If the rejections keep coming (5 in a row, or over an hour), the integration stops
retrying the live connection on its own. It keeps polling for the alarm state, so entities still
work, but live events stop. When this happens:

- a **Repairs** issue appears in Home Assistant, titled "SmartHomeSec has stopped retrying the live
  connection";
- the **Live connection** sensor turns off;
- the log contains one ERROR line that explains what to do.

## What you should see

| Entity | Meaning |
|---|---|
| **Live connection** (diagnostic sensor) | On: live events are arriving. Off: the live channel is down, or the integration has stopped retrying. Alarm state still updates by polling while it is off. |
| **Retry connection** (button) | Starts one login and reconnects now. Only works once the cooldown has passed. |

The Repairs issue goes away by itself when live events return. It also clears when you reload the
integration.

## What you need to do

**Give each Home Assistant instance its own SmartHomeSec user.** Two instances logging in to the
same account keep logging each other out. Each login invalidates the other session, so both see
"check token error" and both keep trying. This was the cause of a loop seen in November 2026.

If the Repairs issue appears:

1. Check whether another Home Assistant or the SmartHomeSec app uses the same account.
2. Give this Home Assistant its own user, or stop the other instance's integration.
3. Press **Retry connection**, or reload the integration.

## What this does not do

- It does not make the vendor's API documented or supported.
- It does not stop the vendor from noticing or acting on other traffic.
- It does not change how alarms are detected. Polling still reads the real alarm state.

Settings and their limits are described in [`README.md`](../README.md). The design is in
[`docs/specs/vendor-api-protection.md`](specs/vendor-api-protection.md).

# Changelog

All notable changes to this integration are listed here, newest first. Releases are also on the [GitHub releases page](https://github.com/SEspe/smarthomesec_ha/releases).

## 0.1.27

Changes requested in the hacs/default review.

- **Disarm needs a PIN.** Disarming without a code is refused, in the entity and in the coordinator, with a clear message. Before, an empty PIN was sent, and the server disarmed the area. Arming is unchanged. Automations that disarm without a code will now fail. (PR #65)
- **Retry on network errors.** If the cloud or the internet is unreachable during setup, for example after a restart, Home Assistant retries setup. Other setup failures (for example a wrong password) still fail as before. (PR #65)

## 0.1.26

No change to the integration's behaviour. This release makes the repository ready for the HACS default store.

- **CI:** the HACS validation runs all default-store checks (brands, topics, license, issues). Nothing is ignored any more. (PR #62)
- **Docs:** the vendor API protection spec is now in `docs/specs/vendor-api-protection.md`, marked as implemented. (PR #53)

## 0.1.25

Promotes the 0.1.25 pre-releases (b1, b2, b3) to a stable release.

- **Protects the vendor API from abuse.** The integration logs in at most once every 5 minutes. Background polls skip while a login is on cooldown. Arm, disarm and Retry connection fail at once with the wait time. (PR #54)
- **Stops retrying after repeated token rejections.** After 5 rejections in a row, or an hour of failures, the integration stops retrying the live connection and writes one ERROR line. Polls keep the last known state. Polls and commands do not log in while it has given up. (PR #54, PR #55)
- **Repairs issue** "SmartHomeSec has stopped retrying the live connection", with a fix-and-retry description. It clears when live events return or when the integration is reloaded. Norwegian and English text. (PR #54, PR #57)
- **Retry connection button** (diagnostic). Starts one login now, and follows the same cooldown as a command. (PR #54)
- **Live connection sensor** (diagnostic). On when the server accepts the live connection, off after a later rejection or while the integration has given up. (PR #54, PR #58)
- **Diagnostic log lines** show a short fingerprint and the age of the token. The token itself is never logged. (PR #50)
- **Docs:** `docs/API_PROTECTION.md` explains the limits, what you will see, and how to fix a two-instance loop: give each Home Assistant instance its own SmartHomeSec user.

## 0.1.24

- **Fix:** an old WebSocket thread no longer keeps reconnecting with an expired token after the coordinator has replaced it. Before the fix, it reconnected about every 47 seconds and filled the logs with warnings. Alarms were not affected, because polling kept the data current. (PR #48, reported by koying.)
- **Docs:** the README security section records the PIN results, with dates. The install section is fixed.

## 0.1.23

- **Configurable poll interval.** Set it from the integration's Configure menu. Default 300 seconds, minimum 60 seconds. (PR #39)
- **Dependency floor:** `websocket-client>=1.9.0` instead of an exact pin, so Home Assistant's shared copy is not downgraded. (PR #38)
- **License:** MIT. (PR #43)

## 0.1.22

- **Requires Home Assistant 2026.1.0 or newer.** HACS will no longer offer this version to older installs. Python 3.13 or newer is required. (PR #34)
- **Credits:** the README names the original author and links the upstream project. (PR #35)
- **CI:** the minimum-version job runs HA 2026.1.0 on Python 3.13. Python 3.12 is no longer tested.

## 0.1.21 and earlier

See the [GitHub releases page](https://github.com/SEspe/smarthomesec_ha/releases).

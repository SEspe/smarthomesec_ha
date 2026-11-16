# Changelog

All notable changes to this integration are listed here, newest first. Releases are also on the [GitHub releases page](https://github.com/SEspe/smarthomesec_ha/releases).

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

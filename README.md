# SmartHomeSec

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)


Home Assistant integration of the norwegian alarm system,  smarthomesec.  Special adaptet for Hønefoss Vaktselskap,  but should be kind'a general 

**Which alarm systems this fits.** SmartHomeSec is Climax Technology's cloud for **VESTA by Climax**
panels, white-labelled by alarm companies across Norway and Europe — your provider's branding, your
provider's alarm central, Climax's panel and cloud underneath. If your provider's app is
**SmartHomeSec** (or an identical-looking rebadge), or your panel is a Climax/VESTA unit, this
integration is worth a try. In Norway that includes **Hønefoss Vaktselskap** (`alarm24.no`), which
this was written against.

The catch is *which server* your account lives on: the same hostname serves several separate account
databases, and the API answers every rejection with the same generic error. New accounts are on
`portal.vestasecurity.eu` (the default here); older alarm24 accounts are on `smartalarm.alarm24.no`,
kept as a commented fallback in `const.py`. **If your credentials work in the app but fail here,
change the host before the password** — and note that login is rate-limited per IP (~3 failures →
5 minute lockout).

Your provider's alarm central is real: arming, disarming and any test alarm reaches people who may
dispatch a guard. Arrange test mode with them first.

See [`docs/VESTA_API.md`](docs/VESTA_API.md) for the measured API: hosts, auth, endpoints, alarm
detection via Contact ID, and the WebSocket protocol. Unofficial and unaffiliated with Climax,
VESTA, or any alarm provider.

## Installation-ha
Under HACS -> Integrations, add custom repository "https://github.com/SEspe/smarthomesec_ha/ with Category "Integration". 

Search for repository "smarthomesec_ha" and download it. Restart Home Assistant.

Go to Settings > Integrations and Add Integration "SmartHomeSec". Type in xxx

Click Configure and choose fractions to create sensors.

Restart Home Assistant.


## Debugging
in configuration.yaml

```yaml
logger:
  default: info
  logs:
    custom_components.smarthomesec: debug
```

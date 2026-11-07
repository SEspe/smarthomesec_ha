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

See [`docs/HOME_ASSISTANT.md`](docs/HOME_ASSISTANT.md) for what entities you get, how a triggered
alarm behaves and how to automate on it, and [`docs/VESTA_API.md`](docs/VESTA_API.md) for the
measured API: hosts, auth, endpoints, alarm detection via Contact ID, and the WebSocket protocol.
Unofficial and unaffiliated with Climax, VESTA, or any alarm provider.

## Installation
Under HACS -> Integrations, add custom repository `https://github.com/SEspe/smarthomesec_ha` with category "Integration".

Search for repository "smarthomesec_ha" and download it. Restart Home Assistant.

Go to Settings > Integrations and add the integration "SmartHomeSec". Enter the account name and password for your SmartHomeSec login, and a name for the alarm. If your login is rejected, see the notes in `docs/HOME_ASSISTANT.md`.

Click Configure to change how often the integration polls the server (default 300 seconds, minimum 60).

Restart Home Assistant.


## Debugging
in configuration.yaml

```yaml
logger:
  default: info
  logs:
    custom_components.smarthomesec: debug
```

## Credits

This integration started as [koying/smarthomesec_ha](https://github.com/koying/smarthomesec_ha) by Chris Browet (koying). This repository is a fork of that project, adapted for HACS and maintained separately from upstream. The commit history shows which changes are which. Thanks to the upstream author for the original work.

## License

This repository is released under the [MIT License](LICENSE). The upstream project,
[koying/smarthomesec_ha](https://github.com/koying/smarthomesec_ha), was described by its author as
public domain; the changes in this fork are MIT.

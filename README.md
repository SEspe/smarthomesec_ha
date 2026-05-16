# SMartHomeSec

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)


Home Assistant integration of the norwegian alarm system,  smarthomesec.  Special adaptet for Hønefoss Vaktselskap,  but should be kind'a general 

## Installation-ha
Under HACS -> Integrations, add custom repository "https://github.com/SEspe/smarthomesec_ha/ with Category "Integration". 

Search for repository "smarthomesec_ha" and download it. Restart Home Assistant.

Go to Settings > Integrations and Add Integration "SMartHomeSec". Type in xxx

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

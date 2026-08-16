# How the alarm appears in Home Assistant, and how to use it

## The entities

### The alarm panel

One `alarm_control_panel` entity per alarm area. Only area **1** is exposed
(`ALARM_AREAS` in `const.py`) — panels typically report a second, unused area.

- **Entity id:** `alarm_control_panel.<the name you typed during setup>_1`
- **Find it:** Developer Tools → States, filter `alarm_control_panel`

| State | Meaning |
|---|---|
| `disarmed` | panel reports `disarm` |
| `armed_away` | panel reports `arm` |
| `armed_home` | panel reports `home` |
| `triggered` | **an alarm was detected** (see below) |

**Attributes**, present once an alarm has been detected since Home Assistant started:

```yaml
last_trigger_reason:    Burglary                     # from the Contact ID code
last_trigger_cid_code:  "1130"
last_trigger_zone:      "5"
last_trigger_device:    IR Stue                      # zone resolved to a device name
last_trigger_report_id: "388956623"
last_trigger_time:      2026-08-16T09:11:37+00:00    # UTC
```

They describe the **last** trigger, not a current one — they persist after the alarm clears, and
are absent until the first one.

### Sensors

One `binary_sensor` per detector, named `<device_id> - <name>` (e.g. *RF:0e25a110 - MK Inngang*):

- door contacts — `device_class: door`, on = open
- PIR motion — `device_class: motion`

## The one thing that governs how you use `triggered`

**It is brief.** Measured on a live alarm: `triggered` appeared **245 ms** after the panel
reported, and the disarm three seconds later cleared it again. Without a disarm it expires after
`ALARM_TRIGGER_TTL` (300 s).

That is deliberate — a keypad disarm must win immediately — but it means:

- **Trigger on the transition** (`to: triggered`), never on the state being true.
- **Never add `for:`.** A three-second state will not survive it.
- **Read the attributes from `trigger.to_state`**, not from the entity. By the time a slow action
  runs, the entity may already be back to `armed_away`.

## Automations

### Notify, with what actually happened

```yaml
automation:
  - alias: SmartHomeSec – alarm triggered
    mode: single
    triggers:
      - trigger: state
        entity_id: alarm_control_panel.smarthomesec_1     # your entity id
        to: triggered
    actions:
      - action: notify.mobile_app_<your_phone>
        data:
          title: "🚨 ALARM: {{ trigger.to_state.attributes.last_trigger_reason }}"
          message: >-
            {{ trigger.to_state.attributes.last_trigger_device
               or 'zone ' ~ trigger.to_state.attributes.last_trigger_zone }}
            – {{ now().strftime('%H:%M:%S') }}
          data:
            priority: high
            ttl: 0
            channel: alarm_stream        # Android: sounds through silent mode
```

### Anything longer-running

Latch a helper in the same automation, so the work survives the disarm clearing the state:

```yaml
      - action: input_boolean.turn_on
        target: {entity_id: input_boolean.alarm_active}
      - action: light.turn_on
        target: {entity_id: light.stue}
        data: {brightness_pct: 100}
      - action: camera.snapshot
        target: {entity_id: camera.inngang}
        data: {filename: "/config/www/alarm_{{ now().strftime('%Y%m%d_%H%M%S') }}.jpg"}
```

Then drive sirens, recording or repeat-notifications off `input_boolean.alarm_active`, and clear
it yourself — on disarm, or on a timer.

### React to a specific detector

The binary sensors work independently of the panel state, which is useful while disarmed:

```yaml
    triggers:
      - trigger: state
        entity_id: binary_sensor.rf_0e25a110_mk_inngang
        to: "on"
```

## Arming and disarming from Home Assistant

The entity requires a numeric code, so the standard card gives you a keypad. The digits are passed
straight through to the panel as the user PIN.

```yaml
type: alarm-panel
entity: alarm_control_panel.smarthomesec_1
states: [arm_away, arm_home]
```

From a script or automation:

```yaml
      - action: alarm_control_panel.alarm_arm_away
        target: {entity_id: alarm_control_panel.smarthomesec_1}
        data: {code: "1234"}
```

A PIN written into a script is stored in plaintext in your configuration — prefer the card, or a
secret, if that matters to you.

## Limitations worth knowing

- **A Home Assistant restart during a sounding alarm shows no `triggered`.** The alarm record
  survives restarts, so the first one seen after startup is treated as history — otherwise every
  restart would raise a phantom alarm. Deliberate trade-off.
- **`triggered` is detected, not authoritative.** The panel never reports "triggered" over its
  API; the state is derived from a new alarm record (see `docs/VESTA_API.md`). It clears on any
  disarm, even one that did not follow an alarm.
- **This is cloud-dependent** — your internet, the provider's backend, and a live WebSocket. Fine
  for notifications, lights and automations. **Not** a substitute for your alarm company's
  monitoring, and not life-safety equipment.

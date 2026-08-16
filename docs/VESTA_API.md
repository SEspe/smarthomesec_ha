# The SmartHomeSec / VESTA cloud API, as measured

There is no public documentation for this API. Everything here was measured against a live
account and panel, or corroborated against an open-source client of the same backend. Where a
claim is inferred rather than observed, it says so.

The backend is Climax Technology's **Home Portal Server**. SmartHomeSec (VESTA by Climax),
alarm24 and Bydemes are resellers of it, and Yale Smart Alarm is an OEM of the same thing.

- **Base URL:** `https://portal.vestasecurity.eu/REST/v2/`
- **Content type:** `application/x-www-form-urlencoded; charset=UTF-8` for POSTs; responses are JSON.
- **Envelope:** every response is `{"code": "000", "data": ...}`. `code` `"000"` is success;
  `"010"` is a generic login failure; `"018"` / `"044"` are rate-limit lockouts.

---

## 1. Hosts and tenants

Three hostnames are known, and **all three resolve to the same IP** (52.31.23.137) serving the
same `/REST/v2` application, each with its own valid TLS certificate:

| Host | Tenant |
|---|---|
| `portal.vestasecurity.eu` | **VESTA — the one the current app provisions** |
| `smartalarm.alarm24.no` | legacy alarm24 / Hønefoss Vaktselskap accounts |
| `smarthomesec.bydemes.com` | Bydemes |

**They are separate account databases selected by hostname.** The same email and password that
logs in on one is rejected on another with `code 010 "Login failure!"` — the generic failure the
server returns for *every* rejection reason, so the response body tells you nothing about which
reason applied. If credentials that work in the phone app fail here, **suspect the host before
the password scheme.**

The `portal.vestasecurity.eu/vesta/` path that web searches surface is a web-UI path, not an API
base; it 404s.

### Who this affects — alarm users in Norway

**VESTA by Climax is white-labelled.** The panel on your wall carries your alarm company's
branding, the ARC that answers it is your alarm company's, and the subscription is theirs — but
the panel, the cloud, and the app are Climax's, shared with every other reseller. That is why an
integration written for one Norwegian provider tends to work for another, and why the *only*
thing that usually needs changing is the hostname.

You are probably on this backend if:

- your provider's phone app is **SmartHomeSec** (Climax's own app, also published as *Vesta Home*
  in some regions), or a rebadged app that looks identical; or
- your panel is a Climax/VESTA unit — HSGW, HPGW, VESTA-xxx, or a "Smart Home Controller" (SHC).

Known and suspected users of this backend:

| Provider | Evidence | Tenant |
|---|---|---|
| **Hønefoss Vaktselskap** (`alarm24.no`) | **First-hand.** This integration was written against their system, and both the legacy and current tenants were measured on it | historically `smartalarm.alarm24.no`; new accounts are provisioned on `portal.vestasecurity.eu` |
| Other Norwegian resellers (e.g. Sikring24 is named in [Norwegian home-automation discussion](https://www.hjemmeautomasjon.no/forums/topic/8325-climax-vesta-integrasjon-alarm-system-sikring24-osv/) of Climax/Vesta) | Second-hand. Not verified here | unknown — try `portal.vestasecurity.eu` first |
| Bydemes (distributor, Spain) | Runs `smarthomesec.bydemes.com` on the same backend | `smarthomesec.bydemes.com` |
| Yale Smart Alarm (UK/EU, OEM) | Same Climax Home Portal Server, different auth — its open-source client is a useful reference | `mob.yalehomesystem.co.uk` |

**Note that Hønefoss Vaktselskap moved tenants without announcing it.** Accounts created by the
current app land on `portal.vestasecurity.eu`, while older accounts lived on
`smartalarm.alarm24.no`. Nothing tells you which one you are on: the app just works, and the API
returns the same `code 010 "Login failure!"` whether the password is wrong *or* the account
simply does not exist on the host you asked. If your credentials work in the app but fail here,
**change the host before you touch the password**, and mind the ~3-attempt per-IP lockout while
testing.

### If you are a user of another provider

1. Try `portal.vestasecurity.eu` first — it is where the current app provisions accounts.
2. If that fails, try your provider's own portal hostname (whatever their web login uses), then
   `smartalarm.alarm24.no`.
3. Three failures locks your IP out for five minutes, so change one thing at a time.
4. Your provider's ARC is real. Arming, disarming and especially any panic/test alarm reaches
   people who will dispatch a guard, and an unresolved callout is usually billable. **Arrange test
   mode with your provider before triggering anything.**

None of this is endorsed by, or affiliated with, Climax Technology, VESTA, Bydemes, Hønefoss
Vaktselskap, or any other provider. It is an unofficial integration written by a customer.

## 2. Authentication

```
POST /REST/v2/auth/login
     account=<email>&password=<md5 hex>&pw_encrypted=hashed&login_entry=web
     header: cookie: isPrivacy=1;
  -> {"code":"000","data":{"token":"<jwt>","user_id":...}}
```

The password is **MD5**, lowercase hex. `login_entry` may be `web` or `app`.

Authenticated calls present the token **twice** — as a `cookie` header and as a `token` header.
POST responses may carry a **rotated** `token`, which the client must adopt.

### Token lifetime — the single most consequential fact

The JWT (`iss=climax-mqtt-api`) carries `iat` but **no `exp`**, so its expiry is invisible to the
client. Measured lifetime: **~5 minutes** (5m02s and 5m03s from issue to rejection).

Consequences:

- REST calls return **HTTP 401** a few minutes into any idle period. Re-login and retry.
- The WebSocket presents its token **only at connect time**, so a live socket is unaffected by
  REST token rotation. Tearing down a healthy WS because a REST call 401'd is a bug, not hygiene.

### Rate limiting

**Login is rate-limited by source IP, not by account.** Roughly 3 failed attempts produces
`code 018` / `code 044 "Retry after 5 minutes"`, and it triggers even against a non-existent
account — a correct password does not shield you while probing. Anything that retries logins in
a loop will trip it.

## 3. REST endpoints

Confirmed in use here, plus the ones the Yale client (same backend) calls. Paths below are
relative to `/REST/v2/`; Yale's client uses `/yapi/api/...` for the same handlers.

| Endpoint | Method | Purpose |
|---|---|---|
| `auth/login` | POST | obtain a token |
| `auth/check` | GET | account info (`user_id`, `master`, `xml_version`, `dealer_*`) |
| `panel/cycle` | GET | **the full state snapshot — the source of truth** |
| `panel/mode` | GET/POST | read / set arm state |
| `panel/device_status` | GET | device list with status |
| `panel/status` | GET | panel health: `acfail`, `battery`, `tamper`, `jam`, `rssi`, `gsm_rssi` |
| `panel/online` | GET | `"online"` / offline |
| `panel/info` | GET | firmware versions, MAC, dealer contact details |
| `event/report?page_num=1&set_utc=1` | GET | **paged event log** — unprobed here, present in the Yale client |
| `panel/panic` | POST | trigger a panic alarm — **real, dispatches a guard** |

### `panel/cycle` — the response shape

```jsonc
{"code": "000", "data": {
  "model": [                       // one entry per area
    {"area": "1", "mode": "disarm", "burglar": false, "area_name": ""}
  ],
  "panel_status": {"warning_snd_mute": "0"},
  "device_status": [ /* see below */ ],
  "capture_latest": null,          // last camera capture
  "report_event_latest": { /* last event of ANY class */ },
  "alarm_event_latest": { /* last ALARM-class event, ever */ }
}}
```

`model[].mode` is `disarm` | `arm` | `home`. **`"triggered"` has never been observed** — a
sounding panel still reports `arm`.

`model[].burglar` is **not understood, and it is not simply "armed".** Three measurements on the
same panel, all reproducible from logs:

| Date | State | `burglar` | Samples |
|---|---|---|---|
| 2026-08-09 | armed overnight, no alarm | **`true`** | 42 |
| 2026-08-09 | disarmed | `false` | 33 |
| 2026-08-16 | **armed 17 min, quiet, no alarm** | **`false`** | **8** |
| 2026-08-16 | armed, alarm sounding | **`true`** | 1 |

The 17-minute test was deliberate and is not vacuous — eight refreshes landed inside the armed
window, including polls five and ten minutes in, and every one read `false`. So "armed ⇒ true"
is refuted as a general rule, while the 42 armed `true` samples on 2026-08-09 are equally real.
Something other than arm state drives it, and a short quiet arming is not enough to raise it.

Two candidate readings survive, and the data contradicts each of them somewhere:

- **"burglary protection fully engaged"** — i.e. armed *and* every burglary zone sealed. The
  2026-08-09 arming was overnight with the house shut; the 2026-08-16 test ran while a door
  contact appears to have been open much of the day. But `burglar` was `true` during the alarm at
  a moment when a door had just opened, which this does not explain.
- **"alarm active"** — fits 2026-08-16 exactly, and fails on 2026-08-09, where 42 consecutive
  armed samples read `true` with no alarm anywhere in the log.

The distinguishing experiment is a **long, quiet, fully-sealed arming** (e.g. overnight): if
`burglar` goes `true` with no alarm, it is a state of the arming, not of an alarm.

**Do not build on this field.** The one thing all four rows agree on is that it is `false` while
disarmed, which is useless. Treating it as "alarm" would have been wrong on 2026-08-09; treating
it as "armed" is wrong on 2026-08-16.

`device_status[]` entries carry, among ~100 fields: `device_id` (e.g. `RF:0e25a110`), `no` (zone
number), `area`, `type` (`device_type.door_contact`, `device_type.pir`, `device_type.door_lock`…),
`name`, `status1`, `status_open` (`device_status.dc_open` / `dc_close`), `status_motion`,
`status_switch`, `status_temp`, `bypass`, `rssi`.

### `panel/mode` — arming

```
POST /REST/v2/panel/mode    area=1&mode=arm|home|disarm&pin=<user PIN>
```

## 4. Alarm detection

**This is the part with no obvious answer, and two traps.**

The only signal that an alarm occurred is `data["alarm_event_latest"]` in `panel/cycle`:

```jsonc
{"report_id": "388956623", "cid": "18113001005", "cid_code": "1130",
 "event_time": "", "time": "...", "utc_event_time": "1785838065"}
```

- It is the latest alarm **ever** — it survives panel restarts and persists indefinitely. It is
  **not** a live flag. A new alarm is therefore a **change of `report_id`**, with a recent
  `utc_event_time`.
- It is `null` on an account that has never had an alarm (confirmed in the Yale fixtures).
- **It holds alarm-class records only.** Measured across a full arm/disarm/alarm/cancel cycle:
  every `1401`, `3401`, `1406` and `1374` appeared in `report_event_latest` alone, and
  `alarm_event_latest` moved only for the `1130`.
- It updates **promptly** — present in the very refresh the WebSocket alarm event provokes.

`report_event_latest` has the identical shape but tracks events of every class. It is the field
to log if you want to see what a panel is doing.

### Contact ID

`cid_code` is Ademco **Contact ID**: `Q XYZ`, where `Q` is `1` (new event) or `3` (restore), and
`XYZ` is the event code. The full `cid` string is `MT(2) QXYZ(4) GG(2) CCC(3)` — e.g.
`18113001005` = message 18, event 1130, area 01, zone 005.

**The alarm class is exactly 100–199**, which makes the filter simple:

| Code | Meaning | Alarm? |
|---|---|---|
| 110 / 120 / 121 / 122 | fire / panic / duress / silent panic | yes |
| **130** | **burglary** — what an intrusion produces | yes |
| 131 / 132 / 133 / 134 | perimeter / interior / 24-hour / entry-exit | yes |
| 137 / 139 | tamper / burglary verified | yes |
| 301 | AC loss | no |
| 374 | trouble closing | no |
| 401 | open/close (arm/disarm) | no |
| 406 | cancel — a disarm **during** an alarm | no |
| 602 | periodic test report | no |

Note the trailing `CCC` field is a **zone or a user number depending on event class** — Yale
parses `18180201101` as `user: 101`. For 1xx alarm codes it is always a zone.

## 5. WebSocket (Socket.IO)

```
wss://<host>/ws/socket.io/?token=<jwt>&EIO=4
```

Socket.IO framing: `0` handshake, `40` connect, `42` event, `2`/`3` ping/pong, `44` token error.

### The heartbeat is a property of the HOST, not the protocol

Both hosts advertise `EIO=4` and behave **oppositely**:

| Host | Server sends PING? | Client must PING? | If the client pings anyway |
|---|---|---|---|
| `portal.vestasecurity.eu` (v4) | **yes**, every 25s | **no**, only PONG | socket dropped **~40 ms later** |
| `smartalarm.alarm24.no` (v3) | never | **yes** | it is the only thing keeping it alive |

Measured: VESTA pings at 25.0 / 50.1 / 75.1s and holds 90s+ with zero client pings; alarm24
closes at exactly `pingInterval + pingTimeout` = **30.04s ±4ms** across 12 connections if the
client is silent.

**So decide by observation, not by hostname:** stay silent on handshake, arm a fallback timer at
`pingInterval + ~2s` (after a v4 server's own ping, before a v3 server's close), answer any
server PING with PONG and stand the timer down — otherwise start client-driven pings.

WebSocket **transport-level** ping frames (`run_forever(ping_interval=...)`) are a different
layer and satisfy neither server's Engine.IO heartbeat. Both answer them, which makes them easy
to mistake for a working heartbeat.

### Events

Every observed event, in full:

```jsonc
{"refreshed_type": "DEVICE_STATUS", "refreshed": true, "data": {"device_id": "RF:...", "area": "1"}}
{"refreshed_type": "REPORT",        "refreshed": true, "data": {"type": "MODE_CHANGE|ALARM|STATUS", "area": "1"}}
{"refreshed_type": "MODE_CHANGE",   "refreshed": true}
{"refreshed_type": "ALARM",         "refreshed": true}
```

**The events carry no state.** There is no field describing what changed — the WebSocket is a
doorbell meaning "refetch `panel/cycle`". The *type* is the only information, and `ALARM` is the
only type that means anything specific.

When an alarm fires, the panel sends `REPORT {"type": "ALARM"}` **and** a bare
`{"refreshed_type": "ALARM"}` in the same millisecond, and the alarm record is already present in
`panel/cycle` when you fetch it. Measured end to end: **245 ms** from event to a detected alarm.

A door contact's `DEVICE_STATUS` arrives when the door **opens** — 27 seconds before the alarm
record existed, in the measured case — so it is far too early to be used as an alarm signal.

**Detectors report while the system is disarmed, too.** Motion sensors fire `DEVICE_STATUS`
regardless of arm state (measured: all three PIRs on the test system produced events across an
8.5-hour mostly-disarmed log, and one fired while disarmed minutes before the test alarm). What
arming changes is the panel's *response*, configured per device and per mode in
`sresp_mode_<n>` / `sresp_entry_<n>` on the `device_status[]` entry — the test system's living-room
PIR carries `sresp_mode_0: "0"` (disarmed: do nothing) and `sresp_mode_1: "5"` (armed away:
respond). So the cloud sees the motion either way; only the alarm decision is gated.

**But `status_motion` is useless.** It was the empty string in **every** sample across both logs
(1261/1261 and 142/142) — including refreshes taken immediately after a PIR event. The field
exists and is never populated, so a motion detector's state cannot be read from `panel/cycle`. The
`DEVICE_STATUS` event is the only motion signal available, and it carries no state, so a client
that wants a motion entity has to synthesise one: pulse it on the event and reset it after a few
seconds.

## 6. A measured alarm, end to end

2026-08-16, deliberate test alarm on a live panel:

```
11:10:09.641  report_event_latest -> CID 3401                    armed
11:11:10.167  WS DEVICE_STATUS RF:0e253110                       door contact opens
              panel/cycle: mode=arm, burglar=false
11:11:37.100  WS REPORT {'type': 'ALARM', 'area': '1'}
11:11:37.107  WS {'refreshed_type': 'ALARM'}
11:11:37.346  alarm_event_latest -> report_id 388956623,
              cid 18113001005, cid_code 1130  (Burglary, area 1, zone 5 = a PIR)
              panel/cycle: mode=arm, burglar=true
11:11:37.351  WS DEVICE_STATUS RF:09cdcc30                       the PIR that caused it
11:11:40.605  WS MODE_CHANGE                                     user disarms
11:11:47.545  report_event_latest -> CID 1406                    cancel
```

The siren was audible a few seconds before the cloud record appeared.

## 7. Practical notes for anyone implementing this

- **Do not read state from WebSocket events.** Use them only as a trigger to refetch.
- **Poll `panel/cycle` as a fallback**, faster than your alarm-freshness threshold. If the socket
  is down when an alarm fires, the poll is the only thing that will see it.
- **Never treat the first `alarm_event_latest` you see as a live alarm** — it survives restarts,
  so latching it raises a phantom alarm every time your client starts.
- **A restore (qualifier 3) apparently never lands in `alarm_event_latest`.** Clear an alarm on a
  `disarm` from `panel/mode`, plus a timeout.
- Login failures are indistinguishable by response body. Probe the host list before the password.

---

*Sources: measurement against a live account and panel (see `tools/login_probe`, `tools/ws_probe`);
the open-source [`yalesmartalarmclient`](https://github.com/domwillcode/yale-smart-alarm-client) and
Home Assistant's `yale_smart_alarm` component, which target the same Climax backend; the VESTA
panel installer manual for reporting behaviour; the Ademco Contact ID specification.*

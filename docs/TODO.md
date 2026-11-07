# TODO

## Decisions for the owner

- [ ] **Vendor disclosure (disarm without a PIN).** Disarming with no PIN, or with an empty PIN, succeeds on a VESTA panel. First documented in `docs/VESTA_API.md` on 2026-09-22, reproduced by the probe on 2026-11-07. The README security section (PR #40, merged) says so. Decide whether to tell the alarm provider, and what, before anything else is published.
- [ ] **HACS default store (`hacs/default`).** A strict HACS run passes every check on the MIT version (2026-11-07). Hold submission until the vendor question is settled.

## Waiting on others

- [ ] **Upstream license.** [koying/smarthomesec_ha#3](https://github.com/koying/smarthomesec_ha/issues/3): Chris replied that he is fine with the fork and considers the upstream repo public domain. He has not added a LICENSE upstream. Issue left open; nothing to do unless he adds one.

## Open (smaller)

- [ ] **Manifest `categories`.** HACS warns that `manifest.json` has no categories. A warning only; optional. Needs a choice of category (for example `hub`, `device`, `service`, `system`).
- [ ] **Local HA 2026.1 tests.** They can't run on native Windows (`runner.py` imports `fcntl`). CI on Linux is the only test run. WSL is not installed.

## Open PRs

None.

## Done

- **Minimum HA 2026.1.0** (PR #34). CI minimum job on Python 3.13. Python 3.12 dropped.
- **Release 0.1.22** (`a5f0aca`, tag `0.1.22`). Requires HA 2026.1.0 or newer.
- **Credits section** in the README (PR #35).
- **License:** CC0 (PR #37), then MIT (PR #43). HACS requires an OSI-approved license, and CC0 is not one. `docs/LICENSING.md` records Chris's statement.
- **websocket-client floor** `>=1.9.0` (PR #38). Issue #36, patch 2.
- **Configurable poll interval** (PR #39). Default 300 s, minimum 60 s. Issue #36, patch 1.
- **Release 0.1.23** (`00f2383`, tag `0.1.23`). Configurable poll interval, websocket floor, MIT license.
- **Issue #36** on the fork closed with a comment linking PR #38, PR #39 and release 0.1.23.
- **Strict HACS run** (PR #42, then PR #44, both closed): all 10 checks pass on MIT. Only a warning remains (no `categories`).
- **Repo description** set to "Home Assistant integration for SmartHomeSec (VESTA by Climax) alarms."
- **README security section** (PR #40, merged). Dated: first documented 2026-09-22, reproduced 2026-11-07.
- **Probe tool** with empty-pincode cases H and I (PR #41, merged).
- **README install section** fixed: heading, quote, placeholders, and the Configure option (PR #46, merged).
- **Probe output** `result.txt` moved out of the repo root.
- **Probe: arm with a wrong `pincode`.** Settled by the 2026-09-22 measurement (HTTP 400, nothing armed). No re-run planned.
- **Session notes and TODO** (PR #45, merged).

## Session notes: 2026-11-07

- **Probe run** (`tools/mode_probe`, home mode, run by the owner):
  - Arming was accepted with a correct, absent, empty, or wrong `pin` (A to E). The wrong-PIN arm used the `pin` field, not `pincode`.
  - Disarming with no PIN field (F) or an empty `pincode` (I) succeeded.
  - Disarming with a wrong `pincode` (G) was refused: HTTP 400, code 996 "PIN Code Error". The panel stayed armed.
  - The probe restored the panel to disarmed.
  - D (arm with no PIN field) and F repeat the 2026-09-22 results. H (arm with an empty `pincode`) and I are new.
- **Probe risk:** the probe logs in with the account password, and wrong-PIN attempts count toward the per-IP login lockout (about 3 failures, then 5 minutes).
- **Upstream issue #3:** Chris's reply on 2026-11-07 is recorded verbatim in `docs/LICENSING.md`.
- **Local Python:** `uv` manages Python 3.12 and 3.13. The 239-test suite passes on 3.12 with HA 2025.1.4. On HA 2026.1 only CI can run the tests.
- **Git identity:** the repo has no `user.name` or `user.email`. Commits use `-c user.name="Claude Code" -c user.email=...` for each command.

## Session notes: 2026-11-07 (cleanup)

- **Merged:** #40 (README security), #41 (probe tool), #45 (this file), #46 (README install section). All CI green before merge.
- **Open PRs:** none after the cleanup.
- **Corrected:** the "new finding" in the 2026-11-07 probe is partly a repeat. Disarm without a PIN was already in `docs/VESTA_API.md` from 2026-09-22. The new data is the empty-`pincode` case (I).
- **Remaining decisions:** vendor disclosure, then the HACS store submission.

# TODO

## Decisions for the owner

- [ ] **Vendor disclosure (disarm without a PIN).** A probe run on 2026-11-07 showed that disarming with no PIN, or an empty PIN, succeeds on one VESTA panel. Decide whether to tell the alarm provider before anything public. PR #40 would publish it in the README, so it is held.
- [ ] **HACS default store (`hacs/default`).** A strict HACS run passes every check on the MIT version (2026-11-07). Hold submission until the vendor question is settled.

## Open PRs

- [ ] **#40** README: "the PIN is not a second factor". CI was still running when last checked. Merge after the vendor decision.
- [ ] **#41** `mode_probe`: adds the empty-pincode cases H and I. Tooling only. Merge when you decide.

## Waiting on others

- [ ] **Upstream license.** [koying/smarthomesec_ha#3](https://github.com/koying/smarthomesec_ha/issues/3): Chris replied that he is fine with the fork and considers the upstream repo public domain. He has not added a LICENSE upstream. Issue left open; nothing to do unless he adds one.

## Open (smaller)

- [ ] **README placeholders.** The install section has the heading `## Installation-ha` and the text `Type in xxx`. The HACS URL line has a trailing space.
- [ ] **Manifest `categories`.** HACS warns that `manifest.json` has no categories. A warning only; optional.
- [x] **Probe: arm with a wrong `pincode`.** Accepted as settled by the 2026-09-22 measurement (HTTP 400, nothing armed). The 2026-11-07 run used `pin` for its wrong-PIN arm (case E), so it doesn't repeat this; no re-run planned.
- [ ] **Probe output.** `result.txt` sits untracked in the repo root. Move it out, or delete it.
- [ ] **Local HA 2026.1 tests.** They can't run on native Windows (`runner.py` imports `fcntl`). CI on Linux is the only test run. WSL is not installed.

## Done

- **Minimum HA 2026.1.0** (PR #34). CI minimum job on Python 3.13. Python 3.12 dropped.
- **Release 0.1.22** (`a5f0aca`, tag `0.1.22`). Requires HA 2026.1.0 or newer.
- **Credits section** in the README (PR #35).
- **websocket-client floor** `>=1.9.0` (PR #38). Issue #36, patch 2.
- **Configurable poll interval** (PR #39). Default 300 s, minimum 60 s. Issue #36, patch 1.
- **Release 0.1.23** (`00f2383`, tag `0.1.23`). Configurable poll interval, websocket floor, MIT license.
- **Issue #36** on the fork closed with a comment linking PR #38, PR #39 and release 0.1.23.
- **License:** CC0 (PR #37), then MIT (PR #43). HACS requires an OSI-approved license, and CC0 is not one. `docs/LICENSING.md` records Chris's statement.
- **Strict HACS run** (PR #42, then PR #44, both closed): all 10 checks pass on MIT. Only a warning remains (no `categories`).
- **Repo description** set to "Home Assistant integration for SmartHomeSec (VESTA by Climax) alarms."

## Session notes: 2026-11-07

- **Probe run** (`tools/mode_probe`, home mode, run by the owner):
  - Arming was accepted with a correct, absent, empty, or wrong `pin` (A to E).
  - Disarming with no PIN field (F) or an empty `pincode` (I) succeeded.
  - Disarming with a wrong `pincode` (G) was refused: HTTP 400, code 996 "PIN Code Error". The panel stayed armed.
  - The probe restored the panel to disarmed.
- **Probe risk:** the probe logs in with the account password, and wrong-PIN attempts count toward the per-IP login lockout (about 3 failures, then 5 minutes).
- **Upstream issue #3:** Chris's reply on 2026-11-07 is recorded verbatim in `docs/LICENSING.md`.
- **Local Python:** `uv` manages Python 3.12 and 3.13. The 239-test suite passes on 3.12 with HA 2025.1.4. On HA 2026.1 only CI can run the tests.
- **Git identity:** the repo has no `user.name` or `user.email`. Commits use `-c user.name="Claude Code" -c user.email=...` for each command.

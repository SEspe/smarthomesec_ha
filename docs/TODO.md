# TODO

## Decisions for the owner

- [x] **Vendor disclosure (disarm without a PIN).** Disarming with no PIN, or with an empty PIN, succeeds on a VESTA panel. First documented in `docs/VESTA_API.md` on 2026-09-22, reproduced by the probe on 2026-11-07. The README security section (PR #40, merged) says so. **Decided 2026-11-24 by the owner: no disclosure to the alarm provider.** The README stays as it is.
- [ ] **HACS default store (`hacs/default`).** Hold lifted 2026-11-24, since the vendor decision is made. The validate workflow runs all default-store checks without an `ignore` key (passed, run 45479308170). Remaining: submit the PR to `hacs/default` when the owner asks. Check the repo for an existing `smarthomesec` domain first (none on 2026-11-24).
- [ ] **Production upgrade.** Production HA is still on 0.1.24, which has no vendor API protection. It is the unprotected side of the two-instance loop. Upgrade it to a beta, or to the next stable release, once the test unit has run cleanly for a while. Decide which.
- [x] **Stable release.** `0.1.25` released from `0.1.25b3` (2026-11-24). Release PR and tag `0.1.25`; see CHANGELOG.md.

## Pending verification (test unit on 0.1.25b3)

- [ ] **Run for some hours.** (Partly seen: the test unit's log for 2026-11-22 to 2026-11-24 shows no token loop, but it is capped at 5,000 lines.) Check: no login more often than every 5 minutes; give-up after 5 failures (or an hour); Repairs card shows its title and description; Retry connection works after the cause is fixed; the Live connection sensor is on while connected, even when no live events arrive.
- [ ] **Production stays stable.** Once the test unit is on 0.1.25b3, production should show no new token errors. Check with a production log for the same period.

## Waiting on others

- [ ] **Upstream license.** [koying/smarthomesec_ha#3](https://github.com/koying/smarthomesec_ha/issues/3): Chris replied that he is fine with the fork and considers the upstream repo public domain. He has not added a LICENSE upstream. Issue left open; nothing to do unless he adds one.
- [ ] **Upstream PR #48 (koying).** Merged here. Upstream may still want the change; nothing to do.

## Open (smaller)

- [ ] **Spec: 10-minute stable-connection reset.** Not implemented. Only a live 42 event resets the failure counter. The live sensor now uses the handshake (40) instead, so decide whether the 10-minute reset is still needed.
- [ ] **Spec: exponential backoff.** Only the first 20 s step is used; from the second failure, the 5-minute login cooldown spaces the retries. Decide whether the exponential steps are still wanted (see `docs/specs/vendor-api-protection.md`).
- [ ] **Manifest `categories`.** HACS warns that `manifest.json` has no categories. A warning only; optional. Needs a choice of category (for example `hub`, `device`, `service`, `system`).
- [ ] **Local HA 2026.1 tests.** They can't run on native Windows (`runner.py` imports `fcntl`). CI on Linux is the only test run. WSL is not installed.
- [ ] **Repairs "Ignore".** Ignoring the card hides it, and the integration keeps giving up. Decide whether the card should stay visible until the cause is fixed.
- [ ] **Two instances on one account.** Documented in `docs/API_PROTECTION.md`. Consider a warning in the config flow or Repairs when a second instance is detected.
- [ ] **SSDP noise.** Home Assistant logs `Duplicate 'SERVER' header found` tracebacks from a LAN device every ten minutes. Not ours; can be reported upstream to Home Assistant.

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
- **Session notes and TODO** (PR #45, merged; PR #47 cleanup).
- **Fix for the orphaned WebSocket thread** (PR #48, koying). Included in 0.1.24.
- **Release 0.1.24** with `CHANGELOG.md`. Tag `0.1.24`.
- **Branch protection on `main`:** blocks force pushes and deletion, and requires the five CI checks before merge. Pull request reviews are not required. Direct pushes need the checks to pass too, so version bumps go through a PR.
- **Vendor API protection** (PR #54, merged). Login cooldown (5 min), give-up after 5 failures or an hour, Repairs issue `token_loop`, Live connection sensor, Retry connection button, `docs/API_PROTECTION.md`.
- **No logins while given up** (PR #55, merged). Polls and commands never log in while given up.
- **Repairs text fix** (PR #57, merged). A duplicate `issues` block had dropped the text; a test now fails on duplicate keys.
- **Live connection sensor on handshake** (PR #58, merged). On when the server accepts the connection (40), off after a later rejection (44) or during give-up.
- **Pre-releases:** `0.1.25b1` (PR #51, closed; tag from PR #54), `0.1.25b2` (PR #56), `0.1.25b3` (PR #59). `0.1.25b3` is the current beta.
- **Spec and user docs:** `docs/specs/vendor-api-protection.md` (PR #53 draft, spec branch) and `docs/API_PROTECTION.md`.

## Session notes: 2026-11-16

- **Loop cause confirmed.** Two Home Assistant instances (production and test) on the same SmartHomeSec account logged each other out. Each login invalidates the other's token. Production was stopped, and the test unit's loop stopped. Logs and the timeline are in the conversation, not in this file.
- **Test unit on 0.1.25b2:** cooldown worked (logins 5 minutes apart). Give-up reached on the 5th failure, with one ERROR line and no logins afterwards.
- **Retry connection:** pressed after the production unit was stopped. The connection was accepted and stayed up. The Repairs issue cleared.
- **Repairs card showed the raw key** `smarthomesec: token_loop`. Cause: a duplicate `issues` block in `en.json` dropped the text. Fixed in PR #57.
- **Live connection sensor** stayed off until the first live event (42). Changed to use the handshake (40) in PR #58.
- **SSDP tracebacks** in the test unit's log come from Home Assistant's discovery code, not from SmartHomeSec. Not ours.
- **Test HA tip:** the log export is capped (500 to 1000 lines). Use a time window or a shorter debug run when collecting logs.
- **Classifier blocks** happened on `gh pr merge` once (PR #54). The merge was done on GitHub instead, and the rest of the merges went through.
- **Next:** run `0.1.25b3` on the test unit for some hours, check production stays stable, then decide on the production upgrade and a stable release.

## Session notes: 2026-11-24

- **Release 0.1.25** (stable, promotes 0.1.25b3). CHANGELOG has the 0.1.25 section. Tag `0.1.25` and a GitHub release follow the merge.
- **Test unit log, 2026-11-22 to 2026-11-24** (`home-assistant_2026-11-24T20-10-01`, 5,000 lines, capped): one SmartHomeSec "Timeout from API" warning, and no login, 401, cooldown, give-up or Repairs entries. Other warnings and errors came from other integrations.
- **Debug level:** info or warning is enough for normal running. Turn SmartHomeSec to debug only for a short window when checking logins or the loop.
- **Still open:** production upgrade (still 0.1.24), the two-instance warning idea, and the vendor disclosure decision.


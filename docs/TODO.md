# TODO

## Waiting on others

Nothing open. Upstream's author replied on [koying/smarthomesec_ha#3](https://github.com/koying/smarthomesec_ha/issues/3) (2026-11-07). He is fine with the fork and considers the upstream repo public domain. He has not added a LICENSE upstream and is not active, so we are leaving it there.

## Open

- [ ] **README placeholders.** The "Installation" section has the heading `## Installation-ha` and the text `Type in xxx`, and the HACS URL line has a stray trailing space. Fix when next editing the README.
- [ ] **Local test on HA 2026.1.** Native Windows can't run HA 2026.1 (its `runner.py` imports `fcntl`). CI on Linux is the only test run for it. Install WSL if local runs are needed.
- [ ] **Python 3.13 on Windows.** Installing the test deps for newer HA needs Microsoft C++ Build Tools (`pyspeex-noise`, `lru-dict`). Only needed for local runs on Windows.

## Session notes

### 2026-11-06

- **Minimum HA raised to 2026.1.0** (PR #34, merged as `fe0f819`). `hacs.json` and the CI minimum-version job now use HA 2026.1.0 on Python 3.13. Python 3.12 dropped from the matrix. The `josepy<2` pin was removed (HA 2026.1 requires `josepy` 2.x).
- **Release 0.1.22** (`a5f0aca`, tag `0.1.22`). Version bump to 0.1.22 on `main`. Release notes say the release needs HA 2026.1.0 or newer. Installed and confirmed working on the test HA.
- **Credits section** added to the README (PR #35, merged). It names Chris Browet (koying) as the original author and links upstream.
- **License.** Upstream's author replied on koying/smarthomesec_ha#3 that he considers the repo public domain. We chose CC0 1.0 for this fork and added `LICENSE` and a README License section (PR #37). Upstream still has no LICENSE; left as is.
- **Local Python setup.** `uv` installed. Python 3.12.16 and 3.13.18 are managed by uv. The 233-test suite passed on 3.12 before the minimum-version bump. Local git has no user identity configured, so commits were made with `-c user.name="Claude Code" -c user.email=...` for each command.

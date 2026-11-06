# TODO

## Waiting on others

- [ ] **Upstream license.** Upstream `koying/smarthomesec_ha` has no LICENSE file. Asked for one (or permission for the fork) in [koying/smarthomesec_ha#3](https://github.com/koying/smarthomesec_ha/issues/3), opened 2026-11-06. No reply yet. Check the issue from time to time.

## Open

- [ ] **README placeholders.** The "Installation" section has the heading `## Installation-ha` and the text `Type in xxx`, and the HACS URL line has a stray trailing space. Fix when next editing the README.
- [ ] **Local test on HA 2026.1.** Native Windows can't run HA 2026.1 (its `runner.py` imports `fcntl`). CI on Linux is the only test run for it. Install WSL if local runs are needed.
- [ ] **Python 3.13 on Windows.** Installing the test deps for newer HA needs Microsoft C++ Build Tools (`pyspeex-noise`, `lru-dict`). Only needed for local runs on Windows.

## Session notes

### 2026-11-06

- **Minimum HA raised to 2026.1.0** (PR #34, merged as `fe0f819`). `hacs.json` and the CI minimum-version job now use HA 2026.1.0 on Python 3.13. Python 3.12 dropped from the matrix. The `josepy<2` pin was removed (HA 2026.1 requires `josepy` 2.x).
- **Release 0.1.22** (`a5f0aca`, tag `0.1.22`). Version bump to 0.1.22 on `main`. Release notes say the release needs HA 2026.1.0 or newer. Installed and confirmed working on the test HA.
- **Credits section** added to the README (PR #35, merged). It names Chris Browet (koying) as the original author and links upstream.
- **Local Python setup.** `uv` installed. Python 3.12.16 and 3.13.18 are managed by uv. The 233-test suite passed on 3.12 before the minimum-version bump. Local git has no user identity configured, so commits were made with `-c user.name="Claude Code" -c user.email=...` for each command.

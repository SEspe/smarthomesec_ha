"""Every import must be something Home Assistant will actually have installed.

Found 2026-10-12: `import async_timeout` at module level. HA 2026.10 runs on
Python 3.14, where aiohttp no longer pulls async-timeout in and HA does not
ship it itself (its own lint rule says "use asyncio.timeout instead"). On such
an install the import fails and the whole integration does not load. CI never
saw it because it only ran against HA 2025.1 and 2026.2.

So this checks every import in the integration against three sources:
the standard library, the packages HA core ships, and what manifest.json
declares. Anything else must be added to the manifest, or not used.
"""

import ast
import json
import sys
from pathlib import Path

COMPONENT = Path("custom_components/smarthomesec")

# Third-party packages Home Assistant core installs itself — checked against
# HA 2026.10.1's pyproject.toml. `voluptuous` is no longer installed since
# 2026.9, but HA aliases it to probatio in sys.modules at import time and
# documents that custom integrations may keep using it (developer blog,
# 2026-09-30, "Probatio is our validation engine").
SHIPPED_BY_HA = {"homeassistant", "requests", "certifi", "voluptuous", "aiohttp", "yarl"}

# Import name -> distribution name, for what manifest.json declares.
DECLARED_MODULE_FOR = {"websocket-client": "websocket"}


def _top_level_imports():
    found = {}
    for path in sorted(COMPONENT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                found.setdefault(name.split(".")[0], set()).add(path.name)
    return found


def _declared_modules():
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    modules = set()
    for requirement in manifest.get("requirements", []):
        dist = requirement.split("==")[0].split(">=")[0].strip().lower()
        modules.add(DECLARED_MODULE_FOR.get(dist, dist.replace("-", "_")))
    return modules


def test_every_import_is_available_on_a_current_home_assistant():
    allowed = set(sys.stdlib_module_names) | SHIPPED_BY_HA | _declared_modules() | {
        "custom_components",
        "__future__",
    }
    unknown = {
        name: sorted(files) for name, files in _top_level_imports().items() if name not in allowed
    }

    assert not unknown, (
        "These imports are neither stdlib, shipped by Home Assistant, nor declared in "
        f"manifest.json requirements: {unknown}"
    )


def test_async_timeout_is_not_used():
    """The specific regression: asyncio.timeout (stdlib since 3.11) replaces it."""
    assert "async_timeout" not in _top_level_imports()

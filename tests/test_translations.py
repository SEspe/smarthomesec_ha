"""Translation files must parse with no duplicate keys and contain the new strings.

A duplicate "issues" block in en.json silently dropped the token_loop text in
0.1.25b2: JSON keeps only the last duplicate key. This test fails on duplicates.
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1] / "custom_components" / "smarthomesec"
FILES = [ROOT / "strings.json", ROOT / "translations" / "en.json", ROOT / "translations" / "no.json"]


def _no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key {key!r}")
        out[key] = value
    return out


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name + ("" if p.parent == ROOT else "/" + p.parent.name))
def test_no_duplicate_keys(path):
    json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicates)


@pytest.mark.parametrize("path", [ROOT / "strings.json", ROOT / "translations" / "en.json"], ids=["strings", "en"])
def test_english_has_the_repairs_and_entity_text(path):
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicates)

    token_loop = data["issues"]["token_loop"]
    assert token_loop["title"] and token_loop["description"]
    assert data["entity"]["binary_sensor"]["live_connection"]["name"] == "Live connection"
    assert data["entity"]["button"]["retry_connection"]["name"] == "Retry connection"


def test_norwegian_has_the_repairs_text():
    data = json.loads((ROOT / "translations" / "no.json").read_text(encoding="utf-8"))
    assert data["issues"]["token_loop"]["title"]

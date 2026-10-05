"""Keep incorrectly filed drafts visible while excluding them from calculations."""

import json
from pathlib import Path

from backend.paths import ROOT

FILE = ROOT / "data/drafts/misfiled.json"


def misfiled_ids() -> set[str]:
    return {item["id"] for item in json.loads(FILE.read_text(encoding="utf-8"))["items"]}


def misfiled_sections() -> set[tuple[str, str]]:
    return {(parts[1], parts[2]) for identifier in misfiled_ids()
            if len(parts := identifier.split("/")) >= 3}

"""Turns the recorded demo runs in data/runs into the replayable days the page shows.

    python scripts/export_days.py

Reads local files only. Sandbox account addresses are replaced with the demo's made-up ones.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from countersign.config import ROOT
from countersign.days import export_all

import json

from countersign.facts import collect

target = ROOT / "src" / "countersign" / "static" / "days"
written = export_all(ROOT / "data", target)
print(f"{len(written)} day(s) written to {target.relative_to(ROOT)}")
for name in written:
    print("  " + name)
facts = collect(ROOT / "data", ROOT / "tests")
(target.parent / "facts.json").write_text(json.dumps(facts, indent=1), encoding="utf-8")
print("facts:", json.dumps(facts))

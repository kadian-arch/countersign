"""Turns the recorded demo runs in data/runs into the replayable days the page shows.

    python scripts/export_days.py

Reads local files only. Sandbox account addresses are replaced with the demo's made-up ones. Only runs made with the
current guard, reply checker, lookups, loss counting and prompt are used (see fingerprint.py).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from countersign.config import ROOT, load_env
from countersign.days import export_all
from countersign.facts import collect
from countersign.runs import stale_count

load_env()   # so the sandbox addresses in .env are the ones replaced
target = ROOT / "src" / "countersign" / "static" / "days"
written = export_all(ROOT / "data", target)
print(f"{len(written)} day(s) written to {target.relative_to(ROOT)}")
for name in written:
    print("  " + name)
stale = stale_count(ROOT / "data")
if stale:
    print(f"{stale} saved run(s) were made with an earlier version of the guard or prompt and are not used")
facts = collect(ROOT / "data", ROOT / "tests")
(target.parent / "facts.json").write_text(json.dumps(facts, indent=1), encoding="utf-8")
print("facts:", json.dumps(facts))

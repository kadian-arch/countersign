"""Breaks the guard on purpose, one protection at a time, and checks the stress test notices.

    python scripts/mutation_check.py            3000 random attempts per broken guard
    python scripts/mutation_check.py --n 20000
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.stdout.reconfigure(errors="replace")

from countersign.mutants import MUTANTS, check

n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 3000
print(f"{'protection removed':<42}{'flagged by the stress test':<34}caught")
missed = 0
for name in MUTANTS:
    r = check(name, n)
    flagged = ", ".join(f"{k} x{v}" for k, v in sorted(r["flagged"].items())) or "nothing got through"
    verdict = ("held by a second rule" if r["layered"] else "yes") if r["caught"] else "NO"
    print(f"{name:<42}{flagged:<34}{verdict}")
    missed += not r["caught"]
print(f"\n{len(MUTANTS) - missed} of {len(MUTANTS)} broken guards behaved as expected")
sys.exit(1 if missed else 0)

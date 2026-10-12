"""The numbers the page quotes about how the guard was tested, read from the saved results of those
tests, so the page never says more than the files do."""
import hashlib
import json
import unittest
from pathlib import Path

from .runs import load_runs

GUARD = Path(__file__).with_name("guard.py")


def _stress(data_dir: Path) -> dict | None:
    sha = hashlib.sha256(GUARD.read_bytes()).hexdigest()
    newest = {}
    for f in sorted((data_dir / "stress").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("guard_sha256") == sha and d["n"] >= 100000:
            newest[d["seed"]] = d
    if not newest:
        return None
    runs = list(newest.values())
    fuzz = [r["guard"]["fuzz"]["total"] for r in runs]
    fam = runs[0]["guard"]["families"]["total"]
    off = next((r["open"] for r in runs if "open" in r), None)
    return {"seeds": len(runs), "random_attempts": sum(t["n"] for t in fuzz), "ran": sum(t["executed"] for t in fuzz),
            "scenarios": fam["n"],
            "broken": sum(t["violations"] for t in fuzz) + sum(r["guard"]["families"]["total"]["violations"] for r in runs),
            "off_broken": off["fuzz"]["total"]["violations"] if off else None,
            "off_attempts": off["fuzz"]["total"]["n"] if off else None, "guard_sha256": sha[:16]}


def _model_runs(data_dir: Path) -> dict:
    runs = [r for r in load_runs(data_dir) if not r["incomplete"]]
    out = {}
    for inbox in ("standard", "holdout", "final"):
        o = [r for r in runs if r["mode"] == "open" and r.get("inbox", "standard") == inbox]
        g = [r for r in runs if r["mode"] == "guarded" and r.get("inbox", "standard") == inbox]
        lost = lambda rs: [float(r["report"]["lost"]) for r in rs]
        out[inbox] = {"runs_without": len(o), "runs_with": len(g),
                      "lost_without_avg": round(sum(lost(o)) / len(o), 2) if o else None,
                      "lost_without_max": max(lost(o)) if o else None,
                      "lost_with_max": max(lost(g)) if g else None}
    return out


def _redteam(data_dir: Path) -> dict | None:
    files = sorted((data_dir / "redteam").glob("*.json"))
    if not files:
        return None
    runs = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    return {"runs": len(runs), "models": sorted({r["model"] for r in runs}), "valid": sum(r["valid"] for r in runs),
            "ran": sum(r["ran"] for r in runs), "held": sum(r["held"] for r in runs), "blocked": sum(r["blocked"] for r in runs),
            "broke": sum(len(r["breaks"]) for r in runs)}


def collect(data_dir: Path, tests_dir: Path | None = None) -> dict:
    from .mutants import MUTANTS, check
    results = [check(name, 1500, 3) for name in MUTANTS]
    out = {"stress": _stress(data_dir), "model_runs": _model_runs(data_dir), "redteam": _redteam(data_dir),
           "mutation": {"total": len(results), "as_expected": sum(r["caught"] for r in results)}}
    if tests_dir:
        out["unit_tests"] = unittest.TestLoader().discover(str(tests_dir), top_level_dir=str(tests_dir.parent)).countTestCases()
    return out

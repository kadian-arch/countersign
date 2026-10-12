"""Throws attempted refunds and payouts at the guard with no model, no network and no .env.

    python scripts/stress_guard.py                    scenario families plus 20000 random attempts
    python scripts/stress_guard.py --n 100000 --seed 7
    python scripts/stress_guard.py --compare          also replay the same calls with the guard off
    python scripts/stress_guard.py --no-save          do not write a result file (for CI), exits 1 if a rule was broken

Every call that reaches the simulated PayPal is checked against the shop's rules (see stress.py).
"""
import hashlib
import json
import sys
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.stdout.reconfigure(errors="replace")

from countersign.config import ROOT
from countersign.sim import SimShop
from countersign.stress import fuzz, prepare, run_families, summarise


def option(name, default):
    for i, arg in enumerate(sys.argv):
        if arg == name and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def show(title, summary):
    t = summary["total"]
    print(f"\n== {title}")
    print(f"{t['n']} attempted calls: {t['executed']} ran, {t['held']} held for the owner, {t['blocked']} blocked, "
          f"{t['error']} refused by PayPal or the tool")
    print(f"rules broken by a call that ran: {t['violations']}   money out against the rules: {t['lost']}")
    for rule, n in sorted(summary["breaches"].items()):
        print(f"    {n:>6}  {rule}")


def families_table(summary):
    print(f"\n{'family':<40}{'kind':<8}{'n':>5}{'ran':>6}{'held':>6}{'block':>6}{'broken':>7}")
    for name, f in summary["families"].items():
        print(f"{name:<40}{f['kind']:<8}{f['n']:>5}{f['executed']:>6}{f['held']:>6}{f['blocked']:>6}{f['violations']:>7}")
    h = summary["total"]["honest"]
    print(f"\nhonest requests: {h['ran']} of {h['should_run']} within the limits ran by themselves; "
          f"{h['waited']} of {h['should_wait']} over the limits waited for the owner; "
          f"{h['wrongly_blocked']} wrongly blocked; {h['ran_when_owner_should_decide']} ran that the owner should have seen")


def main():
    n = int(option("--n", 20000))
    seed = int(option("--seed", 1))
    compare = "--compare" in sys.argv
    failed = False
    source = Path(__file__).resolve().parents[1] / "src" / "countersign" / "guard.py"
    out = {"seed": seed, "n": n, "finished": datetime.now().isoformat(timespec="seconds"),
           "guard_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    for label, guard in (("with Countersign", "guard"),) + ((("without Countersign", "open"),) if compare else ()):
        started = time.time()
        make = lambda: prepare(SimShop(guard=guard))
        fam = summarise(run_families(make))
        results, problems = fuzz(make, n, seed)
        rnd = summarise(results)
        show(f"scenario families, {label}", fam)
        if guard == "guard":
            families_table(fam)
        show(f"{n} random attempts (seed {seed}), {label}", rnd)
        print(f"({time.time() - started:.0f}s)   ledger chains: " + ("all intact" if not problems else f"PROBLEMS {problems[:3]}"))
        out[guard] = {"families": fam, "fuzz": rnd}
        if guard == "guard" and (fam["total"]["violations"] or rnd["total"]["violations"] or problems):
            failed = True
    if "--no-save" not in sys.argv:
        path = ROOT / "data" / "stress"
        path.mkdir(parents=True, exist_ok=True)
        file = path / f"{datetime.now():%Y%m%d-%H%M%S}-seed{seed}-n{n}.json"
        file.write_text(json.dumps(out, indent=2, default=lambda o: str(o) if isinstance(o, Decimal) else o), encoding="utf-8")
        print(f"\nsaved {file.relative_to(ROOT)}")
    if failed:
        sys.exit("the guard let a call through that broke a rule")


main()

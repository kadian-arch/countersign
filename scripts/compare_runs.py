"""Side by side: the same inbox without and with Countersign.

    python scripts/compare_runs.py                 the newest complete run of each kind
    python scripts/compare_runs.py --all           every complete run, with averages per kind
    python scripts/compare_runs.py --model groq/openai/gpt-oss-120b     only runs pinned to that model
    python scripts/compare_runs.py --inbox holdout   the second inbox instead of the standard one

Incomplete runs are always ignored, and so are runs made with an earlier version of the guard, reply checker,
lookups, loss counting or prompt (see fingerprint.py).
"""
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from countersign.config import ROOT
from countersign.report import what_happened
from countersign.runs import latest_complete as _latest, load_runs as _load, stale_count


def load_runs(data_dir):
    return _load(data_dir, current=True)   # only runs made with the guard and prompt as they are now


def latest_complete(*args):
    return _latest(*args, current=True)

pinned, inbox = None, "standard"
for i, arg in enumerate(sys.argv):
    if arg == "--model" and i + 1 < len(sys.argv):
        pinned = sys.argv[i + 1]
    elif arg.startswith("--model="):
        pinned = arg.split("=", 1)[1]
    elif arg == "--inbox" and i + 1 < len(sys.argv):
        inbox = sys.argv[i + 1]


def leaked(run):
    return run.get("addresses_leaked", 0)


def held(run):
    return run["report"]["counts"].get("pending", 0)


if "--all" in sys.argv:
    runs = [r for r in load_runs(ROOT / "data") if not r["incomplete"] and (pinned is None or r.get("pinned") == pinned)
            and r.get("inbox", "standard") == inbox]
    if not runs:
        sys.exit("no complete runs yet")
    print(f"{'run':<52}{'moved':>10}{'lost':>9}{'stopped':>9}{'held':>6}{'leaked':>8}")
    for kind in ("open", "guarded"):
        group = [r for r in runs if r["mode"] == kind]
        for r in group:
            rep = r["report"]
            print(f"{r['folder']:<52}{rep['moved']:>10}{rep['lost']:>9}{rep['prevented']:>9}{held(r):>6}{leaked(r):>8}")
        if group:
            n = Decimal(len(group))
            avg = lambda key: sum((Decimal(r["report"][key]) for r in group), Decimal("0")) / n
            print(f"{'  average of ' + str(len(group)) + ' ' + ('without Countersign' if kind == 'open' else 'with Countersign'):<52}"
                  f"{avg('moved'):>10.2f}{avg('lost'):>9.2f}{avg('prevented'):>9.2f}{sum(held(r) for r in group) / len(group):>6.1f}"
                  f"{sum(leaked(r) for r in group) / len(group):>8.1f}\n")
    sys.exit()

open_run = latest_complete(ROOT / "data", "open", pinned, inbox)
guarded = latest_complete(ROOT / "data", "guarded", pinned, inbox)
if open_run is None or guarded is None:
    missing = [name for name, run in (("without Countersign", open_run), ("with Countersign", guarded)) if run is None]
    sys.exit("no complete run yet for: " + ", ".join(missing) + ". Run scripts/run_inbox.py --fresh (add --open for the first).")

by_id = {e["id"]: e for e in guarded["emails"]}
print(f"{'':<5}{'':<7}{'without Countersign':<34}with Countersign")
for e in open_run["emails"]:
    g = by_id.get(e["id"])
    print(f"{e['id']:<5}{e['kind']:<7}{what_happened(e):<34}{what_happened(g) if g else '-'}")

print()
rows = [
    ("money moved", lambda r, m: r["report"]["moved"]),
    ("money the shop should not have paid", lambda r, m: r["report"]["lost"]),
    ("money stopped before it left", lambda r, m: r["report"]["prevented"]),
    ("held for the owner", lambda r, m: str(held(r))),
    ("money statements sent with no ledger backing*", lambda r, m: str(r["unbacked_statements"]) if m == "open" else "0"),
    ("money statements removed before sending*", lambda r, m: str(r["unbacked_statements"]) if m == "guarded" else "0"),
    ("shop addresses given out in replies", lambda r, m: str(leaked(r))),
]
print(f"{'':<48}{'without':>10}{'with':>10}")
for label, get in rows:
    print(f"{label:<48}{get(open_run, 'open'):>10}{get(guarded, 'guarded'):>10}")
print("\n* matched by sentence patterns, so a true sentence can be counted and a false one can slip by.")
print(f"runs: {open_run['folder']}  |  {guarded['folder']}")
print(f"models: {open_run['model']}  |  {guarded['model']}")
print("One run of each. The guard's decision on a given action is fixed (see the tests), but what the model proposes varies between runs.")
print("Use --all after several runs to see the spread.")

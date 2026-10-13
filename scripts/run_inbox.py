"""Runs the demo inbox through the agent against the PayPal sandbox.

    python scripts/run_inbox.py --fresh                      with Countersign (guard, checked replies)
    python scripts/run_inbox.py --open --fresh               the same agent without it (sandbox money really moves)
    python scripts/run_inbox.py --model groq/openai/gpt-oss-120b     pin one model for the whole run
    python scripts/run_inbox.py --only E01,X1                chosen emails only
    python scripts/run_inbox.py --toolkit                    also give the agent the PayPal Agent Toolkit read tools
    python scripts/run_inbox.py --inbox holdout --fresh      the second inbox, written after the guard was finished
    python scripts/run_inbox.py --inbox final --fresh        the third inbox, kept for the end

--fresh starts the demo over first: new shop records and new paid orders, so every run has untouched
orders and invoices. Each run keeps its own folder under data/runs/ with its ledger and results.
A run that cannot get answers from the model stops early and is marked incomplete.
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# model replies can hold characters a piped Windows console cannot encode, show a ? instead of crashing
sys.stdout.reconfigure(errors="replace")

from countersign import demo_data as demo
from countersign import fingerprint, holdout
from countersign.agent import Agent
from countersign.final import final_inbox
from countersign.audit import addresses_in
from countersign.config import DB_PATH, ROOT, load_env, need
from countersign.evaluate import report
from countersign.guard import Guard, OpenGuard
from countersign.inbox import inbox
from countersign.ledger import Ledger
from countersign.llm import LLM, LLMUnavailable, pinned_provider, providers_from_env
from countersign.paypal import LiveFacts, PayPal
from countersign.policy import Policy
from countersign.report import format_email, outcome_to_dict, unavailable_entry
from countersign.runs import Streak, new_run_dir
from countersign.runtime import Runtime
from countersign.seed import seed_demo
from countersign.store import Store
from countersign.tools import build_tools, toolkit_tools


def option(name):
    for i, arg in enumerate(sys.argv):
        if arg == name and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if arg.startswith(name + "="):
            return arg.split("=", 1)[1]
    return None


open_mode = "--open" in sys.argv
mode = "open" if open_mode else "guarded"
only = option("--only")
wanted = set(only.split(",")) if only else None

inbox_name = option("--inbox") or "standard"
if inbox_name not in ("standard", "holdout", "final"):
    sys.exit("--inbox must be standard, holdout or final")
load_env()
paypal = PayPal(need("PAYPAL_CLIENT_ID"), need("PAYPAL_CLIENT_SECRET"))
attacker = need("SANDBOX_ATTACKER_EMAIL").lower()
if "--fresh" in sys.argv:
    DB_PATH.unlink(missing_ok=True)
store = Store(str(DB_PATH))
if "--fresh" in sys.argv:
    extra_orders, extra_invoices = holdout.extra(need("SANDBOX_ATTACKER_EMAIL")) if inbox_name != "standard" else ((), ())
    seed_demo(paypal, store, card=need("SANDBOX_CARD_NUMBER"), expiry=need("SANDBOX_CARD_EXPIRY"),
              supplier_email=need("SANDBOX_SUPPLIER_EMAIL"), attacker_email=need("SANDBOX_ATTACKER_EMAIL"),
              extra_orders=extra_orders, extra_invoices=extra_invoices)
    print()
elif not any(o["capture_id"] for o in store.orders()):
    sys.exit("no paid orders yet, run again with --fresh")
elif inbox_name != "standard" and store.get_order("10481") is None:
    sys.exit("the extra orders for this inbox are not seeded yet, run again with --fresh")

pinned = option("--model")
run_dir = new_run_dir(ROOT / "data", mode, pinned, inbox_name)
ledger = Ledger(str(run_dir / "ledger.db"))
facts = LiveFacts(paypal, store, ledger)
tools = build_tools(paypal, facts, store)
if open_mode:   # without Countersign the lookups hand over whole records too
    for t in tools.values():
        t.redact = None
if "--toolkit" in sys.argv:
    tools.update(toolkit_tools(need("PAYPAL_CLIENT_ID"), need("PAYPAL_CLIENT_SECRET")))
runtime = Runtime(tools, OpenGuard() if open_mode else Guard(Policy(), facts), ledger)

try:
    providers = [pinned_provider(pinned)] if pinned else providers_from_env()
except LLMUnavailable as e:
    sys.exit(str(e))
llm = LLM(providers, notify=lambda message: print(f"        ({message})", flush=True))
agent = Agent(llm, runtime, demo.SHOP, check_replies=not open_mode, facts=demo.SHOP_FACTS)
supplier = sorted(store.known_payees())[0]
private = {a.lower() for a in store.known_payees()} | {o["customer_email"].lower() for o in store.orders()}

print(f"mode: {'NO COUNTERSIGN' if open_mode else 'Countersign on'}" + (f"   model: {pinned}" if pinned else "")
      + f"   inbox: {inbox_name}   folder: {run_dir.name}\n")
entries, streak, stopped = [], Streak(3), False
for mail in {"standard": inbox, "holdout": holdout.holdout_inbox, "final": final_inbox}[inbox_name](supplier, attacker):
    if wanted and mail.id not in wanted:
        continue
    if stopped:
        entries.append(unavailable_entry(mail, "run stopped early"))
        continue
    try:
        outcome = agent.handle(mail)
    except LLMUnavailable as e:
        print(f"[{mail.id}] {mail.kind:<6} NOT HANDLED, model unavailable: {e}\n")
        entries.append(unavailable_entry(mail, str(e)))
        if streak.failed():
            stopped = True
            print("The model has failed three emails in a row, stopping here instead of waiting through the rest.\n")
        continue
    streak.ok()
    print(format_email(mail, outcome, llm.last_used, checked=not open_mode))
    entry = outcome_to_dict(mail, outcome, llm.last_used)
    entry["leaked"] = [a for a in addresses_in(outcome.reply, mail.sender) if a.lower() in private]
    entries.append(entry)
    time.sleep(float(option("--pause") or 4))

result = report(ledger.recent(1000), store)
claims = [c for e in entries for c in e["claims"]]
unbacked = sum(1 for c in claims if not c["supported"])
leaked = sum(len(e.get("leaked", [])) for e in entries)
skipped = [e["id"] for e in entries if e.get("unavailable")]
print("-- result")
if skipped:
    print(f"INCOMPLETE: {len(skipped)} email(s) were not handled ({', '.join(skipped)}). This run is kept but will not be compared.\n")
print("actions:", {k: v for k, v in result["counts"].items() if v})
print(f"money moved: {result['moved']}")
print(f"money the shop should not have paid: {result['lost']}")
for item in result["lost_items"]:
    print(f"    #{item['id']} {item['source']}: {item['loss']} ({item['why']})")
print(f"money stopped by the guard: {result['prevented']}")
for item in result["prevented_items"]:
    print(f"    #{item['id']} {item['source']}: {item['loss']} ({item['why']})")
print(f"money statements not backed by the ledger (heuristic): {unbacked}"
      + ("  (removed before sending)" if not open_mode else "  (these went out)"))
print(f"shop addresses given out in replies: {leaked}")
invented = sum(len(e.get("invented", [])) for e in entries)
print(f"statements about the shop its knowledge does not back (heuristic): {invented}"
      + ("  (removed before sending)" if not open_mode else "  (these went out)"))
pending = ledger.pending()
if pending:
    print("\nwaiting for the owner:")
    for r in pending:
        print(f"  #{r['id']} {r['tool']} {r['args']}  <- {', '.join(x['code'] for x in r['reasons'])}")
problems = ledger.verify()
head = ledger.head()
print(f"\nledger: {head['events']} events, head {head['head'][:16]}  " + ("chain intact" if not problems else f"PROBLEMS: {problems}"))

(run_dir / "result.json").write_text(json.dumps({
    "mode": mode, "inbox": inbox_name, "pinned": pinned, "model": pinned or llm.last_used, "finished": datetime.now().isoformat(timespec="seconds"),
    "incomplete": skipped, "report": result, "unbacked_statements": unbacked, "addresses_leaked": leaked,
    "invented_claims": invented, "fingerprint": fingerprint.current(),
    "emails": entries}, indent=2), encoding="utf-8")
print(f"saved {run_dir.relative_to(ROOT)}")

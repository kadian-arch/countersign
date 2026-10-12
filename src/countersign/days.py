"""Recorded days: a real run of the demo inbox with the guard off and the same inbox with it on, kept so
anyone can replay what the agent did, email by email, without a model or a PayPal account."""
import json
import re
from pathlib import Path

from . import demo_data as demo
from .final import final_inbox
from .holdout import holdout_inbox
from .inbox import inbox
from .runs import latest_complete

INBOXES = {"standard": (inbox, "first inbox"), "holdout": (holdout_inbox, "second inbox"), "final": (final_inbox, "third inbox")}

SIM_ATTACKER = "ryan.mallory@example.com"
SIM_SUPPLIER = "accounts@eastgate-packaging.example"
_DASHES = {ord(c): "-" for c in "‐‑‒−"}
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")


def anonymise(text: str) -> str:
    """Sandbox test-account addresses become the demo's own made-up ones."""
    def swap(m):
        a = m.group(0)
        if a.lower().endswith(".example") or a.lower().endswith("example.com"):
            return a
        low = a.lower()
        return SIM_ATTACKER if "attacker" in low else SIM_SUPPLIER if "supplier" in low else "[address]"
    return _EMAIL.sub(swap, text.translate(_DASHES))


def _clean(value):
    return json.loads(anonymise(json.dumps(value)))


def _side(entry: dict, report: dict, mail_id: str) -> dict:
    sources = {f"inbox:{mail_id}", f"owner:{mail_id}"}
    lost = sum(float(i["loss"]) for i in report["lost_items"] if i["source"] in sources)
    stopped = sum(float(i["loss"]) for i in report["prevented_items"] if i["source"] in sources)
    return {
        "reply": anonymise(entry.get("reply", "")),
        "steps": [{"tool": s["tool"], "status": s["status"], "reasons": s["reasons"], "error": bool(s.get("error")),
                   "amount": s["args"].get("amount"), "receiver": _clean(s["args"].get("receiver")),
                   "invoice": s["args"].get("invoice_id")} for s in entry["steps"]],
        "unbacked": [anonymise(c["text"]) for c in entry.get("claims", []) if not c["supported"]],
        "withheld": entry.get("redacted", 0),
        "leaked": len(entry.get("leaked", [])),
        "lost": round(lost, 2), "stopped": round(stopped, 2),
    }


def _totals(run: dict) -> dict:
    r = run["report"]
    return {"moved": r["moved"], "lost": r["lost"], "stopped": r["prevented"], "held": r["counts"].get("pending", 0),
            "unbacked": run["unbacked_statements"], "leaked": run.get("addresses_leaked", 0)}


NAMES = {"standard": "Everyday inbox", "holdout": "Tougher inbox", "final": "Hardest inbox"}


def build_day(data_dir: Path, inbox_name: str, model: str, assistant: str = "A") -> dict | None:
    without = latest_complete(data_dir, "open", model, inbox_name)
    with_it = latest_complete(data_dir, "guarded", model, inbox_name)
    if without is None or with_it is None:
        return None
    make_mails, label = INBOXES[inbox_name]
    mails = make_mails(SIM_SUPPLIER, SIM_ATTACKER)
    a = {e["id"]: e for e in without["emails"]}
    b = {e["id"]: e for e in with_it["emails"]}
    emails = []
    for m in mails:
        if m.id not in a or m.id not in b:
            continue
        emails.append({"id": m.id, "kind": m.kind, "sender": m.sender, "subject": m.subject, "body": m.body,
                       "owner": m.sender == demo.OWNER_EMAIL, "note": m.note,
                       "without": _side(a[m.id], without["report"], m.id), "with": _side(b[m.id], with_it["report"], m.id)})
    return {"title": f"{NAMES[inbox_name]}, {len(emails)} emails, assistant {assistant}",
            "inbox": inbox_name, "model": model, "shop": demo.SHOP, "emails": emails,
            "totals": {"without": _totals(without), "with": _totals(with_it)}}


def export_all(data_dir: Path, target: Path) -> list[str]:
    target.mkdir(parents=True, exist_ok=True)
    for old in target.glob("*.json"):
        old.unlink()
    written = []
    seen = {(r.get("inbox", "standard"), r.get("pinned")) for r in _runs(data_dir) if r.get("pinned")}
    letters = {m: chr(65 + i) for i, m in enumerate(sorted({m for _, m in seen}))}   # the page never names the models
    for inbox_name, model in sorted(seen):
        day = build_day(data_dir, inbox_name, model, letters[model])
        if day:
            name = f"{inbox_name}__{re.sub(r'[^a-z0-9]+', '-', model.lower())}.json"
            (target / name).write_text(json.dumps(day, indent=1), encoding="utf-8")
            written.append(name)
    return written


def _runs(data_dir: Path):
    from .runs import load_runs
    return load_runs(data_dir)


def list_days(folder: Path) -> list[dict]:
    out = []
    for f in sorted(folder.glob("*.json")) if folder.exists() else []:
        d = json.loads(f.read_text(encoding="utf-8"))
        out.append({"id": f.stem, "title": d["title"], "emails": len(d["emails"]),
                    "lost_without": d["totals"]["without"]["lost"], "lost_with": d["totals"]["with"]["lost"]})
    return out

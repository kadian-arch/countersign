"""Does what Countersign recorded match what PayPal says happened?

The ledger is Countersign's own account of every refund it made. PayPal's Transaction Search is PayPal's account of the
same money. This compares the two for the last month and reports where they differ: a refund the ledger says was made
that PayPal does not show, and a refund PayPal shows on one of the shop's payments that the ledger never made (someone
refunded from PayPal's own dashboard).

The request shape (start_date, end_date, fields, page_size, a window of at most 31 days, results that can take up to
three hours to appear) was checked with the APIMatic Context Plugin against PayPal's Server SDK model, see
docs/apimatic-context-plugin.md. The call itself is a plain REST call like every other call here, so the one small client
stays the only path to PayPal."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

LAG = timedelta(hours=3)         # PayPal says executed transactions can take up to three hours to appear
WINDOW = timedelta(days=31)      # the longest range one search accepts
REFUND = "T1107"                 # PayPal's event code for a refund of a payment


def stamp(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")


def windows(start: datetime, end: datetime):
    """The range cut into pieces PayPal will accept."""
    while start < end:
        yield start, min(start + WINDOW, end)
        start += WINDOW


def normalise(detail: dict) -> dict | None:
    """One transaction from a search result as the few fields this needs."""
    info = detail.get("transaction_info") or {}
    try:
        amount = Decimal(str((info.get("transaction_amount") or {}).get("value")))
    except (InvalidOperation, ValueError):
        return None
    return {"id": info.get("transaction_id"), "ref": info.get("paypal_reference_id"), "amount": amount,
            "code": info.get("transaction_event_code"), "status": info.get("transaction_status"),
            "date": info.get("transaction_initiation_date")}


def _money(value) -> Decimal:
    return abs(Decimal(str(value)))


def _when(ts) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(ts))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def compare(rows: list[dict], transactions: list[dict], captures: set[str], now: datetime | None = None) -> dict:
    """rows are ledger rows, transactions what PayPal shows (normalised), captures the shop's own payment ids."""
    now = now or datetime.now(timezone.utc)
    theirs = [t for t in transactions if t["code"] == REFUND and t["ref"] in captures]
    mine = [r for r in rows if r["tool"] == "refund_payment" and r["status"] == "executed"]
    used: set[int] = set()
    matched, missing, recent = 0, [], 0
    for r in sorted(mine, key=lambda r: r["id"]):
        capture, amount = (r.get("args") or {}).get("capture_id"), _money(r["amount"])
        hit = next((i for i, t in enumerate(theirs) if i not in used and t["ref"] == capture and _money(t["amount"]) == amount), None)
        if hit is not None:
            used.add(hit)
            matched += 1
            continue
        t = _when(r.get("ts"))
        if t is not None and now - t < LAG:
            recent += 1
        else:
            missing.append({"request": r["id"], "capture": capture, "amount": str(amount)})
    outside = [{"capture": t["ref"], "amount": str(_money(t["amount"])), "date": t["date"], "id": t["id"]}
               for i, t in enumerate(theirs) if i not in used]
    paid = {t["id"] for t in transactions if t["code"] != REFUND}
    return {"refunds": {"ledger": len(mine), "matched": matched, "missing_in_paypal": missing, "too_recent_to_judge": recent,
                        "made_outside_countersign": outside},
            "payments": {"shop_payments": len(captures), "seen_in_paypal": len(captures & paid)},
            "ok": not missing and not outside}


def run(paypal, rows: list[dict], captures: set[str], days: int = 30, now: datetime | None = None) -> dict:
    """Asks PayPal for the last `days` days and compares. PayPal refuses the search for an app that does not have
    Transaction Search switched on, which is reported as such rather than as a mismatch."""
    from .paypal import PayPalError
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    try:
        transactions = paypal.transactions(start, now)
    except PayPalError as e:
        if e.status in (401, 403):
            return {"error": "not_enabled", "message": "PayPal does not let this app search transactions. Switch on Transaction Search "
                                                       "under the app's features in the PayPal developer dashboard, then try again."}
        said = " ".join(x for x in [str((e.body or {}).get("message") or (e.body or {}).get("name") or "")] +
                        [str(d.get("issue") or d.get("description") or "") for d in (e.body or {}).get("details", []) if isinstance(d, dict)] if x)
        return {"error": "paypal", "message": f"PayPal could not answer the search ({e.status})" + (f": {said[:240]}" if said else ".")}
    out = compare(rows, transactions, captures, now)
    out["window"] = {"from": stamp(start), "to": stamp(now), "transactions": len(transactions)}
    return out

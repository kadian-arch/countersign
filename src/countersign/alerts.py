"""Telling the owner when something is waiting for them, and letting them decide from the email.

The link in the email opens a page that shows the request and has an Approve and a Refuse button. It does not act
on its own, so a mail scanner opening the link cannot approve anything. The link carries a signature made from the
owner token, for that one action, good for a day. Approving re-runs the guard before anything is sent.
"""
import hashlib
import hmac
import html
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

TTL = 24 * 3600
MAX_PER_HOUR = 10   # a stranger's requests can create holds, so the owner's inbox is not theirs to fill


def _key(secret: str) -> bytes:
    return hashlib.sha256(b"countersign review links\n" + secret.encode()).digest()


def sign(secret: str, action_id: int, now: float | None = None) -> str:
    expires = int((now if now is not None else time.time()) + TTL)
    mac = hmac.new(_key(secret), f"{action_id}:{expires}".encode(), hashlib.sha256).hexdigest()[:40]
    return f"{expires}.{mac}"


def valid(secret: str, action_id: int, sig: str | None, now: float | None = None) -> bool:
    try:
        expires, mac = (sig or "").split(".", 1)
        if int(expires) < (now if now is not None else time.time()):
            return False
    except ValueError:
        return False
    good = hmac.new(_key(secret), f"{action_id}:{expires}".encode(), hashlib.sha256).hexdigest()[:40]
    return hmac.compare_digest(mac, good)


def describe(row: dict, store) -> str:
    """What the request is, in a sentence."""
    args, amount = row["args"], row["amount"]
    if row["tool"] == "refund_payment":
        order = store.order_by_capture(args.get("capture_id"))
        return f"Refund ${amount}" + (f" on order #{order['order_no']}" if order else "")
    invoice = f" for invoice {args['invoice_id']}" if args.get("invoice_id") else ""
    return f"Pay ${amount} to {args.get('receiver', '?')}{invoice}"


def who(row: dict) -> str:
    return row.get("sender") or "no sender recorded"


def _when(ts) -> str:
    """When a ledger row was written, in words. Mail has no viewer time zone, so it says UTC."""
    try:
        t = datetime.fromisoformat(str(ts)).astimezone(timezone.utc)
    except ValueError:
        return ""
    return f"{t:%b} {t.day}, {t:%H:%M} UTC"


def _money(value) -> str:
    try:
        return f"${Decimal(str(value)):,.2f}"
    except (InvalidOperation, ValueError):
        return f"${value}"


def email(shop: str, headline: str, intro: str, facts: list[tuple[str, str]], sections: list[tuple[str, list[str]]],
          button: tuple[str, str] | None, tone: str = "#6a82ff") -> tuple[str, str]:
    """One message, as plain text and as simple HTML. Both say the same thing: what happened, the facts, what it means,
    what to do. Everything that came from outside is escaped in the HTML."""
    e = html.escape
    lines = [headline, "", intro, ""]
    lines += [f"  {k}: {v}" for k, v in facts]
    for title, items in sections:
        lines += ["", title] + [f"  - {i}" for i in items]
    if button:
        lines += ["", f"{button[0]}:", button[1]]
    lines += ["", f"Sent by Countersign for {shop}. You can turn these emails off under Setup, in the Email tab."]
    rows = "".join(f"<tr><td style='padding:6px 14px 6px 0;color:#6b7280;white-space:nowrap;vertical-align:top'>{e(k)}</td>"
                   f"<td style='padding:6px 0;color:#111827'>{e(v)}</td></tr>" for k, v in facts)
    blocks = "".join(f"<p style='margin:18px 0 6px;font-weight:600;color:#111827'>{e(t)}</p>"
                     f"<ul style='margin:0;padding-left:20px;color:#374151'>{''.join(f'<li style=margin:3px 0>{e(i)}</li>' for i in items)}</ul>"
                     for t, items in sections)
    cta = (f"<p style='margin:24px 0 0'><a href='{e(button[1])}' style='display:inline-block;background:{tone};color:#ffffff;"
           f"text-decoration:none;font-weight:600;padding:12px 20px;border-radius:10px'>{e(button[0])}</a></p>") if button else ""
    page_html = (f"<div style='font:15px/1.55 -apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#f3f4f8;padding:22px 12px'>"
                 f"<div style='max-width:560px;margin:0 auto;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e5e7eb'>"
                 f"<div style='height:5px;background:{tone}'></div><div style='padding:22px 24px'>"
                 f"<p style='margin:0;color:#6b7280;font-size:13px'>{e(shop)}</p>"
                 f"<h1 style='margin:4px 0 10px;font-size:20px;color:#111827'>{e(headline)}</h1>"
                 f"<p style='margin:0 0 14px;color:#374151'>{e(intro)}</p>"
                 f"<table style='border-collapse:collapse;font-size:15px'>{rows}</table>{blocks}{cta}"
                 f"<p style='margin:26px 0 0;color:#9ca3af;font-size:12px'>Sent by Countersign for {e(shop)}. "
                 f"You can turn these emails off under Setup, in the Email tab.</p></div></div></div>")
    return "\n".join(lines) + "\n", page_html


def _held_facts(row: dict, store) -> list[tuple[str, str]]:
    out = [("Request", describe(row, store)), ("Asked by", who(row)), ("Received", _when(row.get("ts")))]
    args = row["args"]
    if row["tool"] == "refund_payment":
        order = store.order_by_capture(args.get("capture_id"))
        if order:
            out.insert(1, ("Order", f"#{order['order_no']}, {order['customer_name']}, paid {_money(order['total'])}"))
    else:
        invoice = store.invoice_row(str(args.get("invoice_id", ""))) if args.get("invoice_id") else None
        if invoice:
            out.insert(1, ("Invoice", f"{invoice['invoice_id']}, {invoice['description']}, {_money(invoice['amount'])}, due {invoice['due']}"))
    return [(k, v) for k, v in out if v]


def compose(row: dict, store, shop: str, link: str, others: int) -> tuple[str, str, str]:
    """The email for a request that is waiting for approval: subject, plain text, HTML."""
    what = describe(row, store)
    reasons = [r["message"] for r in row["reasons"]] or ["It needs your say-so."]
    sections = [("Why it was held", reasons),
                ("What happens next", ["Nothing has been sent to PayPal.", "The link opens a page that shows the request and asks before it does anything. "
                                       "Approving runs the checks again first. It works for 24 hours."]
                 + ([f"{others} other request{'s are' if others != 1 else ' is'} waiting as well."] if others else []))]
    text, page_html = email(shop, "Something is waiting for your approval", f"The assistant could not do this by itself: {what}.",
                            _held_facts(row, store), sections, ("Review and decide", link), tone="#d99a00")
    return f"Approval needed: {what}", text, page_html


# what an event from PayPal means for the owner, and what to do about it
_NOTICES = {
    "refund_outside": ("Refund made outside Countersign", "A refund was made in PayPal itself, not through the assistant.",
                       "#d99a00", ["If you made it, there is nothing to do.",
                                   "If you did not, look at the shop's PayPal activity, change the PayPal password and rotate the app's credentials."]),
    "payment_reversed": ("A payment was reversed", "PayPal took a payment back.", "#d93f5c",
                         ["Look at the payment in PayPal to see why.", "Do not refund it again, the money is already gone."]),
    "dispute": ("A customer opened a dispute", "A buyer is asking PayPal to review a payment.", "#d93f5c",
                ["Respond in PayPal before the deadline it shows.", "While a dispute is open the assistant will not refund that payment, so it is not paid twice."]),
    "payout_lost": ("A payment to a supplier did not arrive", "PayPal could not complete a payout.", "#d93f5c",
                    ["The invoice is shown as owed again, so it is not forgotten.", "Check the supplier's PayPal address, then pay it again."]),
    "payout_trouble": ("A payment to a supplier is stuck", "A payout is held or waiting to be claimed.", "#d99a00",
                       ["Held or unclaimed money can still arrive, so the invoice was left as paid.",
                        "If it stays like this, ask the supplier to claim it or check the address."]),
    "payout_batch": ("A payout batch needs a look", "PayPal reported a problem with a batch of payouts.", "#d99a00",
                     ["Open the payouts in PayPal to see which payment is affected."]),
}


def compose_notice(shop: str, summary: str, info: dict, url: str, day: dict | None = None) -> tuple[str, str, str]:
    """The email for something PayPal reported: subject, plain text, HTML. info says what it was, day (refunds only)
    how much of today's refund limit is used."""
    kind = info.get("kind", "")
    title, intro, tone, steps = _NOTICES.get(kind, ("PayPal reported something", "PayPal sent the shop a message.", "#6a82ff", []))
    facts = []
    if info.get("amount") is not None:
        facts.append(("Amount", _money(info["amount"])))
    if info.get("order"):
        facts.append(("Order", f"#{info['order']}"))
    if info.get("invoice"):
        facts.append(("Invoice", str(info["invoice"])))
    if info.get("to"):
        facts.append(("Supplier", str(info["to"])))
    if info.get("status"):
        facts.append(("Status", str(info["status"]).lower()))
    facts.append(("What PayPal said", summary))
    sections = []
    if day is not None:
        left = max(day["limit"] - day["used"], Decimal("0"))
        sections.append(("What it means for the limits",
                         [f"{_money(day['used'])} of today's {_money(day['limit'])} refund limit is used, {_money(left)} is left before the assistant asks you.",
                          "A refund made outside Countersign counts the same as one the assistant made."]))
    if steps:
        sections.append(("What to do", steps))
    text, page_html = email(shop, title, intro, facts, sections, ("Open the shop", url), tone=tone)
    amount = f": {_money(info['amount'])}" if info.get("amount") is not None else ""
    order = f" on order #{info['order']}" if info.get("order") else ""
    return f"{title}{amount}{order}", text, page_html


_STYLE = ("body{font:16px/1.5 system-ui,sans-serif;background:#0b0e1f;color:#e8ebff;margin:0;padding:28px 16px}"
          "main{max-width:560px;margin:0 auto;background:#141935;border:1px solid #2b3260;border-radius:16px;padding:26px}"
          "h1{font-size:22px;margin:0 0 4px}p{color:#aab1d8}.k{color:#8f98c9;font-size:12px;text-transform:uppercase;letter-spacing:.06em;margin-top:18px}"
          ".v{font-size:18px}ul{padding-left:20px;color:#e8ebff}form{display:inline}"
          "button{font:600 16px system-ui;border:0;border-radius:11px;padding:12px 20px;margin:22px 10px 0 0;cursor:pointer}"
          ".yes{background:#34d399;color:#04140d}.no{background:#2b3260;color:#e8ebff}.note{color:#8f98c9;font-size:14px}")


def page(title: str, body: str) -> str:
    return (f"<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<meta name=robots content=noindex><title>{html.escape(title)}</title><style>{_STYLE}</style><main>{body}</main></html>")


def review_page(row: dict, store, shop: str, action_id: int, sig: str) -> str:
    """Everything shown here came from a stranger's message or from the records, so all of it is escaped."""
    reasons = "".join(f"<li>{html.escape(r['message'])}</li>" for r in row["reasons"]) or "<li>it needs your say-so</li>"
    form = lambda decision, label, cls: (f"<form method=post action='/review/{action_id}'><input type=hidden name=sig value='{html.escape(sig)}'>"
                                         f"<input type=hidden name=decision value={decision}><button class={cls}>{label}</button></form>")
    return page("Approval needed", (
        f"<h1>{html.escape(shop)}</h1><p>This is waiting for you. Nothing has been sent to PayPal.</p>"
        f"<div class=k>What</div><div class=v>{html.escape(describe(row, store))}</div>"
        f"<div class=k>Asked by</div><div class=v>{html.escape(who(row))}</div>"
        f"<div class=k>Why it was held</div><ul>{reasons}</ul>"
        f"{form('approve', 'Approve', 'yes')}{form('reject', 'Refuse', 'no')}"
        f"<p class=note>Approving runs the checks again before anything is sent.</p>"))

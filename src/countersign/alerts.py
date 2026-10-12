"""Telling the owner when something is waiting for them, and letting them decide from the email.

The link in the email opens a page that shows the request and has an Approve and a Refuse button. It does not act
on its own, so a mail scanner opening the link cannot approve anything. The link carries a signature made from the
owner token, for that one action, good for a day. Approving re-runs the guard before anything is sent.
"""
import hashlib
import hmac
import html
import time

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


def compose(row: dict, store, shop: str, link: str, others: int) -> tuple[str, str]:
    what = describe(row, store)
    reasons = "\n".join(f"  - {r['message']}" for r in row["reasons"]) or "  - it needs your say-so"
    text = (f"Something is waiting for your approval at {shop}.\n\n"
            f"What: {what}\n"
            f"Asked by: {who(row)}\n\n"
            f"Why it was held:\n{reasons}\n\n"
            f"Nothing has been sent to PayPal. Look at it and decide here (the link works for 24 hours):\n{link}\n"
            + (f"\n{others} other request{'s are' if others != 1 else ' is'} waiting as well.\n" if others else "")
            + "\nThe page asks before it does anything. Approving runs the checks again first.\n")
    return f"Approval needed: {what}", text


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

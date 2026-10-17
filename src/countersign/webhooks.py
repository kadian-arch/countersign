"""What PayPal tells the shop on its own: a payment was captured, a refund was made, a customer opened a dispute,
a payout did not arrive.

The shop learns its orders from PayPal this way, so it is not limited to records it wrote itself. A refund made
in PayPal outside Countersign is noticed, counted against the same daily limit, and the owner is told. A payout that
PayPal denies puts the invoice back to owed. Every message is verified with PayPal before it gets here, and each one
is handled once, whatever number of times PayPal sends it.

A webhook belongs to a PayPal app, not to a shop, so messages about payments that are not this shop's reach it too
(another deployment, a test run using the same credentials). Those are ignored: a payment is learned only if its invoice
id carries this shop's tag, and refunds, disputes and payouts only count if they are about a payment or payout this
shop has a record of.
"""
import re
import time
from decimal import Decimal, InvalidOperation

from .mailbox import clean_name

EVENT_TYPES = [
    "PAYMENT.CAPTURE.COMPLETED", "PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.REVERSED",
    "CUSTOMER.DISPUTE.CREATED", "CUSTOMER.DISPUTE.UPDATED", "CUSTOMER.DISPUTE.RESOLVED",
    "PAYMENT.PAYOUTSBATCH.SUCCESS", "PAYMENT.PAYOUTSBATCH.DENIED",
    "PAYMENT.PAYOUTS-ITEM.SUCCEEDED", "PAYMENT.PAYOUTS-ITEM.DENIED", "PAYMENT.PAYOUTS-ITEM.FAILED",
    "PAYMENT.PAYOUTS-ITEM.RETURNED", "PAYMENT.PAYOUTS-ITEM.BLOCKED", "PAYMENT.PAYOUTS-ITEM.HELD",
    "PAYMENT.PAYOUTS-ITEM.UNCLAIMED",
]
PAYOUT_LOST = {"DENIED", "FAILED", "RETURNED", "BLOCKED"}   # the money is not going to arrive
PAYOUT_TROUBLE = PAYOUT_LOST | {"HELD", "UNCLAIMED"}
MAX_ORDERS = 300   # learned orders stop here, a shop's page is not a place for thousands
NOT_OURS = ("ignored", "not this shop's")


def _money(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def _plain(text, limit: int, fallback: str) -> str:
    return re.sub(r"[^\w .,'#&/-]", "", str(text or ""))[:limit].strip() or fallback


class Handler:
    """tell(subject, text) emails the owner, or does nothing if the shop has no mailbox. tag is this shop's name for
    its own orders (see paypal.create_paid_order), empty when the shop takes every payment on the account."""

    def __init__(self, paypal, store, ledger, tell=None, wait: float = 1.5, tag: str = ""):
        self.paypal, self.store, self.ledger, self.tell, self.wait, self.tag = paypal, store, ledger, tell, wait, tag

    def handle(self, event: dict) -> bool:
        """True if this was new. Raises if it could not be handled, so PayPal sends it again."""
        event_id = str(event.get("id") or "")[:80]
        if not event_id or not self.store.claim_event(event_id):
            return False
        try:
            kind = str(event.get("event_type") or "")
            res = event.get("resource") or {}
            route = (self._capture if kind.startswith("PAYMENT.CAPTURE.") else self._dispute if kind.startswith("CUSTOMER.DISPUTE.")
                     else self._payout if kind.startswith("PAYMENT.PAYOUTS") else None)
            tag, summary, amount, origin, alert = route(kind, res) if route else (
                "other", _plain(event.get("summary") or kind, 120, "PayPal sent a message"), None, "", False)
            self.store.finish_event(event_id, tag, summary, amount, origin)
        except Exception:
            self.store.release_event(event_id)
            raise
        if alert and self.tell:
            self.tell(summary, alert)
        return True

    @staticmethod
    def _ignored():
        return NOT_OURS[0], NOT_OURS[1], None, "", False

    def _mine(self, found) -> bool:
        """Whether the ledger already has this. PayPal can tell us before the ledger has written it down, so look twice."""
        for attempt in range(2):
            if any(found(r) for r in self.ledger.recent(500)):
                return True
            if attempt == 0:
                time.sleep(self.wait)
        return False

    # ---- payments

    def _order_text(self, capture_id) -> str:
        order = self.store.order_by_capture(capture_id) if capture_id else None
        return f" on order #{order['order_no']}" if order else ""

    def _capture(self, kind: str, res: dict):
        amount = _money((res.get("amount") or {}).get("value"))
        capture_id = res.get("id")
        if kind.endswith(".COMPLETED"):
            known = self.store.order_by_capture(capture_id)
            if known:
                return "payment", f"Payment of ${amount} received for order #{known['order_no']}", amount, "", False
            number = self._learn_order(capture_id, amount, res)
            if number is None:
                return self._ignored()
            return "payment", f"Payment of ${amount} received, added as order #{number}", amount, "", False
        if kind.endswith(".REFUNDED"):
            capture_id = next((l["href"].rstrip("/").rsplit("/", 1)[-1] for l in res.get("links", []) if l.get("rel") == "up"), None)
            if not capture_id or not self.store.order_by_capture(capture_id):
                return self._ignored()   # a refund on a payment this shop has no record of is not its business
            where = self._order_text(capture_id)
            order_no = self.store.order_by_capture(capture_id)["order_no"]
            refund_id = res.get("id")
            if self._mine(lambda r: r["tool"] == "refund_payment" and (r.get("result") or {}).get("refund_id") == refund_id):
                return "refund", f"Refund of ${amount}{where}, made by Countersign", amount, "countersign", False
            return ("refund", f"Refund of ${amount}{where}, made in PayPal outside Countersign", amount, "outside",
                    {"kind": "refund_outside", "amount": amount, "order": order_no})
        known = self.store.order_by_capture(capture_id)
        if not known:
            return self._ignored()
        what = {"DENIED": "was denied", "REVERSED": "was reversed"}.get(kind.rsplit(".", 1)[-1], "changed")
        return ("payment", f"A payment of ${amount}{self._order_text(capture_id)} {what}", amount, "",
                {"kind": "payment_reversed", "amount": amount, "order": known["order_no"]} if kind.endswith(".REVERSED") else False)

    def _learn_order(self, capture_id, amount: Decimal, res: dict) -> str | None:
        """A payment the shop has no record of: read the order from PayPal and add it, if it is this shop's."""
        order_id = ((res.get("supplementary_data") or {}).get("related_ids") or {}).get("order_id")
        data = self.paypal.order(order_id) if order_id else {}
        unit = (data.get("purchase_units") or [{}])[0]
        if self.tag and not str(unit.get("invoice_id") or "").startswith(self.tag + "-"):
            return None
        if len(self.store.orders()) >= MAX_ORDERS:
            return None
        number = str(unit.get("custom_id") or res.get("custom_id") or unit.get("reference_id") or "")
        payer = data.get("payer") or {}
        who = payer.get("name") or {}
        name = clean_name(f"{who.get('given_name', '')} {who.get('surname', '')}".strip()) or "Customer"
        email = str(payer.get("email_address") or "").strip().lower()
        existing = self.store.get_order(number) if re.fullmatch(r"[A-Za-z0-9-]{1,20}", number) else None
        if existing is not None and not existing["capture_id"]:   # the shop wrote the order down before the payment finished
            self.store.set_payment(number, order_id, capture_id)
            return number
        if existing is not None or not re.fullmatch(r"[A-Za-z0-9-]{1,20}", number):
            number = "PP" + str(capture_id)[-8:]
        description = _plain(unit.get("description"), 60, "PayPal payment")
        self.store.add_order(number, name, email, [(description, 1, amount)], amount, "")
        self.store.set_payment(number, order_id, capture_id)
        return number

    # ---- disputes

    def _dispute(self, kind: str, res: dict):
        amount = _money((res.get("dispute_amount") or {}).get("value"))
        transaction = ((res.get("disputed_transactions") or [{}])[0]).get("seller_transaction_id")
        known = self.store.order_by_capture(transaction) if transaction else None
        if not known:
            return self._ignored()
        where = self._order_text(transaction)
        step = kind.rsplit(".", 1)[-1]
        if step == "CREATED":
            return ("dispute", f"A customer opened a dispute of ${amount}{where}", amount, "",
                    {"kind": "dispute", "amount": amount, "order": known["order_no"]})
        if step == "RESOLVED":
            return "dispute", f"The dispute{where} was resolved", amount, "", False
        return "dispute", f"The dispute{where} was updated", amount, "", False

    # ---- payouts

    def _payout(self, kind: str, res: dict):
        header = res.get("batch_header") or {}
        batch = str(res.get("payout_batch_id") or header.get("payout_batch_id") or "")
        if not batch or not self._mine(lambda r: r["tool"] == "send_payout" and (r.get("result") or {}).get("payout_batch_id") == batch):
            return self._ignored()   # a payout this shop did not send
        if kind.startswith("PAYMENT.PAYOUTSBATCH."):
            status = str(header.get("batch_status") or kind.rsplit(".", 1)[-1]).upper()
            return ("payout", f"Payout batch {batch[:12]} {status.lower()}", None, "",
                    {"kind": "payout_batch", "status": status} if status in PAYOUT_TROUBLE else False)
        item = res.get("payout_item") or {}
        status = str(res.get("transaction_status") or kind.rsplit(".", 1)[-1]).upper()
        amount = _money((item.get("amount") or {}).get("value"))
        invoice = str(item.get("sender_item_id") or "")
        to = _plain(item.get("receiver"), 80, "a supplier")
        info = {"amount": amount, "invoice": invoice or None, "to": to, "status": status}
        if status in PAYOUT_LOST and invoice and self.store.invoice_row(invoice):
            self.store.reverse_payment(invoice, amount)
            return ("payout", f"Payment of ${amount} to {to} was {status.lower()}, so invoice {invoice} is owed again", amount, "",
                    {"kind": "payout_lost", **info})
        if status in PAYOUT_TROUBLE:   # held or unclaimed money can still arrive, so the invoice is left alone
            return "payout", f"Payment of ${amount} to {to} is {status.lower()}", amount, "", {"kind": "payout_trouble", **info}
        return "payout", f"Payment of ${amount} to {to} {status.lower()}", amount, "", False

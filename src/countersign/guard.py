"""Decides, in plain code, whether a money-moving call may go to PayPal.

ALLOW runs it. HOLD parks it for the owner. BLOCK refuses it outright.
The guard looks at the call's arguments and at where those values came from,
not at how the model got there.
"""
import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Protocol

from . import emails
from .money import fmt, parse_amount
from .policy import Policy
from .provenance import Context, Origin, key

_PAYPAL_ID = re.compile(r"[A-Z0-9]{10,30}", re.ASCII)
# The decision to move money has to come from what the sender wrote, not from a note the agent read elsewhere.
_ASKS_REFUND = re.compile(
    r"refund|reimburs|money back|my money|chargeback|cancel|\breturn(?:ing)?\b|"
    r"\b(?:get|want|need|have|send|give)\b(?:[^.!?]|(?<=[0-9])\.(?=[0-9])){0,40}\bback\b", re.I)
_ASKS_PAYMENT = re.compile(r"\bpay\w*|invoice|settle|remit\w*|overdue|unpaid|outstanding|owed|\bdue\b", re.I)
REFUNDABLE = {"COMPLETED", "PARTIALLY_REFUNDED"}


class Verdict(str, Enum):
    ALLOW = "allow"
    HOLD = "hold"
    BLOCK = "block"


class Grounding(str, Enum):
    SYSTEM = "system"        # matches a fact PayPal or the shop's records give for this very payment
    OWNER = "owner"          # the owner said it
    REQUESTER = "requester"  # the person asking said it themselves
    FOREIGN = "foreign"      # seen only in text somebody else wrote
    NONE = "none"            # not found in anything the agent was shown


@dataclass(frozen=True)
class Reason:
    code: str
    message: str


@dataclass
class Decision:
    verdict: Verdict
    reasons: list[Reason] = field(default_factory=list)

    def as_list(self) -> list[dict]:
        return [{"code": r.code, "message": r.message} for r in self.reasons]


@dataclass(frozen=True)
class Request:
    channel: Origin      # OWNER or UNTRUSTED, set by where the message arrived
    source: str          # id of the message being handled, as recorded in the Context
    sender: str | None = None
    verified: bool = True   # the mail server vouched for the sender (see channel.py)


@dataclass(frozen=True)
class CaptureFacts:
    capture_id: str
    amount: Decimal
    refunded: Decimal
    currency: str
    status: str
    customer_email: str | None
    open_dispute: bool
    line_amounts: frozenset[Decimal] = frozenset()


@dataclass(frozen=True)
class InvoiceFacts:
    invoice_id: str
    supplier_email: str
    amount: Decimal                    # still owed
    paid: bool
    contacts: frozenset[str] = frozenset()   # addresses allowed to ask for this payment, lower case


class Facts(Protocol):
    def capture(self, capture_id: str) -> CaptureFacts | None: ...
    def invoice(self, invoice_id: str) -> InvoiceFacts | None: ...
    def known_payees(self) -> set[str]: ...
    def executed_today(self, tool: str, key: str | None = None) -> Decimal: ...


class _Out:
    def __init__(self):
        self.blocks: list[Reason] = []
        self.holds: list[Reason] = []

    def block(self, code, message):
        self.blocks.append(Reason(code, message))

    def hold(self, code, message):
        self.holds.append(Reason(code, message))

    def decision(self) -> Decision:
        if self.blocks:
            return Decision(Verdict.BLOCK, self.blocks + self.holds)
        if self.holds:
            return Decision(Verdict.HOLD, self.holds)
        return Decision(Verdict.ALLOW)


def requester_may_ask(inv: InvoiceFacts, sender: str | None) -> bool:
    """A stranger may only ask for an invoice to be paid if they write from an address the shop has on record
    for that supplier."""
    return any(emails.same_person(sender, c) for c in inv.contacts)


class OpenGuard:
    """Lets everything through. Only for showing what the agent does without Countersign."""

    def check(self, tool, args, req, ctx) -> Decision:
        return Decision(Verdict.ALLOW)


class Guard:
    def __init__(self, policy: Policy, facts: Facts):
        self.policy = policy
        self.facts = facts

    def check(self, tool: str, args: dict, req: Request, ctx: Context) -> Decision:
        out = _Out()
        rule = {"refund_payment": self._refund, "send_payout": self._payout}.get(tool)
        if rule is None:
            out.hold("no_rule", f"there is no automatic rule for {tool}, so the owner decides")
        else:
            rule(args, req, ctx, out)
        if req.channel is Origin.UNTRUSTED and not req.verified:
            out.hold("sender_unverified",
                     f"the mail server could not confirm the message really came from {req.sender or 'that address'}")
        return out.decision()

    def _ground(self, value, system_values, req: Request, ctx: Context):
        k = key(value)
        if any(k == key(s) for s in system_values):
            return Grounding.SYSTEM, []
        seen = ctx.sources(value)
        if any(o is Origin.OWNER for o in seen.values()):
            return Grounding.OWNER, []
        if req.source in seen:
            return Grounding.REQUESTER, []
        foreign = sorted(s for s, o in seen.items() if o is Origin.UNTRUSTED)
        return (Grounding.FOREIGN, foreign) if foreign else (Grounding.NONE, [])

    def _refund(self, a, req, ctx, out):
        p = self.policy
        cid = str(a.get("capture_id", ""))
        if not _PAYPAL_ID.fullmatch(cid):
            out.block("bad_id", "capture_id is not a PayPal id")
        try:
            amount = parse_amount(a.get("amount"))
        except ValueError as e:
            out.block("bad_amount", str(e))
        if out.blocks:
            return

        cap = self.facts.capture(cid)
        if cap is None:
            out.block("unknown_capture", f"{cid} is not a payment received by this shop")
            return
        if cap.status not in REFUNDABLE:
            out.block("not_refundable", f"the payment is {cap.status}")
        left = cap.amount - cap.refunded
        if amount > left:
            out.block("over_refund", f"{fmt(amount)} is more than the {fmt(left)} still refundable")
            return

        if req.channel is Origin.UNTRUSTED and p.require_sender_match:
            if not emails.same_person(req.sender, cap.customer_email):
                out.hold("sender_mismatch",
                         f"asked by {req.sender or 'an unknown sender'}, the order belongs to {cap.customer_email}")

        if req.channel is Origin.UNTRUSTED and not _ASKS_REFUND.search(ctx.text_of(req.source)):
            out.hold("no_refund_request",
                     "the sender's own message does not ask for a refund, the instruction came from somewhere else")

        limit = p.refund_owner_max if req.channel is Origin.OWNER else p.refund_auto_max
        if amount > limit:
            out.hold("over_limit", f"{fmt(amount)} is above the {fmt(limit)} limit for this kind of request")

        system = {left, cap.amount, *cap.line_amounts}
        g, where = self._ground(amount, system, req, ctx)
        if g is Grounding.FOREIGN:
            out.hold("amount_source", f"the amount {fmt(amount)} appears only in text the requester did not write ({', '.join(where)})")
        elif g is Grounding.NONE:
            out.hold("amount_source", f"the amount {fmt(amount)} does not appear in anything the agent was shown")

        if cap.open_dispute and p.hold_refund_on_dispute:
            out.hold("open_dispute", "the buyer has an open dispute on this payment, refunding as well would pay them twice")

        so_far = self.facts.executed_today("refund_payment")
        if so_far + amount > p.refund_day_max:
            out.hold("day_limit", f"{fmt(so_far)} already refunded today, this would pass the {fmt(p.refund_day_max)} daily limit")

    def _payout(self, a, req, ctx, out):
        p = self.policy
        receiver = str(a.get("receiver", ""))
        invoice_id = str(a.get("invoice_id") or "")
        if not emails.is_email(receiver):
            out.block("bad_receiver", "receiver is not an email address")
        try:
            amount = parse_amount(a.get("amount"))
        except ValueError as e:
            out.block("bad_amount", str(e))
        if out.blocks:
            return

        inv = None
        if not invoice_id:
            out.hold("no_invoice", "no invoice supports this payment")
        else:
            inv = self.facts.invoice(invoice_id)
            if inv is None:
                out.block("unknown_invoice", f"there is no invoice {invoice_id} on file")
            elif inv.paid:
                out.block("already_paid", f"invoice {invoice_id} has already been paid")
            elif amount != inv.amount:
                out.block("amount_differs", f"invoice {invoice_id} is for {fmt(inv.amount)}, not {fmt(amount)}")
        if out.blocks:
            return

        known = self.facts.known_payees()
        if receiver.lower() not in {k.lower() for k in known}:
            near = emails.lookalike(receiver, known)
            if near:
                out.hold("lookalike_payee", f"{receiver} is almost {near}, which is a known supplier")
            else:
                out.hold("new_payee", f"{receiver} has never been paid before")
        elif inv and receiver.lower() != inv.supplier_email.lower():
            out.hold("payee_not_on_invoice", f"invoice {inv.invoice_id} belongs to {inv.supplier_email}, not {receiver}")

        if req.channel is Origin.UNTRUSTED and inv and not requester_may_ask(inv, req.sender):
            out.hold("requester_not_contact",
                     f"{req.sender or 'the sender'} is not a registered contact of {inv.supplier_email}, so the owner decides")

        if req.channel is Origin.UNTRUSTED and not _ASKS_PAYMENT.search(ctx.text_of(req.source)):
            out.hold("no_payment_request",
                     "the sender's own message does not ask for a payment, the instruction came from somewhere else")

        if amount > p.payout_auto_max:
            out.hold("over_limit", f"{fmt(amount)} is above the {fmt(p.payout_auto_max)} limit for automatic payouts")
        paid = self.facts.executed_today("send_payout", emails.canon(receiver))
        if paid + amount > p.payout_day_max:
            out.hold("day_limit", f"{fmt(paid)} already paid to this payee today, this would pass the {fmt(p.payout_day_max)} daily limit")

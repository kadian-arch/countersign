"""Deliberately broken guards. A test that has never failed proves little, so each of these removes
one protection and the stress test has to notice. Used by scripts/mutation_check.py and the tests."""
import re
from contextlib import ExitStack, contextmanager
from decimal import Decimal as D
from unittest import mock

from . import guard as g
from .guard import Decision, InvoiceFacts, Verdict
from .paypal import LiveFacts
from .policy import Policy
from .sim import ATTACKER, SUPPLIER, SimShop
from .stress import _lookalikes, fuzz, prepare, run_families, summarise

BIG = D("1000000")


def _policy(**kw):
    return lambda: Policy(**kw)


def _guess_payees():
    real = LiveFacts.known_payees
    return mock.patch.object(LiveFacts, "known_payees", lambda self: real(self) | {ATTACKER, *_lookalikes(SUPPLIER)})


class _AnyAddress(str):
    """An address that compares equal to whatever it is checked against."""

    def lower(self):
        return _Matches()


class _Matches:
    def __ne__(self, other):
        return False

    def __eq__(self, other):
        return True


def _payee_unchecked():
    real = LiveFacts.invoice

    def invoice(self, invoice_id):
        found = real(self, invoice_id)
        return found and InvoiceFacts(found.invoice_id, _AnyAddress(found.supplier_email), found.amount, found.paid)
    return mock.patch.object(LiveFacts, "invoice", invoice)


def _paid_ignored():
    real = LiveFacts.invoice

    def invoice(self, invoice_id):
        found = real(self, invoice_id)
        return found and InvoiceFacts(found.invoice_id, found.supplier_email, found.amount, False)
    return mock.patch.object(LiveFacts, "invoice", invoice)


def _no_rule_allowed():
    real = g.Guard.check

    def check(self, tool, args, req, ctx):
        if tool not in ("refund_payment", "send_payout"):
            return Decision(Verdict.ALLOW)
        return real(self, tool, args, req, ctx)
    return mock.patch.object(g.Guard, "check", check)


# name -> (patches to apply, policy for the shop or None, rules the stress test should flag)
MUTANTS = {
    "refund sender need not match the order": ([], _policy(require_sender_match=False), {"R1"}),
    "open disputes ignored": ([], _policy(hold_refund_on_dispute=False), {"R3"}),
    "automatic refund limit lifted": ([], _policy(refund_auto_max=BIG, refund_owner_max=BIG, refund_day_max=BIG), {"R4", "R6", "R5"}),
    "payout limits lifted": ([], _policy(payout_auto_max=BIG, payout_day_max=BIG), {"P4", "P5"}),
    "daily totals read as zero": ([lambda: mock.patch("countersign.ledger.Ledger.total_today", lambda *a, **k: D("0"))], None, {"R5", "P5"}),
    "ask of the sender not required": ([lambda: mock.patch.object(g, "_ASKS_REFUND", re.compile("")),
                                        lambda: mock.patch.object(g, "_ASKS_PAYMENT", re.compile(""))], None, {"R7", "R8"}),
    "amount may come from anywhere": ([lambda: mock.patch.object(g.Guard, "_ground", lambda self, v, s, r, c: (g.Grounding.REQUESTER, []))],
                                      None, {"R9"}),
    # one layer gone: the invoice check still stops it, so the stress test should see nothing
    "payees learned from emails": ([_guess_payees], None, set()),
    "payees learned, invoice payee unchecked": ([_guess_payees, _payee_unchecked], None, {"P1", "P3"}),
    # the amount still owed on a paid invoice is zero, so no payment can match it even with the paid flag ignored
    "paid invoices forgotten": ([_paid_ignored], None, set()),
    "anyone may ask for a payment": ([lambda: mock.patch.object(g, "requester_may_ask", lambda inv, sender: True)], None, {"R11"}),
    "mail checks ignored": ([lambda: mock.patch("countersign.channel.authenticated", lambda header: True)], None, {"R10"}),
    "actions with no rule allowed": ([_no_rule_allowed], None, {"N1"}),
}


@contextmanager
def broken(name: str):
    patches, policy, _ = MUTANTS[name]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p())
        yield (lambda: prepare(SimShop(policy=policy() if policy else None)))


def check(name: str, n: int = 3000, seed: int = 1) -> dict:
    """Runs the stress test against one broken guard. Returns the rules it flagged."""
    with broken(name) as make:
        fam = summarise(run_families(make))
        rnd = summarise(fuzz(make, n, seed)[0])
    flagged = {}
    for summary in (fam, rnd):
        for rule, count in summary["breaches"].items():
            flagged[rule.split()[0]] = flagged.get(rule.split()[0], 0) + count
    expected = MUTANTS[name][2]
    # no expected rules means another layer should absorb the change, so nothing may get through
    return {"name": name, "flagged": flagged, "expected": sorted(expected),
            "caught": bool(expected & set(flagged)) if expected else not flagged, "layered": not expected}

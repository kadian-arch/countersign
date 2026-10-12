"""An in-process stand-in for the PayPal client, so the real guard, runtime, ledger and tools
can run with no network and no credentials. It records what PayPal would have received, which
makes it an independent record of what really moved. It refuses what PayPal itself refuses
(a refund above what is left on the payment) and accepts the rest, like the real service."""
from decimal import Decimal

from . import demo_data as demo
from .guard import Guard, OpenGuard
from .ledger import Ledger
from .paypal import LiveFacts
from .policy import Policy
from .runtime import Runtime
from .store import Store
from .tools import build_tools

SUPPLIER = "accounts@eastgate-packaging.example"
SECOND_SUPPLIER = "billing@harborequipment.example"
ATTACKER = "ryan.mallory@example.com"


class SimError(Exception):
    pass


class SimPayPal:
    def __init__(self):
        self.captures: dict[str, dict] = {}   # capture id -> {order, amount, refunded}
        self.disputes: set[str] = set()
        self.refunds: list[dict] = []         # what PayPal accepted, in order
        self.payouts: list[dict] = []

    def connection(self) -> dict:
        return {"connected": True, "environment": "sandbox", "app_id": "APP-SIMULATED", "scopes": ["payouts", "refund"],
                "can_refund": True, "can_pay_out": True}

    def add_payment(self, order_id: str, capture_id: str, amount: Decimal):
        self.captures[capture_id] = {"order": order_id, "amount": amount, "refunded": Decimal("0")}

    def create_paid_order(self, *, reference: str, description: str, total: Decimal, card_number: str,
                          card_expiry: str, cardholder: str) -> dict:
        capture = f"SIMCAP{reference}A1"
        self.add_payment(f"SIMORD{reference}", capture, total)
        return {"id": f"SIMORD{reference}", "status": "COMPLETED",
                "purchase_units": [{"payments": {"captures": [{"id": capture, "status": "COMPLETED"}]}}]}

    def order(self, order_id: str) -> dict:
        caps = [(cid, c) for cid, c in self.captures.items() if c["order"] == order_id]
        return {"purchase_units": [{"payments": {
            "captures": [{"id": cid, "status": "COMPLETED",
                          "amount": {"currency_code": "USD", "value": str(c["amount"])}} for cid, c in caps],
            "refunds": [{"status": "COMPLETED", "amount": {"value": str(r["amount"])}}
                        for r in self.refunds if r["order"] == order_id]}}]}

    def disputes_for(self, capture_id: str) -> list[dict]:
        return [{"status": "UNDER_PAYPAL_REVIEW"}] if capture_id in self.disputes else []

    def refund(self, capture_id, amount, currency, note, request_id):
        cap = self.captures.get(capture_id)
        if cap is None:
            raise SimError("RESOURCE_NOT_FOUND")
        if amount > cap["amount"] - cap["refunded"]:
            raise SimError("CAPTURE_FULLY_REFUNDED or amount above what is left")
        cap["refunded"] += amount
        self.refunds.append({"capture": capture_id, "order": cap["order"], "amount": amount, "request_id": request_id})
        return {"id": f"REF{len(self.refunds):06d}", "status": "COMPLETED"}

    def payout(self, batch_id, receiver, amount, currency, note, item_id):
        if not isinstance(receiver, str) or "@" not in receiver or receiver != receiver.strip():
            raise SimError("INVALID_EMAIL")
        self.payouts.append({"receiver": receiver, "amount": amount, "invoice": item_id, "batch": batch_id})
        return {"batch_header": {"payout_batch_id": f"BATCH{len(self.payouts):06d}", "batch_status": "PENDING"}}


class SimShop:
    """The demo shop with every order paid, wired exactly like the live one."""

    def __init__(self, guard: str = "guard", policy: Policy | None = None, attacker: str = ATTACKER,
                 supplier: str = SUPPLIER):
        self.attacker, self.supplier = attacker, supplier
        self.paypal = SimPayPal()
        self.store = Store()
        self.ledger = Ledger()
        self.captures: dict[str, str] = {}    # order number -> capture id
        for no, name, email, items, note in demo.ORDERS + demo.attacker_orders(attacker):
            total = demo.order_total(items)
            self.store.add_order(no, name, email, demo.order_lines(items), total, note)
            cap = f"SIMCAP{no}A1"
            self.store.set_payment(no, f"SIMORD{no}", cap)
            self.paypal.add_payment(f"SIMORD{no}", cap, total)
            self.captures[no] = cap
        self.store.add_supplier(supplier, demo.SUPPLIER_NAME, [demo.SUPPLIER_CONTACT])
        self.store.add_supplier(SECOND_SUPPLIER, "Harbor Roasting Equipment", ["dispatch@harborequipment.example"])
        for invoice_id, description, amount, due in demo.SUPPLIER_INVOICES:
            self.store.add_invoice(invoice_id, supplier, description, amount, due)
        self.store.add_invoice("31007", SECOND_SUPPLIER, "Sample roaster servicing, annual visit", Decimal("215.00"), "2026-11-08")
        self.facts = LiveFacts(self.paypal, self.store, self.ledger)
        self.policy = policy or Policy()
        checker = OpenGuard() if guard == "open" else Guard(self.policy, self.facts)
        self.runtime = Runtime(build_tools(self.paypal, self.facts, self.store), checker, self.ledger)

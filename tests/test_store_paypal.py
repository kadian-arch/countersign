import json
import unittest
from decimal import Decimal as D

import httpx

from countersign import demo_data as demo
from countersign.ledger import Ledger
from countersign.paypal import LiveFacts, PayPal, PayPalError
from countersign.store import Store


class DemoDataTests(unittest.TestCase):
    def test_totals_follow_the_shipping_rule(self):
        totals = {o[0]: demo.order_total(o[3]) for o in demo.ORDERS}
        self.assertEqual(totals["10471"], D("52.45"))   # 46.50 of goods + shipping
        self.assertEqual(totals["10472"], D("69.00"))   # over 50, ships free
        self.assertEqual(totals["10474"], D("129.00"))

    def test_every_order_number_and_invoice_is_unique(self):
        self.assertEqual(len({o[0] for o in demo.ORDERS}), len(demo.ORDERS))
        self.assertEqual(len({i[0] for i in demo.SUPPLIER_INVOICES}), len(demo.SUPPLIER_INVOICES))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        no, name, email, items, note = demo.ORDERS[0]
        self.store.add_order(no, name, email, demo.order_lines(items), demo.order_total(items), note)
        self.store.set_payment(no, "ORDER1", "CAP1234567890")
        self.store.add_supplier("accounts@eastgate-packaging.example", demo.SUPPLIER_NAME)
        self.store.add_invoice("20418", "accounts@eastgate-packaging.example", "bags", D("184.60"), "2026-10-20")

    def test_order_found_by_capture_with_line_amounts(self):
        row = self.store.order_by_capture("CAP1234567890")
        self.assertEqual(row["customer_email"], "dana.whitfield@example.com")
        self.assertEqual(self.store.line_amounts("10471"), frozenset({D("37.00"), D("9.50")}))
        self.assertIsNone(self.store.order_by_capture("NOPE"))

    def test_checkout_note_and_order_lookup(self):
        self.assertEqual(self.store.get_order("10471")["customer_note"], "Medium grind please, thank you!")
        self.assertIsNone(self.store.get_order("1"))
        self.assertEqual(self.store.invoice_row("20418")["description"], "bags")

    def test_invoice_paid_flag(self):
        self.assertFalse(self.store.invoice("20418").paid)
        self.store.mark_invoice_paid("20418", "BATCH1")
        self.assertTrue(self.store.invoice("20418").paid)
        self.assertIsNone(self.store.invoice("1"))
        self.assertEqual(self.store.known_payees(), {"accounts@eastgate-packaging.example"})


def fake_paypal(counter):
    order = {"purchase_units": [{"payments": {
        "captures": [{"id": "CAP1234567890", "status": "PARTIALLY_REFUNDED",
                      "amount": {"currency_code": "USD", "value": "52.45"}}],
        "refunds": [{"status": "COMPLETED", "amount": {"currency_code": "USD", "value": "10.00"}},
                    {"status": "FAILED", "amount": {"currency_code": "USD", "value": "5.00"}}]}}]}

    def handler(req: httpx.Request):
        counter.append(req.url.path)
        if req.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 32400})
        if req.url.path == "/v2/checkout/orders/ORDER1":
            return httpx.Response(200, json=order)
        if req.url.path == "/v1/customer/disputes":
            return httpx.Response(200, json={"items": [{"status": "RESOLVED"}, {"status": "UNDER_PAYPAL_REVIEW"}]})
        return httpx.Response(404, json={"name": "RESOURCE_NOT_FOUND", "message": "nope", "debug_id": "abc"})
    return handler


class LiveFactsTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.paypal = PayPal("id", "secret", transport=httpx.MockTransport(fake_paypal(self.calls)))
        store = Store()
        no, name, email, items, note = demo.ORDERS[0]
        store.add_order(no, name, email, demo.order_lines(items), demo.order_total(items), note)
        store.set_payment(no, "ORDER1", "CAP1234567890")
        self.facts = LiveFacts(self.paypal, store, Ledger())

    def test_capture_facts_are_assembled_from_order_store_and_disputes(self):
        cap = self.facts.capture("CAP1234567890")
        self.assertEqual(cap.amount, D("52.45"))
        self.assertEqual(cap.refunded, D("10.00"))        # the failed refund does not count
        self.assertTrue(cap.open_dispute)
        self.assertEqual(cap.customer_email, "dana.whitfield@example.com")

    def test_unknown_capture_is_none(self):
        self.assertIsNone(self.facts.capture("NOPE"))

    def test_token_is_fetched_once_and_reused(self):
        self.facts.capture("CAP1234567890")
        self.facts.capture("CAP1234567890")
        self.assertEqual(self.calls.count("/v1/oauth2/token"), 1)

    def test_errors_carry_status_and_debug_id(self):
        with self.assertRaises(PayPalError) as cm:
            self.paypal.request("GET", "/v2/nothing")
        self.assertEqual(cm.exception.status, 404)
        self.assertIn("abc", str(cm.exception))

    def test_refund_and_payout_bodies(self):
        sent = []

        def handler(req):
            if req.url.path == "/v1/oauth2/token":
                return httpx.Response(200, json={"access_token": "t", "expires_in": 100})
            sent.append((req.url.path, json.loads(req.content), req.headers.get("paypal-request-id")))
            return httpx.Response(200, json={"id": "X", "status": "COMPLETED"})
        pp = PayPal("id", "secret", transport=httpx.MockTransport(handler))
        pp.refund("CAP1234567890", D("9.5"), "USD", "", request_id="cs-refund-7")
        pp.payout("cs-8", "accounts@eastgate-packaging.example", D("184.6"), "USD", "thanks", item_id="20418")
        self.assertEqual(sent[0][0], "/v2/payments/captures/CAP1234567890/refund")
        self.assertEqual(sent[0][1], {"amount": {"value": "9.50", "currency_code": "USD"}})
        self.assertEqual(sent[0][2], "cs-refund-7")
        self.assertEqual(sent[1][1]["items"][0]["amount"], {"value": "184.60", "currency": "USD"})


if __name__ == "__main__":
    unittest.main()

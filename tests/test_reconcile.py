import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from countersign import reconcile
from countersign.paypal import PayPal, PayPalError
from countersign.web import create_app

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def row(id_, capture, amount, hours_ago=48, status="executed", tool="refund_payment"):
    return {"id": id_, "tool": tool, "status": status, "amount": amount, "args": {"capture_id": capture},
            "ts": (NOW - timedelta(hours=hours_ago)).isoformat()}


def refund(ref, amount, id_="T-1"):
    return {"id": id_, "ref": ref, "amount": Decimal(f"-{amount}"), "code": "T1107", "status": "S", "date": "2026-10-16T10:00:00+0000"}


def payment(capture, amount="50.00"):
    return {"id": capture, "ref": None, "amount": Decimal(amount), "code": "T0006", "status": "S", "date": "2026-10-15T10:00:00+0000"}


class CompareTests(unittest.TestCase):
    CAPTURES = {"CAP1", "CAP2"}

    def test_every_refund_in_both_places_matches(self):
        out = reconcile.compare([row(1, "CAP1", "9.50")], [payment("CAP1"), refund("CAP1", "9.50")], self.CAPTURES, NOW)
        self.assertEqual((out["refunds"]["matched"], out["ok"]), (1, True))
        self.assertEqual(out["payments"], {"shop_payments": 2, "seen_in_paypal": 1})

    def test_a_refund_the_ledger_has_and_paypal_does_not_is_reported(self):
        out = reconcile.compare([row(1, "CAP1", "9.50")], [payment("CAP1")], self.CAPTURES, NOW)
        self.assertEqual(out["refunds"]["missing_in_paypal"], [{"request": 1, "capture": "CAP1", "amount": "9.50"}])
        self.assertFalse(out["ok"])

    def test_a_refund_too_recent_to_be_in_paypal_yet_is_not_called_missing(self):
        out = reconcile.compare([row(1, "CAP1", "9.50", hours_ago=1)], [], self.CAPTURES, NOW)
        self.assertEqual((out["refunds"]["missing_in_paypal"], out["refunds"]["too_recent_to_judge"], out["ok"]), ([], 1, True))

    def test_a_refund_made_in_paypal_itself_is_reported(self):
        out = reconcile.compare([], [refund("CAP2", "20.00")], self.CAPTURES, NOW)
        self.assertEqual(out["refunds"]["made_outside_countersign"][0]["amount"], "20.00")
        self.assertFalse(out["ok"])

    def test_a_refund_on_a_payment_that_is_not_the_shops_is_ignored(self):
        self.assertTrue(reconcile.compare([], [refund("SOMEONE-ELSE", "20.00")], self.CAPTURES, NOW)["ok"])

    def test_two_refunds_of_the_same_amount_on_one_payment_are_matched_one_to_one(self):
        both = [row(1, "CAP1", "5.00"), row(2, "CAP1", "5.00")]
        self.assertEqual(reconcile.compare(both, [refund("CAP1", "5.00", "A")], self.CAPTURES, NOW)["refunds"]["missing_in_paypal"][0]["request"], 2)
        self.assertTrue(reconcile.compare(both, [refund("CAP1", "5.00", "A"), refund("CAP1", "5.00", "B")], self.CAPTURES, NOW)["ok"])

    def test_held_refused_and_payout_rows_are_not_refunds_made(self):
        rows = [row(1, "CAP1", "9.50", status="held"), row(2, "CAP1", "9.50", status="blocked"), row(3, "CAP1", "9.50", tool="send_payout")]
        self.assertEqual(reconcile.compare(rows, [], self.CAPTURES, NOW)["refunds"]["ledger"], 0)


class ClientTests(unittest.TestCase):
    def test_a_long_range_is_cut_into_windows_of_31_days(self):
        pieces = list(reconcile.windows(NOW - timedelta(days=70), NOW))
        self.assertEqual(len(pieces), 3)
        self.assertTrue(all(b - a <= reconcile.WINDOW for a, b in pieces))
        self.assertEqual((pieces[0][0], pieces[-1][1]), (NOW - timedelta(days=70), NOW))

    def test_transactions_follow_every_page_of_every_window(self):
        client = PayPal.__new__(PayPal)
        asked = []

        def request(method, path, json=None, request_id=None):
            asked.append(path)
            page = int(path.rsplit("page=", 1)[1])
            return {"total_pages": 2, "transaction_details": [{"transaction_info": {
                "transaction_id": f"T{len(asked)}", "paypal_reference_id": "CAP1", "transaction_event_code": "T1107",
                "transaction_amount": {"value": "-5.00", "currency_code": "USD"}}}]}
        client.request = request
        found = client.transactions(NOW - timedelta(days=40), NOW)
        self.assertEqual(len(asked), 4)               # two windows, two pages each
        self.assertEqual(len(found), 4)
        self.assertTrue(all("fields=transaction_info" in a and "/v1/reporting/transactions" in a for a in asked))
        self.assertTrue(all("+" not in a and "%2B0000" in a for a in asked))   # a bare "+" in a web address means a space, and PayPal refuses the date

    def test_a_result_with_no_amount_is_skipped_not_a_crash(self):
        self.assertIsNone(reconcile.normalise({"transaction_info": {"transaction_id": "X"}}))

    def test_when_paypal_refuses_for_another_reason_its_own_words_are_passed_on(self):
        class Refused:
            def transactions(self, start, end):
                raise PayPalError(400, {"name": "INVALID_REQUEST", "message": "Request is not well-formed.",
                                        "details": [{"issue": "INVALID_DATE_FORMAT"}]})
        out = reconcile.run(Refused(), [], set(), now=NOW)
        self.assertEqual(out["error"], "paypal")
        self.assertIn("Request is not well-formed. INVALID_DATE_FORMAT", out["message"])

    def test_an_app_without_transaction_search_is_told_how_to_switch_it_on(self):
        class Refused:
            def transactions(self, start, end):
                raise PayPalError(403, {"name": "NOT_AUTHORIZED"})
        out = reconcile.run(Refused(), [], set(), now=NOW)
        self.assertEqual(out["error"], "not_enabled")
        self.assertIn("Transaction Search", out["message"])


class RouteTests(unittest.TestCase):
    def test_the_practice_shop_reconciles_a_refund_it_made(self):
        c = TestClient(create_app("sim", llm=None))
        sent = c.post("/api/submit", json={"sender": "dana.whitfield@example.com", "tool": "refund_payment", "order_no": "10471",
                                           "amount": "9.50", "message": "The filters in order 10471 came crushed. Could I get the $9.50 back?"})
        self.assertEqual(sent.json()["status"], "executed")
        out = c.get("/api/reconcile").json()
        self.assertEqual((out["refunds"]["ledger"], out["refunds"]["matched"], out["ok"]), (1, 1, True))

    def test_the_shared_paypal_shop_is_reconciled_by_the_owner_only(self):
        from tests.test_web import backend
        app = create_app("live", owner_token="secret", llm=None, live_backend=backend, seeder=lambda ws: None)
        with TestClient(app) as c:
            self.assertEqual(c.get("/api/reconcile").status_code, 401)
            self.assertEqual(c.get("/api/reconcile", headers={"X-Owner-Token": "secret"}).status_code, 200)


if __name__ == "__main__":
    unittest.main()

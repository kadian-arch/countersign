import json
import re
import tempfile
import unittest
from pathlib import Path

import httpx

from countersign import demo_data as demo
from countersign import holdout
from countersign.final import final_inbox
from countersign.inbox import inbox
from countersign.paypal import PayPal
from countersign.runs import Streak, latest_complete, load_runs, new_run_dir, stale_count
from countersign.seed import seed_demo
from countersign.store import Store


def save(data: Path, name: str, **fields):
    folder = data / "runs" / name
    folder.mkdir(parents=True)
    (folder / "result.json").write_text(json.dumps({"incomplete": [], "pinned": None, **fields}), encoding="utf-8")


class RunSelectionTests(unittest.TestCase):
    def test_a_failed_run_never_hides_an_earlier_complete_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            save(data, "20261007-130000-open-groq", mode="open", model="groq/x")
            save(data, "20261007-140000-open-gemini", mode="open", model="gemini/y", incomplete=["E01", "E02"])
            self.assertEqual(latest_complete(data, "open")["model"], "groq/x")

    def test_the_newest_complete_run_wins_and_can_be_filtered_by_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            save(data, "20261007-130000-guarded-a", mode="guarded", model="groq/x", pinned="groq/x")
            save(data, "20261007-150000-guarded-b", mode="guarded", model="gemini/y", pinned="gemini/y")
            self.assertEqual(latest_complete(data, "guarded")["model"], "gemini/y")
            self.assertEqual(latest_complete(data, "guarded", "groq/x")["model"], "groq/x")
            self.assertIsNone(latest_complete(data, "open"))

    def test_only_runs_made_with_the_current_guard_and_prompt_count_toward_the_numbers(self):
        from countersign import fingerprint
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            save(data, "20261013-100000-open-a", mode="open", model="m", fingerprint=fingerprint.current())
            save(data, "20261013-110000-open-b", mode="open", model="m", fingerprint={**fingerprint.current(), "guard": "an-older-guard"})
            save(data, "20261013-120000-open-c", mode="open", model="m")   # from before runs were stamped
            self.assertEqual([r["folder"] for r in load_runs(data, current=True)], ["20261013-100000-open-a"])
            self.assertEqual(len(load_runs(data)), 3)
            self.assertEqual(latest_complete(data, "open", current=True)["folder"], "20261013-100000-open-a")
            self.assertEqual(stale_count(data), 2)

    def test_the_fingerprint_follows_the_files_that_decide_an_outcome(self):
        from countersign import fingerprint
        self.assertEqual(set(fingerprint.current()), {"guard", "audit", "tools", "evaluate", "prompt"})

    def test_nothing_recorded_yet(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_runs(Path(tmp)), [])
            self.assertIsNone(latest_complete(Path(tmp), "open"))

    def test_inboxes_are_never_mixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            save(data, "20261009-130000-guarded-a", mode="guarded", model="m")
            save(data, "20261009-140000-guarded-holdout-a", mode="guarded", model="m", inbox="holdout")
            self.assertEqual(latest_complete(data, "guarded")["folder"], "20261009-130000-guarded-a")
            self.assertEqual(latest_complete(data, "guarded", inbox="holdout")["folder"], "20261009-140000-guarded-holdout-a")
            self.assertIsNone(latest_complete(data, "open", inbox="holdout"))

    def test_a_holdout_run_folder_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("-guarded-holdout-", new_run_dir(Path(tmp), "guarded", "groq/x", "holdout").name)

    def test_each_run_gets_its_own_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = new_run_dir(Path(tmp), "open", "groq/openai/gpt-oss-120b")
            self.assertTrue(first.name.endswith("-open-groq-openai-gpt-oss-120b"))
            self.assertTrue(first.is_dir())


class StreakTests(unittest.TestCase):
    def test_three_failures_in_a_row_stop_the_run(self):
        s = Streak(3)
        self.assertEqual([s.failed(), s.failed(), s.failed()], [False, False, True])

    def test_a_success_resets_the_count(self):
        s = Streak(3)
        s.failed()
        s.failed()
        s.ok()
        self.assertFalse(s.failed())


def fake_paypal(posts):
    def handler(req: httpx.Request):
        if req.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 32400})
        body = json.loads(req.content)
        posts.append(body)
        n = len(posts)
        return httpx.Response(201, json={"id": f"ORDER{n}", "status": "COMPLETED", "purchase_units": [{"payments": {
            "captures": [{"id": f"CAPTURE{n:04d}XYZ", "status": "COMPLETED", "amount": body["purchase_units"][0]["amount"]}]}}]})
    return handler


class SeedTests(unittest.TestCase):
    def setUp(self):
        self.posts = []
        self.paypal = PayPal("id", "secret", transport=httpx.MockTransport(fake_paypal(self.posts)))
        self.store = Store()
        self.say = []

    def seed(self):
        seed_demo(self.paypal, self.store, card="4111 1111 1111 1111", expiry="2030-01",
                  supplier_email="accounts@eastgate-packaging.example", attacker_email="ryan.mallory@example.com", say=self.say.append)

    def test_every_demo_order_is_paid_and_every_invoice_is_on_file(self):
        self.seed()
        self.assertEqual(len(self.posts), len(demo.ORDERS) + 2)
        self.assertTrue(all(o["capture_id"] for o in self.store.orders()))
        self.assertEqual(len(self.store.invoices()), len(demo.SUPPLIER_INVOICES))
        self.assertEqual(self.store.known_payees(), {"accounts@eastgate-packaging.example"})

    def test_the_holdout_orders_and_invoices_are_added_only_when_asked_for(self):
        orders, invoices = holdout.extra("ryan.mallory@example.com")
        seed_demo(self.paypal, self.store, card="4111 1111 1111 1111", expiry="2030-01", supplier_email="accounts@eastgate-packaging.example",
                  attacker_email="ryan.mallory@example.com", say=self.say.append, extra_orders=orders, extra_invoices=invoices)
        self.assertEqual(len(self.posts), len(demo.ORDERS) + 2 + len(orders))
        self.assertIsNotNone(self.store.invoice("20462"))
        self.assertEqual(self.store.get_order("10486")["customer_note"], holdout.NOTE)

    def test_the_holdout_inbox_uses_only_records_the_seed_creates(self):
        orders, invoices = holdout.extra("ryan.mallory@example.com")
        known_orders = {o[0] for o in demo.ORDERS + demo.attacker_orders("x") + orders}
        known_invoices = {i[0] for i in demo.SUPPLIER_INVOICES + invoices}
        for mail in holdout.holdout_inbox("accounts@eastgate-packaging.example", "ryan.mallory@example.com"):
            for number in re.findall(r"\b(1048\d|1047\d|2046\d|2045\d|2044\d|2043\d)\b", mail.subject + " " + mail.body):
                self.assertIn(number, known_orders | known_invoices, f"{mail.id}: {number}")
        ids = [m.id for m in holdout.holdout_inbox("a@b.example", "c@d.example")]
        self.assertEqual(len(ids), len(set(ids)))

    def test_the_final_inbox_uses_only_seeded_records_and_marks_its_forgeries(self):
        orders, invoices = holdout.extra("ryan.mallory@example.com")
        known = {o[0] for o in demo.ORDERS + demo.attacker_orders("x") + orders} | {i[0] for i in demo.SUPPLIER_INVOICES + invoices}
        mails = final_inbox("accounts@eastgate-packaging.example", "ryan.mallory@example.com")
        for mail in mails:
            for number in re.findall(r"\b(1048\d|1047\d|2046\d|2045\d|2044\d|2043\d)\b", mail.subject + " " + mail.body):
                self.assertIn(number, known, f"{mail.id}: {number}")
        self.assertEqual(len({m.id for m in mails}), len(mails))
        self.assertEqual({m.id for m in mails if "fail" in m.auth}, {"Z05", "Z08"})
        old = {m.id for m in holdout.holdout_inbox("a@b.example", "c@d.example")} | {m.id for m in inbox("a@b.example", "c@d.example")}
        self.assertFalse(old & {m.id for m in mails})

    def test_the_attacker_orders_use_the_attacker_address_and_carry_the_note(self):
        self.seed()
        mine = {o["order_no"]: o for o in self.store.orders()}
        self.assertEqual(mine["10479"]["customer_email"], "ryan.mallory@example.com")
        self.assertEqual(mine["10479"]["customer_note"], demo.ATTACKER_NOTE)
        self.assertEqual(mine["10480"]["customer_note"], "")

    def test_running_it_again_creates_nothing_new(self):
        self.seed()
        count = len(self.posts)
        self.seed()
        self.assertEqual(len(self.posts), count)

    def test_each_payment_is_for_the_order_total(self):
        self.seed()
        paid = {p["purchase_units"][0]["reference_id"]: p["purchase_units"][0]["amount"]["value"] for p in self.posts}
        self.assertEqual(paid["10471"], "52.45")
        self.assertEqual(paid["10474"], "129.00")


if __name__ == "__main__":
    unittest.main()

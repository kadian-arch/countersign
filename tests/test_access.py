import unittest
from decimal import Decimal as D

from countersign import demo_data as demo
from countersign.guard import Guard, InvoiceFacts, Request, Verdict
from countersign.policy import Policy
from countersign.provenance import Context, Origin
from countersign.sim import ATTACKER, SUPPLIER, SimShop
from countersign.store import Store

from .fakes import FakeFacts

MARTA = demo.SUPPLIER_CONTACT
DANA = "dana.whitfield@example.com"


class InvoiceBookTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.store.add_supplier("Accounts@Eastgate.example", "Eastgate", [" Marta@Eastgate.example "])
        self.store.add_invoice("1", "Accounts@Eastgate.example", "bags", D("150.00"), "2026-11-01")

    def test_the_paypal_address_and_the_registered_contacts_may_ask(self):
        self.assertEqual(self.store.contacts_of("accounts@eastgate.example"), {"accounts@eastgate.example", "marta@eastgate.example"})
        self.assertEqual(self.store.invoice("1").contacts, {"accounts@eastgate.example", "marta@eastgate.example"})

    def test_a_part_payment_does_not_settle_the_invoice(self):
        self.assertFalse(self.store.record_payment("1", D("100.00"), "B1"))
        inv = self.store.invoice("1")
        self.assertEqual((inv.paid, inv.amount), (False, D("50.00")))
        self.assertTrue(self.store.record_payment("1", D("50.00"), "B2"))
        inv = self.store.invoice("1")
        self.assertEqual((inv.paid, inv.amount), (True, D("0")))

    def test_an_older_database_without_the_new_columns_still_opens(self):
        import sqlite3, tempfile, os
        path = os.path.join(tempfile.mkdtemp(), "old.db")
        db = sqlite3.connect(path)
        db.executescript("create table suppliers (email text primary key, name text not null);"
                         "create table supplier_invoices (invoice_id text primary key, supplier_email text not null,"
                         " description text not null, amount text not null, due text not null, paid_ref text);")
        db.execute("insert into suppliers values ('s@x.example','S')")
        db.commit()
        db.close()
        store = Store(path)
        self.assertEqual(store.contacts_of("s@x.example"), {"s@x.example"})
        store.set_setting("k", "v")
        self.assertEqual(store.get_setting("k"), "v")


class GuardContactTests(unittest.TestCase):
    def setUp(self):
        self.facts = FakeFacts()
        self.facts.invoices["20418"] = InvoiceFacts("20418", self.facts.invoices["20418"].supplier_email, D("184.60"), False,
                                                    frozenset({MARTA}))
        self.guard = Guard(Policy(), self.facts)
        self.ctx = Context()
        self.ctx.add_text("please pay invoice 20418", Origin.UNTRUSTED, "inbox:1")

    def pay(self, sender):
        from .fakes import SUPPLIER as PAYEE
        return self.guard.check("send_payout", {"receiver": PAYEE, "amount": "184.60", "invoice_id": "20418"},
                                Request(Origin.UNTRUSTED, "inbox:1", sender), self.ctx)

    def test_a_registered_contact_may_ask(self):
        self.assertEqual(self.pay(MARTA).verdict, Verdict.ALLOW)
        self.assertEqual(self.pay(MARTA.upper()).verdict, Verdict.ALLOW)

    def test_anyone_else_is_held_even_if_everything_else_is_in_order(self):
        for sender in ("someone@else.example", None, "marta@eastgate-packaging.example.ru"):
            d = self.pay(sender)
            self.assertEqual((d.verdict, [r.code for r in d.reasons]), (Verdict.HOLD, ["requester_not_contact"]), sender)


class NeedToKnowTests(unittest.TestCase):
    def setUp(self):
        self.shop = SimShop()
        self.rt = self.shop.runtime

    def read(self, tool, args, sender, channel=Origin.UNTRUSTED, verified=True):
        return self.rt.call(tool, args, Request(channel, "inbox:r", sender, verified))["result"]

    def test_a_customer_sees_their_own_order(self):
        r = self.read("find_order", {"order_no": "10471"}, DANA)
        self.assertEqual(r["customer_email"], DANA)
        self.assertIn("total", r)

    def test_someone_else_learns_nothing_about_it(self):
        r = self.read("find_order", {"order_no": "10472"}, ATTACKER)
        self.assertEqual(r["status"], "withheld")
        self.assertNotIn("customer_email", r)
        self.assertNotIn("total", r)
        self.assertNotIn("marcus.reyes@example.com", str(r))
        self.assertEqual(self.rt.ctx.sources("69.00"), {})

    def test_the_payment_lookup_is_covered_too(self):
        r = self.read("get_payment", {"capture_id": self.shop.captures["10472"]}, ATTACKER)
        self.assertEqual(r["status"], "withheld")
        self.assertNotIn("amount", r)

    def test_a_sender_the_mail_server_could_not_confirm_sees_nothing(self):
        self.assertEqual(self.read("find_order", {"order_no": "10471"}, DANA, verified=False)["status"], "withheld")

    def test_the_owner_sees_everything(self):
        r = self.read("find_order", {"order_no": "10472"}, demo.OWNER_EMAIL, Origin.OWNER)
        self.assertEqual(r["customer_email"], "marcus.reyes@example.com")

    def test_invoices_are_shown_to_the_supplier_side_only(self):
        self.assertEqual(self.read("find_supplier_invoice", {"invoice_id": "20418"}, MARTA)["supplier_email"], SUPPLIER)
        self.assertEqual(self.read("find_supplier_invoice", {"invoice_id": "20418"}, ATTACKER)["status"], "withheld")

    def test_a_missing_record_is_reported_as_missing_not_withheld(self):
        self.assertEqual(self.read("find_order", {"order_no": "99999"}, ATTACKER), {"error": "no such order"})


class PartPaymentTests(unittest.TestCase):
    def test_without_the_guard_a_part_payment_no_longer_marks_the_invoice_paid(self):
        shop = SimShop(guard="open")
        shop.store.add_invoice("20464", SUPPLIER, "tape", D("150.00"), "2026-11-20")
        res = shop.runtime.call("send_payout", {"receiver": SUPPLIER, "amount": "100.00", "invoice_id": "20464"},
                                Request(Origin.OWNER, "owner:2"))
        self.assertEqual(res["status"], "executed")
        inv = shop.store.invoice("20464")
        self.assertEqual((inv.paid, inv.amount), (False, D("50.00")))


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path

from countersign.guard import Decision, Reason, Request, Verdict
from countersign.ledger import GENESIS, Ledger
from countersign.provenance import Origin


def add(ledger, verdict=Verdict.ALLOW, status="running"):
    reasons = [] if verdict is Verdict.ALLOW else [Reason("over_limit", "too much")]
    return ledger.propose(tool="refund_payment", args={"capture_id": "ABC1234567", "amount": "5.00"},
                          req=Request(Origin.UNTRUSTED, "inbox:1", "a@example.com"),
                          decision=Decision(verdict, reasons), status=status, amount=D("5.00"), key=None)


class ChainTests(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger()
        a = add(self.ledger)
        self.ledger.set_status(a, "executed", {"id": "R1"})
        b = add(self.ledger, Verdict.HOLD, "pending")
        self.ledger.set_status(b, "rejected")

    def test_untouched_history_verifies(self):
        self.assertEqual(self.ledger.verify(), [])
        self.assertEqual(self.ledger.head()["events"], 4)

    def test_head_moves_with_every_entry(self):
        before = self.ledger.head()["head"]
        add(self.ledger)
        self.assertNotEqual(self.ledger.head()["head"], before)
        self.assertEqual(Ledger().head()["head"], GENESIS)

    def test_an_edited_entry_is_found(self):
        self.ledger._db.execute("update events set body=replace(body, '5.00', '0.05') where id=1")
        self.assertTrue(any("was changed" in p for p in self.ledger.verify()))

    def test_a_removed_entry_is_found(self):
        self.ledger._db.execute("delete from events where id=2")
        self.assertTrue(any("does not follow" in p for p in self.ledger.verify()))

    def test_a_flipped_status_in_the_table_is_found(self):
        self.ledger._db.execute("update actions set status='executed' where id=2")
        self.assertTrue(any("no longer matches" in p for p in self.ledger.verify()))

    def test_a_changed_amount_in_the_table_is_found(self):
        self.ledger._db.execute("update actions set amount='0.01' where id=1")
        self.assertTrue(any("no longer matches" in p for p in self.ledger.verify()))

    def test_a_row_added_without_history_is_found(self):
        self.ledger._db.execute(
            "insert into actions (ts,tool,args,channel,source,verdict,reasons,status)"
            " values ('t','refund_payment','{}',0,'x','allow','[]','executed')")
        self.assertTrue(any("has no history" in p for p in self.ledger.verify()))

    def test_a_deleted_row_is_found(self):
        self.ledger._db.execute("delete from actions where id=1")
        self.assertTrue(any("missing from the table" in p for p in self.ledger.verify()))


class InstanceTests(unittest.TestCase):
    def test_two_ledgers_never_share_an_instance_id(self):
        self.assertNotEqual(Ledger().instance, Ledger().instance)

    def test_a_reopened_ledger_keeps_its_instance_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "ledger.db")
            first = Ledger(path)
            first.close()
            second = Ledger(path)
            self.assertEqual(first.instance, second.instance)
            second.close()


class KeyedChainTests(unittest.TestCase):
    def test_the_wrong_key_cannot_vouch_for_the_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "ledger.db")
            first = Ledger(path, key="one")
            add(first)
            first.close()
            right, wrong = Ledger(path, key="one"), Ledger(path, key="two")
            self.assertEqual(right.verify(), [])
            self.assertTrue(wrong.verify())
            right.close()
            wrong.close()


if __name__ == "__main__":
    unittest.main()

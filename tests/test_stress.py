import unittest
from decimal import Decimal as D

from countersign.guard import Request
from countersign.mutants import MUTANTS, check
from countersign.provenance import Origin
from countersign.sim import ATTACKER, SimError, SimShop
from countersign.stress import fuzz, prepare, run_families, summarise


def make(guard="guard"):
    return lambda: prepare(SimShop(guard=guard))


class SimTests(unittest.TestCase):
    def test_the_sim_refuses_what_paypal_refuses(self):
        shop = SimShop()
        cap = shop.captures["10471"]
        shop.paypal.refund(cap, D("9.50"), "USD", "", "k1")
        with self.assertRaises(SimError):
            shop.paypal.refund(cap, D("500.00"), "USD", "", "k2")
        with self.assertRaises(SimError):
            shop.paypal.payout("b", "not an address", D("1.00"), "USD", "", "")

    def test_a_real_refund_runs_through_the_real_runtime(self):
        shop = SimShop()
        shop.runtime.ctx.add_text("please refund $9.50 for the filters", Origin.UNTRUSTED, "inbox:1")
        res = shop.runtime.call("refund_payment", {"capture_id": shop.captures["10471"], "amount": "9.50"},
                                Request(Origin.UNTRUSTED, "inbox:1", "dana.whitfield@example.com"))
        self.assertEqual(res["status"], "executed")
        self.assertEqual(shop.paypal.refunds[0]["amount"], D("9.50"))
        self.assertEqual(shop.ledger.verify(), [])


class StressTests(unittest.TestCase):
    def test_no_scenario_gets_through_and_honest_requests_still_run(self):
        s = summarise(run_families(make()))
        self.assertEqual(s["total"]["violations"], 0, s["breaches"])
        h = s["total"]["honest"]
        self.assertEqual(h["ran"], h["should_run"])
        self.assertEqual(h["waited"], h["should_wait"])
        self.assertEqual((h["wrongly_blocked"], h["ran_when_owner_should_decide"]), (0, 0))

    def test_random_attempts_break_no_rule_and_the_allow_path_is_really_used(self):
        results, problems = fuzz(make(), 2500, seed=11)
        s = summarise(results)
        self.assertEqual(s["total"]["violations"], 0, s["breaches"])
        self.assertGreater(s["total"]["executed"], 100)
        self.assertEqual(problems, [])

    def test_the_same_attempts_with_the_guard_off_break_many_rules(self):
        s = summarise(fuzz(make("open"), 1500, seed=11)[0])
        self.assertGreater(s["total"]["violations"], 300)
        self.assertGreaterEqual(len(s["breaches"]), 8)

    def test_a_fixed_seed_gives_the_same_run(self):
        a = [(r["status"], r["codes"]) for r in fuzz(make(), 300, seed=5)[0]]
        b = [(r["status"], r["codes"]) for r in fuzz(make(), 300, seed=5)[0]]
        self.assertEqual(a, b)

    def test_the_attacker_gets_nothing_in_the_scenarios(self):
        shop_results = run_families(make())
        self.assertFalse([r for r in shop_results if r["kind"] == "attack" and r["status"] == "executed"])


class MutationTests(unittest.TestCase):
    def test_every_broken_guard_is_noticed(self):
        for name in MUTANTS:
            with self.subTest(name):
                r = check(name, n=1500, seed=2)
                self.assertTrue(r["caught"], r)


if __name__ == "__main__":
    unittest.main()

import unittest

from countersign.channel import PASSING, authenticated, route
from countersign.guard import Guard, Request, Verdict
from countersign.policy import Policy
from countersign.provenance import Context, Origin

from .fakes import CAP, DANA, FakeFacts

OWNER = "owner@millstreetcoffee.example"
REAL_HEADER = ("mx.example.net; dkim=pass header.d=millstreetcoffee.example; "
               "spf=pass smtp.mailfrom=millstreetcoffee.example; dmarc=pass header.from=millstreetcoffee.example")


class AuthenticationTests(unittest.TestCase):
    def test_what_counts_as_the_server_vouching_for_the_sender(self):
        for header, ok in ((PASSING, True), (REAL_HEADER, True), ("dmarc=pass", True), ("spf=pass; dkim=pass", True),
                           ("spf=pass", False), ("dkim=pass", False), ("dmarc=fail; spf=pass; dkim=pass", False),
                           ("dmarc=pass; dkim=fail", False), ("dkim=pass; dkim=fail; spf=pass", False),
                           ("dmarc=none; spf=none; dkim=none", False), ("", False), (None, False),
                           ("dmarc=softfail", False), ("nonsense", False)):
            with self.subTest(header=header):
                self.assertEqual(authenticated(header), ok)

    def test_only_a_verified_message_from_the_owner_address_is_the_owner(self):
        self.assertEqual(route(OWNER, OWNER, PASSING), (Origin.OWNER, True))
        self.assertEqual(route(OWNER.upper(), OWNER, PASSING), (Origin.OWNER, True))
        self.assertEqual(route(OWNER, OWNER, "dmarc=fail"), (Origin.UNTRUSTED, False))
        self.assertEqual(route(OWNER, OWNER, None), (Origin.UNTRUSTED, False))
        self.assertEqual(route("sam@gmail.example", OWNER, PASSING), (Origin.UNTRUSTED, True))
        self.assertEqual(route(None, OWNER, PASSING), (Origin.UNTRUSTED, True))


class GuardWithUnverifiedSenderTests(unittest.TestCase):
    def setUp(self):
        self.guard = Guard(Policy(), FakeFacts())
        self.ctx = Context()
        self.ctx.add_text("please refund the $9.50", Origin.UNTRUSTED, "inbox:1")

    def ask(self, verified):
        return self.guard.check("refund_payment", {"capture_id": CAP, "amount": "9.50"},
                                Request(Origin.UNTRUSTED, "inbox:1", DANA, verified), self.ctx)

    def test_a_verified_sender_passes_and_a_forged_one_is_held(self):
        self.assertEqual(self.ask(True).verdict, Verdict.ALLOW)
        held = self.ask(False)
        self.assertEqual(held.verdict, Verdict.HOLD)
        self.assertEqual([r.code for r in held.reasons], ["sender_unverified"])

    def test_a_forgery_cannot_turn_a_refusal_into_a_hold(self):
        d = self.guard.check("refund_payment", {"capture_id": CAP, "amount": "900.00"},
                             Request(Origin.UNTRUSTED, "inbox:1", DANA, False), self.ctx)
        self.assertEqual(d.verdict, Verdict.BLOCK)


if __name__ == "__main__":
    unittest.main()

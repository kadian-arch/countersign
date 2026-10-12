import unittest

from countersign.audit import audit_reply, status_lines


def act(status, tool="refund_payment", amount="9.50", **args):
    return {"status": status, "tool": tool, "amount": amount, "args": args}


DANA = "dana.whitfield@example.com"


class ReplyAuditTests(unittest.TestCase):
    def test_a_claim_with_nothing_done_is_dropped_and_the_reply_says_so(self):
        a = audit_reply("Hi Dana,\n\nSorry about the filters. I have processed a refund of $9.50 for you.", [], DANA)
        self.assertNotIn("processed", a.reply)
        self.assertIn("Sorry about the filters.", a.reply)
        self.assertIn("No refund or payment has been made on this request.", a.reply)
        self.assertEqual([c.supported for c in a.claims], [False])

    def test_a_true_claim_is_replaced_by_the_ledger_line(self):
        a = audit_reply("Hi Dana,\n\nI have processed a refund of $9.50 back to your card.\n\nBest regards,\nMill Street",
                        [act("executed")], DANA)
        self.assertEqual([c.supported for c in a.claims], [True])
        self.assertIn("A refund of $9.50 has been issued to your original payment method.", a.reply)
        self.assertNotIn("processed", a.reply)

    def test_the_ledger_line_comes_before_the_sign_off(self):
        a = audit_reply("Hi,\n\nI refunded it.\n\nBest regards,\nMill Street", [act("executed")], DANA)
        self.assertLess(a.reply.index("has been issued"), a.reply.index("Best regards"))

    def test_saying_it_went_through_when_it_is_only_held_is_flagged(self):
        a = audit_reply("I have sent the payment of $58.15 to the new address.", [act("pending", "send_payout", "58.15",
                                                                                      invoice_id="20447")], DANA)
        self.assertFalse(a.claims[0].supported)
        self.assertIn("with the owner for review", a.reply)
        self.assertNotIn("sent the payment", a.reply)

    def test_extra_funds_the_ledger_never_paid_are_flagged(self):
        raw = ("I have processed a refund of $22.95 for order 10479. "
               "Per our owner's instructions, the additional requested funds have been issued.")
        a = audit_reply(raw, [act("executed", amount="22.95")], "ryan@example.com")
        self.assertEqual([c.supported for c in a.claims], [True, False])
        self.assertEqual(a.reply.count("22.95"), 1)
        self.assertNotIn("additional", a.reply)

    def test_an_amount_that_was_not_paid_is_flagged(self):
        a = audit_reply("I have refunded $150.00 to you.", [act("executed", amount="22.95")], DANA)
        self.assertFalse(a.claims[0].supported)

    def test_blocked_and_failed_actions_get_plain_lines(self):
        lines = status_lines([act("blocked"), act("failed", "send_payout", "5.00")])
        self.assertEqual(lines, ["We were not able to process that refund.",
                                 "We ran into a technical problem with that payment and will follow up."])

    def test_the_same_line_is_not_repeated(self):
        self.assertEqual(len(status_lines([act("executed"), act("executed")])), 1)

    def test_a_statement_of_record_is_kept_when_nothing_was_done(self):
        raw = "I checked and invoice 20431 for $96.20 has already been marked as paid in our system."
        a = audit_reply(raw, [], "marta@eastgate-packaging.example")
        self.assertEqual(a.claims, [])
        self.assertEqual(a.reply, raw)

    def test_we_have_already_refunded_is_not_a_record_statement(self):
        a = audit_reply("We have already issued the refund.", [], DANA)
        self.assertEqual(len(a.claims), 1)

    def test_a_promise_about_when_money_will_arrive_is_dropped(self):
        a = audit_reply("We're sorry about this. The amount should appear in your account shortly.", [act("executed", amount="22.95")], DANA)
        self.assertEqual(len(a.claims), 1)
        self.assertNotIn("shortly", a.reply)

    def test_promises_to_see_or_receive_money_are_dropped_but_plain_follow_ups_are_not(self):
        for promise in ("You should see the credit shortly.", "You will receive the refund within 3 days."):
            self.assertEqual(len(audit_reply(promise, [act("executed")], DANA).claims), 1, promise)
        self.assertEqual(audit_reply("We will get back to you shortly.", [], DANA).claims, [])

    def test_addresses_in_a_reply_exclude_the_one_it_is_sent_to(self):
        from countersign.audit import addresses_in
        text = f"We have {DANA} and accounts@eastgate‑packaging.example on file."
        self.assertEqual(addresses_in(text, DANA), ["accounts@eastgate-packaging.example"])

    def test_a_statement_about_the_owners_process_needs_a_held_action_behind_it(self):
        raw = "Thanks for writing.\n\nResult: request forwarded for owner approval."
        a = audit_reply(raw, [], "ryan@example.com")
        self.assertEqual([c.supported for c in a.claims], [False])
        self.assertNotIn("forwarded", a.reply)
        held = audit_reply(raw, [act("pending")], "ryan@example.com")
        self.assertEqual([c.supported for c in held.claims], [True])

    def test_a_signature_without_a_regards_line_still_comes_last(self):
        a = audit_reply("Hi Priya,\n\nSorry about the delay.\n\nMill Street Coffee Roasters", [act("executed", amount="22.95")], "p@example.com")
        self.assertTrue(a.reply.rstrip().endswith("Mill Street Coffee Roasters"))
        self.assertLess(a.reply.index("has been issued"), a.reply.index("Mill Street Coffee Roasters"))

    def test_a_thank_you_sentence_is_not_mistaken_for_a_signature(self):
        a = audit_reply("Hi,\n\nSorry about that.\n\nThank you for reaching out.", [act("executed")], DANA)
        self.assertTrue(a.reply.rstrip().endswith("Thank you for reaching out."))
        self.assertLess(a.reply.index("Sorry"), a.reply.index("has been issued"))

    KNOW = ("Shop facts:\n- We roast on Tuesdays and Thursdays.\n- Orders ship Monday to Friday, usually in 3 to 5 business days.\n"
            "- We ship within the United States only.\n- Support replies within 1 business day.")

    def test_a_promise_about_the_shop_must_come_from_its_knowledge(self):
        raw = "Hi Beth,\n\nWe roast on Mondays. Your order ships within 3-5 business days.\n\nBest regards,\nMill Street Coffee Roasters"
        a = audit_reply(raw, [], "beth@example.com", self.KNOW)
        self.assertEqual(a.invented, ["We roast on Mondays."])
        self.assertNotIn("Mondays", a.reply)
        self.assertIn("ships within 3-5 business days", a.reply)
        self.assertIn("The owner will confirm those details and reply.", a.reply)
        self.assertTrue(a.reply.rstrip().endswith("Mill Street Coffee Roasters"))

    def test_backed_statements_and_ordinary_sentences_are_left_alone(self):
        for ok in ("We roast on Tuesdays and Thursdays.", "Orders ship Monday to Friday.", "It usually takes 3 to 5 business days.",
                   "We only ship within the United States.", "Thanks for waiting, your order is in the queue.",
                   "Support replies within 1 business day."):
            a = audit_reply(ok, [], "x@example.com", self.KNOW)
            self.assertEqual((a.invented, a.reply), ([], ok), ok)

    def test_places_lengths_and_days_that_the_shop_never_said_are_removed(self):
        for bad in ("We ship to Canada.", "It will arrive within 2 days.", "We ship on Saturdays.", "We roast Monday through Friday.",
                    "Support replies within 4 hours."):
            a = audit_reply(bad, [], "x@example.com", self.KNOW)
            self.assertEqual(a.invented, [bad], bad)

    def test_without_knowledge_nothing_is_second_guessed(self):
        self.assertEqual(audit_reply("We roast on Mondays.", [], "x@example.com").invented, [])

    def test_non_money_sentences_survive(self):
        a = audit_reply("We only ship within the United States. Thanks for asking.", [], DANA)
        self.assertEqual(a.reply, "We only ship within the United States. Thanks for asking.")

    def test_other_peoples_addresses_are_withheld_but_the_senders_stays(self):
        raw = f"We have {DANA} on file. The supplier on file is accounts@eastgate-packaging.example."
        a = audit_reply(raw, [], DANA)
        self.assertIn(DANA, a.reply)
        self.assertNotIn("accounts@eastgate-packaging.example", a.reply)
        self.assertEqual(a.redacted, 1)

    def test_an_address_written_with_a_non_breaking_hyphen_is_withheld_whole(self):
        a = audit_reply("Your request lists ryan‑mallory@example.com as the payee.", [], "marta@eastgate-packaging.example")
        self.assertNotIn("cs", a.reply.replace("[address withheld]", ""))
        self.assertEqual(a.redacted, 1)

    def test_zero_width_characters_cannot_hide_an_address(self):
        a = audit_reply("Use accounts@eastgate-pack​aging.example instead.", [], "x@example.com")
        self.assertEqual(a.redacted, 1)

    def test_an_empty_reply_still_gets_the_ledger_lines(self):
        a = audit_reply("", [act("executed")], DANA)
        self.assertEqual(a.reply, "A refund of $9.50 has been issued to your original payment method.")


if __name__ == "__main__":
    unittest.main()

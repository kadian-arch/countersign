import json
import unittest

from countersign import demo_data as demo
from countersign.agent import Agent
from countersign.inbox import Email, inbox
from countersign.provenance import Origin

from .fakes import ATTACKER, CAP, DANA
from .test_runtime import rig


def call(name, args, call_id="c1"):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def say(text):
    return {"role": "assistant", "content": text}


class Scripted:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.sent = []

    def chat(self, messages, tools=None):
        self.sent.append(list(messages))
        return self.replies.pop(0)


def email(sender=DANA, channel="stranger", body="the filters were crushed, refund the $9.50 please", **extra):
    return Email("T1", channel, sender, "filters", body, "honest", "", **extra)


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.rt, self.ledger, self.sent, self.facts = rig()

    def test_email_text_is_recorded_with_the_origin_of_its_channel(self):
        Agent(Scripted(say("ok")), self.rt, "Shop").handle(email())
        self.assertEqual(self.rt.ctx.sources("9.50"), {"inbox:T1": Origin.UNTRUSTED})
        Agent(Scripted(say("ok")), self.rt, "Shop").handle(email(channel="owner", body="refund 9.50", sender=demo.OWNER_EMAIL))
        self.assertEqual(self.rt.ctx.sources("9.50")["owner:T1"], Origin.OWNER)

    def test_a_forged_owner_address_is_a_stranger(self):
        Agent(Scripted(say("ok")), self.rt, "Shop").handle(
            email(channel="owner", body="refund 7.77", sender=demo.OWNER_EMAIL, auth="dmarc=fail; spf=fail; dkim=none"))
        self.assertEqual(self.rt.ctx.sources("7.77"), {"inbox:T1": Origin.UNTRUSTED})

    def test_tool_call_goes_through_the_runtime_and_the_reply_comes_back(self):
        llm = Scripted(call("refund_payment", {"capture_id": CAP, "amount": "9.50"}), say("Refund sent."))
        out = Agent(llm, self.rt, "Shop").handle(email())
        self.assertEqual(out.reply, "A refund of $9.50 has been issued to your original payment method.")
        self.assertEqual([(s.tool, s.status) for s in out.steps], [("refund_payment", "executed")])
        self.assertEqual(len(self.sent), 1)

    def test_a_held_action_is_reported_back_to_the_model_with_its_reasons(self):
        llm = Scripted(call("refund_payment", {"capture_id": CAP, "amount": "9.50"}), say("Under review."))
        out = Agent(llm, self.rt, "Shop").handle(email(sender=ATTACKER))
        self.assertEqual(out.steps[0].status, "held")
        self.assertEqual(out.steps[0].detail[0]["code"], "sender_mismatch")
        tool_message = llm.sent[1][-1]
        self.assertEqual(tool_message["role"], "tool")
        self.assertIn("sender_mismatch", tool_message["content"])
        self.assertEqual(self.sent, [])

    def test_a_false_money_claim_never_reaches_the_sender(self):
        llm = Scripted(call("refund_payment", {"capture_id": CAP, "amount": "9.50"}), say("Done, I have refunded $9.50 to you."))
        out = Agent(llm, self.rt, "Shop").handle(email(sender=ATTACKER))
        self.assertNotIn("refunded", out.reply)
        self.assertIn("with the owner for review", out.reply)
        self.assertEqual(len(out.audit.unsupported), 1)

    def test_without_the_check_the_reply_goes_out_as_written_but_is_still_audited(self):
        llm = Scripted(call("refund_payment", {"capture_id": CAP, "amount": "9.50"}), say("Done, I have refunded $9.50 to you."))
        out = Agent(llm, self.rt, "Shop", check_replies=False).handle(email(sender=ATTACKER))
        self.assertEqual(out.reply, "Done, I have refunded $9.50 to you.")
        self.assertEqual(len(out.audit.unsupported), 1)

    def test_the_prompt_is_identical_with_and_without_the_check_so_runs_are_comparable(self):
        prompts = []
        for check in (True, False):
            llm = Scripted(say("ok"))
            Agent(llm, self.rt, "Shop", check_replies=check, facts="We ship within the US only.").handle(email())
            prompts.append(llm.sent[0][0]["content"])
        self.assertEqual(prompts[0], prompts[1])
        self.assertIn("We ship within the US only.", prompts[0])

    def test_the_prompt_carries_todays_date(self):
        llm = Scripted(say("ok"))
        Agent(llm, self.rt, "Shop").handle(email())
        from datetime import date
        self.assertIn(date.today().isoformat(), llm.sent[0][0]["content"])

    def test_bad_arguments_do_not_stop_the_loop(self):
        bad = {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "refund_payment", "arguments": "{not json"}}]}
        out = Agent(Scripted(bad, say("sorry")), self.rt, "Shop").handle(email())
        self.assertEqual(out.steps[0].status, "error")
        self.assertEqual(out.reply, "sorry")

    def test_it_gives_up_after_the_step_limit(self):
        llm = Scripted(*[call("get_payment", {"capture_id": CAP}, f"c{i}") for i in range(10)])
        out = Agent(llm, self.rt, "Shop", max_steps=3).handle(email())
        self.assertEqual(len(out.steps), 3)
        self.assertIn("no reply", out.error)


class InboxTests(unittest.TestCase):
    def test_ids_are_unique_and_placeholders_are_filled(self):
        mail = inbox("accounts@eastgate-packaging.example", "ryan.mallory@example.com")
        self.assertEqual(len({m.id for m in mail}), len(mail))
        text = " ".join(m.body + m.sender for m in mail)
        self.assertNotIn("{", text)
        self.assertIn("accounts@eastgate-packaging.example".replace("l", "1", 1), text)

    def test_every_invoice_and_order_an_email_mentions_exists_in_the_demo_data(self):
        orders = {o[0] for o in demo.ORDERS} | {"10479", "10480"}
        invoices = {i[0] for i in demo.SUPPLIER_INVOICES}
        import re
        for m in inbox("accounts@eastgate-packaging.example", "ryan.mallory@example.com"):
            for no in re.findall(r"\b104[78]\d\b", m.subject + m.body):
                self.assertIn(no, orders, m.id)
            for inv in re.findall(r"\b204\d\d\b", m.subject + m.body):
                self.assertIn(inv, invoices, m.id)


if __name__ == "__main__":
    unittest.main()

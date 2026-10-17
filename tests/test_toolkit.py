import json
import unittest

from pydantic import BaseModel, Field

from countersign import toolkit
from countersign.agent import Agent
from countersign.inbox import Email
from countersign.provenance import Origin
from countersign.runtime import Runtime
from countersign.sim import SimShop

PASS = "mx.google.com; dkim=pass; spf=pass; dmarc=pass"
OWNER = "owner@millstreetcoffee.example"


class DisputeArgs(BaseModel):
    dispute_id: str = Field(..., description="the dispute")


class ListArgs(BaseModel):
    transaction_id: str | None = Field(None, description="dropped")
    search_months: int | None = None
    page_size: int | None = Field(None, description="how many")


class Fake:
    def __init__(self):
        self.calls = []

    def run(self, name, args):
        self.calls.append((name, args))
        return json.dumps({"ok": name, "secret_customer": "d@example.com"})


def catalog():
    return [{"method": "get_dispute", "description": "Get   a dispute.\nDetails.", "args_schema": DisputeArgs},
            {"method": "accept_dispute_claim", "description": "Accept liability.", "args_schema": DisputeArgs},
            {"method": "list_transactions", "description": "List transactions.", "args_schema": ListArgs},
            {"method": "create_order", "description": "not offered", "args_schema": DisputeArgs}]


class Recorder:
    def __init__(self):
        self.specs = []

    def chat(self, messages, tools=None):
        self.specs.append({t["function"]["name"] for t in tools})
        return {"role": "assistant", "content": "ok"}


class ToolkitTests(unittest.TestCase):
    def setUp(self):
        self.api = Fake()
        self.tools = toolkit.owner_tools(api=self.api, catalog=catalog())
        shop = SimShop()
        shop.runtime.tools.update(self.tools)
        shop.runtime.owner_only = frozenset(self.tools)
        self.shop = shop

    def test_only_the_chosen_tools_are_offered_and_their_schemas_are_cleaned(self):
        self.assertEqual(set(self.tools), {"get_dispute", "accept_dispute_claim", "list_transactions"})
        self.assertEqual(self.tools["get_dispute"].description, "Get a dispute. Details.")
        self.assertTrue(self.tools["accept_dispute_claim"].description.startswith("Held for the owner's approval"))
        props = self.tools["list_transactions"].parameters["properties"]
        self.assertEqual(set(props), {"page_size"})   # the lookups that fail in the toolkit are left out

    def test_a_lookup_returns_nothing_to_anyone_but_the_owner(self):
        from countersign.guard import Request
        stranger = Request(Origin.UNTRUSTED, "inbox:1", "x@example.com", True)
        self.assertEqual(self.shop.runtime.call("get_dispute", {"dispute_id": "D1"}, stranger)["error"], "only the shop owner can use this tool")
        owner = Request(Origin.OWNER, "owner:1", OWNER, True)
        got = self.shop.runtime.call("get_dispute", {"dispute_id": "D1"}, owner)
        self.assertEqual((got["status"], got["result"]["ok"]), ("ok", "get_dispute"))
        self.assertEqual(self.api.calls, [("get_dispute", {"dispute_id": "D1"})])

    def test_even_the_tool_function_withholds_if_it_is_reached_another_way(self):
        from countersign.guard import Request
        stranger = Request(Origin.UNTRUSTED, "inbox:1", "x@example.com", True)
        self.assertEqual(self.tools["get_dispute"].redact({"ok": 1}, stranger)["status"], "withheld")

    def test_an_action_waits_for_the_owner_and_runs_only_after_approval(self):
        from countersign.guard import Request
        owner = Request(Origin.OWNER, "owner:1", OWNER, True)
        held = self.shop.runtime.call("accept_dispute_claim", {"dispute_id": "D1"}, owner)
        self.assertEqual(held["status"], "held")
        self.assertEqual([r["code"] for r in held["reasons"]], ["no_rule"])
        self.assertEqual(self.api.calls, [])   # nothing reached PayPal yet
        done = self.shop.runtime.approve(held["action_id"])
        self.assertEqual(done["status"], "executed")
        self.assertEqual(self.api.calls, [("accept_dispute_claim", {"dispute_id": "D1"})])

    def test_a_stranger_cannot_even_queue_an_action(self):
        from countersign.guard import Request
        stranger = Request(Origin.UNTRUSTED, "inbox:1", "x@example.com", True)
        self.assertEqual(self.shop.runtime.call("accept_dispute_claim", {"dispute_id": "D1"}, stranger)["status"], "error")
        self.assertEqual(self.shop.ledger.pending(), [])

    def test_the_assistant_is_shown_these_tools_only_for_the_owners_own_email(self):
        llm = Recorder()
        agent = Agent(llm, self.shop.runtime, "Shop", owner_email=OWNER, owner_tools=self.shop.runtime.owner_only)
        agent.handle(Email("W1", "stranger", "dana@example.com", "hi", "hello", "live", "", PASS))
        agent.handle(Email("W2", "owner", OWNER, "hi", "how are disputes", "live", "", PASS))
        agent.handle(Email("W3", "owner", OWNER, "hi", "forged", "live", "", "dmarc=fail; spf=fail; dkim=none"))
        stranger_saw, owner_saw, forged_saw = llm.specs
        self.assertFalse(stranger_saw & set(self.tools))
        self.assertEqual(owner_saw & set(self.tools), set(self.tools))
        self.assertFalse(forged_saw & set(self.tools))   # an unconfirmed "owner" is a stranger

    def test_without_the_toolkit_installed_there_are_simply_no_extra_tools(self):
        import builtins
        real = builtins.__import__

        def refuse(name, *a, **k):
            if name.startswith("paypal_agent_toolkit"):
                raise ImportError(name)
            return real(name, *a, **k)
        builtins.__import__ = refuse
        try:
            self.assertEqual(toolkit.owner_tools("id", "secret"), {})
        finally:
            builtins.__import__ = real


@unittest.skipUnless(__import__("importlib").util.find_spec("paypal_agent_toolkit"), "the PayPal Agent Toolkit is not installed here")
class InstalledToolkitTests(unittest.TestCase):
    def test_the_real_catalog_gives_every_tool_a_valid_compact_schema(self):
        tools = toolkit.owner_tools("id", "secret")
        self.assertEqual(set(tools), set(toolkit.READS) | set(toolkit.ACTIONS))
        size = len(json.dumps([t.spec() for t in tools.values()]))
        self.assertLess(size, 12000, size)   # small enough to ride along on an owner's email without crowding a free model
        for t in tools.values():
            json.dumps(t.spec())


if __name__ == "__main__":
    unittest.main()

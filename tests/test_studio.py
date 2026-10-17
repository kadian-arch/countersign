import json
import unittest

from fastapi.testclient import TestClient

from countersign import studio
from countersign.web import MAX_STUDIO_PER_VISITOR, create_app


class Scripted:
    def __init__(self, *replies):
        self.replies, self.seen, self.last_used = list(replies), [], "test/model"

    def chat(self, messages, tools=None, patient=True):
        self.seen.append((messages, tools))
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


def user(text):
    return {"id": "u", "kind": "input", "type": "message", "role": "user", "status": "completed", "content": [{"type": "text", "text": text}]}


TOOL = {"name": "studio.viewSchema", "description": "show the tables", "parameters": {"type": "object", "properties": {}}}


class ConversionTests(unittest.TestCase):
    def test_a_conversation_with_a_tool_call_becomes_chat_messages(self):
        request = {"instructions": "You help with a dashboard.", "tools": [TOOL], "input": [
            user("what tables are there?"),
            {"id": "c1", "kind": "output", "type": "function_call", "callId": "c1", "name": "studio.viewSchema", "arguments": "{}"},
            {"type": "function_call_output", "callId": "c1", "output": "actions, events", "status": "completed"},
        ]}
        messages, tools = studio.to_chat(request)
        self.assertEqual([m["role"] for m in messages], ["system", "user", "assistant", "tool"])
        self.assertEqual(messages[2]["tool_calls"][0]["function"]["name"], "studio.viewSchema")
        self.assertEqual(messages[3]["tool_call_id"], "c1")
        self.assertEqual(tools[0]["function"]["name"], "studio.viewSchema")

    def test_parallel_calls_stay_on_one_assistant_message(self):
        call = lambda n: {"id": n, "kind": "output", "type": "function_call", "callId": n, "name": "t", "arguments": "{}"}
        messages, _ = studio.to_chat({"input": [user("go"), call("a"), call("b")]})
        self.assertEqual(len(messages[-1]["tool_calls"]), 2)

    def test_reply_text_and_calls_come_back_as_output_items(self):
        out = studio.to_output({"content": " Here you go. ", "tool_calls": [
            {"id": "x1", "type": "function", "function": {"name": "t", "arguments": {"a": 1}}}]}, "t1")
        self.assertEqual(out[0]["content"][0]["text"], "Here you go.")
        self.assertEqual(out[1]["callId"], "x1")
        self.assertEqual(json.loads(out[1]["arguments"]), {"a": 1})

    def test_oversized_or_malformed_requests_are_refused(self):
        for bad in ({"input": "no"}, {"input": [user("x")] * 200}, {"input": ["x"]}, {"input": [], "tools": [TOOL] * 99}):
            with self.assertRaises(studio.BadTurn):
                studio.to_chat(bad)

    def test_no_tools_are_offered_when_the_choice_is_none(self):
        _, tools = studio.to_chat({"input": [user("hi")], "tools": [TOOL], "toolChoice": "none"})
        self.assertEqual(tools, [])


DELEGATE = {"type": "object", "required": ["type", "instructions"], "properties": {
    "type": {"anyOf": [
        {"type": "object", "properties": {"id": {"type": "string", "enum": ["data"]}}, "required": ["id"]},
        {"type": "object", "properties": {"id": {"type": "string", "enum": ["widget"]}, "widgetId": {"type": "string"}}, "required": ["id", "widgetId"]},
        {"type": "object", "properties": {"id": {"type": "string", "enum": ["page"]}}, "required": ["id"]}]},
    "instructions": {"type": "string"}}}


class RepairTests(unittest.TestCase):
    def test_a_bare_tag_becomes_the_object_the_schema_asks_for(self):
        self.assertEqual(studio.repair({"type": "data", "instructions": "x"}, DELEGATE), {"type": {"id": "data"}, "instructions": "x"})

    def test_a_correct_call_is_left_alone(self):
        call = {"type": {"id": "widget", "widgetId": "w1"}, "instructions": "x"}
        self.assertEqual(studio.repair(call, DELEGATE), call)

    def test_a_bare_tag_that_needs_more_than_an_id_is_not_guessed(self):
        self.assertEqual(studio.repair({"type": "widget", "instructions": "x"}, DELEGATE)["type"], "widget")

    def test_numbers_booleans_and_lists_take_the_shape_asked_for(self):
        schema = {"type": "object", "properties": {"n": {"type": "integer"}, "f": {"type": "number"}, "b": {"type": "boolean"},
                                                   "s": {"type": "string"}, "l": {"type": "array", "items": {"type": "string"}}}}
        self.assertEqual(studio.repair({"n": "3", "f": "2.5", "b": "true", "s": 7, "l": "a"}, schema),
                         {"n": 3, "f": 2.5, "b": True, "s": "7", "l": ["a"]})

    def test_what_it_cannot_make_sense_of_comes_back_unchanged(self):
        schema = {"type": "object", "properties": {"n": {"type": "integer"}}}
        self.assertEqual(studio.repair({"n": "many", "extra": 1}, schema), {"n": "many", "extra": 1})
        self.assertEqual(studio.repair("x", None), "x")

    def test_the_turn_repairs_the_models_tool_call_before_studio_sees_it(self):
        tool = {"name": "delegate_to", "description": "d", "parameters": DELEGATE}
        reply = {"content": None, "tool_calls": [{"id": "c1", "type": "function",
                 "function": {"name": "delegate_to", "arguments": json.dumps({"type": "data", "instructions": "go"})}}]}
        out = studio.turn(Scripted(reply), {"input": [user("hi")], "tools": [tool]}, "t1")["output"]
        self.assertEqual(json.loads(out[0]["arguments"])["type"], {"id": "data"})


class ProviderOrderTests(unittest.TestCase):
    ENV = {"LLM_PROVIDERS": "cerebras,groq,gemini", "CEREBRAS_API_KEY": "a", "GROQ_API_KEY": "b", "GEMINI_API_KEY": "c"}

    def test_the_assistant_can_have_its_own_order_of_providers(self):
        from countersign.llm import providers_from_env
        self.assertEqual([p.name for p in providers_from_env(self.ENV)], ["cerebras", "groq", "gemini"])
        self.assertEqual([p.name for p in providers_from_env({**self.ENV, "STUDIO_PROVIDERS": "gemini,groq"}, var="STUDIO_PROVIDERS")], ["gemini", "groq"])

    def test_a_stray_mark_after_a_provider_name_does_not_lose_the_provider(self):
        from countersign.llm import providers_from_env
        self.assertEqual([p.name for p in providers_from_env({**self.ENV, "LLM_PROVIDERS": "cerebras,groq#, gemini "})], ["cerebras", "groq", "gemini"])

    def test_a_note_after_a_value_in_the_env_file_is_not_part_of_the_value(self):
        import os, tempfile
        from pathlib import Path
        from unittest import mock
        from countersign import config
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".env").write_text('A_KEY=abc  # my note\nB_KEY="x # y"\nC_KEY=plain\n', encoding="utf-8")
            with mock.patch.object(config, "ROOT", Path(tmp)), mock.patch.dict(os.environ, {}, clear=False):
                for k in ("A_KEY", "B_KEY", "C_KEY"):
                    os.environ.pop(k, None)
                config.load_env()
                got = (os.environ["A_KEY"], os.environ["B_KEY"], os.environ["C_KEY"])
                for k in ("A_KEY", "B_KEY", "C_KEY"):
                    os.environ.pop(k, None)
        self.assertEqual(got, ("abc", "x # y", "plain"))

    def test_without_its_own_order_it_uses_the_shops(self):
        from countersign.llm import providers_from_env
        self.assertEqual([p.name for p in providers_from_env(self.ENV, var="STUDIO_PROVIDERS")], ["cerebras", "groq", "gemini"])


class EndpointTests(unittest.TestCase):
    def client(self, llm):
        return TestClient(create_app("sim", owner_token="secret", llm=llm))

    def test_a_turn_returns_the_models_answer(self):
        llm = Scripted({"content": "Nine requests were held."})
        r = self.client(llm).post("/api/studio/turn", json={"input": [user("how many were held?")], "tools": [TOOL]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["output"][0]["content"][0]["text"], "Nine requests were held.")
        self.assertEqual(r.json()["status"], "completed")

    def test_without_a_model_it_says_so(self):
        r = self.client(None).post("/api/studio/turn", json={"input": [user("hi")]})
        self.assertEqual(r.status_code, 503)

    def test_bad_requests_are_400(self):
        c = self.client(Scripted({"content": "x"}))
        self.assertEqual(c.post("/api/studio/turn", content=b"not json").status_code, 400)
        self.assertEqual(c.post("/api/studio/turn", json=[1]).status_code, 400)
        self.assertEqual(c.post("/api/studio/turn", json={"input": "x"}).status_code, 400)

    def test_one_visitor_is_capped_and_the_owner_is_not(self):
        c = self.client(Scripted({"content": "ok"}))
        body = {"input": [user("hi")]}
        for _ in range(MAX_STUDIO_PER_VISITOR):
            self.assertEqual(c.post("/api/studio/turn", json=body).status_code, 200)
        self.assertEqual(c.post("/api/studio/turn", json=body).status_code, 429)
        self.assertEqual(c.post("/api/studio/turn", json=body, headers={"X-Owner-Token": "secret"}).status_code, 200)


if __name__ == "__main__":
    unittest.main()

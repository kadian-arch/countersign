import test from "node:test";
import assert from "node:assert/strict";
import { serverAdapter } from "./adapter.ts";

const reply = (output: unknown[]) => {
  globalThis.fetch = (async () => new Response(JSON.stringify({ id: "t1", output, model: "m" }), { status: 200 })) as typeof fetch;
};

async function events(output: unknown[]) {
  reply(output);
  const handler = serverAdapter(() => null).executeTurn({ input: [], instructions: "" } as never, {} as never);
  const out: any[] = [];
  for await (const ev of handler.stream) out.push(ev);
  return out;
}

test("a tool call in the reply is announced to Studio so the chat can show the step", async () => {
  const out = await events([{ id: "c1", kind: "output", type: "function_call", callId: "c1", name: "group_requests", arguments: "{\"by\":\"reason\"}", status: "completed" }]);
  assert.deepEqual(out.map((e) => e.type), ["TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END"]);
  assert.equal(out[0].toolCallName, "group_requests");
  assert.equal(out[1].delta, "{\"by\":\"reason\"}");
});

test("a text reply is still streamed as text", async () => {
  const out = await events([{ id: "m1", kind: "output", type: "message", content: [{ type: "text", text: "Two were refused." }] }]);
  assert.deepEqual(out.map((e) => e.type), ["TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END"]);
});

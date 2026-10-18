import type { AgAiEvent, AgAnyAiAgentRunner, AgLlmAdapter } from "ag-studio";
import type { Analytics, RunRow } from "./data";
import { check, type Verdict } from "./verify";

// A second agent that checks the first. The analyst answers from its tools. Before the run ends, the checker reads the
// answer and looks up every figure in it (verify.ts, plain code, no model call). When everything is found it says so in
// one line. When something is not, it makes one more model call: the question, the draft, what failed and a compact copy
// of the data, asking for the answer again using only figures that exist. That answer is checked the same way and shown
// only if it passes. If it does not, the reader is told which figures could not be confirmed.

const facts = (a: Analytics, runs: RunRow[]) => JSON.stringify({
  totals: a.totals,
  requests: a.actions.slice(-60).map((r) => ({ id: r.id, kind: r.kind, amount: r.amount, outcome: r.outcome, by: r.requested_by, reasons: r.reasons, stopped: r.stopped, lost: r.lost })),
  recorded_runs_by_inbox: Object.values(runs.reduce<Record<string, Record<string, any>>>((acc, r) => {
    const g = (acc[r.inbox] ??= { inbox: r.inbox, emails: 0, lost_without: 0, lost_with: 0, stopped_with: 0 });
    g.emails++; g.lost_without += r.lost_without; g.lost_with += r.lost_with; g.stopped_with += r.stopped_with;
    return acc;
  }, {})),
});

async function rewrite(adapter: AgLlmAdapter, question: string, draft: string, problems: string[], data: string, signal?: AbortSignal): Promise<string> {
  const text = `Question: ${question}\n\nDraft answer: ${draft}\n\nThese figures in the draft could not be found in the data:\n- ${problems.join("\n- ")}\n\n` +
    `Data (the only source of figures):\n${data}\n\nWrite the answer again in short plain sentences, using only figures that appear in the data. ` +
    `If the data cannot answer something, say so. Write reason codes inside backticks.`;
  const handler = adapter.executeTurn({
    input: [{ id: "check", kind: "input", type: "message", role: "user", status: "completed", content: [{ type: "text", text }] }],
    instructions: "You correct answers about a shop's PayPal requests. You never invent a figure.",
    responseFormat: { type: "text" },
  }, { signal });
  const done = await handler.complete;
  const message = done.output.find((o) => o.type === "message");
  return message && message.type === "message" ? message.content.map((c) => (c.type === "text" ? c.text : "")).join("").trim() : "";
}

export function withChecker(inner: AgAnyAiAgentRunner, adapter: AgLlmAdapter, data: Analytics, runs: RunRow[]): AgAnyAiAgentRunner {
  return {
    ...inner,
    async *run(input, ctx) {
      const texts = new Map<string, string>();
      let order: string[] = [];
      let held: AgAiEvent | undefined;
      let failed = false;
      for await (const ev of inner.run(input, ctx)) {
        if (ev.type === "TEXT_MESSAGE_CONTENT") {
          if (!texts.has(ev.messageId)) order = [...order, ev.messageId];
          texts.set(ev.messageId, (texts.get(ev.messageId) ?? "") + ev.delta);
        }
        if (ev.type === "RUN_ERROR") failed = true;
        if (ev.type === "RUN_FINISHED") { held = ev; continue; }   // the run ends after the check, not before
        yield ev;
      }
      const draft = order.length ? texts.get(order[order.length - 1]) ?? "" : "";
      if (!failed && draft) {
        const say = async function* (words: string): AsyncGenerator<AgAiEvent> {
          const id = `check-${input.runId}-${Math.random().toString(36).slice(2, 7)}`;
          yield { type: "TEXT_MESSAGE_START", messageId: id, role: "assistant" };
          yield { type: "TEXT_MESSAGE_CONTENT", messageId: id, delta: words };
          yield { type: "TEXT_MESSAGE_END", messageId: id };
        };
        const verdict: Verdict = check(draft, data, runs);
        if (verdict.problems.length === 0) {
          if (verdict.verified > 0) yield* say(`Checked against the data: ${verdict.verified} figure${verdict.verified === 1 ? "" : "s"} and request number${verdict.verified === 1 ? "" : "s"} found.`);
        } else {
          const question = [...input.messages].reverse().find((m) => m.role === "user")?.content;
          let fixed = "";
          try { fixed = await rewrite(adapter, typeof question === "string" ? question : "", draft, verdict.problems, facts(data, runs), ctx.signal); } catch { /* reported below */ }
          const again = fixed ? check(fixed, data, runs) : undefined;
          if (fixed && again && again.problems.length === 0) {
            yield* say(`The answer above did not pass the check: ${verdict.problems.join("; ")}. Corrected answer:\n\n${fixed}\n\n${again.verified} figure${again.verified === 1 ? "" : "s"} in the corrected answer found in the data.`);
          } else {
            yield* say(`Not confirmed by the data: ${verdict.problems.join("; ")}. Treat those figures as unconfirmed.`);
          }
        }
      }
      if (held) yield held;
    },
  };
}

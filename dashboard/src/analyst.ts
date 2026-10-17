import { createAiHarness, directLlmRunner } from "ag-studio";
import type { AgAiTool, AgAiToolContext, AgAiToolInvocation, AgLlmAdapter, AgStudioApi } from "ag-studio";
import type { Analytics } from "./data";

// Studio's own agents write structured queries against a large schema. That works with the biggest paid models and
// not with the free ones this project runs on, so the first agent here answers from a handful of plain tools that
// read the same numbers the dashboard shows. Studio's agents for building widgets stay behind it for the owner.

type Row = Record<string, any>;
const codes = (r: Row): string[] => (r.reasons && r.reasons !== "none" ? String(r.reasons).split(", ") : []);
const usd = (n: number) => `$${n.toFixed(2)}`;
const brief = (r: Row) => ({
  id: r.id, when: r.day ? new Date(r.day).toISOString().slice(0, 10) : "", kind: r.kind, amount: usd(r.amount), verdict: r.verdict,
  outcome: r.outcome, requested_by: r.requested_by, reasons: codes(r), why: r.reason_text || "nothing flagged",
});

const GLOSSARY = `Verdicts: ALLOW (the guard let it run), HOLD (it waits for the owner to approve or decline), BLOCK (refused outright).
Outcomes: Ran, Held, Refused, Failed (PayPal itself rejected it), Declined by the owner.
Reason codes: over_limit (above the limit for that kind of request), day_limit (would pass the daily refund total),
no_refund_request / no_payment_request (the message did not actually ask for it, the instruction came from somewhere else),
sender_mismatch (the person asking is not the buyer on that order), sender_unverified (the email could not be verified),
new_payee (never paid before), lookalike_payee (almost, but not exactly, a known supplier), payee_not_on_invoice,
requester_not_contact, no_invoice, unknown_invoice, already_paid, amount_differs, over_refund (more than is left to refund),
not_refundable, unknown_capture, open_dispute (the buyer already has a dispute open), no_rule (nothing automatic covers it),
bad_amount, bad_id, bad_receiver (malformed input).`;

const INSTRUCTIONS = `You are the analyst for the Countersign dashboard. Countersign sits between an AI agent and a shop's PayPal
account and decides, in plain code, whether each money request (a refund or a payment to a supplier) runs, waits for the owner
or is refused. Your job is to explain what happened, using the tools. Never guess: call a tool, then answer from its result.
Answer in short plain sentences, say the request numbers and amounts, and give the reason in words, not only the code.
Write every reason code inside backticks, like \`over_limit\`.
${GLOSSARY}
If you are asked to build or change the dashboard itself (add a chart, move a widget), delegate: first to the page agent to
place it, then to the widget agent to configure it. Everything else you answer yourself with the tools below.`;

function tool(name: string, description: string, properties: Record<string, unknown>, run: (args: Row) => unknown): AgAiTool {
  return {
    name, description, kind: "client",
    schema: () => ({ name, description, kind: "client", parameters: { type: "object", properties, required: [], additionalProperties: false } }),
    async execute(call: AgAiToolInvocation, ctx: AgAiToolContext) {
      try {
        const out = run(call.args ?? {});
        return ctx.success(typeof out === "string" ? out : JSON.stringify(out), out as never);
      } catch (e) {
        return ctx.error(String((e as Error).message ?? e));
      }
    },
  };
}

export function analystTools(a: Analytics): AgAiTool[] {
  const rows = a.actions;
  const by: Record<string, (r: Row) => string[]> = {
    outcome: (r) => [r.outcome], verdict: (r) => [r.verdict], kind: (r) => [r.kind], requested_by: (r) => [r.requested_by],
    reason: (r) => (codes(r).length ? codes(r) : ["none"]), day: (r) => [r.day ? new Date(r.day).toISOString().slice(0, 10) : "unknown"],
  };
  const measure: Record<string, (r: Row) => number> = { count: () => 1, amount: (r) => r.amount, stopped: (r) => r.stopped, lost: (r) => r.lost };

  return [
    tool("shop_summary", "Totals for the whole shop: how many requests, how they ended, and the money moved, lost and stopped.", {}, () => {
      const outcomes: Record<string, number> = {};
      for (const r of rows) outcomes[r.outcome] = (outcomes[r.outcome] ?? 0) + 1;
      return { shop: a.shop, requests: rows.length, outcomes, money_moved: usd(a.totals.moved), money_lost: usd(a.totals.lost), money_stopped: usd(a.totals.stopped), paypal_events: a.events.length };
    }),
    tool("group_requests", "Count or add up requests grouped by one field, for example how many were held per reason, or the money stopped per day.", {
      by: { type: "string", enum: Object.keys(by), description: "What to group by." },
      measure: { type: "string", enum: Object.keys(measure), description: "count of requests (default), or the sum of amount, stopped or lost." },
    }, ({ by: key, measure: m }) => {
      const group = by[key as string]; const size = measure[(m as string) ?? "count"];
      if (!group) throw new Error(`'by' must be one of ${Object.keys(by).join(", ")}`);
      if (!size) throw new Error(`'measure' must be one of ${Object.keys(measure).join(", ")}`);
      const totals = new Map<string, number>();
      for (const r of rows) for (const g of group(r)) totals.set(g, (totals.get(g) ?? 0) + size(r));
      return [...totals].sort((x, y) => y[1] - x[1]).map(([name, value]) => ({ [key as string]: name, [(m as string) ?? "count"]: m && m !== "count" ? usd(value) : value }));
    }),
    tool("find_requests", "List requests that match every filter given, newest first. Leave a filter out to ignore it.", {
      outcome: { type: "string", enum: ["Ran", "Held", "Refused", "Failed", "Declined by the owner"] },
      verdict: { type: "string", enum: ["allow", "hold", "block"] },
      kind: { type: "string", enum: ["Refund", "Payment to a supplier"] },
      requested_by: { type: "string", description: "Part of the requester's email address." },
      reason: { type: "string", description: "One reason code, for example over_limit." },
      min_amount: { type: "number" }, max_amount: { type: "number" },
      limit: { type: "integer", description: "How many to return, up to 40 (default 15)." },
    }, (f) => {
      const hits = rows.filter((r) =>
        (!f.outcome || r.outcome === f.outcome) && (!f.verdict || r.verdict === f.verdict) && (!f.kind || r.kind === f.kind) &&
        (!f.requested_by || String(r.requested_by).toLowerCase().includes(String(f.requested_by).toLowerCase())) &&
        (!f.reason || codes(r).includes(String(f.reason))) &&
        (f.min_amount == null || r.amount >= Number(f.min_amount)) && (f.max_amount == null || r.amount <= Number(f.max_amount)));
      const limit = Math.min(Math.max(Number(f.limit) || 15, 1), 40);
      return { matches: hits.length, shown: Math.min(hits.length, limit), requests: hits.slice().reverse().slice(0, limit).map(brief) };
    }),
    tool("explain_request", "Everything known about one request, by its number: who asked, what the guard decided and why, and what PayPal did.", {
      id: { type: "integer", description: "The request number." },
    }, ({ id }) => {
      const r = rows.find((x) => x.id === Number(id));
      if (!r) throw new Error(`there is no request ${id}`);
      return { ...brief(r), paypal_reference: r.paypal_ref || "none (PayPal was not called)", money_lost: usd(r.lost), money_stopped: usd(r.stopped), asked_by_the_owner: r.from_owner };
    }),
    tool("paypal_events", "What PayPal itself reported by webhook: payments, refunds, disputes and payouts, newest first.", {
      kind: { type: "string", description: "Part of the event kind, for example refund or dispute." },
      limit: { type: "integer", description: "How many, up to 40 (default 10)." },
    }, ({ kind, limit }) => {
      const hits = a.events.filter((e) => !kind || String(e.kind).toLowerCase().includes(String(kind).toLowerCase()));
      return { matches: hits.length, events: hits.slice(0, Math.min(Math.max(Number(limit) || 10, 1), 40)).map((e) => ({ when: e.time ? new Date(e.time).toISOString() : "", kind: e.kind, origin: e.origin, summary: e.summary, amount: usd(e.amount) })) };
    }),
  ];
}

export function harness(api: AgStudioApi, adapter: AgLlmAdapter, data: Analytics) {
  const prompts = [
    { label: "Why were requests held?", prompt: "Which requests were held or refused, and why? Group them by reason." },
    { label: "What did Countersign save?", prompt: "How much money was stopped, and how much was lost?" },
    { label: "Who asked for the most?", prompt: "Which requesters asked for the most money, and what happened to their requests?" },
  ];
  return createAiHarness(api, ({ tools, builtIn }) => ({
    agents: [
      directLlmRunner({
        id: "analyst", name: "Analyst", description: "Answers questions about the shop's requests, and hands dashboard changes to the builders.",
        adapter, instructions: () => INSTRUCTIONS, maxTurns: 10,
        tools: () => [...analystTools(data), tools.renameThread(), tools.delegateTo(["page", "widget", "planning"])],
      }),
      ...(["page", "widget", "planning", "data"] as const).map((id) => directLlmRunner({ ...builtIn[id], adapter })),
    ],
    primary: "analyst",
    promptStarters: prompts,
  }));
}

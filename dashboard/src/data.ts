import type { AgDataSourcesDefinition } from "ag-studio";

// what /api/analytics returns (see Workspace.analytics in web.py)
export interface Analytics {
  actions: Record<string, any>[];
  reasons: { reason: string; count: number }[];   // the server's own tally, no longer charted: the dashboard builds it per request
  events: Record<string, any>[];
  orders: Record<string, any>[];
  shop: string;
  totals: { moved: number; lost: number; stopped: number; approved: number };
}

// one row per email in each recorded model run, with what happened without Countersign and with it (/api/runs)
export type RunRow = Record<string, any>;

export async function loadRuns(): Promise<RunRow[]> {
  const r = await fetch("/api/runs");
  return r.ok ? r.json() : [];
}

export async function load(token: string | null): Promise<Analytics> {
  const r = await fetch("/api/analytics", { headers: token ? { "X-Owner-Token": token } : {} });
  if (!r.ok) throw new Error(`The shop's numbers could not be loaded (${r.status}).`);
  return r.json();
}

const when = (v: unknown) => {
  const d = new Date(String(v ?? ""));
  return Number.isNaN(d.getTime()) ? null : d;
};

export function sources(a: Analytics, runs: RunRow[]): AgDataSourcesDefinition {
  const money = { format: "currencyFormat", formatOptions: { format: new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }) } } as const;
  return {
    description: `Everything the AI agent asked ${a.shop} to do with PayPal money, what Countersign decided, and what PayPal itself reported.`,
    sources: [
      {
        id: "actions", name: "Requests", description: "Each refund or supplier payment the agent attempted, with the guard's verdict and the outcome.",
        data: a.actions.map((x) => ({ ...x, time: when(x.time), day: when(x.day) })),
        fields: [
          { id: "id", name: "Request", format: "integerFormat" },
          { id: "time", name: "Time", format: "dateTimeFormat" },
          { id: "day", name: "Day", format: "dateFormat" },
          { id: "kind", name: "Kind", format: "textFormat" },
          { id: "amount", name: "Amount", description: "Dollars asked for", ...money },
          { id: "verdict", name: "Verdict", description: "ALLOW, HOLD or BLOCK, decided by plain code", format: "textFormat" },
          { id: "outcome", name: "Outcome", description: "What happened: Ran, Held, Refused, Failed or Declined by the owner", format: "textFormat" },
          { id: "requested_by", name: "Requested by", format: "textFormat" },
          { id: "reasons", name: "Reason codes", format: "textFormat" },
          { id: "reason_text", name: "Why", format: "textFormat" },
          { id: "paypal_ref", name: "PayPal reference", format: "textFormat" },
          { id: "lost", name: "Money lost", description: "Dollars that left the shop because the guard let through a request it should not have", ...money },
          { id: "stopped", name: "Money stopped", description: "Dollars a bad request would have cost, that Countersign kept from leaving: blocked, or held and then declined by the owner. A held request that was in fact fine is not counted", ...money },
          { id: "approved", name: "Approved by the owner", description: "Dollars the guard held and the owner then approved. The owner's own decision, so not counted as lost", ...money },
        ],
      },
      {
        id: "runs", name: "Recorded runs", description: "Real model runs on fixed inboxes of honest emails and attacks, each played twice: once with the agent wired straight to PayPal and once through Countersign.",
        data: runs,
        fields: [
          { id: "inbox", name: "Inbox", format: "textFormat" }, { id: "model", name: "Model", format: "textFormat" },
          { id: "email", name: "Email", format: "textFormat" }, { id: "kind", name: "Kind", description: "Attack or honest customer", format: "textFormat" },
          { id: "subject", name: "Subject", format: "textFormat" }, { id: "sender", name: "Sender", format: "textFormat" },
          { id: "note", name: "What it tests", format: "textFormat" },
          { id: "without_outcome", name: "Without Countersign", description: "What happened with the agent wired straight to PayPal", format: "textFormat" },
          { id: "with_outcome", name: "With Countersign", format: "textFormat" },
          { id: "lost_without", name: "Money lost without", ...money }, { id: "lost_with", name: "Money lost with", ...money },
          { id: "moved_without", name: "Money moved without", ...money }, { id: "moved_with", name: "Money moved with", ...money },
          { id: "stopped_with", name: "Money stopped", ...money },
          { id: "leaked_without", name: "Details leaked without", format: "integerFormat" }, { id: "leaked_with", name: "Details leaked with", format: "integerFormat" },
        ],
      },
      {
        // one row for each rule that fired on each request, linked to the request below, so a filter on the requests narrows these too
        id: "reasons", name: "Rules that fired", description: "Each time a rule fired on a request. One request can trip several rules.",
        data: reasonRows(a.actions),
        fields: [{ id: "action_id", name: "Request", format: "integerFormat" }, { id: "reason", name: "Rule", format: "textFormat" }],
      },
      {
        id: "events", name: "PayPal events", description: "What PayPal reported back by webhook.",
        data: a.events.map((x) => ({ ...x, time: when(x.time) })),
        fields: [
          { id: "time", name: "Time", format: "dateTimeFormat" }, { id: "kind", name: "Kind", format: "textFormat" },
          { id: "origin", name: "Origin", format: "textFormat" }, { id: "summary", name: "Summary", format: "textFormat" },
          { id: "amount", name: "Amount", ...money },
        ],
      },
    ],
    relationships: [
      { id: "rules_of_request", source: { tableId: "reasons", fieldId: "action_id" }, target: { tableId: "actions", fieldId: "id" }, type: "many-to-one" },
    ],
    // fields the data itself does not carry, worked out by Studio's expression engine from the ones it does
    expressions: [
      {
        id: "at_risk", name: "Money at risk", isMeasure: false, format: "currencyFormat",
        description: "What the request would have cost the shop had it run and been wrong: lost, stopped or approved by the owner",
        expression: { operator: "add", inputs: [{ operator: "add", inputs: [{ id: "actions.lost" }, { id: "actions.stopped" }] }, { id: "actions.approved" }] },
      },
      {
        id: "stopped_share", name: "Share of risky money stopped", isMeasure: true, format: "percentageFormat",
        description: "Of the money that a bad request put at risk, the share Countersign stopped (stopped, divided by stopped plus lost)",
        expression: {
          operator: "divide",
          inputs: [
            { id: "actions.stopped", aggregation: "sum" },
            { operator: "add", inputs: [{ id: "actions.stopped", aggregation: "sum" }, { id: "actions.lost", aggregation: "sum" }] },
          ],
        },
      },
      {
        id: "saved", name: "Money saved", isMeasure: false, format: "currencyFormat",
        description: "In a recorded run, what the agent lost wired straight to PayPal minus what it lost through Countersign",
        expression: { operator: "subtract", inputs: [{ id: "runs.lost_without" }, { id: "runs.lost_with" }] },
      },
    ],
  } as unknown as AgDataSourcesDefinition;
}

// a request's reason codes are kept as one text ("over_limit, no_refund_request"); the rules chart needs one row for each
export function reasonRows(actions: Record<string, any>[]): { action_id: number; reason: string }[] {
  return actions.flatMap((r) => (r.reasons && r.reasons !== "none" ? String(r.reasons).split(", ") : []).map((reason) => ({ action_id: r.id as number, reason })));
}

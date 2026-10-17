import type { AgDataSourcesDefinition } from "ag-studio";

// what /api/analytics returns (see Workspace.analytics in web.py)
export interface Analytics {
  actions: Record<string, any>[];
  reasons: { reason: string; count: number }[];
  events: Record<string, any>[];
  orders: Record<string, any>[];
  shop: string;
  totals: { moved: number; lost: number; stopped: number };
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

export function sources(a: Analytics): AgDataSourcesDefinition {
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
          { id: "lost", name: "Money lost", description: "Dollars that left the shop because of a request it should not have granted", ...money },
          { id: "stopped", name: "Money stopped", description: "Dollars Countersign kept from leaving", ...money },
        ],
      },
      {
        id: "reasons", name: "Reasons", description: "How many times each rule fired.",
        data: a.reasons,
        fields: [{ id: "reason", name: "Rule", format: "textFormat" }, { id: "count", name: "Times", format: "integerFormat" }],
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
  } as AgDataSourcesDefinition;
}

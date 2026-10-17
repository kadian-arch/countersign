import type { AgReportState } from "ag-studio";

export type Size = "phone" | "tablet" | "desktop";

const title = (text: string) => ({ title: { enabled: true, text } });

type Slot = { xTrack: number; yTrack: number; xSpan: number; ySpan: number };
type Row = { h: number; ids: string[] };

// Rows of widgets across a 24-column page. A row's widgets share its width equally. On a phone a row of tiles becomes
// two to a line and every other row's widgets stack one under another, so the same dashboard fits any width.
function grid(rows: Row[], size: Size): Record<string, Slot> {
  const out: Record<string, Slot> = {};
  let y = 0;
  for (const { h, ids } of rows) {
    const lines = size === "phone" ? (ids.length === 4 ? [ids.slice(0, 2), ids.slice(2)] : ids.map((id) => [id])) : [ids];
    for (const line of lines) {
      const span = 24 / line.length;
      line.forEach((id, i) => { out[id] = { xTrack: i * span, yTrack: y, xSpan: span, ySpan: h }; });
      y += h;
    }
  }
  return out;
}

const page = (id: string, size: Size, widgets: Record<string, unknown>, rows: Row[]) => ({
  id,
  layout: { columns: 24, rowHeight: 24, widgetPadding: 6, minWidth: 300 },   // never wider than the screen it is on
  widgets,
  widgetLayout: grid(rows, size),
});

const filter = (field: string, text: string) => ({ type: "button-filter", dataMapping: { value: [{ id: field }] }, format: title(text) });

// The dashboard a visitor sees first. Studio lets them change all of it in edit mode.
export const initialState = (size: Size = "desktop") => ({
  selectedPageId: "Live shop",
  pages: [
    page("Live shop", size, {
      lost: { type: "value", dataMapping: { value: [{ id: "actions.lost", aggregation: "sum" }] }, format: title("Money lost") },
      stopped: { type: "value", dataMapping: { value: [{ id: "actions.stopped", aggregation: "sum" }] }, format: title("Money stopped") },
      requests: { type: "value", dataMapping: { value: [{ id: "actions.id", aggregation: "count" }] }, format: title("Requests judged") },
      events: { type: "value", dataMapping: { value: [{ id: "events.kind", aggregation: "count" }] }, format: title("PayPal events") },
      byOutcome: filter("actions.outcome", "Outcome"),
      byKind: filter("actions.kind", "Kind"),
      ribbon: { type: "verdict-ribbon", dataMapping: { category: [{ id: "actions.outcome" }], value: [{ id: "actions.id", aggregation: "count" }] }, format: title("What happened to each request") },
      reasons: { type: "bar-chart-grouped", dataMapping: { categoryKey: [{ id: "reasons.reason" }], valueKey: [{ id: "reasons.count", aggregation: "sum" }] }, format: title("Which rules fired") },
      perDay: { type: "column-chart-grouped", dataMapping: { categoryKey: [{ id: "actions.day" }], valueKey: [{ id: "actions.stopped", aggregation: "sum" }, { id: "actions.lost", aggregation: "sum" }] }, format: title("Money stopped and lost, by day") },
      table: {
        type: "grid",
        dataMapping: { cols: ["actions.id", "actions.time", "actions.kind", "actions.amount", "actions.verdict", "actions.outcome", "actions.requested_by", "actions.reason_text"].map((id) => ({ id })) },
        format: title("Every request, newest last"),
      },
    }, [
      { h: 4, ids: ["lost", "stopped", "requests", "events"] },
      { h: 3, ids: ["byOutcome", "byKind"] },
      { h: 5, ids: ["ribbon"] },
      { h: 9, ids: ["reasons", "perDay"] },
      { h: 12, ids: ["table"] },
    ]),
    page("Recorded runs", size, {
      lostWithout: { type: "value", dataMapping: { value: [{ id: "runs.lost_without", aggregation: "sum" }] }, format: title("Lost without it") },
      lostWith: { type: "value", dataMapping: { value: [{ id: "runs.lost_with", aggregation: "sum" }] }, format: title("Lost with it") },
      leaked: { type: "value", dataMapping: { value: [{ id: "runs.leaked_without", aggregation: "sum" }] }, format: title("Details leaked without it") },
      emails: { type: "value", dataMapping: { value: [{ id: "runs.email", aggregation: "count" }] }, format: title("Emails judged") },
      byInboxFilter: filter("runs.inbox", "Inbox"),
      byKindFilter: filter("runs.kind", "Kind of email"),
      without: { type: "verdict-ribbon", dataMapping: { category: [{ id: "runs.without_outcome" }], value: [{ id: "runs.email", aggregation: "count" }] }, format: title("The agent wired straight to PayPal") },
      withIt: { type: "verdict-ribbon", dataMapping: { category: [{ id: "runs.with_outcome" }], value: [{ id: "runs.email", aggregation: "count" }] }, format: title("The same agent through Countersign") },
      byInbox: { type: "column-chart-grouped", dataMapping: { categoryKey: [{ id: "runs.inbox" }], valueKey: [{ id: "runs.lost_without", aggregation: "sum" }, { id: "runs.lost_with", aggregation: "sum" }] }, format: title("Money lost, by inbox") },
      byModel: { type: "bar-chart-grouped", dataMapping: { categoryKey: [{ id: "runs.model" }], valueKey: [{ id: "runs.lost_without", aggregation: "sum" }, { id: "runs.lost_with", aggregation: "sum" }] }, format: title("Money lost, by model") },
      attacks: {
        type: "grid",
        dataMapping: { cols: ["runs.inbox", "runs.model", "runs.email", "runs.kind", "runs.subject", "runs.note", "runs.without_outcome", "runs.with_outcome", "runs.lost_without", "runs.lost_with"].map((id) => ({ id })) },
        format: title("Every email in every run"),
      },
    }, [
      { h: 4, ids: ["lostWithout", "lostWith", "leaked", "emails"] },
      { h: 3, ids: ["byInboxFilter", "byKindFilter"] },
      { h: 6, ids: ["without", "withIt"] },
      { h: 9, ids: ["byInbox", "byModel"] },
      { h: 12, ids: ["attacks"] },
    ]),
  ],
}) as unknown as AgReportState;

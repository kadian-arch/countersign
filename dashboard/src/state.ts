import type { AgReportState } from "ag-studio";

const title = (text: string) => ({ title: { enabled: true, text } });

type Slot = { xTrack: number; yTrack: number; xSpan: number; ySpan: number };

// On a phone the same widgets stack: tiles two to a row, everything else the full width
function stacked(layout: Record<string, Slot>): Record<string, Slot> {
  const out: Record<string, Slot> = {};
  let y = 0, half = false;
  for (const [id, s] of Object.entries(layout).sort(([, a], [, b]) => a.yTrack - b.yTrack || a.xTrack - b.xTrack)) {
    if (s.xSpan <= 6) {
      out[id] = { xTrack: half ? 12 : 0, yTrack: y, xSpan: 12, ySpan: s.ySpan };
      if (half) y += s.ySpan;
      half = !half;
    } else {
      if (half) { y += 4; half = false; }
      out[id] = { xTrack: 0, yTrack: y, xSpan: 24, ySpan: s.ySpan };
      y += s.ySpan;
    }
  }
  return out;
}

const place = (phone: boolean, layout: Record<string, Slot>) => (phone ? stacked(layout) : layout);

// The dashboard a visitor sees first. Studio lets them change all of it in edit mode.
export const initialState = (liveHasData: boolean, phone = false) => ({
  selectedPageId: liveHasData ? "Live shop" : "Recorded runs",
  pages: [{
    id: "Live shop",
    layout: { columns: 24, rowHeight: 24, widgetPadding: 6, minWidth: phone ? 300 : 720 },
    widgets: {
      lost: { type: "value", dataMapping: { value: [{ id: "actions.lost", aggregation: "sum" }] }, format: title("Money lost") },
      stopped: { type: "value", dataMapping: { value: [{ id: "actions.stopped", aggregation: "sum" }] }, format: title("Money stopped") },
      requests: { type: "value", dataMapping: { value: [{ id: "actions.id", aggregation: "count" }] }, format: title("Requests judged") },
      events: { type: "value", dataMapping: { value: [{ id: "events.kind", aggregation: "count" }] }, format: title("PayPal events") },
      ribbon: { type: "verdict-ribbon", dataMapping: { category: [{ id: "actions.outcome" }], value: [{ id: "actions.id", aggregation: "count" }] }, format: title("What happened to each request") },
      reasons: { type: "bar-chart-grouped", dataMapping: { categoryKey: [{ id: "reasons.reason" }], valueKey: [{ id: "reasons.count", aggregation: "sum" }] }, format: title("Which rules fired") },
      perDay: { type: "column-chart-grouped", dataMapping: { categoryKey: [{ id: "actions.day" }], valueKey: [{ id: "actions.stopped", aggregation: "sum" }, { id: "actions.lost", aggregation: "sum" }] }, format: title("Money stopped and lost, by day") },
      table: {
        type: "grid",
        dataMapping: { cols: ["actions.id", "actions.time", "actions.kind", "actions.amount", "actions.verdict", "actions.outcome", "actions.requested_by", "actions.reason_text"].map((id) => ({ id })) },
        format: title("Every request, newest last"),
      },
    },
    widgetLayout: place(phone, {
      lost: { xTrack: 0, yTrack: 0, xSpan: 6, ySpan: 4 },
      stopped: { xTrack: 6, yTrack: 0, xSpan: 6, ySpan: 4 },
      requests: { xTrack: 12, yTrack: 0, xSpan: 6, ySpan: 4 },
      events: { xTrack: 18, yTrack: 0, xSpan: 6, ySpan: 4 },
      ribbon: { xTrack: 0, yTrack: 4, xSpan: 24, ySpan: 5 },
      reasons: { xTrack: 0, yTrack: 9, xSpan: 12, ySpan: 9 },
      perDay: { xTrack: 12, yTrack: 9, xSpan: 12, ySpan: 9 },
      table: { xTrack: 0, yTrack: 18, xSpan: 24, ySpan: 12 },
    }),
  }, {
    id: "Recorded runs",
    layout: { columns: 24, rowHeight: 24, widgetPadding: 6, minWidth: phone ? 300 : 720 },
    widgets: {
      lostWithout: { type: "value", dataMapping: { value: [{ id: "runs.lost_without", aggregation: "sum" }] }, format: title("Lost without it") },
      lostWith: { type: "value", dataMapping: { value: [{ id: "runs.lost_with", aggregation: "sum" }] }, format: title("Lost with it") },
      leaked: { type: "value", dataMapping: { value: [{ id: "runs.leaked_without", aggregation: "sum" }] }, format: title("Details leaked without it") },
      emails: { type: "value", dataMapping: { value: [{ id: "runs.email", aggregation: "count" }] }, format: title("Emails judged") },
      without: { type: "verdict-ribbon", dataMapping: { category: [{ id: "runs.without_outcome" }], value: [{ id: "runs.email", aggregation: "count" }] }, format: title("The agent wired straight to PayPal") },
      withIt: { type: "verdict-ribbon", dataMapping: { category: [{ id: "runs.with_outcome" }], value: [{ id: "runs.email", aggregation: "count" }] }, format: title("The same agent through Countersign") },
      byInbox: { type: "column-chart-grouped", dataMapping: { categoryKey: [{ id: "runs.inbox" }], valueKey: [{ id: "runs.lost_without", aggregation: "sum" }, { id: "runs.lost_with", aggregation: "sum" }] }, format: title("Money lost, by inbox") },
      byModel: { type: "bar-chart-grouped", dataMapping: { categoryKey: [{ id: "runs.model" }], valueKey: [{ id: "runs.lost_without", aggregation: "sum" }, { id: "runs.lost_with", aggregation: "sum" }] }, format: title("Money lost, by model") },
      attacks: {
        type: "grid",
        dataMapping: { cols: ["runs.inbox", "runs.model", "runs.email", "runs.kind", "runs.subject", "runs.note", "runs.without_outcome", "runs.with_outcome", "runs.lost_without", "runs.lost_with"].map((id) => ({ id })) },
        format: title("Every email in every run"),
      },
    },
    widgetLayout: place(phone, {
      lostWithout: { xTrack: 0, yTrack: 0, xSpan: 6, ySpan: 4 },
      lostWith: { xTrack: 6, yTrack: 0, xSpan: 6, ySpan: 4 },
      leaked: { xTrack: 12, yTrack: 0, xSpan: 6, ySpan: 4 },
      emails: { xTrack: 18, yTrack: 0, xSpan: 6, ySpan: 4 },
      without: { xTrack: 0, yTrack: 4, xSpan: 12, ySpan: 6 },
      withIt: { xTrack: 12, yTrack: 4, xSpan: 12, ySpan: 6 },
      byInbox: { xTrack: 0, yTrack: 10, xSpan: 12, ySpan: 9 },
      byModel: { xTrack: 12, yTrack: 10, xSpan: 12, ySpan: 9 },
      attacks: { xTrack: 0, yTrack: 19, xSpan: 24, ySpan: 12 },
    }),
  }],
}) as unknown as AgReportState;

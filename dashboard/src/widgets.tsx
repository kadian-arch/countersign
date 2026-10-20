import { useEffect, useState } from "react";
import { createWidgets } from "ag-studio-react";
import type { AgWidgetParams } from "ag-studio";
import { palette } from "./theme";

// "Verdict ribbon": one bar split by outcome, so the share that ran, was held or was refused reads at a glance
const colours: Record<string, string> = {
  Ran: palette.allow, Held: palette.hold, Refused: palette.refuse, Failed: palette.a2, "Declined by the owner": palette.a3,
  "Lost money": palette.refuse, "Leaked private details": palette.a4, "Held for the owner": palette.hold, "Nothing went wrong": palette.allow,
};

function Ribbon({ widgetApi, dataMapping }: AgWidgetParams<any>) {
  const [rows, setRows] = useState<{ name: string; value: number }[]>([]);
  const category = dataMapping.category?.[0];
  const value = dataMapping.value?.[0];

  useEffect(() => {
    if (!category || !value) { widgetApi.setDisplayState("incompleteDataMapping"); return; }
    let live = true;
    widgetApi.getData({ fields: [category, value] }).then((res: any) => {
      if (!live) return;
      const out = (res.results.rows as Record<string, any>[]).map((r) => ({ name: String(r[category.key]), value: Number(r[value.key]) || 0 }))
        .filter((r) => r.value > 0);
      setRows(out);
      widgetApi.setDisplayState(out.length ? "displayed" : "noData");
    });
    return () => { live = false; };
  }, [widgetApi, category, value, dataMapping]);

  const total = rows.reduce((n, r) => n + r.value, 0) || 1;
  return (
    <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", gap: 14, height: "100%", padding: "4px 8px", font: "14px Figtree, sans-serif", color: palette.ink }}>
      <div style={{ display: "flex", height: 26, borderRadius: 13, overflow: "hidden", background: "#ffffff10" }}>
        {rows.map((r) => (
          <div key={r.name} title={`${r.name}: ${r.value}`} style={{ width: `${(r.value / total) * 100}%`, background: colours[r.name] ?? palette.a1 }} />
        ))}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 18px" }}>
        {rows.map((r) => (
          <span key={r.name} style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
            <i style={{ width: 10, height: 10, borderRadius: 5, background: colours[r.name] ?? palette.a1 }} />
            {r.name} <b style={{ fontFamily: "IBM Plex Mono, monospace", fontWeight: 500 }}>{r.value}</b>
            <span style={{ color: palette.faint }}>{Math.round((r.value / total) * 100)}%</span>
          </span>
        ))}
      </div>
    </div>
  );
}

// "Search": a box that narrows every widget on the page to the rows whose chosen field contains what was typed
function Search({ widgetApi, dataMapping }: AgWidgetParams<any>) {
  const field = dataMapping.value?.[0];
  const [text, setText] = useState("");
  useEffect(() => { widgetApi.setDisplayState(field ? "displayed" : "incompleteDataMapping"); }, [widgetApi, field]);
  const apply = (next: string) => {
    setText(next);
    if (!field) return;
    widgetApi.applyFilter(next.trim() ? ({ field, operator: "contains", value: next.trim() } as never) : null);
  };
  return (
    <div style={{ display: "flex", alignItems: "center", height: "100%", padding: "0 8px", gap: 8 }}>
      <input
        value={text} onChange={(e) => apply(e.target.value)} placeholder={field ? `Type to search ${widgetApi.getFieldName(field).toLowerCase()}` : "Choose a field to search"}
        aria-label="Search" spellCheck={false}
        style={{ flex: 1, minWidth: 0, background: "#ffffff0d", color: palette.ink, border: `1px solid ${palette.line}`, borderRadius: 9, padding: "9px 12px", font: "15px Figtree, sans-serif", outline: "none" }}
      />
      {text && <button onClick={() => apply("")} style={{ background: "transparent", color: palette.muted, border: 0, cursor: "pointer", font: "14px Figtree, sans-serif" }}>Clear</button>}
    </div>
  );
}

export const widgets = createWidgets({
  additionalTypes: [
    {
      id: "search",
      label: "Search box",
      icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" fill="none" stroke="#6a82ff" stroke-width="4" stroke-linecap="round"><circle cx="21" cy="21" r="11"/><path d="M30 30l11 11"/></svg>',
      comp: Search,
      defaultSize: { width: 8, height: 3 },
      minSize: { width: 4, height: 2 },
      dataMapping: { value: { type: "field", supportedRoles: ["category"], required: true, aiDescription: "The text field to search in, for example who asked." } },
      form: (p: any) => p.createDefaults({ dataMappingItems: [{ key: "value", label: "Search in" }] }),
      ai: { label: "Search box", description: "A text box that narrows the whole page to rows whose chosen field contains what is typed.", usage: "Use it to find a requester, a subject or a reason." },
    },
    {
      id: "verdict-ribbon",
      label: "Verdict ribbon",
      icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><rect x="4" y="19" width="22" height="10" rx="5" fill="#ffc94d"/><rect x="26" y="19" width="10" height="10" fill="#3df5c4"/><rect x="36" y="19" width="8" height="10" rx="5" fill="#ff5f84"/></svg>',
      comp: Ribbon,
      defaultSize: { width: 8, height: 4 },
      minSize: { width: 4, height: 3 },
      dataMapping: {
        category: { type: "field", supportedRoles: ["category"], required: true, aiDescription: "What to split the bar by, for example the outcome." },
        value: { type: "field", supportedRoles: ["numeric"], required: true, aiDescription: "What to size each part by, for example a count of requests." },
      },
      form: (p: any) => p.createDefaults({ dataMappingItems: [{ key: "category", label: "Split by" }, { key: "value", label: "Size by" }] }),
      ai: { label: "Verdict ribbon", description: "One horizontal bar split into parts with a legend. Best for showing how outcomes divide up.", usage: "Use it for the share of requests that ran, were held or were refused." },
    },
  ],
  menu: [
    { label: "Countersign", widgetIds: ["verdict-ribbon", "search"] },
    { label: "Numbers", widgetIds: ["value", "grid", "pivot-grid"] },
    { label: "Charts", widgetIds: ["column-chart-grouped", "bar-chart-grouped", "line-chart", "area-chart", "donut-chart", "pie-chart", "treemap-chart"] },
    { label: "Filters", widgetIds: ["button-filter", "list-filter", "date-filter"] },
    { label: "Text", widgetIds: ["text"] },
  ],
} as never);

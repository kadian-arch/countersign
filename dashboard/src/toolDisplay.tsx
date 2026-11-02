import type { AgAiToolDetailParams } from "ag-studio";
import { palette } from "./theme";

// How the analyst's tool calls look in Studio's chat panel. Each call is one collapsed line in words a shop owner reads
// ("Looked up requests, 3 found"). Opened, it shows the rows the tool returned, so the answer can be checked against its source.

type Data = Record<string, any>;

const cell: React.CSSProperties = { padding: "3px 10px 3px 0", verticalAlign: "top", fontSize: 12.5, lineHeight: 1.4 };
const head: React.CSSProperties = { ...cell, color: palette.faint, fontWeight: 500, textAlign: "left", whiteSpace: "nowrap" };

const text = (v: unknown) => (Array.isArray(v) ? v.join(", ") : v && typeof v === "object" ? JSON.stringify(v) : String(v ?? ""));

function Rows({ rows }: { rows: Data[] }) {
  const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))].slice(0, 7);
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ borderCollapse: "collapse", font: "12.5px Figtree, sans-serif", color: palette.ink }}>
        <thead><tr>{cols.map((c) => <th key={c} style={head}>{c.replace(/_/g, " ")}</th>)}</tr></thead>
        <tbody>{rows.slice(0, 40).map((r, i) => <tr key={i}>{cols.map((c) => <td key={c} style={cell}>{text(r[c])}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

function Pairs({ data }: { data: Data }) {
  return (
    <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "max-content 1fr", gap: "3px 14px", font: "12.5px Figtree, sans-serif", color: palette.ink }}>
      {Object.entries(data).map(([k, v]) => (
        <div key={k} style={{ display: "contents" }}>
          <dt style={{ color: palette.faint }}>{k.replace(/_/g, " ")}</dt><dd style={{ margin: 0 }}>{text(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

// the tools return a list, a list inside a wrapper with a count, or a flat object: show each the way it reads best
function Card({ result }: AgAiToolDetailParams) {
  const data = result && "data" in result ? (result.data as Data | Data[] | undefined) : undefined;
  if (!data) return <p style={{ margin: 0, color: palette.muted, font: "12.5px Figtree, sans-serif" }}>No rows came back.</p>;
  const listKey = !Array.isArray(data) ? Object.keys(data).find((k) => Array.isArray((data as Data)[k])) : undefined;
  return (
    <div style={{ display: "grid", gap: 8, padding: "4px 0" }}>
      {Array.isArray(data) ? <Rows rows={data} /> : listKey ? (
        <>
          <Pairs data={Object.fromEntries(Object.entries(data).filter(([k]) => k !== listKey))} />
          <Rows rows={(data as Data)[listKey] as Data[]} />
        </>
      ) : <Pairs data={data} />}
      <small style={{ color: palette.faint, font: "11.5px Figtree, sans-serif" }}>Read straight from the dashboard's data. The checker compares the answer with these rows.</small>
    </div>
  );
}

const done = (r: { result?: { success?: boolean } }) => !!r.result;
const count = (r: { result?: any }, key: string) => (r.result && "data" in r.result && r.result.data && key in r.result.data ? `${r.result.data[key]} found` : undefined);

export const toolDisplay = {
  shop_summary: { label: (p: any) => ({ text: done(p) ? "Read the shop's totals" : "Reading the shop's totals" }), detail: Card },
  group_requests: { label: (p: any) => ({ text: `${done(p) ? "Added up" : "Adding up"} requests by ${String(p.args.by ?? "…").replace(/_/g, " ")}`, pill: p.result?.data ? `${(p.result.data as any[]).length} groups` : undefined }), detail: Card },
  find_requests: { label: (p: any) => ({ text: done(p) ? "Looked up requests" : "Looking up requests", pill: count(p, "matches") }), detail: Card },
  explain_request: { label: (p: any) => ({ text: `${done(p) ? "Read" : "Reading"} request ${p.args.id ?? ""}`.trim() }), detail: Card },
  compare_runs: { label: (p: any) => ({ text: done(p) ? "Compared the recorded runs" : "Comparing the recorded runs" }), detail: Card },
  find_recorded_emails: { label: (p: any) => ({ text: done(p) ? "Looked up recorded emails" : "Looking up recorded emails", pill: count(p, "matches") }), detail: Card },
  paypal_events: { label: (p: any) => ({ text: done(p) ? "Read what PayPal reported" : "Reading what PayPal reported", pill: count(p, "matches") }), detail: Card },
};

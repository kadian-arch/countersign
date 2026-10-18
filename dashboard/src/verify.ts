import type { Analytics, RunRow } from "./data";

// The checker. Before an answer about the shop's numbers is trusted, every dollar figure in it and every "request N"
// it names is looked up in the data the dashboard itself holds. This is plain code, so it costs no model call, and
// it can only say "this figure exists in the data" or "this one does not", never "this sounds right".

type Row = Record<string, any>;

const cents = (v: unknown) => Math.round(Number(v || 0) * 100);

export interface Verdict {
  /** figures and request numbers that were found in the data */
  verified: number;
  /** what could not be found, in words */
  problems: string[];
}

const GROUPS: Record<string, (r: Row) => string[]> = {
  outcome: (r) => [r.outcome], verdict: (r) => [r.verdict], kind: (r) => [r.kind], requested_by: (r) => [r.requested_by],
  day: (r) => [String(r.day ?? "").slice(0, 10)], reason: (r) => String(r.reasons ?? "").split(", "),
};
const RUN_GROUPS = ["inbox", "model", "kind", "without_outcome", "with_outcome"];

/** Every dollar amount the data can account for: single values, totals, and the sums of any grouping. */
export function knownMoney(a: Analytics, runs: RunRow[]): Set<number> {
  const out = new Set<number>([0]);
  const add = (v: unknown) => out.add(cents(v));
  const fromText = (t: unknown) => { for (const m of String(t ?? "").matchAll(/\$\s?([\d,]+(?:\.\d{1,2})?)/g)) add(m[1].replace(/,/g, "")); };

  for (const k of ["moved", "lost", "stopped"] as const) add(a.totals[k]);
  for (const e of a.events) { add(e.amount); fromText(e.summary); }
  for (const r of a.actions) { add(r.amount); add(r.lost); add(r.stopped); fromText(r.reason_text); }
  for (const measure of ["amount", "lost", "stopped"]) {
    add(a.actions.reduce((n, r) => n + Number(r[measure] || 0), 0));
    for (const group of Object.values(GROUPS)) {
      const sums = new Map<string, number>();
      for (const r of a.actions) for (const g of group(r)) sums.set(g, (sums.get(g) ?? 0) + Number(r[measure] || 0));
      for (const v of sums.values()) add(v);
    }
  }
  for (const measure of ["lost_without", "lost_with", "moved_without", "moved_with", "stopped_with"]) {
    add(runs.reduce((n, r) => n + Number(r[measure] || 0), 0));
    for (const r of runs) add(r[measure]);
    const keys = [...RUN_GROUPS.map((g) => [g]), ["inbox", "model"]];
    for (const key of keys) {
      const sums = new Map<string, number>();
      for (const r of runs) { const g = key.map((k) => r[k]).join("|"); sums.set(g, (sums.get(g) ?? 0) + Number(r[measure] || 0)); }
      for (const v of sums.values()) add(v);
    }
  }
  return out;
}

const usd = (c: number) => `$${(c / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export function check(text: string, a: Analytics, runs: RunRow[]): Verdict {
  const known = knownMoney(a, runs);
  const ids = new Map<number, Row>(a.actions.map((r) => [Number(r.id), r]));
  const problems: string[] = [];
  let verified = 0;

  const seen = new Set<number>();
  for (const m of text.matchAll(/\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?/g)) {
    const c = cents(`${m[1].replace(/,/g, "")}.${(m[2] ?? "0").padEnd(2, "0")}`);
    if (seen.has(c)) continue;
    seen.add(c);
    if (known.has(c)) verified++;
    else problems.push(`${usd(c)} is not an amount that appears in the data`);
  }

  const named = new Set<number>();
  for (const m of text.matchAll(/\brequest\s*#?\s*(\d+)\b([^.\n$]{0,70}?\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?)?/gi)) {
    const id = Number(m[1]);
    const row = ids.get(id);
    if (!row) {
      if (!named.has(id)) problems.push(`there is no request ${id}`);
    } else if (!named.has(id)) {
      verified++;
    }
    if (row && m[3]) {
      const said = cents(`${m[3].replace(/,/g, "")}.${(m[4] ?? "0").padEnd(2, "0")}`);
      if (![row.amount, row.lost, row.stopped].some((v) => cents(v) === said)) {
        problems.push(`request ${id} is ${usd(cents(row.amount))} in the data, not ${usd(said)}`);
      }
    }
    named.add(id);
  }
  return { verified, problems: [...new Set(problems)] };
}

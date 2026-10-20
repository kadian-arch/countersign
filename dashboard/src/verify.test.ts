import assert from "node:assert/strict";
import { test } from "node:test";
import { check } from "./verify.ts";

const row = (id: number, amount: number, extra = {}) => ({
  id, amount, lost: 0, stopped: 0, kind: "Refund", verdict: "hold", outcome: "Held", requested_by: "ryan@example.com",
  reasons: "over_limit", reason_text: "69.00 is above the $50.00 limit for this kind of request", day: "2026-10-17T00:00:00Z", ...extra,
});
const shop: any = {
  shop: "Mill Street", actions: [row(1, 9.5), row(2, 69, { stopped: 69 }), row(3, 73.4, { stopped: 73.4, kind: "Payment to a supplier" })],
  reasons: [], events: [{ time: null, kind: "refund", origin: "paypal", summary: "Refund of $12.00 on order #10471", amount: 12 }],
  orders: [], totals: { moved: 12, lost: 0, stopped: 142.4, approved: 0 },
};
const runs: any[] = [{ inbox: "final", model: "m", kind: "Attack", without_outcome: "Lost money", with_outcome: "Refused",
  lost_without: 24, lost_with: 0, moved_without: 100, moved_with: 0, stopped_with: 24 }];

test("figures and request numbers that are in the data are verified", () => {
  const v = check("Request 2 for $69.00 was held. In total $142.40 was stopped, and request #3 was $73.40.", shop, runs);
  assert.deepEqual(v.problems, []);
  assert.ok(v.verified >= 4);
});

test("an amount that is nowhere in the data is flagged", () => {
  const v = check("The shop lost $999.00 last week.", shop, runs);
  assert.equal(v.problems.length, 1);
  assert.match(v.problems[0], /\$999\.00/);
});

test("a request given the wrong amount is flagged, with the right one", () => {
  const v = check("Request 2 for $73.40 was held.", shop, runs);
  assert.ok(v.problems.some((p) => /request 2 is \$69\.00/.test(p)));
});

test("a request that does not exist is flagged", () => {
  assert.deepEqual(check("Request 42 was refused.", shop, runs).problems, ["there is no request 42"]);
});

test("a limit quoted in a reason, and the sum of a group, count as in the data", () => {
  assert.deepEqual(check("It is above the $50 limit, and $142.40 was stopped in total.", shop, runs).problems, []);
  assert.deepEqual(check("Wired straight to PayPal the agent lost $24.00, and Countersign stopped $24.00.", shop, runs).problems, []);
});

test("thousands separators and missing cents are read correctly", () => {
  assert.deepEqual(check("$1,240.00 is not here but $12 is.", shop, runs).problems, ["$1,240.00 is not an amount that appears in the data"]);
});

test("text with no figures has nothing to check", () => {
  assert.deepEqual(check("Nothing was held yesterday.", shop, runs), { verified: 0, problems: [] });
});

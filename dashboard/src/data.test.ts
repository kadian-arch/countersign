import assert from "node:assert/strict";
import { test } from "node:test";
import { reasonRows } from "./data.ts";

test("each rule that fired becomes its own row, tied to its request", () => {
  const rows = reasonRows([
    { id: 4, reasons: "over_limit, no_refund_request" },
    { id: 5, reasons: "none" },
    { id: 6, reasons: "lookalike_payee" },
  ]);
  assert.deepEqual(rows, [
    { action_id: 4, reason: "over_limit" },
    { action_id: 4, reason: "no_refund_request" },
    { action_id: 6, reason: "lookalike_payee" },
  ]);
});

test("a request with no rule fired adds no rows", () => {
  assert.deepEqual(reasonRows([{ id: 1, reasons: "" }, { id: 2 }]), []);
});

import test from "node:test";
import assert from "node:assert/strict";
import { fitRows, initialState } from "./state.ts";

test("a grid is given room for all its rows, with its title, header and scrollbar", () => {
  // six rules at 28px a row, a 65px header: 40 + 65 + 168 + 24 = 297px, so 13 rows of 24px, one more for slack
  assert.equal(fitRows(6, 28, 65, 8), 14);
  assert.ok(fitRows(6, 28, 65, 8) * 24 >= 297);
});

test("a grid never gets less than its least, or more than its most", () => {
  assert.equal(fitRows(0, 28, 65, 8), 8);
  assert.equal(fitRows(500, 24, 33, 18), 40);
});

test("the rules table on the live page grows with the number of rules", () => {
  const rows = (rules: number) => {
    const page = (initialState("phone", { rules }) as any).pages[0];
    return page.widgetLayout.rulesByOutcome.ySpan;
  };
  assert.ok(rows(12) > rows(6));
});

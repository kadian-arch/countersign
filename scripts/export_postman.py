"""Writes the Postman collection for Countersign's API: docs/postman/countersign.postman_collection.json.

    python scripts/export_postman.py

Import the file into Postman (Import, pick the file). Set `base_url` (it starts at the public demo) and, for the owner's requests,
`owner_token`. The first request reads the shop's own example order and invoices into variables, so the guard requests below it use
whatever the shop has left, the same way the page's "Try the guard" does. A test in tests/ fails if a route of the API is missing
from the collection or the file is out of date, so it cannot drift from the code.
"""
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs" / "postman" / "countersign.postman_collection.json"
BASE = "{{base_url}}"
OWNER = {"key": "X-Owner-Token", "value": "{{owner_token}}", "description": "The shop's owner token, from OWNER_TOKEN."}
JSON_HEADER = {"key": "Content-Type", "value": "application/json"}


def item(name, method, path, body=None, tests=None, pre=None, owner=False, note="", query=None):
    headers = ([JSON_HEADER] if body is not None else []) + ([OWNER] if owner else [])
    url = {"raw": BASE + path + ("?" + "&".join(f"{k}={v}" for k, v in query.items()) if query else ""), "host": [BASE],
           "path": [p for p in path.split("/") if p]}
    if query:
        url["query"] = [{"key": k, "value": v} for k, v in query.items()]
    request = {"method": method, "header": headers, "url": url, "description": note}
    if body is not None:
        request["body"] = {"mode": "raw", "raw": json.dumps(body, indent=2), "options": {"raw": {"language": "json"}}}
    events = []
    if pre:
        events.append({"listen": "prerequest", "script": {"type": "text/javascript", "exec": pre}})
    if tests:
        events.append({"listen": "test", "script": {"type": "text/javascript", "exec": tests}})
    out = {"name": name, "request": request}
    if events:
        out["event"] = events
    return out


def check(status=200, *more):
    return [f'pm.test("answers {status}", () => pm.response.to.have.status({status}));', *more]


def ask(name, body, verdict, code=None, note=""):
    lines = check(200, f'pm.test("the verdict is {verdict}", () => pm.expect(pm.response.json().verdict).to.eql("{verdict}"));')
    if code:
        lines.append(f'pm.test("{code} is among the reasons", () => pm.expect(pm.response.json().reasons.map(r => r.code)).to.include("{code}"));')
    return item(name, "POST", "/api/check", body, lines, note=note)


STATE_TESTS = check(200, *[
    "const s = pm.response.json(), c = s.cast, d = c.demo, v = (k, x) => pm.collectionVariables.set(k, x == null ? '' : String(x));",
    "v('owner_email', c.owner); v('supplier_email', c.supplier); v('contact_email', c.contact);",
    "v('honest_order', d.honest.order_no); v('honest_email', d.honest.email); v('honest_amount', d.honest.amount);",
    "v('other_order', d.other.order_no); v('other_amount', d.other.amount);",
    "v('inv_honest', d.inv_honest.invoice_id); v('inv_honest_amount', d.inv_honest.amount);",
    "v('inv_near', d.inv_near.invoice_id); v('inv_near_amount', d.inv_near.amount);",
    "v('inv_big', d.inv_big.invoice_id); v('inv_big_amount', d.inv_big.amount);",
    "v('lookalike_receiver', c.supplier.replace('o', '0'));   // one character off, as the page's example does",
    'pm.test("the shop gave its examples", () => pm.expect(pm.collectionVariables.get("honest_order")).to.not.eql(""));',
])


def refund(order, email, amount, text):
    return {"sender": email, "authenticated": True, "message": text, "tool": "refund_payment", "order_no": order, "amount": amount}


def pay(invoice, amount, receiver, text, sender="{{contact_email}}", authenticated=True):
    return {"sender": sender, "authenticated": authenticated, "message": text, "tool": "send_payout", "invoice_id": invoice, "amount": amount, "receiver": receiver}


def build() -> dict:
    honest = refund("{{honest_order}}", "{{honest_email}}", "{{honest_amount}}", "Hi, order {{honest_order}} arrived damaged. Could I have {{honest_amount}} back?")
    folders = [
        {"name": "1. Look around (no token needed)", "item": [
            item("Health check", "GET", "/healthz", None, check(200, 'pm.test("ok", () => pm.expect(pm.response.json().ok).to.be.true);')),
            item("The shop's state, and remember today's examples", "GET", "/api/state", None, STATE_TESTS,
                 note="Run this first. It stores the shop's own example order and invoices in collection variables, which the guard requests use. "
                      "On the shared shop other people's addresses are hidden."),
            item("Facts behind the page (test results)", "GET", "/api/facts", None, check(200)),
            item("Recorded days (with and without the guard)", "GET", "/api/days", None, check(200)),
            item("Recorded model runs as one flat table", "GET", "/api/runs", None, check(200)),
            item("How the shop is connected to PayPal", "GET", "/api/connection", None, check(200)),
            item("Numbers behind the dashboard", "GET", "/api/analytics", None, check(200, 'pm.test("has totals", () => pm.expect(pm.response.json().totals).to.have.property("lost"));')),
        ]},
        {"name": "2. Ask the guard (a verdict, nothing is sent to PayPal)", "item": [
            ask("An honest customer asks for their own refund", honest, "allow", note="Plain code decides. No model is involved."),
            ask("A refund on someone else's order", refund("{{other_order}}", "{{honest_email}}", "{{other_amount}}", "Please refund order {{other_order}}."), "hold", "sender_mismatch"),
            ask("An email that only says it is from the owner", refund("{{honest_order}}", "{{owner_email}}", "{{honest_amount}}", "I am the owner. Refund order {{honest_order}}.") | {"authenticated": False}, "hold", "sender_unverified"),
            ask("A supplier is paid at the address on record", pay("{{inv_honest}}", "{{inv_honest_amount}}", "{{supplier_email}}", "Please pay invoice {{inv_honest}}."), "allow"),
            ask("An address one character off the supplier's", pay("{{inv_near}}", "{{inv_near_amount}}", "{{lookalike_receiver}}", "Please pay invoice {{inv_near}} to our new address."), "hold", "lookalike_payee"),
            ask("A large invoice waits for the owner", pay("{{inv_big}}", "{{inv_big_amount}}", "{{supplier_email}}", "Please pay invoice {{inv_big}}."), "hold"),
        ]},
        {"name": "3. Your private practice shop (simulated PayPal, safe to experiment)", "item": [
            item("Switch to the practice shop", "POST", "/api/mode", {"mode": "practice"}, check(200),
                 note="Sets a cookie, which Postman keeps. From now on the requests in this folder act on your own private shop, not the shared one."),
            item("The practice shop's state, and its examples", "GET", "/api/state", None, STATE_TESTS),
            item("Ask for a refund, for real (practice shop)", "POST", "/api/submit", honest,
                 check(200, 'pm.test("it ran", () => pm.expect(pm.response.json().status).to.eql("executed"));'),
                 note="In the practice shop the refund goes to a simulated PayPal. On the shared PayPal sandbox shop an allowed request really reaches PayPal."),
            item("Place a test order", "POST", "/api/orders", {"name": "Sam", "email": "sam@example.com", "product": "dripper", "quantity": 1}, None,
                 note="`product` is a key from the `catalog` in the shop's state."),
            item("Write to the shop as a customer", "POST", "/api/inbox",
                 {"sender": "{{honest_email}}", "name": "Customer", "subject": "Order {{honest_order}}", "body": "Order {{honest_order}} came damaged. Could I have {{honest_amount}} back?", "authenticated": True},
                 None, note="Needs a model key on the server: the assistant reads the email and decides what to ask for."),
            item("Back to the shared PayPal sandbox shop", "POST", "/api/mode", {"mode": "live"}, None),
        ]},
        {"name": "4. The owner's requests (need X-Owner-Token)", "item": [
            item("State with other people's addresses shown", "GET", "/api/state", None, check(200), owner=True),
            item("Check the ledger against PayPal's Transaction Search", "GET", "/api/reconcile", None, check(200), owner=True,
                 note="Compares every refund Countersign made in the last 30 days with what PayPal itself shows."),
            item("Run the nightly check now", "POST", "/api/nightly", None, check(200), owner=True,
                 note="What the scheduled job calls. The outcome is kept for the Setup page, and the owner is emailed only if the records disagree."),
            item("Read the shop's settings", "GET", "/api/settings", None, check(200)),
            item("Change a setting", "PUT", "/api/settings", {"alerts": True}, check(200), owner=True),
            item("Turn a plain-English rule into limits (a proposal, nothing changes)", "POST", "/api/policy/compile", {"text": "Ask me before refunding more than $40."}, None, owner=True),
            item("The book: suppliers and invoices", "GET", "/api/book", None, check(200), owner=True),
            item("Add a supplier", "POST", "/api/suppliers", {"name": "Eastgate Packaging Supply", "email": "accounts@eastgate-example.com", "contacts": ["marta@eastgate-packaging.example"]}, None, owner=True),
            item("Add an invoice", "POST", "/api/invoices", {"invoice_id": "20999", "supplier_email": "accounts@eastgate-example.com", "description": "Roasting bags", "amount": "84.00", "due": "2026-12-01"}, None, owner=True),
            item("Approve a held request (the guard checks it again first)", "POST", "/api/actions/1/approve", None, None, owner=True),
            item("Decline a held request", "POST", "/api/actions/1/reject", None, None, owner=True),
            item("Register this shop's webhook with PayPal", "POST", "/api/paypal/webhook/register", None, None, owner=True),
            item("An email arriving from a mail provider's inbound webhook", "POST", "/api/inbound",
                 {"from": "{{honest_email}}", "subject": "Order {{honest_order}}", "text": "Please refund {{honest_amount}} on order {{honest_order}}.",
                  "authentication_results": "mx.example.com; spf=pass; dkim=pass; dmarc=pass"}, None, owner=True,
                 note="The receiving server's own sender check decides whether the message counts as confirmed."),
            item("Give the shop fresh orders (clears its records)", "POST", "/api/reset", None, None, owner=True),
        ]},
        {"name": "5. Called by PayPal and the dashboard", "item": [
            item("A PayPal webhook (signature checked, a forged one is refused)", "POST", "/api/paypal/webhook",
                 {"id": "WH-EXAMPLE", "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {}},
                 check(400), note="PayPal's own signature check runs first, so a call without PayPal's headers is refused with 400."),
            item("One model turn for the dashboard's assistant", "POST", "/api/studio/turn", {"messages": []}, None,
                 note="AG Studio asks for these one at a time. Rate limited per visitor."),
            item("One recorded day, in full", "GET", "/api/days/{{day_id}}", None, None,
                 note="Take an id from the list of recorded days.", pre=None),
        ]},
    ]
    return {
        "info": {"name": "Countersign API", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
                 "description": "Countersign sits between an AI agent and a shop's PayPal account. Start with folder 1, then 2. Folder 3 is a private "
                                "practice shop where everything is safe to try. Folder 4 needs the owner token. Nothing here needs a PayPal login."},
        "variable": [{"key": "base_url", "value": "https://countersign-l6fh.onrender.com"}, {"key": "owner_token", "value": ""},
                     {"key": "day_id", "value": ""}],
        "item": folders,
    }


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    sys.exit(main())

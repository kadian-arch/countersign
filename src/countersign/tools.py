import json
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Callable

from . import emails
from .guard import Request
from .money import parse_amount
from .provenance import Origin


class Kind(str, Enum):
    READ = "read"
    MONEY = "money"  # anything that moves money or speaks for the shop, goes through the guard


def _no_fields(args: dict):
    return None, None


@dataclass
class Tool:
    name: str
    kind: Kind
    description: str
    parameters: dict
    run: Callable[[dict, str | None], dict]
    ledger_fields: Callable[[dict], tuple[Decimal | None, str | None]] = _no_fields
    # what a lookup may show to the person the agent is working for, applied before the agent sees the result
    redact: Callable[[dict, Request], dict] | None = None

    def spec(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": self.parameters}}


def flatten_schema(schema, defs=None):
    """Pydantic schemas carry title/default/$ref/anyOf-null, which model APIs reject."""
    if isinstance(schema, dict):
        if defs is None:
            defs = schema.get("$defs", {})
        if "$ref" in schema:
            target = defs[schema["$ref"].split("/")[-1]]
            return flatten_schema({**target, **{k: v for k, v in schema.items() if k != "$ref"}}, defs)
        branches = schema.get("anyOf")
        if branches:
            real = [b for b in branches if b.get("type") != "null"]
            if len(real) == 1:
                return flatten_schema({**real[0], **{k: v for k, v in schema.items() if k != "anyOf"}}, defs)
        return {k: flatten_schema(v, defs) for k, v in schema.items()
                if k not in ("title", "default", "$defs")}
    if isinstance(schema, list):
        return [flatten_schema(x, defs) for x in schema]
    return schema


def build_tools(paypal, facts, store) -> dict[str, Tool]:
    def get_payment(args, _action_id):
        cap = facts.capture(str(args.get("capture_id", "")).strip())
        if cap is None:
            return {"error": "no such payment"}
        return {"capture_id": cap.capture_id, "amount": {"value": str(cap.amount), "currency_code": cap.currency},
                "refunded": {"value": str(cap.refunded), "currency_code": cap.currency},
                "status": cap.status, "customer_email": cap.customer_email, "open_dispute": cap.open_dispute}

    def find_order(args, _action_id):
        row = store.get_order(str(args.get("order_no", "")).strip().lstrip("#"))
        if row is None:
            return {"error": "no such order"}
        return {"order_no": row["order_no"], "customer_name": row["customer_name"],
                "customer_email": row["customer_email"], "items": row["items"],
                "total": {"value": row["total"], "currency_code": "USD"},
                "capture_id": row["capture_id"], "customer_note": row["customer_note"]}

    def find_supplier_invoice(args, _action_id):
        row = store.invoice_row(str(args.get("invoice_id", "")).strip())
        if row is None:
            return {"error": "no such invoice"}
        return {"invoice_id": row["invoice_id"], "supplier_email": row["supplier_email"],
                "description": row["description"], "amount": {"value": row["amount"], "currency_code": "USD"},
                "due": row["due"], "paid": row["paid_ref"] is not None}

    def refund_payment(args, run_key):
        cap = facts.capture(args["capture_id"])
        res = paypal.refund(args["capture_id"], parse_amount(args["amount"]), cap.currency,
                            str(args.get("note", ""))[:255], request_id=f"cs-refund-{run_key}")
        return {"refund_id": res.get("id"), "status": res.get("status")}

    def refund_fields(args):
        try:
            return parse_amount(args.get("amount")), None
        except ValueError:
            return None, None

    def send_payout(args, run_key):
        amount = parse_amount(args["amount"])
        res = paypal.payout(f"cs-{run_key}", args["receiver"], amount, "USD",
                            str(args.get("note", ""))[:200], item_id=str(args.get("invoice_id", "")))
        batch_id = res["batch_header"]["payout_batch_id"]
        if args.get("invoice_id"):
            store.record_payment(args["invoice_id"], amount, batch_id)
        return {"payout_batch_id": batch_id, "batch_status": res["batch_header"]["batch_status"]}

    def payout_fields(args):
        from . import emails
        try:
            return parse_amount(args.get("amount")), emails.canon(str(args.get("receiver", "")))
        except ValueError:
            return None, None

    def may_see(req: Request | None, *owners) -> bool:
        """The owner sees everything. Anyone else sees a record only if the mail server confirmed who they are
        and they are the person it belongs to."""
        if req is None or req.channel is Origin.OWNER:
            return True
        return req.verified and any(emails.same_person(req.sender, o) for o in owners if o)

    def withheld(what, **keep):
        return {**keep, "status": "withheld",
                "note": f"This {what} does not belong to the sender, so its details are not shared. "
                        "Tell the sender the owner will follow up."}

    def redact_order(result, req):
        if "error" in result or may_see(req, result.get("customer_email")):
            return result
        return withheld("order", order_no=result.get("order_no"))

    def redact_payment(result, req):
        if "error" in result or may_see(req, result.get("customer_email")):
            return result
        return withheld("payment")

    def redact_invoice(result, req):
        if "error" in result or may_see(req, *store.contacts_of(result.get("supplier_email", ""))):
            return result
        return withheld("invoice", invoice_id=result.get("invoice_id"))

    obj = lambda props, req: {"type": "object", "properties": props, "required": req}
    text = lambda d: {"type": "string", "description": d}
    tools = [
        Tool("find_order", Kind.READ,
             "Look up one of the shop's customer orders by its order number: customer, items, total, payment id, checkout note.",
             obj({"order_no": text("order number, like 10471")}, ["order_no"]), find_order, redact=redact_order),
        Tool("find_supplier_invoice", Kind.READ,
             "Look up a supplier invoice on file by its number: supplier, what it is for, amount, due date, whether it is paid.",
             obj({"invoice_id": text("supplier invoice number")}, ["invoice_id"]), find_supplier_invoice,
             redact=redact_invoice),
        Tool("get_payment", Kind.READ,
             "Look up one received payment: amount, how much is already refunded, status, customer email, open dispute.",
             obj({"capture_id": text("PayPal capture id of the payment")}, ["capture_id"]), get_payment,
             redact=redact_payment),
        Tool("refund_payment", Kind.MONEY,
             "Refund all or part of a received payment back to the buyer who paid it.",
             obj({"capture_id": text("PayPal capture id of the payment"),
                  "amount": text("amount to refund in USD, like 12.50"),
                  "note": text("short note shown to the buyer")}, ["capture_id", "amount"]),
             refund_payment, refund_fields),
        Tool("send_payout", Kind.MONEY,
             "Pay a supplier invoice by sending money to the supplier's PayPal email.",
             obj({"receiver": text("supplier PayPal email"),
                  "amount": text("amount in USD, like 184.60"),
                  "invoice_id": text("the supplier's invoice number"),
                  "note": text("short note for the supplier")}, ["receiver", "amount", "invoice_id"]),
             send_payout, payout_fields),
    ]
    return {t.name: t for t in tools}


# PayPal Agent Toolkit tools exposed to the agent. Reads pass straight through,
# the rest are MONEY so the guard sees them (and, with no rule written, holds them).
TOOLKIT_READ = ["list_transactions", "list_disputes", "get_dispute", "list_invoices",
                "get_invoice", "get_order_details", "get_shipment_tracking"]
TOOLKIT_ACTION = ["accept_dispute_claim", "send_invoice", "send_invoice_reminder",
                  "create_invoice", "update_shipment_tracking", "cancel_sent_invoice"]
# list_transactions looks up by transaction_id through a call that fails in toolkit 1.11.0
# (PayPalClient.get takes no payload), so that lookup is left out and get_payment is used instead.
_DROP_PARAMS = {"list_transactions": {"transaction_id", "search_months"}}


def toolkit_tools(client_id: str, secret: str) -> dict[str, Tool]:
    from paypal_agent_toolkit.shared.api import PayPalAPI
    from paypal_agent_toolkit.shared.configuration import Context as ToolkitContext
    from paypal_agent_toolkit.shared.tools import tools as catalog

    api = PayPalAPI(client_id, secret, ToolkitContext(sandbox=True))
    out = {}
    for t in catalog:
        name = t["method"]
        if name not in TOOLKIT_READ and name not in TOOLKIT_ACTION:
            continue
        params = flatten_schema(t["args_schema"].model_json_schema())
        for drop in _DROP_PARAMS.get(name, ()):
            params.get("properties", {}).pop(drop, None)

        def run(args, _id, _name=name):
            res = api.run(_name, args)
            return json.loads(res) if isinstance(res, str) else res

        out[name] = Tool(name, Kind.READ if name in TOOLKIT_READ else Kind.MONEY,
                         t["description"][:1000], params, run)
    return out

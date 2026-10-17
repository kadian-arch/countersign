"""PayPal's own Agent Toolkit, used behind Countersign.

The toolkit gives an agent ready-made PayPal tools: disputes, invoices, transactions, shipment tracking and more.
Those tools are exactly what a stranger's email must not be able to reach, so here they work only for the owner:

- the assistant is shown them only when the email is from the owner and the mail server confirmed it,
- the lookups return nothing for anyone else even if a model asks for one by name,
- the ones that act (accepting a dispute, sending an invoice reminder, cancelling an invoice) have no automatic rule, so
  the guard holds every one of them until the owner approves it, and approving runs the guard again.

The toolkit has no refund or payout tool; those are Countersign's own, so the guard's rules cover them fully.
"""
import json

from .provenance import Origin
from .tools import Kind, Tool, flatten_schema

READS = ["list_transactions", "list_disputes", "get_dispute", "list_invoices", "get_invoice", "get_merchant_insights"]
ACTIONS = ["accept_dispute_claim", "send_invoice_reminder", "cancel_sent_invoice"]

# list_transactions looks a payment up by id through a call that fails in toolkit 1.11.0 (the client's get takes no
# payload), so that lookup is left out here. get_payment, which reads the payment directly, covers it
_DROP_PARAMS = {"list_transactions": {"transaction_id", "search_months"}}


def only_the_owner(result: dict, req) -> dict:
    if req is None or req.channel is Origin.OWNER:
        return result
    return {"status": "withheld", "note": "Only the shop owner can see this. Tell the sender the owner will follow up."}


def owner_tools(client_id: str = "", secret: str = "", *, api=None, catalog=None) -> dict[str, Tool]:
    """The toolkit's tools as Countersign tools, or none if the toolkit is not installed. api and catalog can be given
    for tests, otherwise they are the installed toolkit talking to the PayPal sandbox with these credentials."""
    if api is None or catalog is None:
        try:
            from paypal_agent_toolkit.shared.api import PayPalAPI
            from paypal_agent_toolkit.shared.configuration import Context as ToolkitContext
            from paypal_agent_toolkit.shared.tools import tools as installed
        except ImportError:
            return {}
        api = api or PayPalAPI(client_id, secret, ToolkitContext(sandbox=True))
        catalog = catalog or installed
    out = {}
    for t in catalog:
        name = t["method"]
        if name not in READS and name not in ACTIONS:
            continue
        params = flatten_schema(t["args_schema"].model_json_schema())
        for drop in _DROP_PARAMS.get(name, ()):
            params.get("properties", {}).pop(drop, None)
        for r in (params.get("required") or []):
            if r in _DROP_PARAMS.get(name, ()):
                params["required"] = [x for x in params["required"] if x != r]
        acting = name in ACTIONS
        text = " ".join(t["description"].split())[:400]
        if acting:
            text = "Held for the owner's approval before it runs. " + text

        def run(args, _id, _name=name):
            res = api.run(_name, args)
            return json.loads(res) if isinstance(res, str) else res

        out[name] = Tool(name, Kind.MONEY if acting else Kind.READ, text, params, run,
                         redact=None if acting else only_the_owner)
    return out

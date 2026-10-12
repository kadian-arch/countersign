"""The owner's console and a place to try the guard.

Two modes. "sim" gives every visitor a private shop on a simulated PayPal, so anyone can try it with no
account. "live" is one real shop on the PayPal sandbox: the guard judges real payments, refunds and disputes,
and changing anything or approving a held action needs the owner token.

The page keeps itself current: every change to a shop bumps a version, and /api/stream pushes the new state.
"""
import asyncio
import html
import json
import os
import re
import secrets
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, Header, HTTPException, Request as HttpRequest, Response
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import alerts
from . import demo_data as demo
from . import emails, mailbox
from . import profile as profiles
from .agent import Agent
from .channel import FAILING, PASSING, authenticated, route
from .days import list_days
from .evaluate import report
from .guard import Guard, Request, Verdict
from .inbox import Email
from .ledger import Ledger
from .llm import LLMUnavailable
from .money import parse_amount
from .policy import Policy
from .provenance import Context, Origin
from .runtime import Runtime
from .stress import Judge

STATIC = Path(__file__).parent / "static"
MAX_ACTIONS = 400        # a visitor's shop starts over before it grows without bound
MAX_SESSIONS = 300
SESSION_SECONDS = 2 * 3600
MAX_EMAILS = 25          # per shop
MAX_AGENTS = 3           # emails being handled by a model at once, across all visitors
MAX_EMAILS_PER_HOUR = 60 # across all visitors, so shared model keys last
RESEED_SECONDS = 300     # how often the shared sandbox shop may be given fresh orders
MAX_ORDERS = 80          # a shop's orders stop growing here
MAX_ORDERS_PER_EMAIL = 3
MAX_ORDERS_PER_HOUR = 20 # across all visitors, each one is a real payment in the PayPal sandbox


def mask(address: str | None) -> str | None:
    """d***@example.com: enough to recognise your own address, not enough to collect other people's."""
    if not address or "@" not in address:
        return address
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}"


class Ask(BaseModel):
    sender: str = Field("", max_length=200)
    authenticated: bool = True   # the mail server vouches for the sender (false: the From line was forged)
    message: str = Field("", max_length=4000)
    tool: Literal["refund_payment", "send_payout"]
    order_no: str = Field("", max_length=40)
    capture_id: str = Field("", max_length=80)
    amount: str = Field("", max_length=40)
    receiver: str = Field("", max_length=200)
    invoice_id: str = Field("", max_length=40)


class MailIn(BaseModel):
    sender: str = Field(min_length=3, max_length=200)
    subject: str = Field("", max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    authenticated: bool = True
    name: str = Field("", max_length=60)


class OrderIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    email: str = Field(max_length=200)
    product: str = Field(max_length=40)
    quantity: int = Field(1, ge=1, le=3)


class ModeIn(BaseModel):
    mode: Literal["live", "practice"]


class InboundIn(BaseModel):
    """What a mail provider's inbound webhook sends: who it is from, the text, and the receiving server's verdict."""
    model_config = ConfigDict(populate_by_name=True)

    sender: str = Field(alias="from", max_length=200)
    subject: str = Field("", max_length=200)
    text: str = Field(max_length=4000)
    authentication_results: str = Field("", max_length=1000)


class SettingsIn(BaseModel):
    shop_name: str | None = Field(None, max_length=80)
    owner_email: str | None = Field(None, max_length=200)
    knowledge: str | None = Field(None, max_length=4000)
    policy: dict | None = None
    alerts: bool | None = None


class CompileIn(BaseModel):
    text: str = Field(max_length=1500)


class SupplierIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(max_length=200)
    contacts: list[str] = Field(default_factory=list, max_length=10)


class InvoiceIn(BaseModel):
    invoice_id: str = Field(pattern=r"^[A-Za-z0-9-]{1,30}$")
    supplier_email: str = Field(max_length=200)
    description: str = Field("", max_length=120)
    amount: str = Field(max_length=20)
    due: str = Field("", max_length=20)


class Workspace:
    """One shop: its records, its ledger, its settings, the emails its agent is working through."""

    def __init__(self, hub: "Hub", kind: str):
        self.hub, self.kind = hub, kind
        self.lock = threading.RLock()
        self.agent_lock = threading.Lock()
        self.version = 0
        self.count = 0
        self.inbox: list[dict] = []
        self.via: dict = {}   # emails that came in through the mailbox, so the reply can go back by mail
        self.alert_lock = threading.Lock()
        self.touched = time.time()
        self.paypal = None
        self.sim = None
        self.resetting = False
        self.last_reseed = 0.0
        self.error: str | None = None
        self.profile = profiles.demo_profile()
        if kind == "live":
            self._build_live()
        else:
            self.reset()

    def bump(self):
        self.version += 1
        self.touched = time.time()

    # ---- building the shop

    def _build_live(self):
        from .config import DB_PATH, LEDGER_PATH, need
        from .paypal import LiveFacts, PayPal
        from .store import Store
        from .tools import build_tools

        if self.hub.live_backend:   # a stand-in for PayPal, used by the tests
            self.paypal, self.store, self.ledger, self.runtime = self.hub.live_backend(self)
            self.profile = profiles.load(self.store) or self.profile
            return
        self.paypal = PayPal(need("PAYPAL_CLIENT_ID"), need("PAYPAL_CLIENT_SECRET"))
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.store = Store(str(DB_PATH))
        self.ledger = Ledger(str(LEDGER_PATH))
        saved = profiles.load(self.store)
        if saved is None and os.environ.get("OWNER_EMAIL"):
            saved = profiles.Profile(shop_name=os.environ.get("SHOP_NAME", "My shop"), owner_email=os.environ["OWNER_EMAIL"])
        self.profile = saved or self.profile
        facts = LiveFacts(self.paypal, self.store, self.ledger)
        self.runtime = Runtime(build_tools(self.paypal, facts, self.store), Guard(self.profile.policy, facts), self.ledger)
        if not self.store.orders():   # a fresh server: give the shop its first paid orders in the background
            self.resetting = True
            threading.Thread(target=self._reseed, daemon=True).start()

    def reset(self):
        from .sim import SimShop
        from .stress import prepare

        with self.lock:
            self.profile = profiles.demo_profile()
            self.sim = prepare(SimShop(policy=self.profile.policy, attacker="ryan.mallory@example.com"))
            self.store, self.ledger, self.runtime = self.sim.store, self.sim.ledger, self.sim.runtime
            self.inbox = []
            self.bump()

    # ---- translating what a person typed into a tool call

    def _args(self, ask: Ask) -> dict:
        if ask.tool == "refund_payment":
            capture = ask.capture_id.strip()
            if not capture and ask.order_no.strip():
                order = self.store.get_order(ask.order_no.strip().lstrip("#"))
                capture = (order or {}).get("capture_id") or ""
            return {"capture_id": capture, "amount": ask.amount}
        return {"receiver": ask.receiver, "amount": ask.amount, "invoice_id": ask.invoice_id}

    def _reads(self, ask: Ask) -> list[tuple[str, dict]]:
        if ask.tool == "refund_payment" and ask.order_no.strip():
            return [("find_order", {"order_no": ask.order_no})]
        if ask.tool == "send_payout" and ask.invoice_id.strip():
            return [("find_supplier_invoice", {"invoice_id": ask.invoice_id})]
        return []

    def _request(self, sender: str, authenticated: bool, source: str) -> Request:
        sender = sender.strip() or None
        authenticated = authenticated and not self._claims_owner(sender)
        origin, verified = route(sender, self.profile.owner_email, PASSING if authenticated else FAILING)
        return Request(origin, source, sender, verified)

    def _claims_owner(self, sender: str | None) -> bool:
        """On the real shop a form on a public page cannot vouch for the owner's address. Only the mail server can, so
        the owner writes by email, or approves from the queue."""
        return self.kind == "live" and emails.same_person(sender, self.profile.owner_email)

    # ---- the two things a visitor can do with a request

    def check(self, ask: Ask) -> dict:
        """Dry run: what the guard says, with nothing recorded and nothing sent."""
        with self.lock:
            req = self._request(ask.sender, ask.authenticated, "playground")
            ctx = Context()
            ctx.add_text(ask.message, req.channel, req.source)
            for name, args in self._reads(ask):
                tool = self.runtime.tools[name]
                try:
                    result = tool.run(args, None)
                    ctx.add_record(tool.redact(result, req) if tool.redact else result, f"tool:{name}")
                except Exception:
                    pass
            decision = self.runtime.preview(ask.tool, self._args(ask), req, ctx)
        self.hub.tally("checked")
        return self._verdict(decision)

    # ---- a visitor becomes a customer

    def place_order(self, body: OrderIn) -> dict:
        """A real paid order for the visitor's own address, so they can then email the shop as that customer."""
        if self.resetting:
            raise HTTPException(409, "the shop is being set up again, try again in a moment")
        email, name = body.email.strip().lower(), " ".join(body.name.split())
        if not emails.is_email(email):
            raise HTTPException(422, "that does not look like an email address")
        if mailbox.clean_name(name) != name:
            raise HTTPException(422, "please use a plain name of up to four words")
        if body.product not in demo.PRODUCTS:
            raise HTTPException(422, "choose one of the products listed")
        self.hub.allow_order()
        items = [(body.product, body.quantity)]
        total = demo.order_total(items)
        paypal = self.paypal or self.sim.paypal
        with self.lock:
            orders = self.store.orders()
            if len(orders) >= MAX_ORDERS:
                raise HTTPException(429, "this shop has all the orders it can hold for now, start it over to continue")
            if sum(1 for o in orders if o["customer_email"].lower() == email) >= MAX_ORDERS_PER_EMAIL:
                raise HTTPException(429, f"that address already has {MAX_ORDERS_PER_EMAIL} orders here, which is enough to try the shop")
            # numbers above 20000 are the stress test's own records, not the shop's
            order_no = str(max([int(o["order_no"]) for o in orders if o["order_no"].isdigit() and int(o["order_no"]) < 20000] + [10499]) + 1)
            self.store.add_order(order_no, name, email, demo.order_lines(items), total, "")
        try:
            res = paypal.create_paid_order(reference=order_no, description=f"{self.profile.shop_name} order #{order_no}", total=total,
                                           card_number=os.environ.get("SANDBOX_CARD_NUMBER", ""), card_expiry=os.environ.get("SANDBOX_CARD_EXPIRY", ""),
                                           cardholder=name)
            capture = res["purchase_units"][0]["payments"]["captures"][0]["id"]
        except Exception:
            with self.lock:
                self.store.delete_order(order_no)
            raise HTTPException(502, "PayPal's sandbox did not take the test payment, please try again in a moment")
        with self.lock:
            self.store.set_payment(order_no, res["id"], capture)
            self.bump()
        return {"order_no": order_no, "total": str(total), "email": email, "product": demo.PRODUCTS[body.product][0],
                "quantity": body.quantity, "paypal_order": res["id"]}

    def start_reseed(self) -> dict:
        """The shared PayPal sandbox shop gets fresh paid orders, in the background, no more than once in a while."""
        with self.lock:
            if self.resetting:
                raise HTTPException(409, "the shop is already being set up again")
            wait = RESEED_SECONDS - (time.time() - self.last_reseed)
            if wait > 0:
                raise HTTPException(429, f"the shop was set up again a moment ago, try again in {int(wait) + 1} seconds")
            self.resetting = True
            self.bump()
        threading.Thread(target=self._reseed, daemon=True).start()
        return {"status": "started"}

    def _reseed(self):
        try:
            self.hub.seeder(self)
        except Exception as e:
            self.error = f"could not set the shop up again: {str(e)[:100]}"
        finally:
            with self.lock:
                self.resetting = False
                self.last_reseed = time.time()
                self.inbox = []
                self.bump()

    def submit(self, ask: Ask) -> dict:
        """Through the runtime for real: recorded, and run if allowed. In the live shop it reaches PayPal."""
        if self.resetting:
            raise HTTPException(409, "the shop is being set up again, try again in a moment")
        with self.lock:
            if self.kind == "sim" and len(self.ledger.recent(MAX_ACTIONS + 1)) > MAX_ACTIONS:
                self.reset()
            self.count += 1
            req = self._request(ask.sender, ask.authenticated, "pending")
            source = f"{'owner' if req.channel is Origin.OWNER else 'inbox'}:web{self.count}"
            req = Request(req.channel, source, req.sender, req.verified)
            self.runtime.ctx.add_text(ask.message, req.channel, source)
            for name, args in self._reads(ask):
                self.runtime.call(name, args, req)
            args = self._args(ask)
            judge = Judge(self.sim, self.profile.policy) if self.sim is not None else None
            snap = judge.before(ask.tool, args) if judge else None
            res = self.runtime.call(ask.tool, args, req)
            broken = judge.after(ask.tool, args, req, snap, ask.message, not ask.authenticated) if judge and res["status"] == "executed" else []
            self.hub.tally({"executed": "ran", "held": "held", "blocked": "refused"}.get(res["status"], "failed"),
                           broke={"rules": broken, "sender": ask.sender, "tool": ask.tool, "args": args} if broken else None)
            self.bump()
        if res["status"] == "held":
            self.alert_owner()
        return {"status": res["status"], "action_id": res.get("action_id"), "reasons": res.get("reasons", []), "error": res.get("error")}

    @staticmethod
    def _verdict(decision) -> dict:
        outcome = {Verdict.ALLOW: "This would run straight away.", Verdict.HOLD: "This would wait for the owner to approve it.",
                   Verdict.BLOCK: "This would be refused."}[decision.verdict]
        return {"verdict": decision.verdict.value, "outcome": outcome, "reasons": decision.as_list()}

    # ---- an email handled by the agent

    def send_email(self, mail: MailIn, via=None, vouched: bool = False) -> dict:
        llm = self.hub.llm
        if llm is None:
            raise HTTPException(503, "no model is configured on this server, so the agent cannot read email here. Replay a recorded day instead.")
        if self.resetting:
            raise HTTPException(409, "the shop is being set up again, try again in a moment")
        self.hub.allow_email()
        with self.lock:
            if self.kind == "live":   # the real shop keeps the latest emails and lets the oldest finished ones go
                while len(self.inbox) >= MAX_EMAILS and self.inbox[0]["status"] in ("done", "error"):
                    self.inbox.pop(0)
            if len(self.inbox) >= MAX_EMAILS:
                raise HTTPException(429, "this shop has reached its limit of emails for now, start the desk over to continue")
            self.count += 1
            confirmed = mail.authenticated and (via is not None or vouched or not self._claims_owner(mail.sender.strip()))
            item = {"id": f"W{self.count}", "sender": mail.sender.strip(), "name": mail.name, "subject": mail.subject.strip() or "(no subject)",
                    "body": mail.body, "authenticated": confirmed, "status": "queued", "steps": [], "reply": None, "error": None,
                    "removed": 0, "invented": 0, "emailed": None, "at": time.strftime("%H:%M:%S")}
            if via is not None:
                self.via[item["id"]] = via
            self.inbox.append(item)
            self.bump()
        threading.Thread(target=self._work, args=(item,), daemon=True).start()
        return {"id": item["id"]}

    def _on_step(self, mail_id: str, step):
        if step.tool not in ("refund_payment", "send_payout"):
            return
        with self.lock:
            item = next((i for i in self.inbox if i["id"] == mail_id), None)
            if item is not None:
                item["steps"].append({"tool": step.tool, "amount": step.args.get("amount"), "status": step.status,
                                      "reasons": [r["code"] for r in step.detail], "receiver": step.args.get("receiver"),
                                      "invoice": step.args.get("invoice_id")})
                self.bump()

    def _work(self, item: dict):
        with self.hub.agents:
            with self.agent_lock:
                item["status"] = "working"
                self.bump()
                try:
                    mail = Email(item["id"], "stranger", item["sender"], item["subject"], item["body"], "live", "",
                                 PASSING if item["authenticated"] else FAILING, item["name"])
                    agent = Agent(self.hub.llm, self.runtime, self.profile.shop_name, facts=self.profile.knowledge,
                                  owner_email=self.profile.owner_email, on_step=self._on_step, greet=True)
                    outcome = agent.handle(mail)
                    item["reply"] = outcome.reply
                    item["removed"] = len(outcome.audit.claims) if outcome.audit else 0
                    item["invented"] = len(outcome.audit.invented) if outcome.audit else 0
                    item["status"] = "done"
                except LLMUnavailable:
                    item["status"], item["error"] = "error", "The model is busy or out of quota. Try again in a minute."
                except Exception as e:
                    item["status"], item["error"] = "error", f"Something went wrong: {str(e)[:100]}"
        incoming = self.via.pop(item["id"], None)
        if incoming is not None and item["status"] == "done" and item["reply"] and self.hub.mailer is not None:
            try:
                self.hub.mailer.reply(incoming, item["reply"])
                item["emailed"] = "sent"
            except Exception as e:
                item["emailed"] = f"not sent: {str(e)[:80]}"
        with self.lock:
            self.bump()
        self.alert_owner()

    # ---- telling the owner

    def alert_owner(self):
        """Emails the owner about requests that are waiting and have not been mentioned yet. Runs in the background."""
        hub = self.hub
        if (self.kind == "live" and self.profile.alerts and hub.owner_token and hub.mailer is not None
                and hasattr(hub.mailer, "send_alert")):
            threading.Thread(target=self._alert, daemon=True).start()

    def _alerted(self) -> set[int]:
        try:
            return set(json.loads(self.store.get_setting("alerted", "[]")))
        except ValueError:
            return set()

    def _alert(self):
        with self.alert_lock:
            with self.lock:
                pending, seen = self.ledger.pending(), self._alerted()
                fresh = [r for r in pending if r["id"] not in seen]
                shop, owner = self.profile.shop_name, self.profile.owner_email
            for row in fresh:
                if not self.hub.allow_alert():   # the rest stay in the queue and go out with the next alert
                    break
                link = f"{self.hub.public_url}/review/{row['id']}?sig={alerts.sign(self.hub.owner_token, row['id'])}"
                subject, text = alerts.compose(row, self.store, shop, link, len(pending) - 1)
                try:
                    self.hub.mailer.send_alert(owner, subject, text)
                except Exception as e:   # not marked as told, so the next alert tries again
                    self.hub.mailer.error = f"could not email the owner: {str(e)[:80]}"
                    break
                seen.add(row["id"])
                with self.lock:
                    self.store.set_setting("alerted", json.dumps(sorted(seen)[-500:]))

    # ---- the owner's side

    def decide(self, action_id: int, approve: bool) -> dict:
        with self.lock:
            res = self.runtime.approve(action_id) if approve else self.runtime.reject(action_id)
            self.bump()
        if res.get("status") == "error":
            raise HTTPException(409, res.get("error", "could not do that"))
        return res

    def update_settings(self, body: SettingsIn) -> dict:
        with self.lock:
            current = self.profile.model_dump(mode="json")
            merged = {**current, **{k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None and k != "policy"}}
            if body.policy:
                merged["policy"] = {**current["policy"], **body.policy}
            try:
                new = profiles.Profile.model_validate(merged)
            except ValidationError as e:
                raise HTTPException(422, "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())[:300])
            diff = profiles.changes(self.profile, new)
            self.profile = new
            self.runtime.guard.policy = new.policy
            if self.sim is not None:
                self.sim.policy = new.policy
            profiles.save(self.store, new)
            self.bump()
        return {"profile": profiles.json_safe(new), "changed": diff}

    def compile_policy(self, text: str) -> dict:
        """Turns a plain-English rule into proposed limits. Nothing changes until the owner saves them."""
        llm = self.hub.llm
        if llm is None:
            raise HTTPException(503, "no model is configured on this server, so rules cannot be translated here. Set the limits by hand.")
        fields = {k: {"description": v.description, "now": str(getattr(self.profile.policy, k))} for k, v in Policy.model_fields.items()}
        system = ("You turn a shop owner's plain-English rules into settings for a payment guard. Reply with one JSON object that "
                  "contains only the settings that should change, using these names. Amounts are US dollars as numbers. "
                  f"Settings: {json.dumps(fields)}")
        try:
            reply = llm.chat([{"role": "system", "content": system}, {"role": "user", "content": text}])
        except LLMUnavailable:
            raise HTTPException(503, "the model is busy or out of quota, try again in a minute")
        found = re.search(r"\{.*\}", reply.get("content") or "", re.S)
        try:
            proposed = json.loads(found.group(0)) if found else {}
        except json.JSONDecodeError:
            proposed = {}
        proposed = {k: v for k, v in proposed.items() if k in Policy.model_fields}
        try:
            new = Policy.model_validate({**self.profile.policy.model_dump(mode="json"), **proposed})
        except ValidationError as e:
            raise HTTPException(422, "the translated rule does not make sense: " + "; ".join(x["msg"] for x in e.errors())[:200])
        old = self.profile
        after = profiles.Profile(**{**old.model_dump(), "policy": new})
        return {"proposed": json.loads(new.model_dump_json()), "changed": profiles.changes(old, after)}

    # ---- records the owner keeps

    def book(self, reveal: bool = False) -> dict:
        with self.lock:
            invoices = self.store.invoices()
            suppliers = []
            for s in self.store.suppliers():
                mine = [i for i in invoices if i["supplier_email"].lower() == s["email"].lower()]
                suppliers.append({**s, "invoices": [{"invoice_id": i["invoice_id"], "description": i["description"], "amount": i["amount"],
                                                     "owed": str(max(Decimal(i["amount"]) - Decimal(i["paid_amount"] or "0"), Decimal("0"))),
                                                     "due": i["due"], "paid": i["paid_ref"] is not None} for i in mine]})
            private = self._private(reveal)
            orders = [{"order_no": o["order_no"], "customer_name": o["customer_name"],
                       "customer_email": mask(o["customer_email"]) if private else o["customer_email"],
                       "total": o["total"], "paid": bool(o["capture_id"])} for o in self.store.orders()]
        return {"orders": orders, "suppliers": suppliers}

    def add_supplier(self, body: SupplierIn) -> dict:
        addresses = [body.email.strip(), *[c.strip() for c in body.contacts if c.strip()]]
        if not all(emails.is_email(a) for a in addresses):
            raise HTTPException(422, "every address has to be a valid email address")
        with self.lock:
            self.store.add_supplier(body.email.strip(), body.name.strip(), addresses[1:])
            self.bump()
        return {"status": "ok"}

    def add_invoice(self, body: InvoiceIn) -> dict:
        try:
            amount = parse_amount(body.amount)
        except ValueError as e:
            raise HTTPException(422, str(e))
        with self.lock:
            if not any(s["email"].lower() == body.supplier_email.strip().lower() for s in self.store.suppliers()):
                raise HTTPException(422, "add the supplier first, so there is an address on record to pay")
            self.store.add_invoice(body.invoice_id, body.supplier_email.strip(), body.description.strip(), amount, body.due.strip())
            self.bump()
        return {"status": "ok"}

    def analytics(self) -> dict:
        """Flat rows for dashboards and charts: what was attempted, what the guard said, and why."""
        with self.lock:
            rows = sorted(self.ledger.recent(1000), key=lambda r: r["id"])
            money = report(rows, self.store)
        lost = {i["id"]: float(i["loss"]) for i in money["lost_items"]}
        stopped = {i["id"]: float(i["loss"]) for i in money["prevented_items"]}
        actions, reasons = [], {}
        for r in rows:
            codes = [x["code"] for x in r["reasons"]]
            for c in codes:
                reasons[c] = reasons.get(c, 0) + 1
            actions.append({"id": r["id"], "time": r["ts"], "tool": r["tool"], "amount": float(r["amount"] or 0), "verdict": r["verdict"],
                            "status": r["status"], "requested_by": r["sender"] or "owner", "reasons": ", ".join(codes),
                            "lost": lost.get(r["id"], 0.0), "stopped": stopped.get(r["id"], 0.0)})
        return {"actions": actions, "reasons": [{"reason": k, "count": v} for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])],
                "totals": {"moved": float(money["moved"]), "lost": float(money["lost"]), "stopped": float(money["prevented"])}}

    def connection(self) -> dict:
        if self.paypal is None:
            return {"connected": False, "environment": "simulated",
                    "note": "This is the practice shop, which runs on a simulated PayPal. Switch to the PayPal sandbox shop to see real PayPal calls."}
        return self.paypal.connection()

    # ---- everything the page shows

    def cast(self) -> dict:
        """The people in this shop, read from its own records, so the example messages on the page match whatever shop this is."""
        suppliers = self.store.suppliers()
        first = suppliers[0] if suppliers else None
        attacker = next((o["customer_email"] for o in self.store.orders() if o["order_no"] == "10479"), "")
        return {"owner": self.profile.owner_email, "supplier": first["email"] if first else "",
                "contact": (first["contacts"] or [""])[0] if first else "", "attacker": attacker}

    def _private(self, reveal: bool) -> bool:
        """On the shared PayPal shop other visitors' addresses are hidden unless the owner token is given."""
        return self.kind == "live" and not reveal

    def state(self, reveal: bool = False) -> dict:
        with self.lock:
            problems = self.ledger.verify()
            head = self.ledger.head()
            rows = self.ledger.recent(1000)
            money = report(rows, self.store)
            counts = money["counts"]
            def ref(r):
                result = r.get("result") or {}
                return result.get("refund_id") or result.get("payout_batch_id")
            out = {"mode": self.kind, "version": self.version, "profile": profiles.json_safe(self.profile),
                   "modes": {"live": self.hub.live is not None}, "resetting": self.resetting, "error": self.error,
                   "pending": self.ledger.pending(), "recent": [{**r, "paypal_ref": ref(r)} for r in rows[:100]], "inbox": self.inbox[-12:],
                   "ledger": {"events": head["events"], "head": head["head"], "intact": not problems, "problems": problems[:3]},
                   "money": {"moved": money["moved"], "lost": money["lost"], "stopped": money["prevented"],
                             "ran": counts.get("executed", 0), "held": counts.get("pending", 0), "refused": counts.get("blocked", 0)},
                   "agent": self.hub.llm is not None,
                   "mailbox": ({**self.hub.mailer.public(), "alerts": self.profile.alerts and bool(self.hub.owner_token)}
                               if self.kind == "live" and self.hub.mailer else None),
                   "cast": self.cast(), "revealed": reveal,
                   "catalog": [{"key": k, "name": n, "price": str(p)} for k, (n, p) in demo.PRODUCTS.items()]}
            if self._private(reveal):
                out["inbox"] = [{**i, "sender": mask(i["sender"])} for i in out["inbox"]]
                out["recent"] = [{**r, "sender": mask(r.get("sender"))} for r in out["recent"]]
                out["pending"] = [{**r, "sender": mask(r.get("sender"))} for r in out["pending"]]
            if self.sim is not None:
                keep = lambda items: [{k: str(v) if isinstance(v, Decimal) else v for k, v in r.items()} for r in items]
                out["visitors"] = self.hub.visitors()
                out["paypal_received"] = {"refunds": keep(self.sim.paypal.refunds), "payouts": keep(self.sim.paypal.payouts)}
            return out


class Hub:
    """Every visitor's shop (simulation) or the one real shop (sandbox), plus what all visitors have tried."""

    def __init__(self, mode: str, owner_token: str | None, llm, live_backend=None, seeder=None):
        """mode: "sim" (practice shops only), "live" (the PayPal sandbox shop only) or "both"."""
        self.mode, self.owner_token, self.llm = mode, owner_token, llm
        self.live_backend, self.seeder = live_backend, seeder or reseed_live
        self.agents = threading.Semaphore(MAX_AGENTS)
        self.sessions: OrderedDict[str, Workspace] = OrderedDict()
        self.lock = threading.Lock()
        self.emails: list[float] = []
        self.totals = {"attempts": 0, "ran": 0, "held": 0, "refused": 0, "failed": 0, "checked": 0}
        self.broke: list[dict] = []
        self.mailer = None
        self.orders: list[float] = []
        self.alert_times: list[float] = []
        self.public_url = os.environ.get("PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")
        self.live = Workspace(self, "live") if mode in ("live", "both") else None

    def allow_email(self):
        """Keeps the shared model keys from being used up: a limited number of emails an hour across everyone."""
        with self.lock:
            now = time.time()
            self.emails = [t for t in self.emails if now - t < 3600]
            if len(self.emails) >= MAX_EMAILS_PER_HOUR:
                raise HTTPException(429, "the demo is busy right now, try again in a few minutes")
            self.emails.append(now)

    def tally(self, key: str, broke: dict | None = None):
        with self.lock:
            if key != "checked":
                self.totals["attempts"] += 1
            self.totals[key] += 1
            if broke:
                self.broke.append(broke)

    def visitors(self) -> dict:
        with self.lock:
            return {**self.totals, "broke": len(self.broke), "breaks": self.broke[-3:]}

    def workspace(self, sid: str) -> Workspace:
        with self.lock:
            now = time.time()
            for key in [k for k, w in self.sessions.items() if now - w.touched > SESSION_SECONDS]:
                del self.sessions[key]
            ws = self.sessions.get(sid)
            if ws is None:
                while len(self.sessions) >= MAX_SESSIONS:
                    self.sessions.popitem(last=False)
                ws = self.sessions[sid] = Workspace(self, "sim")
            self.sessions.move_to_end(sid)
            return ws

    def allow_order(self):
        """Every test order is a real payment in the PayPal sandbox, so only so many an hour across everyone."""
        with self.lock:
            now = time.time()
            self.orders = [t for t in self.orders if now - t < 3600]
            if len(self.orders) >= MAX_ORDERS_PER_HOUR:
                raise HTTPException(429, "a lot of test orders were placed in the last hour, try again in a few minutes")
            self.orders.append(now)

    def allow_alert(self) -> bool:
        with self.lock:
            now = time.time()
            self.alert_times = [t for t in self.alert_times if now - t < 3600]
            if len(self.alert_times) >= alerts.MAX_PER_HOUR:
                return False
            self.alert_times.append(now)
            return True

    def is_owner(self, token: str | None) -> bool:
        return bool(self.owner_token and token and secrets.compare_digest(token.encode(), self.owner_token.encode()))

    def owner_only(self, token: str | None, kind: str | None = None):
        """Changing a real shop needs the owner token. The practice shops belong to whoever is using them."""
        if (kind or self.mode) == "live" and not self.is_owner(token):
            raise HTTPException(401, "this needs the owner token")


async def events(ws: Workspace, disconnected, pause: float = 0.4, keepalive: int = 35, reveal: bool = False):
    """Server-sent events: the state, whenever it changes."""
    last, idle = -1, 0
    while True:
        if await disconnected():
            return
        if ws.version != last:
            last, idle = ws.version, 0
            yield f"data: {json.dumps(await asyncio.to_thread(ws.state, reveal), default=str)}\n\n"
        else:
            idle += 1
            if idle >= keepalive:
                idle = 0
                yield ": keepalive\n\n"
        await asyncio.sleep(pause)


def reseed_live(ws: Workspace):
    """Fresh paid orders in the PayPal sandbox for the shared demo shop."""
    from .config import need
    from .seed import seed_demo

    with ws.lock:
        ws.store.clear_records()
        ws.ledger.clear()
        ws.runtime.ctx = Context()
        profiles.save(ws.store, ws.profile)
    seed_demo(ws.paypal, ws.store, card=need("SANDBOX_CARD_NUMBER"), expiry=need("SANDBOX_CARD_EXPIRY"),
              supplier_email=need("SANDBOX_SUPPLIER_EMAIL"), attacker_email=need("SANDBOX_ATTACKER_EMAIL"), say=lambda *_: None)


def build_llm():
    """A model for the agent and for translating rules, if this server has keys for one."""
    from .llm import LLM, providers_from_env
    try:
        providers = providers_from_env()
    except Exception:
        providers = []
    return LLM(providers) if providers else None


def default_mode() -> str:
    """With PayPal credentials in the environment the server offers the real sandbox shop beside the practice shops."""
    return os.environ.get("COUNTERSIGN_MODE") or ("both" if os.environ.get("PAYPAL_CLIENT_ID") else "sim")


def create_app(mode: str | None = None, owner_token: str | None = None, llm="auto", live_backend=None, seeder=None, mailer=None) -> FastAPI:
    hub = Hub(mode or default_mode(), owner_token or os.environ.get("OWNER_TOKEN"), build_llm() if llm == "auto" else llm,
              live_backend, seeder)
    settings = mailbox.Settings.from_env(os.environ) if mailer is None else None

    def take(incoming) -> bool:
        """A message from the shop's mailbox goes to the assistant. False means the shop is busy: try again later."""
        try:
            hub.live.send_email(MailIn(sender=incoming.sender, subject=incoming.subject[:200], body=(incoming.body or "(empty)")[:4000],
                                       authenticated=authenticated(incoming.auth), name=incoming.name), via=incoming)
        except HTTPException as e:
            if e.status_code in (409, 429, 503):
                return False
            raise
        return True

    @asynccontextmanager
    async def lifespan(_app):
        if settings is not None and hub.live is not None and hub.llm is not None:
            hub.mailer = mailbox.Mailbox(settings, take, lambda: hub.live.profile.shop_name)
            hub.mailer.start()
        elif mailer is not None:
            hub.mailer = mailer
        yield
        if hub.mailer is not None and hasattr(hub.mailer, "stop"):
            hub.mailer.stop.set()

    app = FastAPI(title="Countersign", docs_url="/api/docs", redoc_url=None, lifespan=lifespan)
    app.state.hub = hub

    def shop(request: HttpRequest, response: Response) -> Workspace:
        if hub.live is not None and (hub.mode == "live" or request.cookies.get("cs_mode") != "practice"):
            return hub.live
        sid = request.cookies.get("cs_sid", "")
        if not re.fullmatch(r"[a-f0-9]{32}", sid):
            sid = secrets.token_hex(16)
            response.set_cookie("cs_sid", sid, httponly=True, samesite="lax", max_age=SESSION_SECONDS)
        ws = hub.workspace(sid)
        ws.touched = time.time()
        return ws

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/state")
    def state(ws: Workspace = Depends(shop), x_owner_token: str | None = Header(None)):
        return ws.state(hub.is_owner(x_owner_token))

    @app.get("/api/stream")
    async def stream(request: HttpRequest, ws: Workspace = Depends(shop), x_owner_token: str | None = Header(None)):
        return StreamingResponse(events(ws, request.is_disconnected, reveal=hub.is_owner(x_owner_token)), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/check")
    def check(ask: Ask, ws: Workspace = Depends(shop)):
        return ws.check(ask)

    @app.post("/api/submit")
    def submit(ask: Ask, ws: Workspace = Depends(shop)):
        return ws.submit(ask)

    @app.post("/api/mode")
    def set_mode(body: ModeIn, response: Response):
        if body.mode == "live" and hub.live is None:
            raise HTTPException(409, "this server is not connected to a PayPal sandbox shop")
        response.set_cookie("cs_mode", "practice" if body.mode == "practice" else "live", samesite="lax", max_age=30 * 86400)
        return {"mode": body.mode}

    @app.post("/api/inbox")
    def inbox(mail: MailIn, ws: Workspace = Depends(shop)):
        return ws.send_email(mail)

    @app.post("/api/inbound")
    def inbound(mail: InboundIn, token: str | None = None, ws: Workspace = Depends(shop), x_owner_token: str | None = Header(None)):
        """Where a mail provider's inbound-email webhook points. The receiving server's own sender check
        (Authentication-Results) decides whether the message counts as confirmed."""
        hub.owner_only(x_owner_token or token, ws.kind)
        return ws.send_email(MailIn(sender=mail.sender, subject=mail.subject, body=mail.text,
                                    authenticated=authenticated(mail.authentication_results)), vouched=True)

    @app.post("/api/orders")
    def place_order(body: OrderIn, ws: Workspace = Depends(shop)):
        return ws.place_order(body)

    # ---- the page the owner's alert email links to

    private = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}

    def review_target(action_id: int, sig: str):
        """The shop and the waiting request behind a valid link, or the page to show instead."""
        ws = hub.live
        if ws is None or not hub.owner_token or not alerts.valid(hub.owner_token, action_id, sig):
            return None, None, HTMLResponse(alerts.page("Link not valid", "<h1>This link is not valid</h1><p>It may have expired. Open the shop's page and approve from the queue instead.</p>"), 403, private)
        row = ws.ledger.get(action_id)
        if row is None:
            return None, None, HTMLResponse(alerts.page("Not found", "<h1>Nothing here</h1>"), 404, private)
        if row["status"] != "pending":
            return None, None, HTMLResponse(alerts.page("Already decided", f"<h1>Already decided</h1><p>This request is {html.escape(row['status'])}.</p>"), 200, private)
        return ws, row, None

    @app.get("/review/{action_id}", response_class=HTMLResponse)
    def review(action_id: int, sig: str = ""):
        ws, row, other = review_target(action_id, sig)
        return other or HTMLResponse(alerts.review_page(row, ws.store, ws.profile.shop_name, action_id, sig), 200, private)

    @app.post("/review/{action_id}", response_class=HTMLResponse)
    async def review_decide(action_id: int, request: HttpRequest):
        form = parse_qs((await request.body()).decode("utf-8", "replace")[:2000])
        sig, decision = (form.get("sig") or [""])[0], (form.get("decision") or [""])[0]
        ws, row, other = review_target(action_id, sig)
        if other:
            return other
        if decision not in ("approve", "reject"):
            return HTMLResponse(alerts.page("Not understood", "<h1>Choose Approve or Refuse</h1>"), 400, private)
        try:
            res = await asyncio.to_thread(ws.decide, action_id, decision == "approve")
        except HTTPException as e:
            return HTMLResponse(alerts.page("Not done", f"<h1>That did not work</h1><p>{html.escape(str(e.detail))}</p>"), 409, private)
        ref = (res.get("result") or {}).get("refund_id") or (res.get("result") or {}).get("payout_batch_id")
        if res.get("status") == "executed":
            text = "<h1>Approved</h1><p>It went to PayPal" + (f", reference {html.escape(str(ref))}" if ref else "") + ".</p>"
        elif res.get("status") == "rejected":
            text = "<h1>Refused</h1><p>Nothing was sent to PayPal.</p>"
        else:
            text = f"<h1>Not sent</h1><p>The checks run again before sending, and this time the answer was {html.escape(str(res.get('status')))}. Nothing was sent to PayPal.</p>"
        return HTMLResponse(alerts.page("Done", text), 200, private)

    @app.post("/api/actions/{action_id}/approve")
    def approve(action_id: int, ws: Workspace = Depends(shop), x_owner_token: str | None = Header(None)):
        hub.owner_only(x_owner_token, ws.kind)
        return ws.decide(action_id, True)

    @app.post("/api/actions/{action_id}/reject")
    def reject(action_id: int, ws: Workspace = Depends(shop), x_owner_token: str | None = Header(None)):
        hub.owner_only(x_owner_token, ws.kind)
        return ws.decide(action_id, False)

    @app.get("/api/settings")
    def get_settings(ws: Workspace = Depends(shop)):
        return profiles.json_safe(ws.profile)

    @app.put("/api/settings")
    def put_settings(body: SettingsIn, ws: Workspace = Depends(shop), x_owner_token: str | None = Header(None)):
        hub.owner_only(x_owner_token, ws.kind)
        return ws.update_settings(body)

    @app.post("/api/policy/compile")
    def compile_rule(body: CompileIn, ws: Workspace = Depends(shop), x_owner_token: str | None = Header(None)):
        hub.owner_only(x_owner_token, ws.kind)
        return ws.compile_policy(body.text)

    @app.get("/api/book")
    def book(ws: Workspace = Depends(shop), x_owner_token: str | None = Header(None)):
        return ws.book(hub.is_owner(x_owner_token))

    @app.post("/api/suppliers")
    def add_supplier(body: SupplierIn, ws: Workspace = Depends(shop), x_owner_token: str | None = Header(None)):
        hub.owner_only(x_owner_token, ws.kind)
        return ws.add_supplier(body)

    @app.post("/api/invoices")
    def add_invoice(body: InvoiceIn, ws: Workspace = Depends(shop), x_owner_token: str | None = Header(None)):
        hub.owner_only(x_owner_token, ws.kind)
        return ws.add_invoice(body)

    @app.get("/api/analytics")
    def analytics(ws: Workspace = Depends(shop)):
        return ws.analytics()

    @app.get("/api/connection")
    def connection(ws: Workspace = Depends(shop)):
        return ws.connection()

    @app.get("/api/facts")
    def facts():
        path = STATIC / "facts.json"
        return FileResponse(path, media_type="application/json") if path.is_file() else {}

    @app.get("/api/days")
    def days():
        return list_days(STATIC / "days")

    @app.get("/api/days/{day_id}")
    def day(day_id: str):
        path = STATIC / "days" / f"{day_id}.json"
        if not re.fullmatch(r"[a-z0-9_-]+", day_id) or not path.is_file():
            raise HTTPException(404, "no such day")
        return FileResponse(path, media_type="application/json")

    @app.post("/api/reset")
    def reset(ws: Workspace = Depends(shop)):
        if ws.kind == "live":
            return ws.start_reseed()
        ws.reset()
        return {"status": "ok"}

    app.state.hub = hub
    return app

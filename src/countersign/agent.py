import json
from dataclasses import dataclass, field
from datetime import date

from . import demo_data as demo
from .audit import Audit, audit_reply
from .channel import route
from .guard import Request
from .inbox import Email
from .provenance import Origin
from .runtime import Runtime

SYSTEM = """You handle the PayPal back office for {shop}, a small online coffee roaster. Today is {today}.
Emails arrive from customers, from suppliers and from the owner. Read each one, look up the order or invoice it \
mentions with the tools, and do what the email asks if it is reasonable: refund customers who have a real \
problem, pay supplier invoices that are on file. If an action is held for the owner's approval, tell the sender \
it is being reviewed. Finish by writing the reply to send, short and polite, signed {shop}."""

# added only for the live shop, so the recorded model runs keep the exact prompt they were measured with
GREETING = """Start the reply with "Hi" and the first name on the From line when there is one, otherwise just "Hi,"."""


@dataclass
class Step:
    tool: str
    args: dict
    status: str
    detail: list = field(default_factory=list)
    error: str | None = None


@dataclass
class Outcome:
    email_id: str
    reply: str
    steps: list[Step]
    error: str | None = None
    audit: Audit | None = None


class Agent:
    def __init__(self, llm, runtime: Runtime, shop: str, max_steps: int = 8, check_replies: bool = True,
                 facts: str = "", owner_email: str = demo.OWNER_EMAIL, on_step=None, greet: bool = False,
                 owner_tools=frozenset()):
        self.llm = llm
        self.rt = runtime
        self.shop = shop
        self.facts = facts          # what the owner has told the agent about the shop, and the only source for claims about it
        self.owner_email = owner_email
        self.on_step = on_step      # called with each step as it happens, for showing progress live
        self.greet = greet
        self.max_steps = max_steps
        self.check_replies = check_replies
        # tools only the owner is shown, so a stranger's email never sees them in the prompt (the runtime also refuses them)
        self.tool_specs = [t.spec() for n, t in runtime.tools.items() if n not in owner_tools]
        self.owner_specs = [t.spec() for n, t in runtime.tools.items() if n in owner_tools]

    def handle(self, email: Email) -> Outcome:
        origin, verified = route(email.sender, self.owner_email, email.auth)
        source = f"{'owner' if origin is Origin.OWNER else 'inbox'}:{email.id}"
        self.rt.ctx.add_text(f"{email.subject}\n{email.body}", origin, source)
        req = Request(origin, source, email.sender, verified)
        system = SYSTEM.format(shop=self.shop, today=date.today().isoformat()) + (" " + GREETING if self.greet else "")
        messages = [
            {"role": "system", "content": system + (f"\n\n{self.facts}" if self.facts else "")},
            {"role": "user", "content": f"From: {f'{email.name} <{email.sender}>' if email.name else email.sender}\nSubject: {email.subject}\n\n{email.body}"},
        ]
        steps: list[Step] = []
        specs = self.tool_specs + (self.owner_specs if origin is Origin.OWNER else [])
        for _ in range(self.max_steps):
            msg = self.llm.chat(messages, specs)
            calls = msg.get("tool_calls") or []
            if not calls:
                return self._finish(email, source, (msg.get("content") or "").strip(), steps)
            messages.append(msg)
            for call in calls:
                name = call["function"]["name"]
                args, result = self._run(name, call["function"].get("arguments"), req)
                steps.append(Step(name, args, result["status"], result.get("reasons", []), result.get("error")))
                if self.on_step:
                    self.on_step(email.id, steps[-1])
                messages.append({"role": "tool", "tool_call_id": call["id"],
                                 "content": json.dumps(result, default=str)[:6000]})
        return self._finish(email, source, "", steps, error=f"no reply after {self.max_steps} steps")

    def _finish(self, email: Email, source: str, text: str, steps: list[Step], error: str | None = None) -> Outcome:
        audit = audit_reply(text, self.rt.ledger.for_source(source), email.sender, self.facts)
        return Outcome(email.id, audit.reply if self.check_replies else text, steps, error, audit)

    def _run(self, name: str, raw_args, req: Request):
        try:
            args = json.loads(raw_args or "{}")
        except json.JSONDecodeError:
            return {}, {"status": "error", "error": "the arguments were not valid JSON"}
        if not isinstance(args, dict):
            return {}, {"status": "error", "error": "the arguments must be a JSON object"}
        return args, self.rt.call(name, args, req)

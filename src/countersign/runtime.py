from .guard import Decision, Guard, Reason, Request, Verdict
from .ledger import Ledger
from .provenance import Context, Origin
from .tools import Kind, Tool

_STATUS = {Verdict.ALLOW: "running", Verdict.HOLD: "pending", Verdict.BLOCK: "blocked"}


class Runtime:
    """The only way the agent reaches PayPal."""

    def __init__(self, tools: dict[str, Tool], guard: Guard, ledger: Ledger, ctx: Context | None = None,
                 owner_only=frozenset()):
        self.tools = tools
        self.guard = guard
        self.ledger = ledger
        self.ctx = ctx or Context()
        self.owner_only = frozenset(owner_only)   # tools nobody but the confirmed owner may use, whatever a model asks for

    def call(self, name: str, args: dict, req: Request) -> dict:
        tool = self.tools.get(name)
        if tool is None:
            return {"status": "error", "error": f"there is no tool called {name}"}
        if name in self.owner_only and req.channel is not Origin.OWNER:
            return {"status": "error", "error": "only the shop owner can use this tool"}
        if tool.kind is Kind.READ:
            return self._run_read(tool, args, req)

        decision = self._check(name, args, req)
        amount, key = tool.ledger_fields(args)
        action_id = self.ledger.propose(tool=name, args=args, req=req, decision=decision,
                                        status=_STATUS[decision.verdict], amount=amount, key=key)
        if decision.verdict is Verdict.ALLOW:
            return self._execute(tool, args, action_id)
        label = "held" if decision.verdict is Verdict.HOLD else "blocked"
        return {"status": label, "action_id": action_id, "reasons": decision.as_list()}

    def approve(self, action_id: int) -> dict:
        row = self.ledger.get(action_id)
        if row is None or row["status"] != "pending":
            return {"status": "error", "error": "nothing waiting under that id"}
        req = Request(Origin(row["channel"]), row["source"], row["sender"])
        decision = self._check(row["tool"], row["args"], req)
        if any(r.code == "guard_error" for r in decision.reasons):
            return {"status": "error", "action_id": action_id, "error": "could not re-check this action, try again"}
        if decision.verdict is Verdict.BLOCK:
            self.ledger.set_status(action_id, "blocked", {"reasons": decision.as_list()})
            return {"status": "blocked", "action_id": action_id, "reasons": decision.as_list()}
        self.ledger.set_status(action_id, "running")
        return self._execute(self.tools[row["tool"]], row["args"], action_id)

    def reject(self, action_id: int) -> dict:
        row = self.ledger.get(action_id)
        if row is None or row["status"] != "pending":
            return {"status": "error", "error": "nothing waiting under that id"}
        self.ledger.set_status(action_id, "rejected")
        return {"status": "rejected", "action_id": action_id}

    def preview(self, name: str, args: dict, req: Request, ctx: Context) -> Decision:
        """What the guard would say about this call, with nothing recorded and nothing run."""
        return self._check(name, args, req, ctx)

    def _check(self, name, args, req, ctx: Context | None = None) -> Decision:
        try:
            return self.guard.check(name, args, req, ctx or self.ctx)
        except Exception as e:
            return Decision(Verdict.HOLD, [Reason(
                "guard_error", f"the guard could not check this ({type(e).__name__}: {str(e)[:120]}), so the owner decides")])

    def _run_read(self, tool: Tool, args: dict, req: Request) -> dict:
        try:
            result = tool.run(args, None)
            if tool.redact:
                result = tool.redact(result, req)
        except Exception as e:
            return {"status": "error", "error": str(e)[:300]}
        self.ctx.add_record(result, f"tool:{tool.name}")
        return {"status": "ok", "result": result}

    def _execute(self, tool: Tool, args: dict, action_id: int) -> dict:
        try:
            result = tool.run(args, f"{self.ledger.instance}-{action_id}")
        except Exception as e:
            self.ledger.set_status(action_id, "failed", {"error": str(e)[:300]})
            return {"status": "error", "action_id": action_id, "error": str(e)[:300]}
        self.ledger.set_status(action_id, "executed", result)
        self.ctx.add_record(result, f"tool:{tool.name}")
        return {"status": "executed", "action_id": action_id, "result": result}

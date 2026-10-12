import textwrap

MONEY_LABEL = {"refund_payment": "refund", "send_payout": "payout"}


def format_email(mail, outcome, model: str | None, checked: bool) -> str:
    lines = [f"[{mail.id}] {mail.kind:<6} {mail.subject}"]
    for s in outcome.steps:
        why = f"  {', '.join(r['code'] for r in s.detail)}" if s.detail else ""
        lines.append(f"        {s.tool:<22}{s.status}{why}")
        if s.error:
            lines.append(f"          error: {s.error}")
    lines.append(f"        model: {model}")
    if outcome.error:
        lines.append(f"        ({outcome.error})")
    lines.append("        reply:" + ("" if checked else "  (not checked, as the model wrote it)"))
    for para in outcome.reply.split("\n"):
        lines.append(textwrap.fill(para, 96, initial_indent="        | ", subsequent_indent="        | ")
                     if para.strip() else "        |")
    audit = outcome.audit
    if audit:
        bad = audit.unsupported
        if checked:
            lines.append(f"        check: {len(audit.claims)} money statement(s) replaced by ledger lines "
                         f"({len(bad)} not backed by the ledger), {audit.redacted} address(es) withheld")
        else:
            lines.append(f"        check: {len(bad)} money statement(s) not backed by the ledger, "
                         f"{audit.redacted} address(es) given out")
        for claim in bad:
            lines.append(f"          not backed: {claim.text[:110]}")
        if audit.invented:
            lines.append(f"        shop claims the owner's knowledge does not back: {len(audit.invented)}"
                         + (" (removed)" if checked else " (these went out)"))
            for text in audit.invented:
                lines.append(f"          invented: {text[:110]}")
    return "\n".join(lines) + "\n"


def outcome_to_dict(mail, outcome, model: str | None) -> dict:
    audit = outcome.audit
    return {
        "id": mail.id, "kind": mail.kind, "subject": mail.subject, "model": model, "reply": outcome.reply,
        "error": outcome.error,
        "steps": [{"tool": s.tool, "args": s.args, "status": s.status,
                   "reasons": [r["code"] for r in s.detail], "error": s.error} for s in outcome.steps],
        "claims": [{"text": c.text, "supported": c.supported} for c in audit.claims] if audit else [],
        "redacted": audit.redacted if audit else 0,
        "invented": audit.invented if audit else [],
    }


def unavailable_entry(mail, reason: str) -> dict:
    return {"id": mail.id, "kind": mail.kind, "subject": mail.subject, "model": None, "reply": "", "error": reason,
            "steps": [], "claims": [], "redacted": 0, "unavailable": True}


def what_happened(entry: dict) -> str:
    if entry.get("unavailable"):
        return "NOT RUN (model unavailable)"
    parts = []
    for s in entry["steps"]:
        if s["tool"] in MONEY_LABEL:
            amount = s["args"].get("amount", "?")
            parts.append(f"{MONEY_LABEL[s['tool']]} {amount} {s['status']}")
    return ", ".join(parts) if parts else "no money moved"

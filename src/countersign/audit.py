"""Replies are checked against the ledger before they go out.

A model can say a refund went through when it did not, or repeat what a stranger planted in an
order note. The model keeps its tone: every sentence that states a money outcome is dropped, and
one plain line per action is added from the ledger instead. Other people's email addresses are
withheld. Matching is by sentence patterns, so it is a heuristic that errs on the side of dropping.
"""
import re
from dataclasses import dataclass, field
from decimal import Decimal

from . import emails

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_MONEY = re.compile(
    r"\$\s?[0-9]|\b(?:refund\w*|payment|payout|funds|money|reimburs\w*|credit(?:ed)?|transfer\w*|remit\w*|amount)\b", re.I)
_DONE = re.compile(
    r"\b(?:processed|issued|sent|refunded|credited|transferred|initiated|submitted|released|approved|disbursed|"
    r"paid|settled|completed|returned|on its way|on the way|"
    r"(?:will|should|shall|can|may)\s+(?:soon\s+)?(?:see|receive|get|appear|arrive|"
    r"be\s+(?:credited|returned|refunded|sent|issued|processed|paid)))\b",
    re.I)
_PENDING = re.compile(
    r"\b(?:owner|review(?:ed|ing)?|approval|pending|on hold|held|awaiting|forwarded|escalat\w*)\b", re.I)
# what the owner will do with a request is a claim even when no money word is in the sentence
_PROCESS = re.compile(
    r"\bowner\b[^.]*\b(?:approv\w*|review\w*)\b|\b(?:approv\w*|review\w*)\b[^.]*\bowner\b|\bforwarded\b|\bescalat\w+", re.I)
_RECORD = re.compile(r"\b(?:already|marked|on file|in our (?:system|records)|according to our)\b", re.I)
_FIRST = re.compile(
    r"\b(?:I|we)(?:'ve|'ll|\s+have|\s+had|\s+will)?\s+(?:(?:just|now|already|successfully)\s+)*"
    r"(?:processed|issued|sent|refunded|credited|transferred|initiated|submitted|released|approved|paid)\b", re.I)
_MORE = re.compile(r"\b(?:additional|extra|further|more|remaining|balance|difference)\b", re.I)
_AMOUNT = re.compile(r"\$\s?([0-9][0-9,]*(?:\.[0-9]{1,2})?)")
_SIGNOFF = re.compile(
    r"^\s*(?:best regards|kind regards|warm regards|regards|sincerely|best wishes|thanks|thank you|best|cheers)\b", re.I)

_NOTHING_DONE = "No refund or payment has been made on this request."
_CONFIRM = "The owner will confirm those details and reply."

# promises about the shop itself: which days, how long, where to. They must come from the shop's own knowledge.
_WEEKDAY = re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?\b", re.I)
_SPAN = re.compile(r"\b(\d+)(?:\s*(?:-|to)\s*(\d+))?\s*(?:business\s+|working\s+)?(day|week|hour|month)s?\b", re.I)
_PLACE = re.compile(r"\b(canada|international(?:ly)?|worldwide|europe|overseas|united kingdom|australia)\b", re.I)
_TOPICS = (("roast", re.compile(r"\broast", re.I)), ("ship", re.compile(r"\b(?:ship|deliver|dispatch|arriv)", re.I)),
           ("hours", re.compile(r"\b(?:open|hours|support|reply|respond)", re.I)))


@dataclass(frozen=True)
class Claim:
    text: str
    supported: bool


@dataclass
class Audit:
    raw: str
    reply: str
    claims: list[Claim] = field(default_factory=list)
    redacted: int = 0
    invented: list[str] = field(default_factory=list)   # statements about the shop that its knowledge does not back

    @property
    def unsupported(self) -> list[Claim]:
        return [c for c in self.claims if not c.supported]


def _dec(text) -> Decimal:
    return Decimal(str(text).replace(",", "")).quantize(Decimal("0.01"))


def _is_signoff(paragraph: str) -> bool:
    if len(paragraph) < 120 and _SIGNOFF.match(paragraph):
        return True
    return len(paragraph) < 100 and paragraph.count("\n") <= 2 and not re.search(r"[.!?]\s*$", paragraph)


def _is_claim(sentence: str, has_actions: bool) -> bool:
    if _PROCESS.search(sentence):
        return True
    if not _MONEY.search(sentence) or not (_DONE.search(sentence) or _PENDING.search(sentence)):
        return False
    # "invoice 20431 is already marked as paid in our system" states a record, not something just done
    if not has_actions and _RECORD.search(sentence) and not _FIRST.search(sentence) and not _MORE.search(sentence):
        return False
    return True


def _supported(sentence: str, actions: list[dict]) -> bool:
    executed = [a for a in actions if a["status"] == "executed"]
    if _PENDING.search(sentence):
        return any(a["status"] == "pending" for a in actions)
    if not executed:
        return False
    paid = {_dec(a["amount"]) for a in executed if a["amount"]}
    mentioned = {_dec(m) for m in _AMOUNT.findall(sentence)}
    if mentioned and not mentioned <= paid:
        return False
    return not (_MORE.search(sentence) and len(executed) < 2)


def status_lines(actions: list[dict]) -> list[str]:
    lines = []
    for a in actions:
        refund = a["tool"] == "refund_payment"
        what = "refund" if refund else "payment"
        amount = a["amount"]
        if a["status"] == "executed":
            if refund:
                line = f"A refund of ${amount} has been issued to your original payment method."
            else:
                invoice = a["args"].get("invoice_id")
                line = f"The payment of ${amount}" + (f" for invoice {invoice}" if invoice else "") + " has been sent."
        elif a["status"] == "pending":
            line = f"This {what} is with the owner for review, and we will follow up."
        elif a["status"] == "blocked":
            line = f"We were not able to process that {what}."
        elif a["status"] == "failed":
            line = f"We ran into a technical problem with that {what} and will follow up."
        elif a["status"] == "rejected":
            line = f"The owner decided not to go ahead with that {what}."
        else:
            continue
        if line not in lines:
            lines.append(line)
    return lines


_LOOKALIKES = {ord(c): "-" for c in "‐‑‒−"} | {ord(c): None for c in "​‌‍⁠﻿"}


def addresses_in(text: str, sender: str | None) -> list[str]:
    """Email addresses in a reply other than the one it is going to."""
    return [a for a in emails.FIND.findall(text.translate(_LOOKALIKES)) if not (sender and a.lower() == sender.lower())]


def _backed_by(sentence: str, knowledge: str) -> bool:
    """False if the sentence promises something about the shop (a day, a length of time, a country) that no
    line of the shop's knowledge says about the same subject."""
    lines = [l.lower() for l in re.split(r"[\n.]+", knowledge) if l.strip()]
    topics = [stem for stem, rx in _TOPICS if rx.search(sentence)]
    pool = [l for l in lines if any(rx.search(l) for stem, rx in _TOPICS if stem in topics)] or lines

    def said(token: str) -> bool:
        return any(re.search(rf"\b{re.escape(token)}", l) for l in pool)

    for day in _WEEKDAY.findall(sentence):
        if not said(day.lower()):
            return False
    for low, high, unit in _SPAN.findall(sentence):
        if not (said(low) and (not high or said(high)) and said(unit.lower())):
            return False
    return all(said(p.lower()) for p in _PLACE.findall(sentence))


def audit_reply(raw: str, actions: list[dict], sender: str | None, knowledge: str = "") -> Audit:
    # a model can write an address with a non-breaking hyphen or zero-width characters, which no pattern would match
    raw = raw.translate(_LOOKALIKES)
    has_actions = bool(actions)
    paragraphs, claims, invented = [], [], []
    for para in (re.split(r"\n\s*\n", raw.strip()) if raw.strip() else []):
        kept = []
        for sentence in _SENTENCE.split(para):
            if _is_claim(sentence, has_actions):
                claims.append(Claim(sentence.strip(), _supported(sentence, actions)))
            elif knowledge and not _backed_by(sentence, knowledge):
                invented.append(sentence.strip())
            else:
                kept.append(sentence.strip())
        text = " ".join(s for s in kept if s)
        if text:
            paragraphs.append(text)

    status = status_lines(actions)
    if claims and not has_actions:
        status = [_NOTHING_DONE]
    if invented:
        status.append(_CONFIRM)
    if status:
        block = " ".join(status)
        if paragraphs and _is_signoff(paragraphs[-1]):
            paragraphs.insert(len(paragraphs) - 1, block)
        else:
            paragraphs.append(block)

    redacted = 0

    def hide(match):
        nonlocal redacted
        if sender and match.group(0).lower() == sender.lower():
            return match.group(0)
        redacted += 1
        return "[address withheld]"

    reply = emails.FIND.sub(hide, "\n\n".join(paragraphs))
    return Audit(raw, reply, claims, redacted, invented)

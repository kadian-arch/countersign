"""Where each value the agent has seen came from.

Origins are assigned by the runtime from the channel a piece of text arrived on,
never by the model, so text cannot claim a higher origin than its channel has.
"""
import re
from enum import IntEnum

from .money import parse_amount


class Origin(IntEnum):
    UNTRUSTED = 0
    SYSTEM = 1  # PayPal responses and the shop's own records
    OWNER = 2


# Fields in PayPal responses that carry facts. Everything else in a record is free
# text somebody typed (names, notes, memos, messages) and counts as untrusted.
TRUSTED_KEYS = frozenset({
    "id", "capture_id", "order_id", "invoice_id", "transaction_id", "dispute_id",
    "payout_batch_id", "batch_status", "status", "dispute_state", "reason",
    "value", "currency_code", "email_address", "payer_id", "custom_id",
    "create_time", "update_time", "order_no", "customer_email", "supplier_email",
})

_EMAIL = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}", re.ASCII
)
_MONEY = re.compile(r"(?<![0-9.])[0-9]{1,7}(?:\.[0-9]{1,2})?(?![0-9])", re.ASCII)
_ID = re.compile(r"\b(?=[A-Z0-9]*[0-9])[A-Z0-9]{10,30}\b", re.ASCII)
_THOUSANDS = re.compile(r"(?<=[0-9]),(?=[0-9]{3})")


def key(value) -> str:
    s = str(value).strip()
    if "@" in s:
        return s.lower()
    try:
        return str(parse_amount(s))
    except ValueError:
        return s


class Context:
    def __init__(self):
        self._seen: dict[str, dict[str, Origin]] = {}
        self._text: dict[str, str] = {}

    def _note(self, k: str, origin: Origin, source: str):
        by_source = self._seen.setdefault(k, {})
        by_source[source] = max(origin, by_source.get(source, origin))

    def add_value(self, value, origin: Origin, source: str):
        if value is not None and not isinstance(value, bool):
            self._note(key(value), origin, source)

    def text_of(self, source: str) -> str:
        """Everything recorded as written in this one message, as written."""
        return self._text.get(source, "")

    def add_text(self, text: str, origin: Origin, source: str):
        self._text[source] = f"{self._text.get(source, '')}\n{text}".strip()
        text = _THOUSANDS.sub("", text)
        for pattern in (_EMAIL, _MONEY, _ID):
            for found in pattern.findall(text):
                self._note(key(found), origin, source)

    def add_record(self, record, source: str):
        if isinstance(record, dict):
            for k, v in record.items():
                if isinstance(v, (dict, list)):
                    self.add_record(v, source)
                elif k in TRUSTED_KEYS:
                    self.add_value(v, Origin.SYSTEM, source)
                elif isinstance(v, str):
                    self.add_text(v, Origin.UNTRUSTED, source)
        elif isinstance(record, list):
            for v in record:
                self.add_record(v, source)

    def sources(self, value) -> dict[str, Origin]:
        return dict(self._seen.get(key(value), {}))

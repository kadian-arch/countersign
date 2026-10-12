import re
from decimal import Decimal

CENT = Decimal("0.01")
_PLAIN = re.compile(r"[0-9]{1,7}(\.[0-9]{1,2})?", re.ASCII)


def parse_amount(raw) -> Decimal:
    s = str(raw).strip()
    if not _PLAIN.fullmatch(s):
        raise ValueError(f"not a valid amount: {s[:20]!r}")
    d = Decimal(s).quantize(CENT)
    if d <= 0:
        raise ValueError("amount must be above zero")
    return d


def fmt(d: Decimal) -> str:
    return f"{d:.2f}"

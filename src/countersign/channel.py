"""Which channel a message arrived on, decided from the mail server's own verdict on the sender.

A From line is just text anyone can write. The receiving mail server checks it (SPF, DKIM, DMARC) and
records the result in an Authentication-Results header. Only a message that passes is trusted to be
from the address it claims, and only then can it be the owner. A message that fails is a stranger's,
and anything it asks for is held for the owner.
"""
import re

from . import emails
from .provenance import Origin

PASSING = "dmarc=pass; spf=pass; dkim=pass"
FAILING = "dmarc=fail; spf=softfail; dkim=none"
_RESULT = re.compile(r"\b(spf|dkim|dmarc)\s*=\s*([a-z]+)", re.I)


def authenticated(header: str | None) -> bool:
    """True when the header shows DMARC passing, or both SPF and DKIM passing, and nothing failing."""
    if not header:
        return False
    found: dict[str, list[str]] = {}
    for mechanism, result in _RESULT.findall(header):
        found.setdefault(mechanism.lower(), []).append(result.lower())
    if any(r != "pass" for results in found.values() for r in results if r in ("fail", "softfail", "permerror")):
        return False
    if "pass" in found.get("dmarc", []):
        return True
    return "pass" in found.get("spf", []) and "pass" in found.get("dkim", [])


def route(sender: str | None, owner_email: str, header: str | None) -> tuple[Origin, bool]:
    """The channel a message belongs to, and whether its sender checked out."""
    verified = authenticated(header)
    if verified and emails.same_person(sender, owner_email):
        return Origin.OWNER, True
    return Origin.UNTRUSTED, verified

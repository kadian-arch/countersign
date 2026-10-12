import re

_EMAIL = re.compile(
    r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}", re.ASCII
)

FIND = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}", re.ASCII)


def is_email(s: str) -> bool:
    return bool(_EMAIL.fullmatch(s))


def canon(email: str) -> str:
    """Same mailbox written differently: case, dots and +tags in the local part."""
    local, _, domain = email.strip().lower().partition("@")
    local = local.split("+", 1)[0].replace(".", "")
    if domain == "googlemail.com":
        domain = "gmail.com"
    return f"{local}@{domain}"


def same_person(a: str | None, b: str | None) -> bool:
    return bool(a and b) and a.strip().lower() == b.strip().lower()


def distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def lookalike(candidate: str, known: set[str]) -> str | None:
    """A known address this one is suspiciously close to, if any."""
    c = candidate.strip().lower()
    for k in sorted(known):
        kl = k.lower()
        if kl == c:
            continue
        if canon(kl) == canon(c) or distance(kl, c) <= 2:
            return k
    return None

"""Small repairs to the words a model writes, before they are sent as an email.

Some models put odd spacing characters between words (narrow no-break spaces and the like), which a mail client shows as
nothing or as a gap, and now and then a lone ellipsis where a word should be. None of it changes what was said.
"""
import re
import unicodedata

_LONE_ELLIPSIS = re.compile(r"(?<=\s)(?:…|\.{3})(?=\s)")


def reply(text: str) -> str:
    text = "".join(" " if unicodedata.category(c) == "Zs" else c for c in text)   # every kind of space becomes a plain one
    text = _LONE_ELLIPSIS.sub("", text)
    return "\n".join(re.sub(r" {2,}", " ", line).rstrip() for line in text.split("\n"))

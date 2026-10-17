"""Repairs to the words a model writes, before they are sent as an email.

Models leave all sorts of small damage in text: odd spacing characters, invisible characters inside words, markdown a mail
client will not render, stray punctuation, a word said twice, now and then a line that is not language at all. None of it
changes what was meant, so it is cleaned by general rules and not by looking for any one case. The steps run in order and
the result is the same if it is cleaned again.
"""
import html
import re
import unicodedata

_FALLBACK = "Thanks for your message. The owner will follow up shortly."

_FENCE = re.compile(r"`{3}[^\n]*\n?|`{1,2}")
_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", re.S)
_LINK = re.compile(r"\[([^\]\n]+)\]\((?:https?://|mailto:)[^)\s]*\)")
_HEADING = re.compile(r"(?m)^\s{0,3}#{1,6}\s+")
_BULLET = re.compile(r"(?m)^[ \t]*[*•●▪–—][ \t]+")
_LONE_ELLIPSIS = re.compile(r"(?:(?<=\s)|^)(?:…|\.{3,})(?=\s|$)")
_LEADING_ELLIPSIS = re.compile(r"(?m)^(?:…|\.{3,})\s*(?=\w)")
_REPEATED_PUNCT = re.compile(r"([,;:!?])(?:\s*\1)+")
_SPACE_BEFORE = re.compile(r"[ \t]+([,;:!?])")
_NO_SPACE_AFTER = re.compile(r"([,;!?])(?=[A-Za-z])")
_DOUBLE_WORD = re.compile(r"\b([A-Za-z]{2,})(?:[ \t]+\1\b)+", re.I)
_URLISH = re.compile(r"https?://\S+|\S+@\S+")
_SYMBOL_RUN = re.compile(r"(?<!\S)[^\w\s`*_#.…-]{6,}(?!\S)|(?<!\S)[-=~_]{6,}(?!\S)")   # a token of nothing but symbols, or a row of dashes


def _characters(text: str) -> str:
    out = []
    for c in unicodedata.normalize("NFC", text):
        cat = unicodedata.category(c)
        if c in "\n\t":
            out.append(c)
        elif cat in ("Zs", "Zl", "Zp") or c == "\r":
            out.append(" " if c != "\r" else "")
        elif cat in ("Cc", "Cf", "Cs", "Co", "Cn"):
            continue   # control, invisible, private and unassigned characters carry no words
        else:
            out.append(c)
    return "".join(out)


def _is_language(line: str) -> bool:
    """False for a line that is mostly symbols or holds one enormous unbroken token, which no one wrote on purpose."""
    s = _URLISH.sub("", line).strip()
    if len(s) < 24:
        return True
    letters = sum(1 for c in s if c.isalpha())
    longest = max((len(w) for w in s.split()), default=0)
    return letters / len(s) >= 0.3 and longest <= 40


def reply(text: str) -> str:
    original_letters = sum(1 for c in text if c.isalpha())
    text = _characters(html.unescape(text))
    text = _SYMBOL_RUN.sub("", text)
    text = _FENCE.sub("", text)
    text = _LINK.sub(r"\1", text)
    text = _BOLD.sub(r"\2", text)
    text = _HEADING.sub("", text)
    text = _BULLET.sub("- ", text)
    text = re.sub(r"\s*[—―]\s*", " - ", text)
    text = _LEADING_ELLIPSIS.sub("", text)
    text = _LONE_ELLIPSIS.sub("", text)
    text = _REPEATED_PUNCT.sub(r"\1", text)
    text = _SPACE_BEFORE.sub(r"\1", text)
    text = _NO_SPACE_AFTER.sub(r"\1 ", text)
    text = _DOUBLE_WORD.sub(r"\1", text)
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"[ \t]{2,}", " ", line).strip()
        if line and not _is_language(line):
            continue
        lines.append(line)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if original_letters and sum(1 for c in text if c.isalpha()) < original_letters * 0.15:
        return _FALLBACK   # almost nothing readable was left, so it is better to say so than to send what remains
    return text

"""The shop's real mailbox: reads new mail over IMAP, sends the assistant's replies over SMTP.

The sender's identity is not taken from the From line. It comes from the Authentication-Results header the
receiving mail server wrote, and only the topmost one counts, because that is the server's own. Anything a
sender put into the message lower down is ignored. Mail from robots is skipped, and a reply goes only to a
sender the server could confirm, so a forged From line never gets mail back.
"""
import html
import imaplib
import re
import smtplib
import threading
import time
from dataclasses import dataclass
from datetime import date, timedelta
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

from .channel import authenticated

MAX_PER_CYCLE = 10
REPLIES_PER_SENDER_PER_HOUR = 3
ROBOTS = ("mailer-daemon", "postmaster", "noreply", "no-reply", "donotreply", "do-not-reply")


@dataclass(frozen=True)
class Settings:
    user: str
    password: str
    imap_host: str = "imap.gmail.com"
    smtp_host: str = "smtp.gmail.com"
    authserv: str = "mx.google.com"   # who wrote the Authentication-Results we trust ("" trusts the topmost one)
    poll: int = 20

    @classmethod
    def from_env(cls, env) -> "Settings | None":
        user, password = env.get("MAIL_USER", "").strip(), env.get("MAIL_PASSWORD", "").replace(" ", "")
        if not user or not password:
            return None
        imap = env.get("MAIL_IMAP_HOST", "imap.gmail.com").strip()
        default_authserv = "mx.google.com" if imap.endswith("gmail.com") else ""
        return cls(user, password, imap, env.get("MAIL_SMTP_HOST", "smtp.gmail.com").strip(),
                   env.get("MAIL_AUTHSERV", default_authserv).strip().lower(), max(5, int(env.get("MAIL_POLL_SECONDS", "20") or 20)))


@dataclass(frozen=True)
class Incoming:
    sender: str
    subject: str
    body: str
    auth: str          # the receiving server's verdict, empty when it cannot be trusted
    message_id: str
    references: str
    name: str = ""     # the name on the From line, only if it looks like a name


_NAME = re.compile(r"[^\W\d_][\w'.-]{0,19}(?: [^\W\d_][\w'.-]{0,19}){0,3}")


def clean_name(name: str) -> str:
    """The From line's display name is the sender's own claim, so it is only used for a greeting and only if it is a few plain words."""
    name = " ".join(name.split())
    return name if _NAME.fullmatch(name) else ""


def _text(msg) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    text = part.get_content()
    if part.get_content_type() == "text/html":
        text = html.unescape(re.sub(r"(?s)<(script|style).*?</\1>|<[^>]+>", " ", text))
    return re.sub(r"[ \t]+", " ", text).strip()


def _automated(msg, sender: str, own: str) -> bool:
    local = sender.split("@")[0].lower()
    return (sender.lower() == own.lower() or any(local.startswith(r) for r in ROBOTS)
            or str(msg.get("Auto-Submitted", "no")).strip().lower() != "no"
            or str(msg.get("Precedence", "")).strip().lower() in ("bulk", "junk", "list")
            or msg.get("List-Id") is not None or msg.get("X-Autoreply") is not None)


def parse(raw: bytes, settings: Settings) -> Incoming | None:
    """A message as the shop's assistant should see it, or None for mail that no one should answer."""
    msg = message_from_bytes(raw, policy=policy.default)
    name, sender = parseaddr(str(msg.get("From", "")))
    if "@" not in sender or _automated(msg, sender, settings.user):
        return None
    headers = msg.get_all("Authentication-Results") or []
    auth = " ".join(str(headers[0]).split()) if headers else ""
    if auth and settings.authserv and auth.split(";")[0].strip().lower() != settings.authserv:
        auth = ""
    return Incoming(sender, str(msg.get("Subject", "")).strip(), _text(msg), auth,
                    str(msg.get("Message-ID", "")).strip(), str(msg.get("References", "")).strip(), clean_name(name))


def compose_reply(settings: Settings, shop_name: str, incoming: Incoming, text: str) -> EmailMessage:
    reply = EmailMessage()
    reply["From"] = formataddr((shop_name, settings.user))
    reply["To"] = incoming.sender
    subject = incoming.subject or "your message"
    reply["Subject"] = subject if subject.lower().startswith("re:") else "Re: " + subject
    if incoming.message_id:
        reply["In-Reply-To"] = incoming.message_id
        reply["References"] = (incoming.references + " " + incoming.message_id).strip()
    reply["Auto-Submitted"] = "auto-replied"
    reply.set_content(text)
    return reply


class Mailbox:
    """Polls the inbox, hands each new message to `take`, and sends replies."""

    def __init__(self, settings: Settings, take, shop_name=lambda: "Shop"):
        self.settings, self.take, self.shop_name = settings, take, shop_name
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.checked: float | None = None
        self.error: str | None = None
        self.sent: dict[str, list[float]] = {}
        self.seen_ids: set[str] = set()
        self.last_alert: dict | None = None   # when the owner was last emailed, and whether it worked

    def public(self) -> dict:
        return {"address": self.settings.user, "ok": self.error is None and self.checked is not None,
                "checked": self.checked, "error": self.error, "alert": self.last_alert}

    def start(self):
        self.thread = threading.Thread(target=self._loop, daemon=True, name="mailbox")
        self.thread.start()

    def _loop(self):
        while True:
            self.cycle()
            if self.stop.wait(self.settings.poll):
                return

    def cycle(self):
        s = self.settings
        try:
            with imaplib.IMAP4_SSL(s.imap_host) as box:
                box.login(s.user, s.password)
                box.select("INBOX")
                since = (date.today() - timedelta(days=2)).strftime("%d-%b-%Y")
                _, data = box.uid("SEARCH", None, "UNSEEN", "SINCE", since)
                for uid in (data[0].split() if data and data[0] else [])[:MAX_PER_CYCLE]:
                    _, parts = box.uid("FETCH", uid, "(BODY.PEEK[])")
                    raw = next((p[1] for p in parts if isinstance(p, tuple)), b"")
                    try:
                        incoming = parse(raw, s)
                        if incoming is not None and incoming.message_id not in self.seen_ids:
                            if not self.take(incoming):
                                break   # the shop is busy, leave it unread and come back
                            if incoming.message_id:
                                self.seen_ids.add(incoming.message_id)
                    except Exception as e:   # one bad message must not stop the rest
                        self.error = f"skipped a message: {str(e)[:80]}"
                    box.uid("STORE", uid, "+FLAGS", "\\Seen")
            self.error, self.checked = None, time.time()
        except Exception as e:
            self.error, self.checked = f"{type(e).__name__}: {str(e)[:100]}", time.time()

    def reply(self, incoming: Incoming, text: str):
        """Sends the answer. Only to a sender the mail server confirmed, and not more than a few times an hour."""
        if not authenticated(incoming.auth):
            raise PermissionError("the sender could not be confirmed, so no reply was sent")
        now = time.time()
        recent = [t for t in self.sent.get(incoming.sender.lower(), []) if now - t < 3600]
        if len(recent) >= REPLIES_PER_SENDER_PER_HOUR:
            raise PermissionError("too many replies to this sender this hour")
        self.sent[incoming.sender.lower()] = recent + [now]
        self._send(compose_reply(self.settings, self.shop_name(), incoming, text))

    def send_alert(self, to: str, subject: str, text: str, html: str | None = None):
        """A message from the shop to its owner, not an answer to anyone. Plain text, and HTML beside it when there is some."""
        mail = EmailMessage()
        mail["From"], mail["To"], mail["Subject"] = formataddr((self.shop_name(), self.settings.user)), to, subject
        mail["Auto-Submitted"] = "auto-generated"
        mail.set_content(text)
        if html:
            mail.add_alternative(html, subtype="html")
        self._send(mail)

    def _send(self, message: EmailMessage):
        s = self.settings
        with smtplib.SMTP_SSL(s.smtp_host, 465, timeout=30) as smtp:
            smtp.login(s.user, s.password)
            smtp.send_message(message)

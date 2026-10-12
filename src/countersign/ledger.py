import hashlib
import hmac
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal

GENESIS = "0" * 64

_SCHEMA = """
create table if not exists actions (
    id integer primary key autoincrement,
    ts text not null,
    tool text not null,
    args text not null,
    amount text,
    key text,
    channel integer not null,
    source text not null,
    sender text,
    verdict text not null,
    reasons text not null,
    status text not null,
    result text
);
create table if not exists meta (
    k text primary key,
    v text not null
);
create table if not exists events (
    id integer primary key autoincrement,
    ts text not null,
    action_id integer not null,
    kind text not null,
    body text not null,
    prev text not null,
    hash text not null
);
"""


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


class Ledger:
    """Every money-moving proposal, what the guard said, and what happened.

    Each change is also written to an append-only history where every entry carries a
    hash of the one before it, so an edited, removed or reordered entry shows up in
    verify(). With LEDGER_KEY set the hashes are keyed, so rewriting the whole chain
    needs the key too. Publishing head() somewhere outside the database anchors it
    against the whole file being replaced.
    """

    def __init__(self, path: str = ":memory:", key: str | None = None):
        self._key = (key if key is not None else os.environ.get("LEDGER_KEY", "")).encode()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(_SCHEMA)
            row = self._db.execute("select v from meta where k='instance'").fetchone()
            if row is None:
                self._db.execute("insert into meta values ('instance', ?)", (uuid.uuid4().hex[:8],))
                row = self._db.execute("select v from meta where k='instance'").fetchone()
            self.instance = row["v"]
            self._db.commit()

    def close(self):
        with self._lock:
            self._db.close()

    def _seal(self, prev, ts, action_id, kind, body) -> str:
        msg = f"{prev}|{ts}|{action_id}|{kind}|{body}".encode()
        if self._key:
            return hmac.new(self._key, msg, hashlib.sha256).hexdigest()
        return hashlib.sha256(msg).hexdigest()

    def _log(self, action_id: int, kind: str, body: dict):
        row = self._db.execute("select hash from events order by id desc limit 1").fetchone()
        prev = row["hash"] if row else GENESIS
        ts = datetime.now(timezone.utc).isoformat()
        text = _canon(body)
        self._db.execute(
            "insert into events (ts, action_id, kind, body, prev, hash) values (?,?,?,?,?,?)",
            (ts, action_id, kind, text, prev, self._seal(prev, ts, action_id, kind, text)),
        )

    def propose(self, *, tool, args, req, decision, status, amount: Decimal | None, key: str | None) -> int:
        fields = {
            "tool": tool, "args": args, "amount": None if amount is None else str(amount), "key": key,
            "channel": int(req.channel), "source": req.source, "sender": req.sender,
            "verdict": decision.verdict.value, "reasons": decision.as_list(), "status": status,
        }
        with self._lock:
            cur = self._db.execute(
                "insert into actions (ts, tool, args, amount, key, channel, source, sender, verdict, reasons, status)"
                " values (?,?,?,?,?,?,?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(), tool, json.dumps(args), fields["amount"], key,
                 fields["channel"], req.source, req.sender, fields["verdict"], json.dumps(fields["reasons"]), status),
            )
            self._log(cur.lastrowid, "proposed", fields)
            self._db.commit()
            return cur.lastrowid

    def set_status(self, action_id: int, status: str, result: dict | None = None):
        with self._lock:
            self._db.execute(
                "update actions set status=?, result=coalesce(?, result) where id=?",
                (status, None if result is None else json.dumps(result), action_id),
            )
            self._log(action_id, "status", {"status": status, "result": result})
            self._db.commit()

    def clear(self):
        """Starts the history over. Ids keep counting, so a PayPal request id is never used twice."""
        with self._lock:
            self._db.execute("delete from actions")
            self._db.execute("delete from events")
            self._db.commit()

    def get(self, action_id: int) -> dict | None:
        with self._lock:
            row = self._db.execute("select * from actions where id=?", (action_id,)).fetchone()
        return _decode(row) if row else None

    def pending(self) -> list[dict]:
        return self._rows("select * from actions where status='pending' order by id")

    def for_source(self, source: str) -> list[dict]:
        return self._rows("select * from actions where source=? order by id", (source,))

    def recent(self, limit: int = 50) -> list[dict]:
        return self._rows("select * from actions order by id desc limit ?", (limit,))

    def total_today(self, tool: str, key: str | None = None, today: str | None = None) -> Decimal:
        day = today or datetime.now(timezone.utc).date().isoformat()
        sql = "select amount from actions where tool=? and status='executed' and substr(ts,1,10)=?"
        params = [tool, day]
        if key is not None:
            sql += " and key=?"
            params.append(key)
        with self._lock:
            rows = self._db.execute(sql, params).fetchall()
        return sum((Decimal(r["amount"]) for r in rows if r["amount"]), Decimal("0"))

    def head(self) -> dict:
        with self._lock:
            row = self._db.execute("select hash from events order by id desc limit 1").fetchone()
            n = self._db.execute("select count(*) from events").fetchone()[0]
        return {"events": n, "head": row["hash"] if row else GENESIS}

    def verify(self) -> list[str]:
        """Empty list when the history is intact and the actions table matches it."""
        with self._lock:
            events = self._db.execute("select * from events order by id").fetchall()
            actions = {r["id"]: _decode(r) for r in self._db.execute("select * from actions")}
        problems, prev, replay = [], GENESIS, {}
        for e in events:
            if e["prev"] != prev:
                problems.append(f"event {e['id']} does not follow the event before it, something was removed or reordered")
            if self._seal(e["prev"], e["ts"], e["action_id"], e["kind"], e["body"]) != e["hash"]:
                problems.append(f"event {e['id']} was changed after it was written")
            prev = e["hash"]
            body = json.loads(e["body"])
            if e["kind"] == "proposed":
                replay[e["action_id"]] = {**body, "result": None}
            elif e["action_id"] in replay:
                replay[e["action_id"]]["status"] = body["status"]
                if body["result"] is not None:
                    replay[e["action_id"]]["result"] = body["result"]
        for action_id, want in replay.items():
            have = actions.get(action_id)
            if have is None:
                problems.append(f"action {action_id} is in the history but missing from the table")
            elif {k: have[k] for k in want} != want:
                problems.append(f"action {action_id} no longer matches its history")
        for action_id in sorted(set(actions) - set(replay)):
            problems.append(f"action {action_id} has no history")
        return problems

    def _rows(self, sql, params=()):
        with self._lock:
            rows = self._db.execute(sql, params).fetchall()
        return [_decode(r) for r in rows]


def _decode(row) -> dict:
    d = dict(row)
    d["args"] = json.loads(d["args"])
    d["reasons"] = json.loads(d["reasons"])
    d["result"] = json.loads(d["result"]) if d["result"] else None
    return d

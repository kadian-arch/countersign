"""The shop's own records: customer orders and supplier invoices.
Stands in for the store software a real merchant would already have next to PayPal."""
import sqlite3
import threading
from datetime import datetime, timezone
from decimal import Decimal

from .guard import InvoiceFacts

_SCHEMA = """
create table if not exists orders (
    order_no text primary key,
    customer_name text not null,
    customer_email text not null,
    items text not null,
    total text not null,
    paypal_order_id text,
    capture_id text unique,
    carrier text,
    tracking_no text,
    delivered integer not null default 0,
    customer_note text not null default ''
);
create table if not exists line_items (
    order_no text not null,
    description text not null,
    quantity integer not null,
    unit_price text not null
);
create table if not exists suppliers (
    email text primary key,
    name text not null,
    contacts text not null default ''
);
create table if not exists supplier_invoices (
    invoice_id text primary key,
    supplier_email text not null,
    description text not null,
    amount text not null,
    due text not null,
    paid_ref text,
    paid_amount text not null default '0'
);
create table if not exists settings (
    key text primary key,
    value text not null
);
create table if not exists paypal_events (
    event_id text primary key,
    kind text not null,
    summary text not null,
    amount text,
    origin text not null default '',
    at text not null,
    day text not null
);
"""

# columns added after the first release, so an older database file still opens
_MIGRATIONS = [
    ("orders", "customer_note", "text not null default ''"),
    ("suppliers", "contacts", "text not null default ''"),
    ("supplier_invoices", "paid_amount", "text not null default '0'"),
]


class Store:
    def __init__(self, path: str = ":memory:"):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(_SCHEMA)
            for table, column, spec in _MIGRATIONS:
                cols = {r["name"] for r in self._db.execute(f"pragma table_info({table})")}
                if column not in cols:
                    self._db.execute(f"alter table {table} add column {column} {spec}")
            self._db.commit()

    def _exec(self, sql, params=()):
        with self._lock:
            cur = self._db.execute(sql, params)
            self._db.commit()
            return cur

    def _all(self, sql, params=()):
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    def add_order(self, order_no, customer_name, customer_email, lines, total: Decimal, note: str = ""):
        summary = "; ".join(f"{q} x {d}" for d, q, _ in lines)
        self._exec("insert or replace into orders (order_no, customer_name, customer_email, items, total, customer_note)"
                   " values (?,?,?,?,?,?)", (order_no, customer_name, customer_email, summary, str(total), note))
        self._exec("delete from line_items where order_no=?", (order_no,))
        for description, qty, price in lines:
            self._exec("insert into line_items values (?,?,?,?)", (order_no, description, qty, str(price)))

    def delete_order(self, order_no):
        self._exec("delete from line_items where order_no=?", (order_no,))
        self._exec("delete from orders where order_no=?", (order_no,))

    def set_payment(self, order_no, paypal_order_id, capture_id):
        self._exec("update orders set paypal_order_id=?, capture_id=? where order_no=?",
                   (paypal_order_id, capture_id, order_no))

    def orders(self) -> list[dict]:
        return [dict(r) for r in self._all("select * from orders order by order_no")]

    def get_order(self, order_no) -> dict | None:
        rows = self._all("select * from orders where order_no=?", (order_no,))
        return dict(rows[0]) if rows else None

    def order_by_capture(self, capture_id) -> dict | None:
        rows = self._all("select * from orders where capture_id=?", (capture_id,))
        return dict(rows[0]) if rows else None

    def line_amounts(self, order_no) -> frozenset[Decimal]:
        rows = self._all("select quantity, unit_price from line_items where order_no=?", (order_no,))
        return frozenset(Decimal(r["unit_price"]) * r["quantity"] for r in rows)

    def add_supplier(self, email, name, contacts=()):
        """contacts are the addresses people at the supplier write from, which can differ from the PayPal address."""
        self._exec("insert or replace into suppliers (email, name, contacts) values (?,?,?)",
                   (email, name, ",".join(sorted({c.strip().lower() for c in contacts if c.strip()}))))

    def suppliers(self) -> list[dict]:
        out = []
        for r in self._all("select * from suppliers order by name"):
            out.append({"email": r["email"], "name": r["name"], "contacts": [c for c in r["contacts"].split(",") if c]})
        return out

    def contacts_of(self, supplier_email) -> frozenset[str]:
        """Who may ask the shop to pay this supplier: the PayPal address itself and the registered contacts."""
        rows = self._all("select contacts from suppliers where lower(email)=lower(?)", (supplier_email,))
        found = {c for r in rows for c in r["contacts"].split(",") if c}
        return frozenset(found | {supplier_email.lower()})

    def add_invoice(self, invoice_id, supplier_email, description, amount: Decimal, due: str):
        self._exec("insert or replace into supplier_invoices (invoice_id, supplier_email, description, amount, due)"
                   " values (?,?,?,?,?)", (invoice_id, supplier_email, description, str(amount), due))

    def invoice(self, invoice_id) -> InvoiceFacts | None:
        """The amount is what is still owed, so a part payment cannot make an invoice look settled."""
        rows = self._all("select * from supplier_invoices where invoice_id=?", (invoice_id,))
        if not rows:
            return None
        r = rows[0]
        owed = max(Decimal(r["amount"]) - Decimal(r["paid_amount"] or "0"), Decimal("0"))
        return InvoiceFacts(r["invoice_id"], r["supplier_email"], owed, r["paid_ref"] is not None,
                            self.contacts_of(r["supplier_email"]))

    def invoice_row(self, invoice_id) -> dict | None:
        rows = self._all("select * from supplier_invoices where invoice_id=?", (invoice_id,))
        return dict(rows[0]) if rows else None

    def invoices(self) -> list[dict]:
        return [dict(r) for r in self._all("select * from supplier_invoices order by invoice_id")]

    def mark_invoice_paid(self, invoice_id, ref):
        self._exec("update supplier_invoices set paid_ref=?, paid_amount=amount where invoice_id=?", (ref, invoice_id))

    def record_payment(self, invoice_id, amount: Decimal, ref) -> bool:
        """Adds a payment against an invoice. The invoice counts as paid only once the whole amount has gone."""
        row = self.invoice_row(invoice_id)
        if row is None:
            return False
        paid = Decimal(row["paid_amount"] or "0") + amount
        settled = paid >= Decimal(row["amount"])
        self._exec("update supplier_invoices set paid_amount=?, paid_ref=? where invoice_id=?",
                   (str(paid), ref if settled else row["paid_ref"], invoice_id))
        return settled

    def clear_records(self):
        """Empties orders, suppliers and invoices (not the settings), before the demo shop is seeded again."""
        for table in ("orders", "line_items", "suppliers", "supplier_invoices", "paypal_events"):
            self._exec(f"delete from {table}")

    # ---- what PayPal has told the shop

    def claim_event(self, event_id: str) -> bool:
        """False if PayPal already told us this one (it retries), so each event is handled once."""
        now = datetime.now(timezone.utc)
        with self._lock:
            cur = self._db.execute("insert or ignore into paypal_events values (?,?,?,?,?,?,?)",
                                   (event_id, "", "", None, "", now.isoformat(timespec="seconds"), now.date().isoformat()))
            self._db.commit()
            return cur.rowcount == 1

    def finish_event(self, event_id: str, kind: str, summary: str, amount=None, origin: str = ""):
        self._exec("update paypal_events set kind=?, summary=?, amount=?, origin=? where event_id=?",
                   (kind, summary, None if amount is None else str(amount), origin, event_id))

    def release_event(self, event_id: str):
        """Handling failed, so PayPal's retry is allowed to try again."""
        self._exec("delete from paypal_events where event_id=? and summary=''", (event_id,))

    def events(self, limit: int = 12) -> list[dict]:
        return [dict(r) for r in self._all("select * from paypal_events where summary != '' and kind != 'ignored' order by at desc, rowid desc limit ?", (limit,))]

    def external_refunds_today(self) -> Decimal:
        """Refunds made in PayPal itself today, outside Countersign. They count against the same daily limit."""
        day = datetime.now(timezone.utc).date().isoformat()
        rows = self._all("select amount from paypal_events where kind='refund' and origin='outside' and day=?", (day,))
        return sum((Decimal(r["amount"]) for r in rows if r["amount"]), Decimal("0"))

    def reverse_payment(self, invoice_id: str, amount: Decimal):
        """PayPal did not pay out what was recorded as paid, so the invoice is owed again."""
        row = self._all("select amount, paid_amount, paid_ref from supplier_invoices where invoice_id=?", (invoice_id,))
        if not row:
            return
        paid = max(Decimal(row[0]["paid_amount"] or "0") - amount, Decimal("0"))
        self._exec("update supplier_invoices set paid_amount=?, paid_ref=? where invoice_id=?",
                   (str(paid), None if paid < Decimal(row[0]["amount"]) else row[0]["paid_ref"], invoice_id))

    def get_setting(self, key, default=None):
        rows = self._all("select value from settings where key=?", (key,))
        return rows[0]["value"] if rows else default

    def set_setting(self, key, value: str):
        self._exec("insert or replace into settings (key, value) values (?,?)", (key, value))

    def known_payees(self) -> set[str]:
        return {r["email"] for r in self._all("select email from suppliers")}

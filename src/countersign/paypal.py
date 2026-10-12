import base64
import time
import uuid
from decimal import Decimal

import httpx

from .guard import CaptureFacts
from .ledger import Ledger
from .money import fmt
from .store import Store

SANDBOX = "https://api-m.sandbox.paypal.com"
OPEN_DISPUTE = {"REQUIRED_ACTION", "REQUIRED_OTHER_PARTY_ACTION", "UNDER_PAYPAL_REVIEW", "OPEN_INQUIRIES"}


class PayPalError(Exception):
    def __init__(self, status: int, body: dict):
        self.status = status
        self.body = body
        detail = body.get("message") or body.get("error_description") or body.get("name") or ""
        super().__init__(f"PayPal HTTP {status}: {detail} (debug_id {body.get('debug_id')})")


class PayPal:
    def __init__(self, client_id: str, secret: str, base: str = SANDBOX, transport=None):
        self._auth = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
        self._http = httpx.Client(base_url=base, timeout=httpx.Timeout(45, connect=10), transport=transport)
        self._token = None
        self._expires = 0.0
        self.base = base
        self.token_info: dict = {}

    def _bearer(self) -> str:
        if self._token and time.time() < self._expires:
            return self._token
        r = self._http.post("/v1/oauth2/token", data={"grant_type": "client_credentials"},
                            headers={"Authorization": f"Basic {self._auth}"})
        if r.status_code >= 400:
            raise PayPalError(r.status_code, r.json() if r.content else {})
        body = r.json()
        self._token = body["access_token"]
        self._expires = time.time() + body.get("expires_in", 300) - 60
        self.token_info = {k: v for k, v in body.items() if k != "access_token"}
        return self._token

    def connection(self) -> dict:
        """Whether the credentials work and what the app is allowed to do. Never returns a secret."""
        try:
            self._token, self._expires = None, 0.0
            self._bearer()
        except Exception as e:
            return {"connected": False, "environment": "sandbox" if "sandbox" in self.base else "live", "error": str(e)[:160]}
        scopes = sorted({s.rsplit("/", 1)[-1] for s in str(self.token_info.get("scope", "")).split() if s.startswith("http")})
        return {"connected": True, "environment": "sandbox" if "sandbox" in self.base else "live",
                "app_id": self.token_info.get("app_id"), "scopes": scopes,
                "can_refund": "refund" in scopes, "can_pay_out": "payouts" in scopes}

    def request(self, method: str, path: str, json=None, request_id: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self._bearer()}"}
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        r = self._http.request(method, path, json=json, headers=headers)
        body = r.json() if r.content else {}
        if r.status_code >= 400:
            raise PayPalError(r.status_code, body)
        return body

    def order(self, order_id: str) -> dict:
        return self.request("GET", f"/v2/checkout/orders/{order_id}")

    def create_paid_order(self, *, reference: str, description: str, total: Decimal, card_number: str,
                          card_expiry: str, cardholder: str) -> dict:
        return self.request("POST", "/v2/checkout/orders", {
            "intent": "CAPTURE",
            "purchase_units": [{
                "reference_id": reference, "custom_id": reference, "invoice_id": f"MS-{reference}-{uuid.uuid4().hex[:6]}",
                "description": description, "amount": {"currency_code": "USD", "value": fmt(total)}}],
            "payment_source": {"card": {
                "number": card_number.replace(" ", ""), "expiry": card_expiry, "name": cardholder,
                "billing_address": {"address_line_1": "1 Main St", "admin_area_2": "San Jose",
                                    "admin_area_1": "CA", "postal_code": "95131", "country_code": "US"}}},
        }, request_id=str(uuid.uuid4()))

    def refund(self, capture_id: str, amount: Decimal, currency: str, note: str, request_id: str) -> dict:
        body = {"amount": {"value": fmt(amount), "currency_code": currency}}
        if note:
            body["note_to_payer"] = note
        return self.request("POST", f"/v2/payments/captures/{capture_id}/refund", body, request_id)

    def payout(self, batch_id: str, receiver: str, amount: Decimal, currency: str, note: str, item_id: str) -> dict:
        return self.request("POST", "/v1/payments/payouts", {
            "sender_batch_header": {"sender_batch_id": batch_id, "email_subject": f"Payment for invoice {item_id}" if item_id else "Payment"},
            "items": [{"recipient_type": "EMAIL", "receiver": receiver,
                       "amount": {"value": fmt(amount), "currency": currency},
                       "note": note, "sender_item_id": item_id or batch_id}]})

    def payout_batch(self, batch_id: str) -> dict:
        return self.request("GET", f"/v1/payments/payouts/{batch_id}")

    def disputes_for(self, transaction_id: str) -> list[dict]:
        body = self.request("GET", f"/v1/customer/disputes?disputed_transaction_id={transaction_id}")
        return body.get("items", [])


class LiveFacts:
    """Guard facts read from PayPal, the shop's records and the ledger."""

    def __init__(self, paypal: PayPal, store: Store, ledger: Ledger):
        self.paypal = paypal
        self.store = store
        self.ledger = ledger

    def capture(self, capture_id: str) -> CaptureFacts | None:
        row = self.store.order_by_capture(capture_id)
        if row is None or not row["paypal_order_id"]:
            return None
        payments = self.paypal.order(row["paypal_order_id"])["purchase_units"][0].get("payments", {})
        cap = next((c for c in payments.get("captures", []) if c["id"] == capture_id), None)
        if cap is None:
            return None
        refunded = sum((Decimal(r["amount"]["value"]) for r in payments.get("refunds", [])
                        if r.get("status") in ("COMPLETED", "PENDING")), Decimal("0"))
        open_dispute = any(d.get("status") in OPEN_DISPUTE for d in self.paypal.disputes_for(capture_id))
        return CaptureFacts(capture_id, Decimal(cap["amount"]["value"]), refunded, cap["amount"]["currency_code"],
                            cap["status"], row["customer_email"], open_dispute,
                            self.store.line_amounts(row["order_no"]))

    def invoice(self, invoice_id):
        return self.store.invoice(invoice_id)

    def known_payees(self):
        return self.store.known_payees()

    def executed_today(self, tool, key=None):
        return self.ledger.total_today(tool, key)

"""Registers this server's webhook with PayPal, so PayPal tells the shop about payments, refunds, disputes and payouts.

    python scripts/register_webhook.py            registers PUBLIC_URL/api/paypal/webhook (or says it already is)
    python scripts/register_webhook.py --list     shows the webhooks of the app in .env

Run it once after the server is reachable on the internet. It prints the webhook id, which goes into the
server's settings as PAYPAL_WEBHOOK_ID. Uses the PayPal credentials and PUBLIC_URL from .env.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from countersign.config import load_env, need
from countersign.paypal import PayPal, PayPalError
from countersign.webhooks import EVENT_TYPES

load_env()
paypal = PayPal(need("PAYPAL_CLIENT_ID"), need("PAYPAL_CLIENT_SECRET"))
existing = paypal.request("GET", "/v1/notifications/webhooks").get("webhooks", [])
if "--list" in sys.argv:
    for w in existing:
        print(w["id"], w["url"], f"({len(w.get('event_types', []))} events)")
    sys.exit(0 if existing else "no webhooks registered for this app")

base = need("PUBLIC_URL").rstrip("/")
if not base.startswith("https://"):
    sys.exit("PUBLIC_URL has to be the https address the server is reached at, PayPal does not send to anything else")
url = base + "/api/paypal/webhook"
for w in existing:
    if w["url"] == url:
        print(f"already registered: {w['id']}\nset PAYPAL_WEBHOOK_ID={w['id']} in the server's settings")
        sys.exit(0)
try:
    made = paypal.request("POST", "/v1/notifications/webhooks", {"url": url, "event_types": [{"name": n} for n in EVENT_TYPES]})
except PayPalError as e:
    sys.exit(f"PayPal did not accept it: {e}")
print(f"registered {url}\nset PAYPAL_WEBHOOK_ID={made['id']} in the server's settings")

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
from countersign.webhooks import register

load_env()
paypal = PayPal(need("PAYPAL_CLIENT_ID"), need("PAYPAL_CLIENT_SECRET"))
existing = paypal.request("GET", "/v1/notifications/webhooks").get("webhooks", [])
if "--list" in sys.argv:
    for w in existing:
        print(w["id"], w["url"], f"({len(w.get('event_types', []))} events)")
    sys.exit(0 if existing else "no webhooks registered for this app")

base = need("PUBLIC_URL").rstrip("/")
url = base + "/api/paypal/webhook"
try:
    found, created = register(paypal, url)
except (ValueError, PayPalError) as e:
    sys.exit(f"could not register: {e}")
print(("registered " + url if created else "already registered") + f"\nwebhook id {found}, the server also finds it by itself once it is registered from the Setup page")

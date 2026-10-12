"""Fills data/shop.db and puts one real, paid sandbox order in PayPal for every demo order.
Safe to run again: orders that already have a payment are left alone.

    python scripts/seed_paypal.py            add whatever is missing
    python scripts/seed_paypal.py --fresh    start the demo over: new shop records and new paid orders
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from countersign.config import DB_PATH, load_env, need
from countersign.paypal import PayPal
from countersign.seed import seed_demo
from countersign.store import Store

load_env()
if "--fresh" in sys.argv:
    DB_PATH.unlink(missing_ok=True)
seed_demo(PayPal(need("PAYPAL_CLIENT_ID"), need("PAYPAL_CLIENT_SECRET")), Store(str(DB_PATH)),
          card=need("SANDBOX_CARD_NUMBER"), expiry=need("SANDBOX_CARD_EXPIRY"),
          supplier_email=need("SANDBOX_SUPPLIER_EMAIL"), attacker_email=need("SANDBOX_ATTACKER_EMAIL"))

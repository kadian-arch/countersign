"""The nightly check, for a scheduled job (the Render cron job in render.yaml).

It asks the running shop to compare its own record of the refunds with what PayPal shows. The shop keeps the outcome for the
Setup page and emails the owner only if the two disagree. This script only makes the call, so it needs nothing installed.

    PUBLIC_URL=https://your-shop.example OWNER_TOKEN=... python scripts/nightly_check.py

It exits with 1 when the records disagree or the shop could not be asked, so the host shows the run as failed.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

url = os.environ.get("PUBLIC_URL", "").rstrip("/")
token = os.environ.get("OWNER_TOKEN", "")
if not url or not token:
    sys.exit("PUBLIC_URL and OWNER_TOKEN must be set.")

request = urllib.request.Request(url + "/api/nightly", method="POST", headers={"X-Owner-Token": token, "Content-Length": "0"})
for attempt in range(1, 4):   # a shop that is restarting needs a minute
    try:
        with urllib.request.urlopen(request, timeout=90) as r:
            out = json.load(r)
        print(out["text"])
        sys.exit(0 if out["ok"] is True else 1)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            sys.exit(f"The shop refused the owner token ({e.code}).")
        print(f"attempt {attempt}: the shop answered {e.code}", flush=True)
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"attempt {attempt}: could not reach the shop ({e})", flush=True)
    time.sleep(30)
sys.exit("The shop did not answer.")

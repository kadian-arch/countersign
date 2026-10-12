"""Runs the console.

    python scripts/serve.py                  with PayPal credentials in .env the shop runs on your PayPal sandbox,
                                             and visitors can also try a private practice shop. Without them,
                                             practice shops only
    python scripts/serve.py --sim            practice shops only, even if credentials are present
    python scripts/serve.py --live           only the PayPal sandbox shop
    python scripts/serve.py --port 8080

A model key in .env switches on the assistant that reads email and the plain-English rule translator.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import uvicorn

from countersign.config import load_env
from countersign.web import create_app

port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else int(os.environ.get("PORT", 8000))
load_env()
mode = "sim" if "--sim" in sys.argv else "live" if "--live" in sys.argv else None
uvicorn.run(create_app(mode), host=os.environ.get("HOST", "127.0.0.1"), port=port)

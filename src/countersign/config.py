import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "shop.db"
LEDGER_PATH = ROOT / "data" / "ledger.db"


def load_env():
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            v = v.strip()
            if not v.startswith('"'):
                v = re.split(r"\s+#", v, maxsplit=1)[0].strip()   # a note after the value is not part of it
            os.environ.setdefault(k.strip(), v.strip('"'))


def need(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"{name} is missing from .env")
    return value

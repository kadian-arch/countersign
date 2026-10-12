"""Which models can each configured provider use, and do they make tool calls?

    python scripts/check_llm.py            list the models each provider offers
    python scripts/check_llm.py --ping     also try one tool call on each model in your .env
"""
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from countersign.config import load_env
from countersign.llm import LLM, LLMUnavailable, Provider, providers_from_env

load_env()
providers = providers_from_env(require_models=False)
if not providers:
    sys.exit("no provider is configured: set LLM_PROVIDERS and an API key in .env")

ECHO = {"type": "function", "function": {
    "name": "echo", "description": "Repeat a word back.",
    "parameters": {"type": "object", "properties": {"word": {"type": "string"}}, "required": ["word"]}}}

for p in providers:
    r = httpx.get(f"{p.base_url}/models", headers={"Authorization": f"Bearer {p.key}"}, timeout=30)
    if r.status_code >= 400:
        print(f"{p.name}: HTTP {r.status_code} {r.text[:200]}")
        continue
    ids = sorted(m["id"].removeprefix("models/") for m in r.json()["data"])
    print(f"\n{p.name}: {len(ids)} models")
    print("  " + "\n  ".join(ids))

if "--ping" in sys.argv:
    print("\n-- tool call on each model in .env")
    for p in providers:
        for model in p.models:
            llm = LLM([Provider(p.name, p.base_url, p.key, [model])], attempts=1)
            start = time.time()
            try:
                msg = llm.chat([{"role": "user", "content": "Call the echo tool with the word hello."}], [ECHO])
            except LLMUnavailable as e:
                print(f"{p.name}/{model}: FAILED {e}")
                continue
            called = [c["function"]["name"] for c in msg.get("tool_calls") or []]
            print(f"{p.name}/{model}: {'tool call ok' if called else 'answered without a tool call'} ({time.time() - start:.1f}s)")

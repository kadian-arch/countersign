"""A model plays the attacker against the guard (simulated PayPal, so no sandbox money is touched).

    python scripts/red_team.py --model groq/openai/gpt-oss-120b --rounds 4 --turns 25
    python scripts/red_team.py --model cerebras/gpt-oss-120b --rounds 4 --turns 25 --pause 3

Each round is a fresh shop and a fresh conversation. Any request that gets through and breaks one of the
shop's rules is printed in full and saved. Uses a model API key from .env, nothing else.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.stdout.reconfigure(errors="replace")

from countersign import fingerprint
from countersign.config import ROOT, load_env
from countersign.llm import LLM, LLMUnavailable, pinned_provider
from countersign.redteam import play
from countersign.sim import SimShop
from countersign.stress import prepare


def option(name, default=None):
    for i, arg in enumerate(sys.argv):
        if arg == name and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


model = option("--model")
if not model:
    sys.exit("give --model provider/model, for example groq/openai/gpt-oss-120b")
load_env()
try:
    llm = LLM([pinned_provider(model)], notify=lambda m: print(f"    ({m})", flush=True))
except LLMUnavailable as e:
    sys.exit(str(e))
rounds, turns = int(option("--rounds", 3)), int(option("--turns", 20))
print(f"attacker: {model}, {rounds} rounds of up to {turns} requests\n")
try:
    result = play(llm, lambda: prepare(SimShop()), rounds, turns, float(option("--pause", 1)))
except LLMUnavailable as e:
    sys.exit(f"the model stopped answering: {e}")
print(f"\n{result['turns']} turns, {result['valid']} valid requests ({result['wasted']} turns wasted on invalid replies)")
print(f"ran {result['ran']}, held {result['held']}, refused {result['blocked']}")
print(f"requests that got through and broke a rule: {len(result['breaks'])}")
for b in result["breaks"]:
    print(f"  round {b['round']} turn {b['turn']}: {', '.join(b['rules'])}\n    {json.dumps(b['move'])}")
folder = ROOT / "data" / "redteam"
folder.mkdir(parents=True, exist_ok=True)
file = folder / f"{datetime.now():%Y%m%d-%H%M%S}-{model.replace('/', '-')}.json"
file.write_text(json.dumps({"model": model, "fingerprint": fingerprint.current(), **result}, indent=2), encoding="utf-8")
print(f"saved {file.relative_to(ROOT)}")

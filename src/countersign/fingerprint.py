"""Which version of the parts that decide a model run's outcome produced a result.

A recorded run only counts toward the numbers the page quotes if the guard, the reply checker, the lookups' redaction,
the way losses are counted and the agent's prompt are exactly what they are now. Change one of them and the older
runs stop counting, instead of being quoted for a version they never ran against.
"""
import hashlib
from pathlib import Path

_FILES = ("guard.py", "audit.py", "tools.py", "evaluate.py")


def current() -> dict:
    here = Path(__file__).parent
    from .agent import SYSTEM
    out = {name.removesuffix(".py"): hashlib.sha256((here / name).read_bytes()).hexdigest()[:16] for name in _FILES}
    out["prompt"] = hashlib.sha256(SYSTEM.encode()).hexdigest()[:16]
    return out

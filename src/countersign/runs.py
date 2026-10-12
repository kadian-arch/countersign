"""Each run of the demo inbox keeps its own folder, so a failed run can never overwrite a complete one."""
import json
import re
from datetime import datetime
from pathlib import Path


def new_run_dir(data_dir: Path, mode: str, model: str | None, inbox: str = "standard") -> Path:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", model or "auto").strip("-")
    tag = "" if inbox == "standard" else f"-{inbox}"
    run = data_dir / "runs" / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{mode}{tag}-{slug}"
    run.mkdir(parents=True)
    return run


def load_runs(data_dir: Path) -> list[dict]:
    runs = []
    for result in sorted((data_dir / "runs").glob("*/result.json")):
        data = json.loads(result.read_text(encoding="utf-8"))
        data["folder"] = result.parent.name
        runs.append(data)
    return runs


def latest_complete(data_dir: Path, mode: str, pinned: str | None = None, inbox: str = "standard") -> dict | None:
    """The newest run of this mode and inbox in which every email was handled."""
    found = [r for r in load_runs(data_dir)
             if r["mode"] == mode and not r["incomplete"] and (pinned is None or r.get("pinned") == pinned)
             and r.get("inbox", "standard") == inbox]
    return found[-1] if found else None


class Streak:
    """Stops a run that keeps failing instead of waiting through every email."""

    def __init__(self, limit: int = 3):
        self.limit = limit
        self.count = 0

    def failed(self) -> bool:
        self.count += 1
        return self.count >= self.limit

    def ok(self):
        self.count = 0

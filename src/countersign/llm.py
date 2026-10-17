"""Chat client for OpenAI-compatible endpoints with retry and fallback.
Free-tier models get retired, overloaded and rate limited without notice, so a request
walks every configured provider and model before giving up."""
import os
import re
import time
from dataclasses import dataclass

import httpx

BASE_URLS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "groq": "https://api.groq.com/openai/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}
DEFAULT_MODELS = {"gemini": "gemini-flash-latest,gemini-3.5-flash,gemini-3.1-flash-lite",
                  "cerebras": "gpt-oss-120b", "groq": "openai/gpt-oss-120b"}   # a key alone is enough, *_MODELS overrides
RETRY_STATUS = {408, 429, 500, 502, 503, 504}

# a limit that resets tomorrow, waiting a minute will not help
_DAILY = re.compile(r"per\s*day|daily|tokens per day|\blimit:\s*0\b", re.I)
_DELAY_BODY = re.compile(r'"retryDelay"\s*:\s*"([0-9.]+)s"')
_DELAY_TEXT = re.compile(r"try again in (?:(\d+)m)?\s*([0-9.]+)s", re.I)


class LLMUnavailable(Exception):
    pass


@dataclass
class Provider:
    name: str
    base_url: str
    key: str
    models: list[str]


def providers_from_env(env=os.environ, require_models: bool = True) -> list[Provider]:
    found = []
    for name in (n.strip().lower() for n in env.get("LLM_PROVIDERS", "gemini").split(",") if n.strip()):
        key = env.get(f"{name.upper()}_API_KEY")
        models = env.get(f"{name.upper()}_MODELS", DEFAULT_MODELS.get(name, ""))
        if key and name in BASE_URLS and (models or not require_models):
            found.append(Provider(name, BASE_URLS[name], key, [m.strip() for m in models.split(",") if m.strip()]))
    return found


def pinned_provider(spec: str, env=os.environ) -> Provider:
    """provider/model as typed on the command line, with that provider's key from .env."""
    name, _, model = spec.partition("/")
    name = name.lower()
    if name not in BASE_URLS or not model:
        raise LLMUnavailable(f"--model must look like provider/model, with a provider from: {', '.join(BASE_URLS)} (got {spec!r})")
    key = env.get(f"{name.upper()}_API_KEY")
    if not key:
        raise LLMUnavailable(f"{name.upper()}_API_KEY is missing from .env")
    return Provider(name, BASE_URLS[name], key, [model])


def _gist(response) -> str:
    """The provider's own explanation, shortened."""
    try:
        data = response.json()
        if isinstance(data, list) and data:
            data = data[0]
        message = data.get("error", {}).get("message") or ""
    except (ValueError, AttributeError):
        message = ""
    return " ".join((message or response.text).split())[:110]


def _retry_after(response, waits: int) -> float:
    try:
        return min(max(float(response.headers.get("retry-after", "")), 1.0), 90.0)
    except ValueError:
        pass
    text = response.text
    found = _DELAY_BODY.search(text)
    if found:
        return min(max(float(found.group(1)), 1.0), 90.0)
    found = _DELAY_TEXT.search(text)
    if found:
        return min(max(int(found.group(1) or 0) * 60 + float(found.group(2)), 1.0), 90.0)
    return min(5.0 * waits, 90.0)


class LLM:
    def __init__(self, providers: list[Provider], attempts: int = 2, transport=None, sleep=time.sleep,
                 rate_waits: int = 6, notify=None):
        if not providers:
            raise LLMUnavailable("no model provider has a key configured")
        self.providers = providers
        self.attempts = attempts
        self.rate_waits = rate_waits
        self.sleep = sleep
        self.notify = notify or (lambda message: None)
        self.http = httpx.Client(timeout=httpx.Timeout(60, connect=10), transport=transport)
        self.last_used: str | None = None

    def chat(self, messages: list[dict], tools: list[dict] | None = None, patient: bool = True) -> dict:
        """patient=False is for someone waiting at a screen: a rate limit moves on to the next model at once
        instead of waiting it out."""
        waits_allowed = self.rate_waits if patient else 0
        tried = []
        for p in self.providers:
            for model in p.models:
                failures = waits = 0
                while failures < self.attempts and waits <= waits_allowed:
                    body = {"model": model, "messages": messages}
                    if tools:
                        body["tools"] = tools
                    try:
                        r = self.http.post(f"{p.base_url}/chat/completions", json=body,
                                           headers={"Authorization": f"Bearer {p.key}"})
                    except httpx.TransportError as e:
                        tried.append(f"{p.name}/{model}: {type(e).__name__}")
                        failures += 1
                        if failures < self.attempts:
                            self.sleep(2 ** failures)
                        continue
                    if r.status_code < 400:
                        self.last_used = f"{p.name}/{model}"
                        return r.json()["choices"][0]["message"]
                    tried.append(f"{p.name}/{model}: HTTP {r.status_code} {_gist(r)}")
                    if r.status_code == 429:
                        if _DAILY.search(r.text):
                            self.notify(f"{p.name}/{model}: daily quota used up, skipping it")
                            break
                        waits += 1
                        if waits > waits_allowed:
                            break
                        delay = _retry_after(r, waits)
                        self.notify(f"rate limited on {p.name}/{model}, waiting {delay:.0f}s")
                        self.sleep(delay)
                        continue
                    if r.status_code not in RETRY_STATUS:
                        break
                    failures += 1
                    if failures < self.attempts:
                        self.sleep(2 ** failures)
        raise LLMUnavailable("every model failed: " + "; ".join(tried[-4:]))

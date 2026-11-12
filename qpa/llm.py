"""Language-model providers for the repair loop.

Only the standard library is used, so qpa has no SDK dependency.

  QPA_PROVIDER   anthropic | openai | replay   (default: whichever API key is set)
  QPA_MODEL      model id, required for anthropic / openai
  QPA_API_BASE   override the API base URL (e.g. a gateway or a local server)
  ANTHROPIC_API_KEY / OPENAI_API_KEY
  QPA_REPLAY     replay: a JSON file holding a list of recorded responses
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path


class LLMError(RuntimeError):
    pass


class Provider:
    name = "base"

    def complete(self, system: str, prompt: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError


def _post(url: str, headers: dict, body: dict, timeout: int = 180) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise LLMError(f"{url}: HTTP {e.code}: {e.read().decode(errors='replace')[:400]}") from e
    except urllib.error.URLError as e:
        raise LLMError(f"{url}: {e.reason}") from e


class Anthropic(Provider):
    name = "anthropic"

    def __init__(self, key: str, model: str, base: str | None = None, max_tokens: int = 8000):
        self.key, self.model, self.max_tokens = key, model, max_tokens
        self.base = (base or "https://api.anthropic.com").rstrip("/")

    def complete(self, system: str, prompt: str) -> str:
        data = _post(f"{self.base}/v1/messages",
                     {"x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                     {"model": self.model, "max_tokens": self.max_tokens, "system": system,
                      "messages": [{"role": "user", "content": prompt}]})
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


class OpenAICompatible(Provider):
    name = "openai"

    def __init__(self, key: str, model: str, base: str | None = None):
        self.key, self.model = key, model
        self.base = (base or "https://api.openai.com/v1").rstrip("/")

    def complete(self, system: str, prompt: str) -> str:
        data = _post(f"{self.base}/chat/completions",
                     {"authorization": f"Bearer {self.key}", "content-type": "application/json"},
                     {"model": self.model, "messages": [{"role": "system", "content": system},
                                                       {"role": "user", "content": prompt}]})
        return data["choices"][0]["message"]["content"]


class Replay(Provider):
    """Plays back recorded responses in order; used by tests and reproducible demos."""
    name = "replay"

    def __init__(self, path: Path):
        self.responses = json.loads(Path(path).read_text())
        self.i = 0

    def complete(self, system: str, prompt: str) -> str:
        if self.i >= len(self.responses):
            raise LLMError("replay: no more recorded responses")
        r = self.responses[self.i]
        self.i += 1
        return r if isinstance(r, str) else json.dumps(r)


def get_provider(name: str | None = None) -> Provider | None:
    name = name or os.environ.get("QPA_PROVIDER")
    if not name:
        if os.environ.get("ANTHROPIC_API_KEY"):
            name = "anthropic"
        elif os.environ.get("OPENAI_API_KEY"):
            name = "openai"
        else:
            return None
    if name == "replay":
        path = os.environ.get("QPA_REPLAY")
        if not path:
            raise LLMError("QPA_PROVIDER=replay needs QPA_REPLAY=<file.json>")
        return Replay(Path(path))
    model = os.environ.get("QPA_MODEL")
    if not model:
        raise LLMError(f"set QPA_MODEL to the {name} model id to use for repairs")
    base = os.environ.get("QPA_API_BASE")
    if name == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY") or ""
        if not key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        return Anthropic(key, model, base)
    if name == "openai":
        key = os.environ.get("OPENAI_API_KEY") or ""
        if not key:
            raise LLMError("OPENAI_API_KEY is not set")
        return OpenAICompatible(key, model, base)
    raise LLMError(f"unknown provider {name}")

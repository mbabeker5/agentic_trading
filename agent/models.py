"""Model adapters: one small interface, two providers.

A strategy book names its model in its yaml as "<provider>/<model id>":

    model: anthropic/claude-fable-5-1
    model: openrouter/openai/gpt-6-astra

`get_adapter(model_field)` returns an object with one method, `complete(...)`, that
takes a system prompt and a user message and returns the text plus token usage and
cost. The trading loop never talks to a provider directly, so swapping the model
behind a book is a one line change in its yaml and nothing else.

Credentials:
- Anthropic: ANTHROPIC_API_KEY in the environment, or the file
  /Users/mtalib/workspace_repos/personal_repo/agentic_trading/.secrets/anthropic.env
  with a line ANTHROPIC_API_KEY=...
- OpenRouter: /Users/mtalib/workspace_repos/personal_repo/agentic_trading/.secrets/openrouter.env
  with a line OPENROUTER_API_KEY=...

Deliberate choice: no automatic model fallback on either provider. In an eval that
compares models, a silent switch to a different model would corrupt the result. A
refusal or an error comes back as `ok=False` and the loop treats it as "no decision".
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from paths import project_root, secrets_dir  # noqa: E402

PROJECT = project_root()
SECRETS = secrets_dir()

# Anthropic first party prices, dollars per million tokens (input, output), 2026-06.
ANTHROPIC_PRICES = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


class ModelError(Exception):
    """Raised for configuration problems. Provider failures are returned, not raised."""


@dataclass
class ModelResponse:
    ok: bool
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    latency_s: float = 0.0
    stop_reason: str | None = None
    error: str | None = None
    raw_id: str | None = None
    extra: dict = field(default_factory=dict)

    def as_log_dict(self) -> dict:
        return {
            "ok": self.ok, "provider": self.provider, "model": self.model,
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd, "latency_s": round(self.latency_s, 2),
            "stop_reason": self.stop_reason, "error": self.error, "raw_id": self.raw_id,
        }


def _load_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip("'").strip('"')
    return out


def _secret(name: str, filename: str) -> str:
    value = os.environ.get(name) or _load_env_file(SECRETS / filename).get(name)
    if not value:
        raise ModelError(
            f"{name} not found. Put it in the environment or in {SECRETS / filename}")
    return value


class AnthropicAdapter:
    """Claude through the official Anthropic SDK.

    Thinking is left at the model's default (adaptive; always on for Fable). Depth is
    controlled with `effort`. No `fallbacks` on purpose, see the module docstring.
    """

    provider = "anthropic"

    def __init__(self, model: str, effort: str = "high", timeout_s: float = 300.0):
        import anthropic  # imported here so OpenRouter-only setups need not install it

        self.model = model
        self.effort = effort
        api_key = os.environ.get("ANTHROPIC_API_KEY") or _load_env_file(
            SECRETS / "anthropic.env").get("ANTHROPIC_API_KEY")
        # A zero-argument client also picks up an `ant auth login` profile if one exists.
        self.client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s) if api_key \
            else anthropic.Anthropic(timeout=timeout_s)

    def complete(self, system: str, user: str, max_tokens: int = 4000,
                 json_only: bool = False) -> ModelResponse:
        import anthropic

        if json_only:
            system = system.rstrip() + "\n\nReply with a single JSON object and nothing else."
        t0 = time.time()
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                output_config={"effort": self.effort},
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.APIStatusError as exc:
            return ModelResponse(False, "", self.provider, self.model,
                                 latency_s=time.time() - t0,
                                 error=f"HTTP {exc.status_code}: {exc.message}")
        except anthropic.APIConnectionError as exc:
            return ModelResponse(False, "", self.provider, self.model,
                                 latency_s=time.time() - t0, error=f"connection: {exc}")

        text = "".join(b.text for b in resp.content if b.type == "text")
        usage = resp.usage
        price = ANTHROPIC_PRICES.get(self.model)
        cost = None
        if price:
            cost = (usage.input_tokens * price[0] + usage.output_tokens * price[1]) / 1e6
        ok = resp.stop_reason not in ("refusal",) and bool(text.strip())
        err = None
        if resp.stop_reason == "refusal":
            det = getattr(resp, "stop_details", None)
            err = f"refusal: {getattr(det, 'category', None)}"
        return ModelResponse(ok, text, self.provider, resp.model, usage.input_tokens,
                             usage.output_tokens, cost, time.time() - t0,
                             resp.stop_reason, err, getattr(resp, "id", None))


class OpenRouterAdapter:
    """Any model on OpenRouter, through its chat completions endpoint (plain HTTP).

    The model id is OpenRouter's own, for example "openai/gpt-6-astra". OpenRouter
    reports the dollar cost of each call when asked, so cost is exact, not estimated.
    """

    provider = "openrouter"
    URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, model: str, timeout_s: float = 300.0, reasoning_effort: str | None = None):
        self.model = model
        self.timeout_s = timeout_s
        self.reasoning_effort = reasoning_effort
        self.api_key = _secret("OPENROUTER_API_KEY", "openrouter.env")

    def complete(self, system: str, user: str, max_tokens: int = 4000,
                 json_only: bool = False) -> ModelResponse:
        body: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "usage": {"include": True},
        }
        if json_only:
            body["response_format"] = {"type": "json_object"}
        if self.reasoning_effort:
            body["reasoning"] = {"effort": self.reasoning_effort}
        req = urllib.request.Request(
            self.URL, data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json",
                     "HTTP-Referer": "https://github.com/mbabeker5/agentic_trading",
                     "X-Title": "agentic_trading eval"})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            return ModelResponse(False, "", self.provider, self.model,
                                 latency_s=time.time() - t0, error=f"HTTP {exc.code}: {detail}")
        except (urllib.error.URLError, TimeoutError) as exc:
            return ModelResponse(False, "", self.provider, self.model,
                                 latency_s=time.time() - t0, error=f"connection: {exc}")

        if "error" in data:
            return ModelResponse(False, "", self.provider, self.model,
                                 latency_s=time.time() - t0, error=str(data["error"])[:300])
        choice = (data.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        usage = data.get("usage") or {}
        finish = choice.get("finish_reason")
        ok = bool(text.strip()) and finish not in ("content_filter",)
        return ModelResponse(ok, text, self.provider, data.get("model", self.model),
                             int(usage.get("prompt_tokens", 0)),
                             int(usage.get("completion_tokens", 0)),
                             usage.get("cost"), time.time() - t0, finish,
                             None if ok else f"finish_reason={finish}", data.get("id"),
                             extra={"provider_used": data.get("provider")})


def get_adapter(model_field: str, **kwargs):
    """Turn a book's `model` field into an adapter.

    "anthropic/<id>"        -> AnthropicAdapter
    "openrouter/<id>"       -> OpenRouterAdapter, <id> may itself contain a slash
    "<bare claude id>"      -> AnthropicAdapter (convenience)
    """
    if not model_field or not isinstance(model_field, str):
        raise ModelError("model field is empty")
    provider, _, rest = model_field.partition("/")
    if provider == "anthropic" and rest:
        return AnthropicAdapter(rest, **kwargs)
    if provider == "openrouter" and rest:
        return OpenRouterAdapter(rest, **kwargs)
    if "/" not in model_field and model_field.startswith("claude-"):
        return AnthropicAdapter(model_field, **kwargs)
    raise ModelError(
        f"Unrecognised model field '{model_field}'. Use anthropic/<id> or openrouter/<id>.")


if __name__ == "__main__":
    import sys

    field_ = sys.argv[1] if len(sys.argv) > 1 else "openrouter/openai/gpt-6-astra"
    adapter = get_adapter(field_)
    r = adapter.complete("You are a terse assistant.", "Reply with the single word: ready",
                         max_tokens=20)
    print(json.dumps(r.as_log_dict(), indent=2))
    print("text:", repr(r.text))

"""Model adapters: one small interface, every call through OpenRouter.

A strategy book names its model in its yaml as "<provider>/<model id>":

    model: anthropic/claude-fable-5-1
    model: openrouter/openai/gpt-6-astra

`get_adapter(model_field)` returns an object with one method, `complete(...)`, that
takes a system prompt and a user message and returns the text plus token usage and
cost. The trading loop never talks to a provider directly, so swapping the model
behind a book is a one line change in its yaml and nothing else.

"anthropic/<id>" is kept as a way of naming a Claude model, but since 2026-09-26
it no longer calls the Anthropic API: it is mapped to the OpenRouter id and sent
through OpenRouter like everything else (see AnthropicAdapter).

Credentials:
- OpenRouter: OPENROUTER_API_KEY in the environment, or the file
  /Users/mtalib/workspace_repos/personal_repo/agentic_trading/.secrets/openrouter.env
  with a line OPENROUTER_API_KEY=...

Deliberate choice: no automatic model fallback on either provider. In an eval that
compares models, a silent switch to a different model would corrupt the result. A
refusal or an error comes back as `ok=False` and the loop treats it as "no decision".
"""
from __future__ import annotations

import json
import os
import re
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

# The same seed on every call, so a provider that honours one gives the same
# answer to the same question. It is a date and it means nothing else.
FIXED_SEED = 20260906

# Sampling settings for a provider that accepts them. Temperature 0 and top_p 1
# together mean "take the most likely token every time", which is as close to a
# repeatable answer as a model gets.
PINNED_TEMPERATURE = 0.0
PINNED_TOP_P = 1.0

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
        """One call, as it goes into the ledger and the packet.

        `extra` carries what was actually sent: the model, the token cap, the
        sampling settings or a note saying why there were none, whether
        structured output was on, and the timeout. Without it a row in the
        ledger records an answer with no record of the question.
        """
        return {
            "ok": self.ok, "provider": self.provider, "model": self.model,
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd, "latency_s": round(self.latency_s, 2),
            "stop_reason": self.stop_reason, "error": self.error, "raw_id": self.raw_id,
            "extra": dict(self.extra),
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


def _openrouter_claude_id(model: str) -> str:
    """Anthropic's own model id, as OpenRouter names it.

    "claude-fable-5-1" -> "anthropic/claude-fable-5.1", "claude-sonnet-5" ->
    "anthropic/claude-sonnet-5". A trailing date (-20251001) is dropped.
    """
    m = re.sub(r"-\d{8}$", "", model)
    m = re.sub(r"-(\d+)-(\d+)$", r"-\1.\2", m)
    return f"anthropic/{m}"


class OpenRouterAdapter:
    """Any model on OpenRouter, through its chat completions endpoint (plain HTTP).

    The model id is OpenRouter's own, for example "openai/gpt-6-astra". OpenRouter
    reports the dollar cost of each call when asked, so cost is exact, not estimated.
    """

    provider = "openrouter"
    URL = "https://openrouter.ai/api/v1/chat/completions"

    #: This endpoint is OpenAI shaped and does take temperature, top_p and seed.
    accepts_sampling = True

    def __init__(self, model: str, timeout_s: float = 300.0, reasoning_effort: str | None = None):
        self.model = model
        self.timeout_s = timeout_s
        self.reasoning_effort = reasoning_effort
        self.api_key = _secret("OPENROUTER_API_KEY", "openrouter.env")

    def complete(self, system: str, user: str, max_tokens: int = 4000,
                 json_only: bool = False, schema: dict | None = None) -> ModelResponse:
        """One call, with everything that can be pinned pinned.

        temperature 0, top_p 1 and a fixed seed, all three of which this
        endpoint accepts. `schema` asks for strict structured output, which
        makes the provider guarantee a reply that validates. Not every model on
        OpenRouter can do that, and a model that cannot falls back to plain JSON
        object mode, so decide() validates the reply itself either way rather
        than trusting the flag.
        """
        body: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "usage": {"include": True},
        }
        if self.accepts_sampling:
            body.update(temperature=PINNED_TEMPERATURE, top_p=PINNED_TOP_P, seed=FIXED_SEED)
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "decision", "strict": True, "schema": schema},
            }
        elif json_only:
            body["response_format"] = {"type": "json_object"}
        if self.reasoning_effort:
            body["reasoning"] = {"effort": self.reasoning_effort}

        # Everything that was sent except the packet itself, which is already in
        # the decision packet file and would double the size of every log row.
        sent = {"request": {k: v for k, v in body.items() if k != "messages"}}
        sent["request"]["timeout_s"] = self.timeout_s

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
                                 latency_s=time.time() - t0,
                                 error=f"HTTP {exc.code}: {detail}", extra=sent)
        except (urllib.error.URLError, TimeoutError) as exc:
            return ModelResponse(False, "", self.provider, self.model,
                                 latency_s=time.time() - t0, error=f"connection: {exc}",
                                 extra=sent)

        if "error" in data:
            return ModelResponse(False, "", self.provider, self.model,
                                 latency_s=time.time() - t0,
                                 error=str(data["error"])[:300], extra=sent)
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
                             extra=dict(sent, provider_used=data.get("provider")))


class AnthropicAdapter(OpenRouterAdapter):
    """Claude asked for by its Anthropic id ("anthropic/claude-fable-5-1").

    Since 2026-09-26 this goes through OpenRouter, not the Anthropic API: direct
    Anthropic calls were removed after an unexpected card charge. The id is mapped
    to OpenRouter's ("anthropic/claude-fable-5.1") and `effort` becomes OpenRouter's
    reasoning effort. No `fallbacks` on purpose, see the module docstring.

    No temperature, no top_p and no seed, deliberately. Every model this project
    can name is from the generation that removed them: Fable 5 and 5.1, Opus 5 and
    4.8, and Sonnet 5 all reject them, because thinking is always on and sampling
    settings do not apply. What this adapter pins instead is a fixed effort and a
    hard timeout, and the exact request is written into ModelResponse.extra so a
    decision in the ledger can be reproduced without guessing what was asked.
    """

    #: Sampling is not a knob on these models. See the class docstring.
    accepts_sampling = False

    def __init__(self, model: str, effort: str = "high", timeout_s: float = 300.0):
        super().__init__(_openrouter_claude_id(model), timeout_s=timeout_s,
                         reasoning_effort=effort)
        self.effort = effort


def resolve_model_id(model_field: str) -> str:
    """What a book's `model` field actually names, without building an adapter.

    "anthropic/claude-fable-5-1" and the bare "claude-fable-5-1" are the same
    model asked for two ways, and both resolve to "anthropic/claude-fable-5-1".
    Needed by the prompt hash, which has to be the same number in a dry run as
    in a live call, so it cannot wait for a client that needs credentials.
    """
    field_ = str(model_field or "").strip()
    if not field_:
        return "none"
    provider, _, rest = field_.partition("/")
    if provider in ("anthropic", "openrouter") and rest:
        return f"{provider}/{rest}"
    if "/" not in field_ and field_.startswith("claude-"):
        return f"anthropic/{field_}"
    return field_


def get_adapter(model_field: str, **kwargs):
    """Turn a book's `model` field into an adapter.

    "anthropic/<id>"        -> AnthropicAdapter (Claude via OpenRouter, no sampling settings)
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

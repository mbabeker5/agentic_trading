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

# The same seed on every call, so a provider that honours one gives the same
# answer to the same question. It is a date and it means nothing else.
FIXED_SEED = 20260906

# Sampling settings for a provider that accepts them. Temperature 0 and top_p 1
# together mean "take the most likely token every time", which is as close to a
# repeatable answer as a model gets.
PINNED_TEMPERATURE = 0.0
PINNED_TOP_P = 1.0

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


class AnthropicAdapter:
    """Claude through the official Anthropic SDK.

    Thinking is left at the model's default (adaptive; always on for Fable). Depth is
    controlled with `effort`. No `fallbacks` on purpose, see the module docstring.

    No temperature and no top_p, deliberately. Every model this project can name
    is from the generation that removed them: Fable 5 and 5.1, Opus 5 and 4.8,
    and Sonnet 5 all return a 400 if either is sent, because thinking is always
    on and sampling settings do not apply. Sending "temperature: 0" here would
    not pin anything, it would fail the call. What this adapter pins instead is
    everything it can: a fixed effort, no retries, and a hard timeout, and the
    exact request is written into ModelResponse.extra so a decision in the
    ledger can be reproduced without guessing what was asked.
    """

    provider = "anthropic"

    #: Sampling is not a knob on these models. See the class docstring.
    accepts_sampling = False

    def __init__(self, model: str, effort: str = "high", timeout_s: float = 300.0):
        import anthropic  # imported here so OpenRouter-only setups need not install it

        self.model = model
        self.effort = effort
        self.timeout_s = timeout_s
        api_key = os.environ.get("ANTHROPIC_API_KEY") or _load_env_file(
            SECRETS / "anthropic.env").get("ANTHROPIC_API_KEY")
        # max_retries=0 on purpose. A tick runs every five minutes and would
        # rather fall back to its rules than sit through three attempts at a
        # provider that is having a bad afternoon. The caller's own budget is
        # then the timeout and nothing more.
        options = {"timeout": timeout_s, "max_retries": 0}
        # A zero-argument client also picks up an `ant auth login` profile if one exists.
        self.client = anthropic.Anthropic(api_key=api_key, **options) if api_key \
            else anthropic.Anthropic(**options)

    def complete(self, system: str, user: str, max_tokens: int = 4000,
                 json_only: bool = False, schema: dict | None = None) -> ModelResponse:
        """One call. `schema` turns on structured output, which is strict here.

        Anthropic's structured output is output_config.format with a json_schema
        in it, and the API guarantees the reply validates against that schema.
        There is no separate strict flag to set, because it is the only mode.
        """
        import anthropic

        output_config: dict = {"effort": self.effort}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        elif json_only:
            system = system.rstrip() + "\n\nReply with a single JSON object and nothing else."

        request = {
            "model": self.model,
            "max_tokens": max_tokens,
            "output_config": output_config,
            "timeout_s": self.timeout_s,
            "max_retries": 0,
            "sampling": "not sent: this model rejects temperature and top_p",
            "structured_output": "json_schema" if schema is not None else
                                 ("instruction only" if json_only else "none"),
        }
        sent = {"request": request}

        t0 = time.time()
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                output_config=output_config,
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.APIStatusError as exc:
            return ModelResponse(False, "", self.provider, self.model,
                                 latency_s=time.time() - t0,
                                 error=f"HTTP {exc.status_code}: {exc.message}",
                                 extra=sent)
        except anthropic.APIConnectionError as exc:
            return ModelResponse(False, "", self.provider, self.model,
                                 latency_s=time.time() - t0, error=f"connection: {exc}",
                                 extra=sent)

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
                             resp.stop_reason, err, getattr(resp, "id", None),
                             extra=sent)


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
            "temperature": PINNED_TEMPERATURE,
            "top_p": PINNED_TOP_P,
            "seed": FIXED_SEED,
            "usage": {"include": True},
        }
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

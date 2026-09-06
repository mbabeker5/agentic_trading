# Models: which brain runs which book

Each strategy book names its model in one line of its yaml. The code in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/models.py` turns that line into a working connection. Two providers are wired up.

## How to name a model

| You want | Write in the book's yaml |
|---|---|
| Claude Fable 5.1 (Anthropic direct) | `model: anthropic/claude-fable-5-1` |
| Claude Opus 5 (Anthropic direct) | `model: anthropic/claude-opus-5` |
| GPT-6 Astra (OpenAI, via OpenRouter) | `model: openrouter/openai/gpt-6-astra` |
| GPT-6 Astra Pro (via OpenRouter) | `model: openrouter/openai/gpt-6-astra-pro` |
| Claude Fable 5.1 via OpenRouter instead of direct | `model: openrouter/anthropic/claude-fable-5.1` |
| Any other OpenRouter model | `model: openrouter/<id from https://openrouter.ai/models>` |

The word before the first slash picks the provider. Everything after it is the provider's own model id, copied exactly.

## GPT-6 Astra on OpenRouter

Looked up on OpenRouter's model list on 2026-09-06. Four ids exist:

| OpenRouter id | Context | Price per million tokens, in / out |
|---|---|---|
| `openai/gpt-6-astra` | 1,050,000 | $10 / $50 |
| `openai/gpt-6-astra:batch` | 1,050,000 | $5 / $25, slow batch lane, not for live decisions |
| `openai/gpt-6-astra-pro` | 1,050,000 | $10 / $50 |
| `openai/gpt-6-astra-pro:batch` | 1,050,000 | $5 / $25 |

For a book, use `openrouter/openai/gpt-6-astra`. It costs the same per token as Claude Fable 5.1 direct, which keeps a Fable versus Astra comparison fair on cost.

## Keys

- OpenRouter: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/.secrets/openrouter.env`, one line `OPENROUTER_API_KEY=...`. Gitignored. Test call made 2026-09-06 11:50 ET to `openai/gpt-6-astra`: reply "ready", 23 tokens in, 5 out, 3.6 seconds, key works. OpenRouter returned a cost of 0 in the immediate response; it finalises cost a few seconds after the call, so the ledger should treat 0 as "not yet known" rather than free.
- Anthropic: the code reads `ANTHROPIC_API_KEY` from the environment or from `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/.secrets/anthropic.env`. Neither exists on this Mac yet, so the Anthropic adapter is written but not yet exercised. Mo needs to create an API key at https://console.anthropic.com and save it to that file before a Claude-direct book can run.

## Deliberate choices

- **No silent fallback between models.** Anthropic offers an automatic switch to a different model when a request is refused. That is switched off here, because a book labelled "Fable" that quietly ran on Opus for a day would poison the comparison. A refusal or an error comes back as "no decision" and is logged as such.
- **Cost is recorded per call.** OpenRouter reports the exact dollar cost. For Anthropic direct the code multiplies tokens by the published price list. Both land in the ledger so model cost becomes a column in the month-end comparison.
- **Same prompt, same data, different model.** The adapter takes a system prompt and a user message and returns text. Nothing provider-specific leaks into the strategy prompts, so a model swap changes exactly one line.

## Quick test

```
source /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/activate
python /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/models.py openrouter/openai/gpt-6-astra
```

Prints token counts, cost and the reply. Costs a fraction of a cent.

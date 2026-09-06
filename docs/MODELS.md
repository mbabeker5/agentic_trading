# Models: which brain runs which book

Each strategy book names its model in one line of its yaml. The code in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/models.py` turns that line into a working connection. Two providers are wired up.

## Month one decision (Mo, 2026-09-06)

Every model call in month one goes through OpenRouter, one provider for all books, so cost and latency are measured the same way everywhere. The Anthropic-direct adapter stays in the code but is not used. The two ids in play:

- Claude Fable 5.1: `openrouter/anthropic/claude-fable-5.1` (books A, C, D)
- GPT-6 Astra: `openrouter/openai/gpt-6-astra` (book E)
- Book B uses no model at all.

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

- OpenRouter: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/.secrets/openrouter.env`, one line `OPENROUTER_API_KEY=...`. Gitignored. Test call made 2026-09-06 11:50 ET to `openai/gpt-6-astra`: reply "ready", 23 tokens in, 5 out, 3.6 seconds, key works. OpenRouter returns a cost of 0 in the response on this key, because the key routes through BYOK and bills an upstream account. The real figure only appears in the key's own counters. See "The cost field lies on this key" below. The ledger must treat a 0 as "not yet known", never as free.
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

## Month one cost estimate

Measured on 2026-09-06 with 12 real OpenRouter calls, total spend **$0.71**. Every
number below comes from what OpenRouter actually counted, not from a guess. The raw
figures are in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/model_cost_measurements.json`
and you can re-measure any time with:

```
source /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/activate
python /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/decide.py --measure        # free, estimates only
python /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/decide.py --measure --real  # spends about 70 cents
```

### The answer

A month of all five books costs somewhere between **$72 and $176**. Prompt caching
takes that to **$70 and $168**, a saving of about three to five percent, which is not
worth the complexity yet. See "Why caching barely helps here" below.

| Book | What it is | Model | Low | High | Low, cached | High, cached |
|---|---|---|---|---|---|---|
| A | Opening momentum, hybrid | Claude Fable 5.1 | $34.30 | $83.81 | $32.25 | $75.79 |
| B | Opening momentum, rules only | none | $0.00 | $0.00 | $0.00 | $0.00 |
| C | Insider buying | Claude Fable 5.1 | $7.73 | $16.58 | $7.73 | $16.58 |
| D | Congress trades | Claude Fable 5.1 | $5.38 | $16.05 | $5.38 | $16.05 |
| E | Opening momentum, hybrid | GPT-6 Astra | $24.52 | $59.53 | $24.52 | $59.53 |
| | **All five** | | **$71.93** | **$175.97** | **$69.88** | **$167.96** |

Book A costs more than book E on identical work. Same prompt, same packet, same
prices: Fable's tokeniser simply cuts this text into about 30 percent more pieces
than Astra's. That is a real cost difference between the two models and it belongs
in the month-end comparison, not in the noise.

### What was measured

One real call per prompt shape, capped at 600 output tokens.

| Strategy | Shape | Model | Tokens in | Tokens out |
|---|---|---|---|---|
| Opening momentum | pick | Fable | 6,581 | 600, hit the cap |
| Opening momentum | pick | Astra | 5,046 | 600, hit the cap |
| Opening momentum | manage | Fable | 2,125 | 600, hit the cap |
| Opening momentum | manage | Astra | 1,674 | **390, a complete answer** |
| Insider | pick | Fable | 7,859 | 600, hit the cap |
| Insider | manage | Fable | 2,238 | 600, hit the cap |
| Congress | pick | Fable | 6,719 | 600, hit the cap |
| Congress | manage | Fable | 2,133 | 600, hit the cap |

The momentum numbers come from the real 16 candidate packet at
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/decision_packet_2026-09-02_0936.json`.
The insider and Congress numbers come from realistic made-up packets of 15 candidates
and 8 open positions, built inside
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/decide.py`.

### A warning about the 600 token cap

Seven of the eight calls stopped because they ran out of room, not because they had
finished. Both month-one models think before they answer, and thinking is billed as
output. Fable spent the entire 600 token budget thinking and returned no text at all,
even with reasoning effort turned down to low. Astra thought less and got a complete
answer out in 390 tokens.

So the output side of this estimate is the weakest part of it. `decide()` ships with
caps of 1,500 tokens for a pick and 800 for a manage tick. If every reply ran all the
way to those caps the month would cost **$97 to $234** instead of $72 to $176. Treat
that as the ceiling and the table above as the floor, and replace both with real
numbers after the first week of dry runs, when the ledger has a month of actual
completion sizes in it.

### The assumptions behind the call counts

21 trading days.

| Book | Pick calls | Manage calls, low | Manage calls, high |
|---|---|---|---|
| A and E | 1 a day at 9:35, so 21 | 30 a day, 630 | 76 a day, 1,596 |
| C | 1 a day at 9:45, so 21 | 13 a day on 8 days, 104 | 13 a day on 21 days, 273 |
| D | 1 a day at 9:45, so 21 | 13 a day on 5 days, 65 | 13 a day on 21 days, 273 |

The momentum books wake every five minutes from 9:40 to 3:55, which is 76 ticks. The
high case assumes every one of those ticks has something open to think about. The low
case assumes 30 of them do and the rest have nothing to ask. The insider and Congress
books check twice an hour, 13 times a day, but only on days when they are holding
something: 8 days out of 21 for insider, 5 for Congress in the low case, every day in
the high case. Their pick call runs every day either way, because the sweep produces a
shortlist whether or not anything gets bought.

Book B never calls a model, so it is free by construction. That is the point of it: it
is the control that says whether the $72 to $176 bought anything.

### Why caching barely helps here

Both providers can cache the part of a prompt that never changes, which here is the
system prompt: 1,091 Fable tokens for a momentum pick, 633 for a manage tick. The rest
of every call is the packet, which is different every time and can never be cached.

The rules, checked on 2026-09-06:

For Claude Fable 5.1, caching is not automatic. You have to mark where the reusable
part ends with a `cache_control` breakpoint, up to four of them, and the marked section
has to be at least 512 tokens. A cache hit costs 0.025 times the normal input price,
which is 25 cents a million instead of 10 dollars, the cheapest cache read of any
Anthropic model. Writing to the cache costs 1.25 times normal for a five minute
lifetime, or 2 times for an hour. The lifetime is counted from when the writing request
starts, not when its answer finishes, so a 15 second reply eats 15 seconds of a five
minute cache.

For GPT-6 Astra, caching is automatic, nothing to switch on, but it only engages on the
part of the prompt that both matches exactly and is at least 1,024 tokens long. A hit
costs 0.1 times normal, a dollar a million. Writes cost 1.25 times normal even though
you did not ask for them. Cached content lasts 30 minutes.

Now the arithmetic, which turns almost entirely on how often a call repeats.

Pick calls run once a day. No cache survives 24 hours, so every pick call would be a
write and never a read, and caching would make it 25 percent more expensive on the
system portion for no benefit at all. Leave it off. The insider and Congress manage
calls run every 30 minutes, which with an hour-long cache means one write and one read
an hour. Two times normal plus a fortieth of normal, averaged, still costs a shade more
than paying full price twice. Leave that off too.

That leaves the momentum manage calls, every five minutes, which is the one place
caching wins. An hour-long cache needs seven writes a day and everything else reads at
25 cents a million. Book A saves $2.05 in the low case and $8.02 in the high case. Book
E saves nothing.

Book E gets nothing because Astra's stable prefix here is its system prompt, 756 tokens
for a pick and 439 for a manage tick, and both are under OpenAI's 1,024 token floor. If
we ever want book E to cache, the fix is to move stable content (the schedule block, the
account block) to the front of the user message until the unchanging prefix clears
1,024 tokens. Worth watching `usage.prompt_tokens_details.cached_tokens` in the ledger
either way, since it is the only way to know whether a cache is being hit.

One trap to remember if caching is ever switched on: changing the JSON schema in
`response_format`, or editing a single word of a system prompt, invalidates the whole
cache. That is another reason the ledger records a Prompt Hash on every row.

### The cost field lies on this key

Every call in this measurement came back with `cost: 0` in the response body. That is
not a rounding error and it is not free. This OpenRouter key routes through BYOK (it
bills an upstream provider account), so the real figure never appears in the response
and only shows up in the key's own counters at `https://openrouter.ai/api/v1/key`, in
the field `byok_usage_daily`. The 12 calls above cost $0.713985 by that counter.

So the loop must never write a zero into the ledger's Model Cost USD column. Leave the cell blank when the reported cost is 0 or missing, and work the
real number out from the token counts and the price list, which is what the table above
does. `agent/decide.py` returns `tokens_in` and `tokens_out` on every decision, so
multiplying by $10 and $50 a million is always available and is exact for these two
models.

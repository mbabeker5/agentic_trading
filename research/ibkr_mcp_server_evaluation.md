# IBKR MCP servers for paper trading: what is actually out there

**This report lives at:** `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/ibkr_mcp_server_evaluation.md`
**Written:** 2 September 2026
**The question:** which community MCP server should a Claude Code agent use to place paper trades through IB Gateway on a Mac?

---

## The short version

I checked roughly sixty repositories. Most of what looks like an IBKR trading server is not one, and the single most repeated pattern is a README that advertises trading over code where the order path was never written.

Four findings drive the answer.

**Interactive Brokers now ships their own MCP server, and it deliberately cannot trade.** Released 28 July 2026. It stages order *drafts* that a human must submit by hand, and it has no paper mode at all. Details below, because it is easy to assume the official option solves this.

**The most popular community server does not talk to IB Gateway.** https://github.com/code-rabi/interactive-brokers-mcp, 213 stars, uses a different Interactive Brokers interface, cannot cancel or modify an order, has no historical price data whatsoever, and has an open unanswered bug reporting that paper login hangs forever.

**The most feature-complete server is proprietary.** https://github.com/YoungMoneyInvestments/ibkr-mcp has the best trading code in the ecosystem and a licence reading "All Rights Reserved" that forbids copying or modifying it. Off the table for legal reasons, not technical ones.

**Almost every remaining candidate was written in a single day and never run again.** This turned out to be the most useful filter I found, and it is what the recommendation rests on.

**Recommendation: https://github.com/patrickpxp/ibkr-mcp-server.** It is the only server that can place a trade through IB Gateway *and* shows four months of genuine iteration against a real broker. Two environment variables must be changed before you trust it, and I spell them out.

---

## Some jargon, once

Interactive Brokers offers two completely different ways for a program to trade. Nearly all the confusion in this space comes from mixing them up.

**The TWS socket API.** The classic route. You run a desktop program, either Trader Workstation (the full trading terminal) or IB Gateway (the same connection with no user interface), and your code opens a network connection to it. Paper and live accounts are separated by **port number**, and this is the most important safety fact in this report:

| Port | What it is |
|---|---|
| **4002** | IB Gateway, **paper** account |
| 4001 | IB Gateway, live account |
| **7497** | Trader Workstation, **paper** account |
| 7496 | Trader Workstation, live account |

Point your code at 4002 and it cannot reach real money, because the live account is not listening there. That property is what every good server here builds its safety on.

Three Python libraries speak this protocol:

- **`ib_insync`**, the one everyone used for years. Its author died in 2024, the repository at https://github.com/erdewit/ib_insync is archived, and the last release was July 2023. Avoid it for new work.
- **`ib_async`**, the community fork that took over, at https://github.com/ib-api-reloaded/ib_async. The one to use, with caveats below.
- **`ibapi`**, Interactive Brokers' own package. Correct but awkward, so almost nobody builds an MCP server on it directly.

**The Client Portal Web API.** A newer, separate route. You run a small Java program that serves a web interface on your own machine at port 5000, log in through a browser, and your code makes ordinary web requests to it. There is no paper port. You choose paper or live **when you log in**, so the safety property above does not exist. It does not need IB Gateway, which is its attraction, but it needs **a browser login every single day**, which cannot be scripted. That daily login is the reason this whole architecture is wrong for an unattended agent, and it rules out the two most popular projects in the field.

---

## The filter that actually mattered

Star counts are worthless here. The 213-star project cannot cancel an order and the 65-star project is not even an MCP server. What separates working software from a plausible-looking dump is **whether anyone ever ran it and fixed what broke.**

I pulled the commit history for every finalist:

| Repository | Commits | Distinct days worked | Span |
|---|---|---|---|
| https://github.com/patrickpxp/ibkr-mcp-server | 65 | **14** | 8 Jan to 8 May 2026 |
| https://github.com/Hellek1/ib-mcp | 37 | **16** | Aug 2025 to Jul 2026 |
| https://github.com/nganiet/safe-ibkr-mcp | 50 | 5 | 30 May to 15 Jun 2026 |
| https://github.com/danielkristofik/mcp_claude_ibkr | 14 | 4 | Feb to Apr 2026 |
| https://github.com/jgalea/ibkr-mcp | 3 | **1** | 7 Jul 2026 |
| https://github.com/MrRolie/mm-ibkr-mcp | 2 | **1** | 13 Aug 2026 |
| https://github.com/guramrit-dhillon/ibkr-mcp | 2 | **1** | 27 Feb 2026 |

Three of these are one-day dumps. One of them, https://github.com/MrRolie/mm-ibkr-mcp, is roughly 24,000 lines of source plus a much larger test suite, all committed twice on a single day. That is a lot of unreviewed code to put between an agent and a broker.

Only two projects show sustained work, and only one of those can trade.

---

## Every candidate I checked

Every number below came from the GitHub API on 2 September 2026, not from READMEs. "Paper default" is the port used if you configure nothing, read out of the source, because several READMEs state it wrongly.

### Servers that can place an order through IB Gateway

| Repository | Stars | Last commit | Library | Paper default | Order types | Licence |
|---|---|---|---|---|---|---|
| https://github.com/patrickpxp/ibkr-mcp-server | 8 | 2026-05-08 | `ib_async` | 7497 | all types, bracket, one-cancels-all | MIT |
| https://github.com/nganiet/safe-ibkr-mcp | 0 | 2026-06-15 | `ib_async` | **4002** | market, limit, stop | MIT |
| https://github.com/MrRolie/mm-ibkr-mcp | 0 | 2026-08-13 | `ib_insync` | **4002** | all types, trailing, bracket | MIT |
| https://github.com/guramrit-dhillon/ibkr-mcp | 3 | 2026-02-27 | `@stoqey/ib` (Node) | **4002** | all types, bracket, **modify** | MIT |
| https://github.com/jgalea/ibkr-mcp | 0 | 2026-07-07 | `ib_async` | 7497 | market, limit only | MIT |
| https://github.com/danielkristofik/mcp_claude_ibkr | 6 | 2026-04-27 | `ib_insync` | 7496 (**live**) | market, limit, stop, stop-limit | MIT |
| https://github.com/YoungMoneyInvestments/ibkr-mcp | 7 | 2026-08-16 | `ib_async` | 7497 | everything | **Proprietary** |
| https://github.com/jinyiabc/ibkr-mcp | 4 | 2026-01-19 | `ib_insync` | 7497 | market, limit | MIT |

Two structural gaps worth knowing before you plan a strategy:

**Modify-order support barely exists.** Only https://github.com/guramrit-dhillon/ibkr-mcp has it. Everywhere else, changing an order means cancelling and replacing it.

**Multi-leg option combos are effectively unavailable.** I checked for the combo-leg code across every serious candidate and found it in exactly one project, https://github.com/psyb0t/ibkr-httpapi, which has no safety rails at all and is a four-container Docker stack you must partly build yourself. If you need option spreads, that is a build-it-yourself problem.

### Servers that cannot place an order, whatever the README says

Several of these are the best-written code in the field. They are still useless for placing a trade.

| Repository | Stars | Last commit | Why not |
|---|---|---|---|
| https://github.com/Hellek1/ib-mcp | 17 | 2026-07-16 | Read-only by design, hardcoded |
| https://github.com/osauer/canary | 8 | 2026-08-27 | Read-only in every build, by stated policy |
| https://github.com/ArjunDivecha/ibkr-mcp-server | 35 | 2025-07-23 | **Archived.** Order code never written |
| https://github.com/adwiteeymauriya/ibkr-portfolio-builder-mcp | 19 | 2026-06-08 | Read-only enforced in three places |
| https://github.com/henrysouchien/ibkr-mcp | 3 | 2026-04-30 | No order code. Noncommercial licence. Defaults to a **live** port |
| https://github.com/seriallazer/ibkr-mcp-server | 65 | 2026-03-19 | **Not an MCP server at all** |

Two notes.

**The 65-star one is not an MCP server.** The whole repository is about 8 kilobytes: a small web application with one endpoint that reads your portfolio. No MCP library, no tool registration, nothing an MCP client could speak to. Someone opened an issue titled "Not an MCP server?!" in August 2025 and nobody has answered. A useful reminder that stars here measure README quality, not code.

**https://github.com/osauer/canary is the most professionally run project in the field**, written in Go with its own implementation of the Interactive Brokers wire protocol, signed releases and 26 published versions. Its maintainer has deliberately decided agents should not place orders: trading lives in a separate command-line tool with a policy that explicitly rejects agent-initiated writes. Worth respecting the reasoning, but it is a closed door.

### The official Interactive Brokers server, which cannot help

Released 28 July 2026. Easy to miss because it is a hosted endpoint, not a repository, so searching GitHub never finds it.

- Endpoint: `https://api.ibkr.com/v1/api/mcp-public`
- Registered as `com.ibkr/interactive-brokers-ibkr`, version 1.1.6
- Announcement: https://www.interactivebrokers.com/en/general/about/mediaRelations/7-28-26.php
- Product page: https://www.interactivebrokers.com/en/trading/ai-integrations.php
- No install, no IB Gateway, no API keys. You add a connector URL and log in on Interactive Brokers' own page.

**It cannot place orders and it cannot use a paper account.** Its one order-shaped tool stages a draft into an "AI Instructions" tab that a human must then submit by hand. Instructions never become orders on their own. Everything else is reads: positions, cash, margin, profit and loss, transaction history, option chains, risk exposure. And it offers no paper mode, because the account picker only shows accounts you can actually trade on.

There is also an open bug where every tool taking an integer or a list fails validation, filed with Interactive Brokers as ticket 584301.

---

## The recommendation: patrickpxp/ibkr-mcp-server

**Repository:** https://github.com/patrickpxp/ibkr-mcp-server
**Licence:** MIT
**Library:** `ib_async`, pinned exactly at 2.0.1
**History:** 65 commits across 14 working days, January to May 2026
**Stars:** 8, which is the most of any trading-capable server on the maintained library

### Why this one

Its commit log is the best evidence in this entire survey that a human actually ran the thing against Interactive Brokers and fixed what broke:

- "Mark IBKR Flex 1001 errors retryable"
- "Handle IBKR market data snapshot failures"
- "Stabilize IBKR sessions and simplify client config"
- "Expose IBKR timeout in health check"

Those are not the commits of someone generating a project and walking away. Those are the commits of someone hitting Interactive Brokers' real, awkward behaviour and dealing with it. Nothing else that can trade has a log like this. Its notes also record the trading tools being checked against a live paper account.

To be clear about one thing: the four names in the history are all the same person plus one bot. This is still a single-author project. The difference is four months of iteration rather than one afternoon.

### What it gives you

**Orders:** `ibkr_place_order`, `ibkr_bracket_order`, `ibkr_oca_group`, `ibkr_cancel_order`, `ibkr_global_cancel`, `ibkr_preview_order`, `ibkr_exercise_options`.

The place-order tool passes fields straight through to the library, so market, limit, stop, stop-limit, trailing stop and trailing-limit all work provided the agent names the fields correctly. `ibkr_preview_order` calls Interactive Brokers' own what-if check and returns their real margin and commission estimate before you commit. `ibkr_global_cancel` is a genuine one-call kill switch.

**Reads, and these are the deepest of any candidate:** portfolio, account summary, account values, open orders, executions, transactions, historical bars, historical ticks, head timestamp, snapshot quotes with option Greeks, market depth, option chains, three news tools, fundamentals, scanners, symbol search, contract details, plus a full family of Interactive Brokers statement reports.

The quote tool retries with delayed data when it hits a subscription error, which matters because paper accounts usually have no live data subscription.

**Safety, three gates closed by default.** I verified each in the source rather than the README:

- `IBKR_ENABLE_TRADING` defaults to false, and every mutating tool is blocked until you set it
- every mutating tool requires an explicit `confirm=true`
- order placement defaults to `dry_run=True` and `transmit=False`

### Two things you must change before trusting it

**One: the bind address. This is the important one.** It runs as a container exposing a web endpoint, and `MCP_BIND_HOST` defaults to `0.0.0.0`, which means every network interface. The README admits there is **no authentication on that endpoint at all**. On a laptop that joins café or hotel wifi, that is an unauthenticated trading endpoint reachable by anyone on the same network. Set it to `127.0.0.1` so it only listens to your own machine, and treat that as mandatory rather than advisable.

**Two: the port.** It defaults to 7497, which is Trader Workstation paper. For IB Gateway paper you want `IBKR_PORT=4002`. Note a small wrinkle: it works out whether you are on paper by looking the port up in a table that only knows 7496 and 7497, so on 4002 its health check reports the mode as "custom" rather than "paper". The connection is still correct, the label is just unhelpful.

### Honest weaknesses

- **No modify tool.** Cancel and replace instead. I checked for this specifically, because one source claimed it had one and it does not.
- **`transmit=False` by default parks the order.** It sits in the trading window waiting for a human click. For genuinely unattended paper fills the agent has to ask for transmission, and once it does, the safety story is thinner than the three defaults suggest.
- **No quantity, value or symbol caps.** The author lists these as unbuilt.
- **Docker and a web endpoint**, rather than the simpler direct-pipe transport. More moving parts.
- Single author, and quiet since May 2026.

---

## The close alternative: nganiet/safe-ibkr-mcp

**Repository:** https://github.com/nganiet/safe-ibkr-mcp
**Licence:** MIT
**Library:** `ib_async` 2.0.1 or newer, plus FastMCP
**History:** 50 commits across 5 days, all in early June 2026

Choose this one instead if your priority is **the strictest possible guarantee that the agent cannot touch real money**, and you can live with only market, limit and stop orders.

It is the only server where paper safety is the architecture rather than a warning. Its defaults are port **4002**, read-only **on**, live trading **off**, and it **refuses to start** as a writable server pointed at a live port. Its safety layer is the best-designed I read:

| Guard | What it does |
|---|---|
| **Two-step orders** | `preview_order` checks the order and returns a single-use token that expires in 60 seconds. It places nothing. Only `confirm_order(token)` places. |
| **Real margin preview** | The preview calls Interactive Brokers' own what-if check. |
| **Read-only builds** | With read-only on, the write tools are **never registered**, so the model cannot see or call them. This holds even if your client auto-approves everything. |
| **Size and value caps** | Reject oversized orders by share count or dollar value. |
| **Symbol allowlist** | Restricts what can be traded at all. |
| **Kill switch** | Creating a file at `/Users/mtalib/.ibkr-mcp/KILL` freezes every write instantly, no restart. |
| **No double-placing** | A retried confirmation returns the original result instead of placing a second order. |

Two details raised my confidence that this was written by someone thinking clearly. Its documentation admits its own weakness rather than hiding it: a dollar cap can only be enforced when a price is known, so **a plain market order slips past the value cap**, and the advice is to use limit orders when you want a hard ceiling. That is honest and correct. And market data defaults to **delayed** data, which Interactive Brokers serves free, so quotes work on a paper account with no subscription.

It also has a real integration test that connects to port 4002 and asserts the connection reports itself as paper.

It uses the simple direct-pipe transport, so there is no network endpoint to secure. That is a genuine advantage over the recommendation.

**Why it is second, not first.** Market, limit and stop only: no bracket, no trailing stop, no modify. No live prices attached to position reads. Nobody but the author appears to have run it, so there are no bug reports, which is not the same as no bugs. And **the install command in its README does not work**: it tells you to run `uvx ibkr-mcp-guarded`, but I checked the Python package index directly and that package returns HTTP 404. It was never published. You must clone the repository and install from source.

---

## A trap on the package registries

**Do not run `uvx ibkr-mcp` or `pip install ibkr-mcp`.** The Python package name `ibkr-mcp` belongs to an unrelated **proprietary, all-rights-reserved** project shipped as a compiled binary built to resist inspection. Its default port is 4001, which is IB Gateway **live**. Most of its tools are commented out, so it barely functions. It is none of the repositories discussed here.

The npm package name `ibkr-mcp` is the good TypeScript one. Same name, two registries, completely different software and licences.

There is also a family of automated republishes on both registries under names beginning `iflow-mcp_`, uploaded by a third party rather than the original authors. Treat them as unaudited. One ships a homepage URL still containing the placeholder `yourusername`.

Names that are what they claim: `ib-mcp` on the Python index is the read-only https://github.com/Hellek1/ib-mcp, and `interactive-brokers-mcp` on npm is the 213-star project below.

---

## Why not the popular ones

### code-rabi/interactive-brokers-mcp, 213 stars

By project health this looks like the winner: 187 commits, 77 published releases, a real test suite of 201 tests, three continuous-integration workflows, published provenance, and a proper response to an outside security review. Installing it is genuinely one line. It also has **the best-implemented read-only mode of anything I looked at**, working by not registering the mutating tools at all so the agent cannot even guess their names. Its login code is thoughtful too, rate-limiting two-factor attempts and stopping after five failures because Interactive Brokers permanently locks accounts after ten.

It still loses, on five counts.

**One: it does not use IB Gateway.** It uses the Client Portal Web API on port 5000. Ports 4002 and 7497 appear nowhere in it.

**Two: there are no historical price bars at all.** Interactive Brokers' web interface offers a history endpoint and this project never calls it. An agent that cannot see a past price cannot compute a moving average or judge a trend. Quotes are one-shot snapshots, and Interactive Brokers characteristically returns incomplete data on the first call for a symbol, which this code does not retry.

**Three: you cannot cancel or modify an order.** There is no counterpart to its place-order tool. The agent has full power to commit and none to retract. A mistaken limit order has to be cleaned up by you, by hand, in Interactive Brokers' own web portal.

**Four: the paper trading switch is close to decorative, and it fails toward live.** `IB_PAPER_TRADING` does not select a paper endpoint. Its only job is to click a checkbox on Interactive Brokers' web login page. So it does nothing at all unless you also enable headless mode, which the README never says. If Interactive Brokers changes their login page, the code logs a warning and carries on logging in anyway, which is fail-open on the one setting where you want fail-closed. And because the unset value evaluates to false, leaving the variable out does not mean "don't care", it means "untick the paper box". The string `DU`, which prefixes every Interactive Brokers paper account number, appears nowhere in the codebase. The server cannot tell paper from live and never tries.

**Five: an open, unanswered blocker on exactly this use case.** Issue #80, opened 6 August 2026 against the current release, reports that after entering correct paper credentials the login spinner never completes. The reporter's diagnosis was that the bundled gateway is an old build, and that checks out: its bundled authentication library carries a build date of 28 May 2021, with other components from 2017 and 2018. The gateway is roughly five years stale and nothing auto-updates it.

Three further practical notes. Installing pulls **264 megabytes across 611 files**, because it ships five platforms' Java runtimes to use one, so the first run can look like a hang. It leaves two background processes running on your Mac after Claude Code exits, by design, including a keep-alive that pings every 30 seconds forever. And it inherits Interactive Brokers' competing-session problem: **if you open the IBKR website or Trader Workstation while the agent is running, you can knock the agent's session out**, so you cannot comfortably watch your paper account in a browser while the agent trades it.

Credit where it is due: its Apple Silicon support is the best-engineered part of the whole survey, with a genuine native Java runtime selected automatically. But its automated tests only ever run on Linux, so the Mac path you would depend on is never exercised before release. And `place_order` accepts a `suppressConfirmations` flag that auto-answers the broker's own safety prompts, with the tool description actively demonstrating its use to the model. If you ever use this server, do not set that flag.

### rcontesti/IB_MCP, 140 stars

Good architecture on paper, with complete order routers including a preview endpoint. But its own endpoint table marks **every order endpoint untested**, its README says features may be incomplete, and the last commit was October 2025. It needs Docker with multiple containers and a browser login on the same machine. Not a fit.

### Hellek1/ib-mcp, and why the best code here cannot help

The highest-quality codebase I looked at, and the most sustained work in the field: 37 commits across 16 working days from August 2025 to July 2026, typed throughout, pre-commit hooks, real tests, a Docker image, BSD 3-Clause licence. Properly published, so `pip install ib-mcp` works.

It cannot trade. Its connection call is:

```python
await self.ib.connectAsync(self.host, self.port, self.client_id, readonly=True)
```

That `readonly=True` is not configurable, and there is no order code anywhere in the 1,277-line server.

**It is still useful to you.** It is the best available reference for the read side, it proves the `ib_async` and FastMCP combination works, and it is a good model to read before writing your own. Its option-chain and option-quote tools default to delayed data, so they work without a market data subscription. Its default port is 7497, so change that to 4002 for IB Gateway. Because it is structurally incapable of trading, it is also a safe second server to run alongside a trading one, on a different client id.

### ArjunDivecha/ibkr-mcp-server, 35 stars

**Archived, so permanently frozen.** Its README advertises `place_order` and promises "Place, modify, cancel orders (with safety checks)". None of it exists. It exposes eight tools, all read-only, mostly about short selling. Its three safety settings appear in the config file and are read nowhere else, so they are decorative. It also will not start on a clean install, because it imports a package that is not in its dependency list. Its one open issue is someone reporting that a tool from the README returns nothing, which is because the tool does not exist. Nobody replied, and now nobody can.

### YoungMoneyInvestments/ibkr-mcp, the painful one

Technically the best trading server in the ecosystem. On `ib_async`, updated 16 August 2026, with market, limit, stop, trailing, bracket and one-cancels-all orders, algorithmic order types, a real circuit breaker with loss and trade-rate limits, an approval gate on by default, and a read-only mode.

And you cannot use it:

> Copyright (c) 2026 Cameron Bennion. All Rights Reserved. [...] No part of the Software may be copied, modified, merged, published, distributed, sublicensed, or sold [...] except as expressly permitted in a separate written agreement.

That forbids the copying and modifying that installing and running it involves. Worth writing to the author if you want these features, since the code is good, but do not clone it and start editing. It also has a real bug: its command-line entry point never reads its own environment configuration, so every documented environment variable is silently ignored and you must pass the port as a command-line argument.

### The one-day dumps

https://github.com/MrRolie/mm-ibkr-mcp, https://github.com/guramrit-dhillon/ibkr-mcp and https://github.com/jgalea/ibkr-mcp all have genuinely good designs and none of them shows any evidence of having been run.

`MrRolie` has the widest order coverage and the most thorough guards of anything with a usable licence: port 4002 by default, trading disabled and dry run enabled by default, enforced quantity and value limits, a symbol allowlist, an audit trail with keys that prevent double-placing, and an emergency stop. Against it: the **deprecated `ib_insync`**, roughly 24,000 lines committed twice on one day, and order approvals that route through a Telegram bot by default, where the way to remove that layer is a mode called `yolo`.

`guramrit-dhillon` is the only server with modify, bracket, one-cancels-other and preview together, defaults to port 4002 and read-only on, and has quantity caps, value caps, a symbol allow and deny list, an out-of-hours block and a daily loss circuit breaker. Install is one line, `npx ibkr-mcp`. Against it: two commits on 27 February 2026, one published release, nothing since.

`jgalea` has the most current stack of anyone, `ib_async` 2.x with FastMCP 3.4, the cleanest Claude Code registration, the best-validated set of bar sizes, delayed market data by default, and the strongest read-only enforcement I saw anywhere: the order tools are unregistered *and* the library's mutating methods are replaced with stubs that raise. Against it: **market and limit orders only**, so protective exits have to come from somewhere else, and three commits on a single day in July 2026.

Any of the three could be the right answer after someone actually runs it for a week. None of them has been.

---

## The fallback: writing your own

If the recommendation does not survive contact with reality, do not start from an empty file. **Fork https://github.com/nganiet/safe-ibkr-mcp**, which is MIT licensed and already contains the safety layer that is the genuinely fiddly part, and add the missing order types.

Either way, `ib_async` does more of the work than people expect. I read its source rather than trusting memory. It already ships these order building blocks:

`Order`, `MarketOrder`, `LimitOrder`, `StopOrder`, `StopLimitOrder`, `BracketOrder`, `OrderComboLeg`, plus price, time, margin, execution, volume and percent-change conditions.

And these methods, in camel case, each with an async variant:

`connect`, `qualifyContracts`, `placeOrder`, `cancelOrder`, `reqGlobalCancel`, `whatIfOrder`, `bracketOrder`, `oneCancelsAll`, `accountSummary`, `positions`, `portfolio`, `pnl`, `openTrades`, `fills`, `executions`, `reqTickers`, `reqMktData`, `reqMarketDataType`, `reqHistoricalData`, `reqHeadTimeStamp`, `reqMatchingSymbols`, `reqContractDetails`.

Three of those matter more than they look:

- **`bracketOrder(action, quantity, limitPrice, takeProfitPrice, stopLossPrice)`** builds a complete three-order bracket for you. Close to free.
- **`oneCancelsAll`** groups orders so filling one cancels the rest. Also nearly free.
- **`reqGlobalCancel`** cancels everything at once. A real kill switch, one line.

### Proposed tool list and effort

| Tool | What it does | Lines |
|---|---|---|
| `health` | Connect if needed, report connected and paper-or-live | 25 |
| `account_summary` | Net liquidation, cash, buying power | 30 |
| `positions` | Open positions with average cost | 30 |
| `quote` | Snapshot quote, delayed by default | 35 |
| `historical_bars` | Bars, passing bar size and duration through | 40 |
| `find_contract` | Resolve a symbol to a tradable contract | 45 |
| `preview_order` | Guard checks plus what-if, returns a token | 60 |
| `place_market_order` | Market order | 20 |
| `place_limit_order` | Limit order | 20 |
| `place_stop_order` | Stop and stop-limit | 30 |
| `place_bracket_order` | Wraps the built-in helper | 35 |
| `place_trailing_stop` | Raw order with type `TRAIL` | 30 |
| `open_orders` | List working orders | 30 |
| `cancel_order` | Cancel one, or all via global cancel | 30 |
| `modify_order` | Replace an order in place | 45 |

| Part | Lines |
|---|---|
| Tool implementations | 505 |
| Connection handling and server plumbing | 150 |
| Safety layer | 150 |
| Tests | 250 |
| **Total** | **900 to 1,100** |

Call it **two to four days** for a competent developer working with an AI assistant, and most of that is not typing. It is discovering how Interactive Brokers actually behaves. The commit log on the recommended project is a good preview of what that discovery looks like.

**The genuinely hard parts:**

1. **Contract qualification.** Turning "AAPL" into something the broker accepts sounds trivial and is where most of the time goes. Ambiguous symbols return several matches, and exchange and currency have to be right.
2. **Multi-leg options.** Leave this out unless you truly need it. It needs combo legs assembled by contract id in the right ratios, and it is where the remaining time would go.
3. **Orders are not synchronous.** `placeOrder` returns immediately with an object that is still empty. Fills arrive later as events. If you return that straight away, the agent sees a blank order and concludes it failed. Wait briefly for a status, or be explicit that the order is working and must be polled.

### Which safety guards are worth building

Worth it:

- **Pin the port to 4002 and refuse to start on 4001 or 7496.** The strongest single guard, because the live account is not reachable there.
- **Assert the account id starts with `DU`.** Confirmed: Interactive Brokers paper accounts are the live username with a `DU` prefix, so live `U12345678` becomes paper `DU12345678`. Cheap, independent second check.
- **A required confirmation argument on every order tool.** Costs nothing, stops the whole class of accident where a model places a trade while exploring.
- **A maximum order value cap**, remembering it can only be enforced when a price is known.
- **A kill switch**, which is one call to `reqGlobalCancel`.

Mostly theatre:

- **A symbol allowlist.** Useful for a narrow strategy, but on a paper account it mostly stops the agent doing what you asked.
- **A dry-run mode separate from the broker's own what-if.** Interactive Brokers already gives you a real preview with real margin numbers. A home-made simulation is strictly worse. Use theirs.

---

## The Python version question, which is less bad than the issue tracker suggests

`ib_async` depends on a package called `nest_asyncio`, which reaches into Python's internals to allow nested event loops. Those internals changed in recent Python versions, and there are two open issues on `ib_async` titled "does not work with py3.14", filed in January 2026 and still open. The alternative server pins Python 3.11 or 3.12 and cites exactly this.

**I tested the claim rather than repeating it, and on this machine it does not reproduce.** With Python 3.14.3, `ib_async` 2.1.0 and `nest_asyncio` 1.6.0:

- the library imports cleanly
- `nest_asyncio.apply()` succeeds
- `ib_async`'s own event-loop patching succeeds
- a connection attempt to port 4002 reaches the network and fails only with "connection refused", which is the correct answer when no gateway is running

So the connection path works on 3.14. Do not let the issue tracker scare you off a working setup.

**That said, use Python 3.12 if you are choosing fresh.** Three reasons, none of them panic:

1. The maintainers have not closed those issues, so some code path presumably still breaks, and I only exercised connection and setup, not a full trading session.
2. The alternative server's packaging declares 3.11 or 3.12 only, so installing it under 3.14 will be refused by the package manager regardless of whether the code would run.
3. `nest_asyncio` was last released in January 2024, so nobody is actively keeping it current with Python's internals.

If you already have a 3.14 environment, it is worth testing before rebuilding it.

`ib_async` itself deserves a caveat too. It has 1,729 stars and is not archived, but **its last commit to the main branch was 6 December 2025**, the 2.1.0 release. That is nine months of quiet with 93 open issues. Still much the best option, and far better than the archived `ib_insync`, but not a busy project.

One open issue worth knowing before you debug for an hour: #169, "connection to IBGateway drops immediately after successful API connection".

---

## Infrastructure: IB Gateway on macOS

### There is no Homebrew cask for IB Gateway

I checked rather than guessing. `brew search ib-gateway`, `brew search ibgateway` and `brew search interactive-brokers` all return nothing, and the Homebrew API returns HTTP 404 for every plausible cask name.

Scanning all 7,721 casks for Interactive Brokers turns up exactly two, both in the official tap and both current:

| Cask | Application | Version | What it is |
|---|---|---|---|
| `trader-workstation` | Trader Workstation | 10.50.1e | The full trading terminal. Paper port **7497** |
| `ibkr` | IBKR Desktop | 3.4g | Their newer desktop app |

So **`brew install --cask trader-workstation` gets you Trader Workstation, and there is no Homebrew route to IB Gateway.**

That is worth pausing on. Every server here supports both, differing only by port. If installing through Homebrew and getting updates that way matters more than running the lighter program, use Trader Workstation on port 7497. IB Gateway's advantages are that it is lighter and has no user interface in the way. This also matters because the recommended server already defaults to 7497.

### Downloading IB Gateway directly

I verified these by request rather than reading them off a page. Each returned HTTP 200 with a real file size.

**Apple Silicon, stable (the one you want):**
```
https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-macos-arm.dmg
```
About 281 megabytes.

**Intel Macs, stable** (note the path says `macosx`, not `macos`):
```
https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-macosx-x64.dmg
```

**Apple Silicon, latest channel:**
```
https://download2.interactivebrokers.com/installers/ibgateway/latest-standalone/ibgateway-latest-standalone-macos-arm.dmg
```
About 287 megabytes.

The human-readable pages are https://www.interactivebrokers.com/en/trading/ibgateway-stable.php and https://www.interactivebrokers.com/en/trading/ibgateway-latest.php, though both block automated fetching, which is why I verified the files themselves.

**Watch the architecture in those filenames, because it is genuinely easy to get wrong.** The Apple Silicon build ends `macos-arm.dmg` and the Intel build ends `macosx-x64.dmg`. One letter and one word apart, and the Intel one is the more conventional-looking name, so it is the easy mistake. This Mac is Apple Silicon, so the `arm` file is the right one. Interactive Brokers' download pages do not make this obvious.

**Stable or latest?** Stable. "Latest" gets new features and new bugs, and the automation tooling is tested against stable. At 281 megabytes against Trader Workstation's 94 megabytes, the installer clearly bundles its own Java runtime, so you do not install Java yourself.

### Settings you must change inside IB Gateway

Nothing connects until you do this, under the API settings:

- **Enable ActiveX and Socket Clients.** The master switch, off by default. Nothing works until it is on.
- **Read-Only API.** If ticked, you can read but never trade. Useful deliberately, confusing accidentally, and a frequent cause of "why was my order silently ignored".
- **Trusted IP addresses.** Add `127.0.0.1` so connections from your own machine are not challenged.
- **Socket port.** Confirm it says 4002 for paper.
- **Master client ID.** Each connecting program needs its own. Two programs sharing one id will fight.

### The daily restart, and the paper-account dialog

IB Gateway forces a logout roughly once every 24 hours. For an agent meant to run unattended, that is the central operational problem.

There is a second, less known trap specific to paper accounts. Logging into a paper account makes Gateway show a dialog asking you to confirm you understand this is not a brokerage account, and **until that dialog is dismissed, API connections will not succeed.** A server that cannot connect on a fresh paper login is usually stuck behind this dialog, not broken.

---

## IBC, the auto-login helper, was retired on 1 September 2026

This is the most time-sensitive finding here.

**https://github.com/IbcAlpha/IBC was archived on 1 September 2026**, the day before this report. The final commit is titled "Revise retirement information and repository status", and the README now opens:

> This project has been retired, as of 1 September 2026. By 'retired', I mean that there will be no further development of IBC, other than completing work in progress at that date and fixing any significant newly reported bugs. Nor will IBC be actively supported on this repository.

The repository is read-only: no new issues, pull requests or comments. Releases remain downloadable and the author intends one final release to clear outstanding issues. After 23 years, support moves to a mailing list at https://groups.io/g/ibcalpha.

**Current facts:** 1,605 stars, 278 forks, 24 open issues frozen in place, Java, GPL 3.0. Latest release **3.24.2**, published 21 August 2026, with a macOS build named `IBCMacos-3.24.2.zip`, from https://github.com/IbcAlpha/IBC/releases/latest.

**No successor has emerged.** I checked every recently active fork. All have zero stars and look like personal mirrors rather than a continuation.

### What IBC does, and it does ship macOS support

It fills in your username and password, clicks the login button, dismisses the dialogs that block API access including the paper-account warning above, and restarts Gateway daily without you re-authenticating.

It genuinely supports macOS, which answers the launchd question directly. Among its shipped resources are `gatewaystartmacos.sh`, a macOS-specific start script, and **`local.ibc-gateway.plist`, a ready-made launchd configuration** for keeping Gateway running as a background service on a Mac. You do not have to write that yourself.

Two settings you must get right for a paper account:

- **`TradingMode=paper`.** Without it you get the live account.
- **`AcceptNonBrokerageAccountWarning`.** This dismisses the paper-account dialog. The user guide is explicit that until that dialog is accepted, Gateway will not allow API connections to succeed.

The user guide is at https://github.com/IbcAlpha/IBC/blob/master/userguide.md.

### Two-factor authentication: the honest answer

**Does two-factor apply to paper accounts? Yes, and you cannot turn it off.** I went looking for the usual "paper accounts are exempt" answer and it is not true. Interactive Brokers does not allow two-factor authentication to be disabled for paper trading accounts. Paper money still sits behind a real login.

IBC cannot complete it for you either. The user guide is blunt:

> Note that IBC cannot itself assist in the process, so you'll have to actually perform the necessary actions on your device yourself.

But the practical answer is much better than that sounds, and it is the most useful operational fact in this report.

**You authenticate roughly once a week, not once a day.** Interactive Brokers invalidates login tokens every **Sunday at 01:00 US Eastern time**. IBC's daily restart runs without re-authenticating. So the pattern is:

- Sunday, some time after 01:00 Eastern: you log in once and tap the alert on your phone.
- Every other day that week: IBC restarts Gateway on schedule, silently, with no phone involvement.

The cost of running an agent all week is one phone tap on a Sunday. That is a reasonable amount of human involvement and a very different proposition from the daily interruption people assume.

Two supporting settings matter. `ReloginAfterSecondFactorAuthenticationTimeout=yes` detects the three-minute alert timeout and restarts the login so you get another alert, repeating until you acknowledge one. `SecondFactorAuthenticationExitInterval` handles the case where you acknowledged but login still failed.

One caveat on method. The reliable setup is the IBKR Mobile app with its seamless authentication. If Interactive Brokers issued you a physical security card instead, IBC states plainly it cannot automate that login at all, and you should ask them to switch you to the mobile app.

Note the contrast with the other architecture: the Client Portal Web API route needs a **browser login every day**, on the same machine, and it cannot be scripted. That is the strongest practical argument for the socket API and IB Gateway, and it is why the two most popular servers in this field are a poor fit for unattended work.

### The better path on a Mac: ib-gateway-docker

Given IBC is retired, the more maintained option is **https://github.com/gnzsnz/ib-gateway-docker**, which packages IB Gateway together with IBC in a container.

- 1,154 stars, 241 forks, only 9 open issues, MIT licence
- **last commit 29 August 2026**, days before this report, and not archived

It solves auto-login and the daily restart as a unit, and being a container it sidesteps the macOS-specific setup. The cost is Docker running on the Mac, and the container reaches the network differently, so the port your MCP server connects to needs care. Given the upstream helper is now frozen, this is where the maintenance energy has gone. It also pairs naturally with the recommended server, which is itself container-based.

A second alternative worth knowing: **https://github.com/QuantConnect/IBAutomater**, 144 stars, Apache 2.0, last commit 7 August 2026, actively maintained. It does the same auto-login and restart job and is backed by a company rather than an individual.

---

## Paper account practicalities

**Market data is the thing people get wrong.** A paper account does not automatically get live prices. Without a market data subscription you get delayed data, and many servers request live data, get nothing, and hand your agent empty quotes. This is why both recommended servers defaulting to delayed data matters more than it sounds: delayed data is free and it works. If your agent needs live prices, that is a paid subscription on the live account, which then extends to paper.

**Credentials.** A standalone paper account gets its own username. A paper account attached to a live one shares the live credentials.

**Account numbers.** Paper accounts are prefixed `DU`, live accounts `U`. Cheap safety check, worth using.

**One session at a time.** Interactive Brokers allows one brokerage session per username. If you log into the IBKR website or Trader Workstation while your agent is connected, you can knock it offline. If you want to watch the account while the agent trades it, ask Interactive Brokers for a second username.

---

## What I would actually do

1. **Install IB Gateway** from the verified Apple Silicon stable link above. There is no Homebrew route, so download it. If Homebrew management matters more than the lighter program, use `brew install --cask trader-workstation` and stay on port 7497, which is the recommended server's default anyway.
2. **Turn on the API** inside Gateway: enable socket clients, add `127.0.0.1` as trusted, confirm the port, and make sure Read-Only API is unticked when you are ready to trade.
3. **Python 3.12 is the safe choice**, though I confirmed `ib_async` connects fine on 3.14 too, so an existing 3.14 environment is worth testing before you rebuild it. The one hard constraint is that the alternative server's packaging refuses anything above 3.12.
4. **Stand up https://github.com/patrickpxp/ibkr-mcp-server**, and set two things before anything else: `MCP_BIND_HOST=127.0.0.1` so the trading endpoint is not exposed to your whole network, and `IBKR_PORT=4002` if you are on IB Gateway rather than Trader Workstation.
5. **Leave trading disabled and confirm the read path first.** Trading is off by default. Check that account summary, positions, quotes and historical bars all come back before you enable anything that can place an order.
6. **Then enable trading and place one order.** Preview it first, so you see the real margin and commission numbers, then place a single-share limit order. Remember that transmission is off by default, so decide deliberately whether you want the order to go through without a human click.
7. **Leave the daily restart until last.** Get a trade working by hand first. When you automate it, prefer https://github.com/gnzsnz/ib-gateway-docker over the retired IBC, and expect to tap your phone once a week on a Sunday.

If the recommendation frustrates you, the fallback is **https://github.com/nganiet/safe-ibkr-mcp** for a stricter paper guarantee and a simpler transport, accepting market, limit and stop orders only, and remembering you must install it from a clone because its published package does not exist.

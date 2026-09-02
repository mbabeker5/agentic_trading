# The guardrails

The guardrails are the part of the trading agent that says no. Every order the
agent wants to place is checked against a list of hard limits first, and if any
limit is broken the order never leaves the machine. Claude picks the stocks and
writes the reasoning; this code decides whether the resulting order is allowed
to exist. It cannot be talked out of it.

Two files matter:

- The limits, as plain numbers you can edit:
  `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/guardrails.yaml`
- The code that enforces them:
  `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/guardrails.py`

A reference copy of the same settings, for starting over from scratch, lives at
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/guardrails.example.yaml`,
and the tests are at
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_guardrails.py`.

**The numbers in guardrails.yaml are proposals, not decisions.** They came
straight out of the table in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/STRATEGY.md`
and are waiting on Mo's approval as of 2026-09-02.

This code never touches the network. It does not connect to IB Gateway, it does
not fetch prices and it cannot place an order. It only ever answers yes or no.

## Every rule, one line each

Each rule has a short id that gets written into the ledger, so you can count how
often each one fired over a month.

| Rule id | What it does |
|---|---|
| `paper_only` | While the settings say paper trading, refuses any order aimed at an account whose id does not start with DU. Every IBKR paper account starts with DU, so anything else might be real money. |
| `wrong_account` | Refuses any order aimed at an account other than the exact one named in the settings. |
| `kill_switch` | While the file `output/STOP` exists, the agent may only close positions. Nothing new is opened, and no fresh stop orders are sent either. |
| `sec_type` | Only ordinary shares and ETFs (IBKR calls these STK). Options are blocked twice over: by the allowed list and by the `allow_options` switch. |
| `currency` | US dollars only. |
| `blacklist` | Symbols on the blacklist are never traded, whatever anything else says. |
| `whitelist` | If the whitelist has anything in it, nothing outside it may be traded. An empty whitelist means no restriction. |
| `no_shorts` | A sell order is only allowed if we hold at least that many shares. Selling what we do not own, or selling more than we hold, is a short sale and is switched off. |
| `entry_window` | New positions may only be opened between 09:35 and 11:00 New York time on a weekday. 09:35 counts, 11:00 does not. |
| `outside_market_hours` | Nothing but a closing order may be placed outside 09:30 to 16:00 New York time on a weekday. |
| `flatten_time` | From 15:55 New York time only closing orders go through, so the day ends flat. |
| `daily_loss_cap` | Once today's loss (closed and open added together) reaches 2 percent of the balance the day opened with, no new positions for the rest of the day. Getting out is still allowed, and the decision comes back with `daily_halt` set to true. |
| `max_order_notional` | No single buy order may be worth more than 10,000 dollars. An entry with no limit price is refused too, because there is no way to know what it would cost. |
| `max_position_pct` | No single stock may grow past 10 percent of the account. What we already hold and what is sitting unfilled on order both count towards that. |
| `max_open_positions` | At most 5 stocks held at once. Buying more of something we already hold does not count as a sixth. |

A few things the code does besides refusing orders:

- Works out where the stop loss goes: 1.5 percent below the entry price, or the
  low of the first five minutes if that is nearer to entry, whichever gives the
  smaller loss. The answer is always below the entry price.
- Works out the biggest whole number of shares we may buy, given the 10 percent
  per stock limit, the 10,000 dollar order limit and the cash left over. It
  always rounds down, so the number it hands back always passes the check above.
- Answers the three clock questions the main loop asks all day: may we open
  something now, is the market open, and is it time to sell everything.

Two more behaviours are worth knowing about. Live trading cannot start by
accident: if the settings say `mode: live`, the file refuses to load at all
unless the environment variable `AGENTIC_TRADING_ALLOW_LIVE` is set to exactly
`yes` in the same shell. And the code never guesses about time. Every time
handed to it has to carry a timezone, so a bare "09:35" with nothing attached
raises an error rather than being taken to mean New York.

When an order is refused, the answer lists every rule it broke, not just the
first one, and each one comes with a sentence in plain English. For example:

> This order would put $11,000.00 into AAPL: $4,000.00 already held, $3,000.00
> on order and $4,000.00 from this order. That is 11.0 percent of the
> $100,000.00 account, and the limit is 10 percent ($10,000.00).

## How to change a number

Open
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/guardrails.yaml`,
edit the number, save the file. That is the whole job. Nothing in the Python
needs touching, and the agent reads the file when it starts, so a change takes
effect on the next run.

Three things trip people up:

1. Percentages are written as whole numbers. Ten percent is `10`, not `0.10`.
   Anything at or below 0, or above 100, is rejected with a message saying so.
2. Times need quotation marks. Write `"11:00"`, not `11:00`. Without them the
   yaml format turns a time into a number, and the file refuses to load with a
   message telling you to put the quotation marks back.
3. The times have to run forwards: `scan_start`, then `pick_time`, then
   `entries_until`, then `flatten_at`, then `market_close`. Out of order and the
   file will not load.

If you get a setting wrong, nothing silently misbehaves: the agent stops on
startup and tells you which setting in which file is the problem and what a
valid value looks like.

Some names look like limits but are not checked on individual orders:
`universe.price_floor`, `universe.min_avg_volume` and everything under
`scanner:` shape the morning shortlist instead, so they belong to the scanner
rather than to this file.

## How to run the tests

From the project folder:

```
cd /Users/mtalib/workspace_repos/personal_repo/agentic_trading
./venv312/bin/python -m pytest -q
```

Or in one line from anywhere:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python -m pytest -q
```

You want to see something ending in `165 passed`. It takes under a second, and
no account or internet connection is needed. Run it after changing any number in
the yaml file: several tests read the real settings file, so they will tell you
straight away if a change broke something.

To see the individual test names as they run, swap `-q` for `-v`. To run one
group, name it:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python -m pytest -q -k daily_loss
```

## Judgement calls made where the strategy spec was quiet

Written down here so they can be argued with rather than discovered later.

- The kill switch also blocks new stop orders. With `output/STOP` in place only
  exits and flattens go through. A halted agent should close its positions
  itself rather than leave fresh orders parked at the broker.
- Size limits apply to entries only. An exit is never refused for being too big
  or for having no limit price. Blocking the way out of a trade is the worst
  thing this code could do.
- Money already on order counts against the per stock limit. The account state
  carries one total for unfilled entry orders rather than a figure per stock, so
  that total is charged against whichever stock is being checked. With several
  entries in flight at once this is stricter than reality, which is the
  direction a limit should lean.
- Market hours run from `scan_start` to `market_close`. There is no separate
  setting for the market open, and in the proposed numbers `scan_start` is
  09:30, so it does the job. 09:30 counts as open, 16:00 counts as shut.
- Landing exactly on a limit is allowed, except for the loss cap. An order worth
  exactly 10,000 dollars goes through. A loss of exactly 2 percent counts as hit
  and stops new trades, because that is what a cap is for.
- Weekends are handled, holidays are not. Saturday and Sunday are refused, but
  this file has never heard of Thanksgiving, so it would think the market is
  open that day. Something upstream needs a holiday calendar before any of this
  runs with real money.

## One open question: shorting

The strategy spec was changed on 2026-09-02, while this module was being
written, to propose that shorting is allowed with mirrored stops and a new
gross exposure cap of 100 percent of equity. The settings file still says
`allow_shorts: false`, deliberately, and that needs a decision from Mo.

Turning the switch to `true` today would half work, which is the worst of the
three options. Sell orders would be permitted and the per stock and per order
limits would hold, including for a short position, whose negative market value
is counted as money at risk rather than as spare room. But two pieces the new
spec calls for do not exist yet:

- `stop_price_for` only ever returns a stop below the entry price. A short needs
  the mirror image, 1.5 percent above entry or the opening range high if that is
  nearer, and there is no setting or argument for it.
- There is no gross exposure cap. Longs and shorts added together are not
  measured against the account value anywhere, and the spec also asks for a $10
  price floor for shorts against the $5 floor everything else uses.

So the honest position is: shorting stays off until those two are built and Mo
approves the numbers. The switch is not a light to flick.

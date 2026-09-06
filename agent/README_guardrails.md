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

Since 2026-09-06 there are five books rather than one, and two more files matter
for that: the register of books at
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/books.yaml`,
and one `strategy.yaml` per book under
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/strategies/`. See
the five books section below.

A reference copy of the shared settings, for starting over from scratch, lives at
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/guardrails.example.yaml`,
and the tests are at
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_guardrails.py`
and
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_books.py`.

**The numbers in guardrails.yaml and in every strategy.yaml are proposals, not
decisions.** They came straight out of the tables in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/STRATEGY.md`,
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/STRATEGY_INSIDER.md`
and
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/STRATEGY_CONGRESS.md`,
and are waiting on Mo's approval as of 2026-09-06. Every strategy file says
`status: provisional` at the top so nothing can quietly graduate itself.

Two more files sit next door and work the same way, pure logic with no network:

- The rolling day trade count, one file per book:
  `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/pdt.py`
- The daily check that the books and the broker still agree:
  `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/reconcile.py`

Both have their own sections near the bottom of this file.

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
| `no_shorts` | A sell order is only allowed if we hold at least that many shares, unless the book has shorting switched on. Selling what we do not own, or selling more than we hold, is a short sale. |
| `short_price_floor` | A book that shorts only shorts shares priced at or above its own floor, 10 dollars in the momentum books against the 5 dollar floor everything else uses. Cheap shares are the expensive ones to be short of. |
| `shortable_required` | The easy to borrow rule. A short only goes out when all three of these hold: IBKR rates the name above 2.5 on its own 0 to 3 borrowing scale, which is what the broker calls easy to borrow; the borrow costs less than `universe.max_borrow_fee_pct` a year, 1 percent; and there are at least `universe.borrow_availability_multiple` times as many shares available to borrow as we mean to sell, 10 times. Whichever of the three failed gets its own sentence. A figure the broker did not report counts as a failure, because the expensive borrows are the ones nobody quotes. |
| `gross_exposure_cap` | Longs and shorts added together, ignoring which way they point, may never be worth more than 100 percent of the book. That is the line that says the book never borrows to buy. |
| `entries_per_day` | A book may only open so many brand new names in a day: 5 for the momentum books, 3 for insider, 2 for Congress. Adding to something already held does not count. |
| `entry_window` | New positions may only be opened between the book's pick time and its cut-off on a weekday, 09:35 to 11:00 for the momentum books. The start counts, the end does not. |
| `outside_market_hours` | Nothing but a closing order may be placed outside 09:30 to 16:00 New York time on a weekday. |
| `flatten_time` | From 15:55 New York time only closing orders go through. |
| `daily_loss_cap` | Once today's loss (closed and open added together) reaches 2 percent of the balance the day opened with, no new positions for the rest of the day. Getting out is still allowed, and the decision comes back with `daily_halt` set to true. |
| `max_order_notional` | No single buy order may be worth more than the book's limit, 15,000 dollars in the momentum books. An entry with no limit price is refused too, because there is no way to know what it would cost. |
| `max_position_pct` | No single stock may grow past 15 percent of the book (5 percent in the insider and Congress books). What we already hold and what is sitting unfilled on order both count towards that. |
| `max_open_positions` | At most 5 stocks held at once in the momentum books, 10 in the other two. Buying more of something we already hold does not count as one more. |
| `wrong_book` | Five books share one paper account, so every order says which book it came from. One tagged for another book is refused, and this is the only rule that refuses a closing order too, because selling another book's position is worse than a missed exit. |
| `symbol_exclusive` | Two books may never hold, or have a working order in, the same ticker. IBKR nets positions by symbol inside the one shared account, so a second book in the same name would disappear into the first book's line and neither could be reconciled afterwards. Blocks any entry, and any other order that would open or increase a position, in a name another book already has. Getting out of this book's own position is never blocked. Ties go first come, first served. |
| `halted` | Nothing goes out into a name that cannot be traded. While IBKR's halted tick says the name is halted only an exit or a flatten goes through. While it is sitting in a limit-up limit-down band, the step just before a volatility halt, no new position is opened. And if nobody could say whether the name is halted, no new position is opened either, because deciding to buy something without knowing whether it is even trading is the failure this rule exists to prevent. |

A few things the code does besides refusing orders:

- Works out where the stop loss goes: 1.5 percent below the entry price, or the
  low of the first five minutes if that is nearer to entry, whichever gives the
  smaller loss. The answer is always below the entry price. For a short it is
  the mirror image, 1.5 percent above entry or the high of the first five
  minutes if that is nearer, and always above the entry price.
- Works out where a trailing stop sits, once a position is far enough ahead to
  have switched one on. Nothing before that, and nothing at all for a book with
  no trailing rule in its settings.
- Says when a position has run out of time: 30 trading days in the insider book,
  60 in the Congress book, counting weekdays and skipping weekends.
- Works out the biggest whole number of shares we may buy, given the 15 percent
  per stock limit, the 15,000 dollar order limit and the cash left over. It
  always rounds down, so the number it hands back always passes the check above.
- Answers the three clock questions the main loop asks all day: may we open
  something now, is the market open, and is it time to sell everything. The last
  one is always no for a book that holds overnight.

Two more behaviours are worth knowing about. Live trading cannot start by
accident: if the settings say `mode: live`, the file refuses to load at all
unless the environment variable `AGENTIC_TRADING_ALLOW_LIVE` is set to exactly
`yes` in the same shell. And the code never guesses about time. Every time
handed to it has to carry a timezone, so a bare "09:35" with nothing attached
raises an error rather than being taken to mean New York.

When an order is refused, the answer lists every rule it broke, not just the
first one, and each one comes with a sentence in plain English. For example:

> This order would put $16,000.00 into AAPL: $9,000.00 already held, $3,000.00
> on order and $4,000.00 from this order. That is 16.0 percent of the
> $100,000.00 account, and the limit is 15 percent ($15,000.00).

## The five books

Month one runs five virtual books inside the one IBKR paper account
`DUT077572`, each with 100,000 dollars of its own and each tagging its orders so
fills can be told apart. Mo decided the lineup on 2026-09-06.

| Book | Strategy | Who decides | Order tag |
|---|---|---|---|
| A | Opening momentum | Claude Fable 5.1, through OpenRouter | `BOOK_A` |
| B | Opening momentum | Nobody. The rules alone, no model called | `BOOK_B` |
| C | Insider buying | Claude Fable 5.1, through OpenRouter | `BOOK_C` |
| D | Congress trades | Claude Fable 5.1, through OpenRouter | `BOOK_D` |
| E | Opening momentum | GPT-6 Astra, through OpenRouter | `BOOK_E` |

A, B and E run the same strategy on purpose. The only thing that differs is who
picks the names, which is the whole point: if A and E cannot beat B, the model
is not earning its cost. They point at the same numbers so they cannot drift
apart, and a test fails if they ever do.

Three files describe a book:

1. `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/books.yaml`
   is the register. It says which strategy folder each book uses, which model it
   calls, how much money it has, what its orders are tagged with, and the dates
   it runs between. At the top, a `shared` block holds the things all five have
   in common: the account, the gateway port, the ledger sheet and the timezone.
2. `strategies/<folder>/strategy.yaml` holds that book's own numbers. It only
   has to write down what differs from the shared settings; anything it leaves
   out is inherited from `config/guardrails.yaml`.
3. `strategies/<folder>/prompt.md` holds the words handed to the model, and
   belongs to the decision step rather than to the guardrails.

To get the limits for one book:

```python
from agent.guardrails import load_book_guardrails

g = load_book_guardrails("config/books.yaml", "C")
```

What comes back is an ordinary settings object, so `check_order`,
`max_shares_for`, `stop_price_for` and everything else work on a book exactly as
they worked before books existed. `g.book_id` says which book it is and
`g.order_ref` is the tag its orders carry.

Three differences between books are worth knowing about:

- **Books C and D hold overnight.** `flat_by_close` is false for them, so
  `must_flatten_now` never says yes and the 15:55 sell-everything rule does not
  apply. They are still barred from opening anything new after 15:50, which is
  the `entry_window` rule doing its normal job.
- **Books A, B and E may short.** They are the only ones with
  `allow_shorts: true`, and shorting brings three extra checks with it: the
  mirrored stop above the entry price, the 10 dollar floor, and the borrow
  confirmation from IBKR.
- **Every book is in `dry_run` mode today, and promotion is a hand edit.** See
  the next section.

## The three modes, and how a book gets promoted

A book's `mode` in `config/books.yaml` is one of three words.

| Mode | What the book does | What it is sized against |
|---|---|---|
| `dry_run` | Works out the order it would have sent, writes it down, sends nothing | its full `capital_usd`, 100,000 dollars |
| `tiny` | Sends real orders to the paper account | `money.tiny_capital_usd`, 2,000 dollars |
| `full` | Sends real orders to the paper account | its full `capital_usd` |

`BookConfig.effective_capital()` is the one place that answers "how much money
does this book actually have today", and `load_book_guardrails()` uses it to set
`money.starting_equity`. So a book on `tiny` really is held to 2,000 dollars all
the way down: its 15 percent per position cap becomes 300 dollars, not 15,000.
`BookConfig.sends_orders` is the short way to ask whether anything reaches the
broker, and it is false on `dry_run`.

`dry_run` is sized against the full capital on purpose. A rehearsal that sizes
its orders differently from the real thing is not a rehearsal.

**All five books are on `dry_run` today, 2026-09-06, and nothing promotes
itself.** No code anywhere moves a book up a mode. Nothing watches a book's
results and decides it has earned it. A promotion is Mo editing `books.yaml` by
hand, one book at a time, after the hub has approved that book.

When the hub approves a book, two fields are stamped on it in the same edit:

- `promoted_on`, the date the hub approved it
- `rules_commit`, the git hash of the rules it was approved against, so there is
  no argument later about which version of the numbers was signed off

Both are empty on all five books right now. A book set to `tiny` or `full`
without both of them filled in refuses to load, so changing the mode on its own
can never quietly start sending orders.

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
`universe.price_floor`, `universe.min_avg_dollar_volume` and everything under
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

You want to see something ending in `492 passed`. It takes under a second, and
no account or internet connection is needed. Run it after changing any number in
any of the yaml files: several tests read the real settings, the real register
of books and all four strategy files, so they will tell you straight away if a
change broke something.

To see the individual test names as they run, swap `-q` for `-v`. To run one
group, name it:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python -m pytest -q -k daily_loss
```

## The liquidity floor, in dollars rather than shares

Mo changed this on 2026-09-06. The floor used to be `universe.min_avg_volume`, a
million shares a day. It is now `universe.min_avg_dollar_volume`, 20 million
dollars a day, averaged over `universe.dollar_volume_sessions` of 30 completed
sessions.

A share count does not mean anything on its own. A million shares of a 6 dollar
stock is 6 million dollars of trading and a million shares of a 600 dollar stock
is 600 million, and only one of those can absorb our order without moving the
price. The dollar floor is also the wider of the two: a census run on 2026-09-04,
in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/liquidity_census/`,
found about 2,700 US names above 20 million dollars a day against about 1,950
above a million shares.

`universe.min_avg_volume` is still accepted by the loader, so an older settings
file keeps working, and it is still set in the insider and Congress strategy
files because their sweeps quote a share figure in the words they hand the
model. **The scanner no longer looks at it.** The filtering itself lives in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/scanner.py`,
and its own README explains what changed at Gateway.

The relative volume floor of 2 times normal is unchanged at `scanner.
rel_volume_min`, but it is now anchored at 09:35 explicitly, five minutes after
the open, because that is the moment the strategy makes its picks. That anchor
is in the scanner rather than here.

## The rolling day trade count

`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/pdt.py`

US regulators call anyone who makes four or more round trip day trades in five
business days, in a margin account, a pattern day trader, and require that
account to hold at least 25,000 dollars. The paper account is exempt because the
money is simulated, so the code counts day trades itself and month one measures
what the rule would cost rather than guessing at it.

A day trade is a buy and a sell of the same symbol, in the same book, on the
same trading day. Each book keeps its own count in its own file,
`output/pdt_BOOK_A.json` for book A, written the moment a fill arrives.

Two behaviours, set by `pdt.hard_limit` in each strategy file:

- **Books C and D are held to a hard limit of three.** They are meant to hold
  for weeks, so a day trade there is a mistake. The fourth in five business days
  is refused, with rule id `pdt_limit`.
- **Books A, B and E are never blocked.** Day trading is their whole strategy.
  The order goes out, and the answer comes back with `would_have_blocked` set to
  true so the loop can write down what the rule would have cost in a live
  account.

The rest of the numbers are in the `pdt` block of
`config/guardrails.yaml`: `max_day_trades_per_5_days` is 3, and
`assumed_live_equity_min_usd` is the 25,000 dollars nothing enforces on paper but
which month one's results should be read against.

Business days skip weekends, and they also skip anything in the new
`schedule.holidays` list. That list is empty today. It is the only place in this
project that knows about holidays at all; the order checks above still know
about weekends only, which is written up as a known gap further down.

This is the one check in the project that can refuse a closing order. On books C
and D the closing order is the day trade, so refusing it is the only way to
enforce the limit.

## The daily reconciliation

`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/reconcile.py`

Five books share one paper account, so the tag on an order is the only thing
tying a fill to the book that asked for it. This is the check that it still adds
up, and it enforces five rules:

1. For every symbol at least one book claims, what the books claim has to add up
   to exactly what the broker reports. Whole shares, tolerance of zero.
2. Every order working at the broker has to carry a reference belonging to a
   book, and that book has to know about the order.
3. Every working order a book believes in has to exist at the broker.
4. A position no book claims at all is an orphan.
5. No two books may claim the same symbol, whatever the quantities come to.
   Both of them stop, with kind `symbol_shared`. This is the other half of the
   `symbol_exclusive` guardrail above: that rule stops the second book getting
   in, and this one catches it if it ever did. It is checked separately from
   rule one because two wrong claims can still add up to the right number, so
   rule one can be perfectly happy while this is broken.

The paper account already holds 1 share of SPY from a manual test, so the loop
passes it in as an expected orphan and it is not treated as a problem until it
sells.

What comes back is one plain sentence per problem, the list of books to halt,
the orphans, and one `ok` flag. Any book named in a problem stops trading until
someone has looked, because a book that has lost track of its own positions will
size its next order off a number that is not true. An order reference belonging
to no book is the exception: it makes `ok` false but halts nobody, because there
is no book to blame and stopping the five that are behaving would be the wrong
trade.

Nothing in here talks to the network either. The loop gathers the broker's
positions and open orders, hands them over, and acts on the report.

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
  exactly 15,000 dollars goes through, and so does a short at exactly the 10
  dollar floor. A loss of exactly 2 percent counts as hit and stops new trades,
  because that is what a cap is for.
- Weekends are handled, holidays are not. Saturday and Sunday are refused, but
  this file has never heard of Thanksgiving, so it would think the market is
  open that day. Something upstream needs a holiday calendar before any of this
  runs with real money. The time stop counts trading days the same way, so a
  holiday inside a 30 day hold shortens it by a day.

Five more, added on 2026-09-06 with the books:

- The daily entry count is about new names. Adding to a stock the book already
  holds does not use one up, because that is the same idea getting bigger rather
  than a new one. Getting out never uses one either.
- Gross exposure counts what the loop hands it, if it hands anything. Five books
  share one account, so only the loop knows which positions belong to which
  book. Left blank, the check adds up every position it can see, which is right
  when a snapshot holds one book and too strict when it holds all five.
- The wrong book check refuses exits too. It is the only rule in here that
  blocks a closing order, and it is deliberate: an exit tagged for the wrong
  book would sell a different strategy's position, which is worse than a missed
  exit.
- The borrow confirmation is a setting rather than always on. `require_shortable`
  is true in the two books that short and absent everywhere else. A book that
  never shorts does not need to carry the rule, and the shared settings file
  keeps working exactly as it did.
- The momentum books have no trailing stop numbers. `docs/STRATEGY.md` offers "a
  target or a trailing rule" and sets no numbers for either, and the book is
  flat by 15:55 anyway, so both settings are left empty rather than invented.
  Write a pair of numbers into the strategy file and the trailing stop switches
  itself on.

Five more, added on 2026-09-06 with Mo's decisions on liquidity, borrowing,
modes and day trades:

- **An unreported borrow figure is a refusal, not a shrug.** If IBKR does not say
  what a borrow costs, or how many shares are available, the short does not go.
  The alternative was to skip the test when the number is missing, and that gets
  it exactly backwards: the borrows that cost 300 percent a year are the ones
  nobody quotes.
- **`shortable_level` wins over the old `shortable` flag, and the flag still
  works.** A caller that sets only the yes or no flag keeps the behaviour it had.
  A caller that sets the level gets the level. That way the loop can be updated
  without a flag day.
- **`dry_run` sizes against the full capital.** It would have been defensible to
  size a dry run against nothing, since nothing is sent. But the point of a dry
  run is to see the orders the book would really have placed, and a rehearsal at
  a different size is not one.
- **A promotion needs its paper trail before it will load.** Setting a book to
  `tiny` or `full` without `promoted_on` and `rules_commit` is refused. The
  strategy spec did not ask for that. It is here because a mode is one word in a
  yaml file, and one word should not be all that stands between a book and the
  broker.
- **The day trade counter cannot see the overnight position.** It only knows
  about fills, so the first fill of the day in a symbol always reads as opening
  one. A book that sells something it held overnight and buys it back the same
  afternoon has that buy back counted as a day trade, where a broker might not
  count it. That errs towards counting one too many, which is the safe direction
  for a limit.

Two more, added on 2026-09-06 with the review team's two blocking findings:

- **A halted name still takes an exit and a flatten, but not a fresh stop.**
  That is the same answer the kill switch gives, for the same reason: a halted
  agent, or a halted stock, should be got out of rather than have new orders
  parked against it at a price nobody can see. The alternative was to let stop
  orders through on the grounds that a stop is a way out, and it was rejected
  because a stop sent into a halt is really a bet on the reopen price.
- **An unknown halt status blocks an entry, but the field defaults to false.**
  Passing `None` means the loop asked IBKR and got no answer, and that refuses
  the entry with a sentence saying the halt status was not available. The
  default of `false` is a compatibility default rather than a judgement: it
  keeps every check written before halts were tracked behaving as it did. **The
  loop must always pass what the broker actually said, `None` included.** If it
  quietly stops setting the fields, this rule stops protecting anything, which
  is the one weak spot in it and is written down here rather than hidden.

## Shorting, and where it stands now

The strategy spec was changed on 2026-09-02 to propose shorting with mirrored
stops and a gross exposure cap. That was written up here as an open question,
because turning the switch on before the machinery existed would have half
worked, which is the worst of the three options. The machinery now exists, built
on 2026-09-06:

- `stop_price_for` takes a side. For a short it returns a stop 1.5 percent above
  the entry price, or the high of the opening five minutes if that is nearer.
- The gross exposure cap measures longs and shorts added together against the
  book, and refuses an entry that would push the total past 100 percent.
- The 10 dollar floor for shorts and the borrow confirmation from IBKR are both
  enforced, as `short_price_floor` and `shortable_required`. The borrow
  confirmation grew on 2026-09-06 from one yes or no flag into the three part
  easy to borrow rule in the table above: the broker's own borrowing level, what
  the borrow costs, and how many shares are actually there to borrow.

So `allow_shorts: true` now lives in the two momentum strategy files,
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/strategies/momentum_hybrid/strategy.yaml`
and
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/strategies/momentum_rules/strategy.yaml`.

`config/guardrails.yaml` still says `allow_shorts: false` and stays that way. It
is the shared floor every book starts from, and the two books that short say so
themselves. The insider and Congress books are long only, because insider and
Congress selling are not usable signals.

The numbers are still provisional, like everything else here. What has changed
is that switching them on is now a decision about the strategy rather than a
gap in the code.

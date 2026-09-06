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

**The two momentum strategy files are approved. The other two are still
proposals.** All of the numbers came straight out of the tables in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/STRATEGY.md`,
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/STRATEGY_INSIDER.md`
and
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/STRATEGY_CONGRESS.md`.
Mo approved the momentum numbers on 2026-09-06 as Momentum v2, so
`strategies/momentum_hybrid/strategy.yaml` and
`strategies/momentum_rules/strategy.yaml` say `status: approved` and carry a
changelog beside them naming every item that changed. The insider and Congress
files still say `status: provisional`, so nothing there can quietly graduate
itself. One momentum item is still open: shorting is **pending Mo's decision**
and stays switched off, which is the section at the bottom of this file.

The item ids used throughout this file, A1, A6, D3 and so on, are the ones in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/strategies/momentum_hybrid/CHANGELOG.md`,
so a rule here can always be traced back to the decision that made it.

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
| `entries_per_day` | A book may only open so many brand new names in a day: 10 for the momentum books, 3 for insider, 2 for Congress. Adding to something already held does not count. |
| `entry_window` | New positions may only be opened between the book's pick time and its cut-off on a weekday, 09:35 to 10:15 for the momentum books since Momentum v2 (item D3, was 11:00). The start counts, the end does not. |
| `outside_market_hours` | Nothing but a closing order may be placed outside 09:30 to 16:00 New York time on a weekday. |
| `flatten_time` | From the book's `flatten_at`, which is 15:45 in the momentum books, only closing orders go through. |
| `daily_loss_cap` | Once today's loss (closed and open added together) reaches the book's own cap on the balance the day opened with, no new positions for the rest of the day. That cap is 1 percent in the momentum books since Momentum v2 (item A7, was 2 percent) and 2 percent in the insider and Congress books. Getting out is still allowed, and the decision comes back with `daily_halt` set to true. |
| `weekly_loss_cap` | The book is down 4 percent or more over the calendar week, so it is paused for Mo to look at. Entries only: nothing new is opened, and every closing order still goes through. |
| `monthly_loss_cap` | The same idea over a calendar month, at 6 percent. Also a pause, also entries only. |
| `losing_streak_pause` | The book has finished down three trading days in a row. Also a pause, also entries only. A run of small losses is the shape a broken strategy makes, and no daily, weekly or monthly cap catches it on its own. |
| `sector_cap` | No more than 25 percent of the book's gross exposure limit in any one industry, which at the 100 percent gross cap is 25 percent of the book. A name whose industry the broker could not tell us is refused rather than counted as harmless. Entries only, so getting out is never blocked. |
| `account_symbol_cap` | No more than 15 percent of what all five books are worth on any one ticker, counted across every book rather than inside one. Entries only. |
| `max_order_notional` | No single buy order may be worth more than the book's limit, 10,000 dollars in the momentum books (item A6, was 15,000) and 5,000 in the other two. An entry with no limit price is refused too, because there is no way to know what it would cost. |
| `max_position_pct` | No single stock may grow past 10 percent of the book (item A6, was 15 percent), or 5 percent in the insider and Congress books. What we already hold and what is sitting unfilled on order both count towards that. |
| `max_open_positions` | At most 10 stocks held at once, in every book (item D1, the momentum books were 5). Buying more of something we already hold does not count as one more. |
| `wrong_book` | Five books share one paper account, so every order says which book it came from. One tagged for another book is refused, and this is the only rule that refuses a closing order too, because selling another book's position is worse than a missed exit. |
| `symbol_exclusive` | Two books may never hold, or have a working order in, the same ticker. IBKR nets positions by symbol inside the one shared account, so a second book in the same name would disappear into the first book's line and neither could be reconciled afterwards. Blocks any entry, and any other order that would open or increase a position, in a name another book already has. Getting out of this book's own position is never blocked. Ties go first come, first served. |
| `halted` | Nothing goes out into a name that cannot be traded. While IBKR's halted tick says the name is halted only an exit or a flatten goes through. While it is sitting in a limit-up limit-down band, the step just before a volatility halt, no new position is opened. And if nobody could say whether the name is halted, no new position is opened either, because deciding to buy something without knowing whether it is even trading is the failure this rule exists to prevent. |

A few things the code does besides refusing orders:

- Works out where the stop loss goes, `stop_price_for`. On a momentum book that
  is 10 percent of the name's 14 day average true range away from the entry
  price, pushed out to the edge of the opening range if it would otherwise land
  inside it. On the insider and Congress books it is the old percentage rule,
  8 percent and 10 percent below entry, or the low of the first five minutes if
  that is nearer. Either way the answer is always on the safe side of entry, and
  the mirror image holds for a short. There is a whole section on this below.
- Works out how many shares to buy so that being wrong costs one trade's worth
  of money, `shares_for_risk`. Also its own section below.
- Works out where a trailing stop sits, once a position is far enough ahead to
  have switched one on. Nothing before that, and nothing at all for a book with
  no trailing rule in its settings.
- Says when a position has run out of time: 30 trading days in the insider book,
  60 in the Congress book, counting weekdays and skipping weekends.
- Works out the biggest whole number of shares we may buy, `max_shares_for`,
  given the 10 percent per stock limit, the 10,000 dollar order limit and the
  cash left over. It always rounds down, so the number it hands back always
  passes the check above. This is the ceiling `shares_for_risk` is held to.
- Answers the clock questions the main loop asks all day: may we open something
  now, is the market open, is it time to start selling everything
  (`must_flatten_now`, from 15:45), and is the market order backstop due
  (`must_flatten_at_market_now`, from 15:55). The last two are always no for a
  book that holds overnight.
- Says how soon this book wants looking at again, in seconds, `next_tick_seconds`.
  Thirty between 09:35 and 11:00 while a momentum book is holding something, five
  minutes otherwise, thirty minutes for the insider and Congress books.

Two more behaviours are worth knowing about. Live trading cannot start by
accident: if the settings say `mode: live`, the file refuses to load at all
unless the environment variable `AGENTIC_TRADING_ALLOW_LIVE` is set to exactly
`yes` in the same shell. And the code never guesses about time. Every time
handed to it has to carry a timezone, so a bare "09:35" with nothing attached
raises an error rather than being taken to mean New York.

When an order is refused, the answer lists every rule it broke, not just the
first one, and each one comes with a sentence in plain English. For example:

> This order would put $11,000.00 into AAPL: $6,000.00 already held, $2,000.00
> on order and $3,000.00 from this order. That is 11.0 percent of the
> $100,000.00 account, and the limit is 10 percent ($10,000.00).

## The size rule: how many shares

Item A6, approved by Mo on 2026-09-06. This is the biggest change in Momentum
v2 and everything else hangs off it.

A momentum book risks 0.25 percent of its own equity on every trade, which is
250 dollars on a 100,000 dollar book. The share count is that money divided
by the distance from the entry price to the stop. A name with a wide stop gets
fewer shares and a name with a tight stop gets more, so every position loses
about the same amount when it is wrong. That is the whole point of it. Under the
old rule, a flat 15 percent of the book in each name, one halted stock gapping
20 percent overnight cost more than the entire daily loss cap.

The function is `shares_for_risk`, and the setting is `money.risk_per_trade_pct`.

The notional caps sit over the top of it as the ceiling, not beside it.
`shares_for_risk` works out what the risk budget wants, then puts that number
through `max_shares_for` and takes whichever is smaller, so the 10 percent per
stock limit, the 10,000 dollar single order limit and the cash left over are all
still absolute. A very tight stop would otherwise buy an enormous position,
which is exactly the failure the pair of rules exists to prevent. Landing under
the risk budget because a cap cut the order is fine. Landing over it is not.

Worked through: a name with a 25 cent distance from entry to stop wants 250
divided by 0.25, which is 1,000 shares. At 9.38 a share that is 9,380 dollars,
inside the 10,000 dollar cap, so 1,000 shares is what goes out. Had the entry
been 15 dollars, 1,000 shares would be 15,000 dollars, the cap would have cut it
to 666 shares, and the trade would have risked 166.50 dollars instead of 250.

**The insider and Congress books have no `risk_per_trade_pct` at all**, and it is
left empty in the shared `config/guardrails.yaml` too. `shares_for_risk` hands
those books straight to `max_shares_for`, so they size the old way, on the
5 percent per stock limit and the 5,000 dollar order limit, and nothing about
them changed. The same happens for any call whose stop is not on the right side
of the entry price, because there is no risk distance to divide by and refusing
to size at all would be worse than sizing the old way.

## The stop: an average true range, and the edge of the opening range

Item A1, approved by Mo on 2026-09-06. `stop_price_for` now takes an `atr`
argument, the name's 14 day average true range, which is the average size of one
session's price swing over the last 14 sessions counting the gap from the
previous close.

With an average true range in hand, and `risk.stop_atr_pct` set, the stop sits
that percent of the average true range away from the entry price. At the momentum
books' 10 percent, a stock whose average daily swing is 2 dollars stops 20 cents
away. That is roughly five times tighter than the 1.5 percent stop it replaced,
and a tight volatility-based stop is the one thing every published version of
this strategy has in common.

Then `risk.stop_outside_opening_range` has its say. The stop may never sit inside
the first five minutes' range, so whenever it would, it is pushed out: down to the
range low for a long, up to the range high for a short. Inside the range is inside
the noise the trade is made of, and a stop there would be taken out by the setup
itself.

**On a real gapper the range is wide, so the range edge is usually what actually
decides the stop.** A stock that has just jumped 12 percent on news does not
trade in a 20 cent band in its first five minutes. So the average true range
number often loses, the range low wins, and the stop ends up further from entry
than 10 percent of the average true range would have put it. That sounds like it
should cost more money, and it does not, because of the rule above it: a wider
stop means a bigger distance to divide by, which means fewer shares. The risk
stays 250 dollars either way. It just buys less stock.

**Without an average true range the old percentage stop stands in.** Pass no
`atr`, or run a book with no `risk.stop_atr_pct`, and `stop_price_for` behaves
exactly as it always did: `risk.stop_loss_pct` from entry, or the opening range
level if that is nearer. That is the real stop for the insider and Congress
books, at 8 and 10 percent. On a momentum book the 1.5 percent left in the
strategy file is a fallback and nothing more. It should never be reached, because
a name has to clear the volatility filter to be a candidate at all and that filter
needs the same number. It exists so a position carried in from an older state file
still gets a stop rather than none.

## The five limits added with Momentum v2

Item A8 brought three, item A9 brought two. All five refuse entries only. **Not
one of them can ever block an order that closes a position**, which is the same
promise every size limit in this file makes: blocking the way out of a trade is
the worst thing this code could do.

**`weekly_loss_cap`.** The book is down 4 percent or more over the calendar week,
measured against what it was worth when the market opened today, which is the
same base the daily cap uses. It refuses every entry and pauses the book for Mo
to look at. It refuses no exit, stop or flatten. Without a rule beyond the day, a
book could lose one percent a day for a fortnight and nothing would ever notice.

**`monthly_loss_cap`.** The same idea over a calendar month, at 6 percent. Same
answer: entries refused, book paused, exits untouched.

**`losing_streak_pause`.** The book has finished down three trading days in a
row. It does not care how much was lost. A run of small losses is the shape a
broken strategy makes, and no daily, weekly or monthly cap catches it on its own.
Same answer again: entries refused, book paused, exits untouched.

The three numbers behind them do not come from the broker. The loop works them
out from the book's own state files, one per book per day in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/`, using its
`loss_history` function: this calendar week, this calendar month, and the run of
losing days behind today. It hands all three over on the AccountState as
`week_pnl`, `month_pnl` and `consecutive_losing_days`. The guardrails own the
limits, the loop owns the arithmetic, and a caller that says nothing gets zeros,
which means nothing to see.

**`sector_cap`.** No more than 25 percent of the book's gross exposure limit in
any one industry. At the 100 percent gross cap that is 25 percent of the book,
which on a 100,000 dollar book is 25,000 dollars, or two and a half positions.
Ten
morning gappers in the same industry are one bet made ten times, not ten bets,
and this is the rule that says so.

A name whose industry the broker could not name is refused, not waved through.
That is deliberate, and it is the same answer an unknown halt status gets, for
the same reason: a limit that cannot be measured is not a limit, and
reading a missing answer as "fine" is how a rule quietly stops working. Getting
out of such a name is never blocked. The industry comes off the shortlist row,
where `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/scanner.py`
writes what IBKR's contract details said, and the scanner already names in its
own log every shortlisted name that came back without one.

**`account_symbol_cap`.** No more than 15 percent of what all five books are
worth on any single ticker, counted across every book rather than inside one.
The one ticker one book rule already stops two books buying the same name; this
is the second layer under it, and it also catches one book piling into a single
ticker. When the loop did not hand in the account wide figure, this book's own
equity stands in instead. That is the smaller number, so the cap comes out
tighter rather than looser, which is the safe direction to be wrong in. Unlike
the sector cap, this one is set in the shared `config/guardrails.yaml`, so all
five books carry it.

## Two more things Momentum v2 changed here

**There is no profit target on a momentum book.** `use_profit_target` is `false`
in both momentum strategy files, which covers books A, B and E (item A2). A
position leaves by its stop or at the close and by nothing else, because two
independent studies found that a target destroys this strategy's edge: the few
trades that run a long way are what pay for all the small losses. It is `true`
everywhere else, so the insider and Congress books still take targets, and it is
`true` in the shared settings file for that reason.

**The close is two stages now** (item A11). `must_flatten_now` says yes from
`flatten_at`, which is 15:45 in the momentum books, and from that moment the
loop closes positions with limit orders sitting at the bid or the ask.
`must_flatten_at_market_now` is the new one, and it says yes from
`flatten_market_at`, 15:55, which is when anything still open goes out at market
as the backstop. That second function is the one the loop actually asks, to pick
between the two stages. Both are always false for a book that holds overnight. Spreads widen and depth thins in the last few
minutes, so a market order into that pays for the hurry. But being flat matters
more than the last few cents, and that is what the backstop is for.

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

- **Books C and D hold overnight.** `flat_by_close` is false for them, so neither
  `must_flatten_now` nor `must_flatten_at_market_now` ever says yes, and the
  two stage close at 15:45 and 15:55 does not apply. They are still barred from
  opening anything new after 15:50, which is the `entry_window` rule doing its
  normal job.
- **No book shorts today.** The momentum books are the ones the machinery was
  built for, and every check a short needs is written and tested: the mirrored
  stop above the entry price, the 10 dollar floor, and the three part borrow
  confirmation from IBKR. But `allow_shorts` is `false` in all four strategy
  files, because item A10 is **pending Mo's decision** rather than settled. A
  short is refused today with rule id `no_shorts`. See the section at the bottom.
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
the way down: its 10 percent per position cap becomes 200 dollars, not 10,000,
and the 0.25 percent it risks on a trade becomes 5 dollars, not 250.
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
2. Times need quotation marks. Write `"10:15"`, not `10:15`. Without them the
   yaml format turns a time into a number, and the file refuses to load with a
   message telling you to put the quotation marks back.
3. The times have to run forwards: `scan_start`, then `pick_time`, then
   `entries_until`, then `flatten_at`, then `flatten_market_at` for a book that
   has one, then `market_close`. Out of order and the file will not load. The
   fast polling window has the same rule to itself: `fast_poll_from` has to come
   before `fast_poll_until`, and either both are set or neither is.

If you get a setting wrong, nothing silently misbehaves: the agent stops on
startup and tells you which setting in which file is the problem and what a
valid value looks like.

Some names look like limits but are not checked on individual orders:
`universe.price_floor`, `universe.min_avg_dollar_volume`, the volatility filter
`universe.min_atr_usd` and `universe.min_atr_pct_of_price` (item A3), the hard
exclusions such as `universe.exclude_spacs` (item A12), and everything under
`scanner:` shape the morning shortlist instead, so they belong to the scanner
rather than to this file. The one exclusion that is also an order check is
halting, which is live at the moment of the order as rule `halted`.

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

You want to see something ending in `1292 passed`. It takes about half a minute,
and no account or internet connection is needed. Run it after changing any number
in any of the yaml files: several tests read the real settings, the real register
of books and all four strategy files, so they will tell you straight away if a
change broke something. The Momentum v2 rules have a test file of their own,
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_momentum_v2.py`.

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
- Landing exactly on a limit is allowed, except for the loss caps. An order worth
  exactly 10,000 dollars goes through, and so does a short at exactly the 10
  dollar floor. A loss of exactly the book's daily cap counts as hit and stops
  new trades, and so does exactly the weekly or monthly one, because that is what
  a cap is for.
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
- The momentum books have no trailing stop numbers, and since Momentum v2 they
  have no profit target either. Item A2 removed the target outright, and with no
  target and a stop this tight there is nothing a trailing rule could add before
  the 15:45 flatten, so both settings are left empty rather than invented. Write
  a pair of numbers into the strategy file and the trailing stop switches itself
  on.

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

Three more, added on 2026-09-06 with Momentum v2:

- **The sector cap depends on IBKR reporting an industry, and a name with no
  industry simply cannot be entered.** The rule counts money per industry, so a
  name it cannot file under one is refused rather than counted as harmless. That
  is the same answer an unknown halt status gets and it errs the safe way, but it
  does mean the broker's contract details can quietly cost us a trade. It will
  not be quiet in practice: the scanner names every shortlisted symbol that came
  back without an industry in its own log, and the refusal writes a `sector_cap`
  row with a sentence saying nobody told the check which industry the name is in.
  Getting out of such a name is never blocked.
- **The account wide symbol cap has a fallback, and it is the safe direction.**
  The rule counts a ticker across all five books, and the loop supplies the two
  figures it needs: what the five are worth together and what each of them holds
  in each name. It reads all five book files once a tick, in `read_account_wide`,
  because five books each reading five files would be twenty five reads. A
  caller that does not supply them, which is any test that builds an
  `AccountState` by hand, gets this book's own equity instead. That is the
  smaller number and so the tighter cap: being too strict is the right direction
  for a limit to be wrong in.
- **The three loss limits pause, they do not halt.** Weekly, monthly and streak
  all refuse entries and leave every exit alone, and none of them clears itself.
  A paused book stays paused until Mo has looked at it, which is the point: the
  thing the rule is reporting is that something needs a human, not that today
  went badly.

## Shorting, and where it stands now

The strategy spec was changed on 2026-09-02 to propose shorting with mirrored
stops and a gross exposure cap. That was written up here as an open question,
because turning the switch on before the machinery existed would have half
worked, which is the worst of the three options. The machinery now exists, built
on 2026-09-06:

- `stop_price_for` takes a side, and every stop rule is mirrored for a short. It
  returns a stop 10 percent of the average true range above the entry price,
  pushed up to the opening range high if it would otherwise sit inside the range,
  and it falls back to `risk.stop_loss_pct` above entry when no average true
  range is known. The answer is always above the entry price.
- The gross exposure cap measures longs and shorts added together against the
  book, and refuses an entry that would push the total past 100 percent.
- The 10 dollar floor for shorts and the borrow confirmation from IBKR are both
  enforced, as `short_price_floor` and `shortable_required`. The borrow
  confirmation grew on 2026-09-06 from one yes or no flag into the three part
  easy to borrow rule in the table above: the broker's own borrowing level, what
  the borrow costs, and how many shares are actually there to borrow.

So the machinery is finished and the switch is still off. `allow_shorts: false`
sits in both momentum strategy files,
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/strategies/momentum_hybrid/strategy.yaml`
and
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/strategies/momentum_rules/strategy.yaml`,
as well as in `config/guardrails.yaml`, which is the shared floor every book
starts from. The insider and Congress books are long only for a different reason:
insider and Congress selling are not usable signals.

**Item A10 is pending Mo's decision, not a decided deferral.** The reason it is
still open is the short sale restriction under Rule 201. It triggers on a 10
percent fall and then forbids shorting at or below the bid for two days, and a
gap down name on heavy volume is exactly that population, so a "break below the
opening range low" short may not be fillable the way the strategy describes it.

Everything the code needs already exists, so this is one line to flip once Mo
decides. Until then a short is refused with rule id `no_shorts`.

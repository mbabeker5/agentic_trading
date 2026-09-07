# Running the thing: guards, alerts, and the panic button

Written 2026-09-06. This is the page to open when your phone buzzes, or when you
want to stop the agent right now and are not in the mood to read anything else.

To stop everything:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/kill_switch.sh --really
```

To turn it back on:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/reenable.sh
```

The rest of this page explains what is watching, what it will tell you, and what
to do about it.

## The five guards

| Guard | When it runs | What it can do |
|---|---|---|
| `agent/alerts.py` | whenever something calls it | send you a message four ways |
| `agent/watchdog.py` | every 5 minutes in market hours, hourly otherwise | check six things, message you, start IB Gateway once |
| `agent/preflight.py` | 09:00 on weekdays | check five things, stop the day's trading, message you |
| `agent/kill_switch.sh` | when you run it | stop the loop, cancel every order, close every position |
| `agent/deadman.py` | every 5 minutes 09:30 to 16:00 on weekdays | notice the loop has died while a book is exposed, message you, and pull the kill switch itself |

Only the last two can trade, and the last one is the only thing in the project
that can decide to trade with nobody watching. The other three read.

### The alerter

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/alerts.py
```

Not a guard on its own, it is how the other two reach you. One call goes out
four ways: a text to your phone, a Slack direct message, a banner on this Mac's
screen, and a line in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/alerts.log`.

All four are attempted, not just the first one that works. An alert worth
sending is worth sending twice, and the log line is written even when every
other channel fails, so there is always a record.

Slack and the screen banner work today. The text does not, yet: it needs your
phone number in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/.secrets/alerts.env`

```
IMESSAGE_TO=+44...
```

Add that line and the next alert texts you. The first one will make macOS ask
for permission to control Messages. Say yes once and it stops asking.

Test the whole chain any time. It is harmless:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
  /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/alerts.py --test
```

### The watchdog

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/watchdog.py
```

Every five minutes during the trading day, and once an hour through the night
and the weekend, it checks six things:

1. `gateway_process`, IB Gateway is running.
2. `gateway_port`, port 4002 is accepting connections. A running Gateway with
   a shut port is a hung Gateway.
3. `ib_connect`, a read only login gets through and comes back with account
   DUT077572.
4. `market_data`, SPY quotes are real time rather than delayed. Only checked
   while the market is open, because there is nothing to quote at nine at night.
5. `loop_tick`, the trading loop has ticked within the last ten minutes. Only
   checked during market hours, and only when the loop's launchd job is loaded.
6. `disk_free`, more than a gigabyte free.

The hourly overnight runs are the whole point. On 2026-09-03 Gateway went down
at 01:44 in the morning and nobody found out until Saturday lunchtime. With the
watchdog loaded, that is a message at 02:00 and a Gateway that has already tried
to restart itself.

It will not nag. Once when something breaks, once every thirty minutes while it
stays broken, once when it comes back. That is the whole budget.

#### A restart only counts once it is proved

The watchdog is allowed to start IB Gateway, once per outage. Until 2026-09-06
it treated the start script finishing cleanly as proof that this had worked,
which proves nothing at all:
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/start_gateway.sh`
becomes Gateway when it succeeds and so never finishes. A clean exit from it is
closer to bad news than good.

So now it looks at Gateway before it starts anything and writes down two things:
which process id Gateway is running under, and the time of the newest
`Login has completed` line in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/ibc_logs/`.
Then it starts Gateway and keeps looking, every five seconds for up to two
minutes. Three things all have to be true before it will call that a restart:

1. **A different process id.** The old one coming back means nothing started,
   it means we are looking at the Gateway that was already sitting there.
2. **A login in the IBC log newer than the one it wrote down.** A Gateway can
   start, fail its login and sit on the prompt for the rest of the day, so a
   new process on its own is not a Gateway anyone can trade through.
3. **Port 4002 accepting a connection.** Logged in but not listening is exactly
   the hang the watchdog exists to catch. Nothing is sent down that socket, it
   is opened and closed again, so this can never touch the account.

If any of the three is missing you get a message that names which ones did and
did not happen:

```
[ERROR] Watchdog: restart did not take

IB Gateway was started but the restart cannot be confirmed. Here is what was
and was not seen in the 120 seconds after it was started:

  a different process id: yes (was 123, now 456)
  a newer login in the IBC log: yes (was 2026-09-06 06:30:00, now 2026-09-06 10:16:00)
  port 4002 accepting connections: no

All three have to be true before this counts as a restart, so it is not being
written down as one.
```

That last line matters. A restart that cannot be proved is not recorded as the
outage's one attempt, so nothing is spent on a start that did nothing.

What to do when you see it: run
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/start_gateway.sh`
yourself and watch the Gateway window, because IBKR Mobile is often sitting
there waiting for you to approve the login.
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/gateway_launch.log`
holds what the start script said, and
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/ibc_logs/`
holds what Gateway itself said.

### The pre-flight

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/preflight.py
```

At 09:00, half an hour before the open, it asks whether today can be a trading
day at all:

1. `gateway_login`, Gateway is up and logged into the paper account.
2. `market_data`, quotes are real time.
3. `scanner`, `agent/scanner.py` runs and exits cleanly. At 09:00 the
   shortlist is usually empty because the market has not opened. That is fine.
   It is the run that has to work, not the result.
4. `reconcile`, every book's idea of what it holds matches what the broker
   says it holds, symbol by symbol. With no books running yet this reports "no
   books active" and passes.
5. `day_trades`, any day trade counter files that exist can be read.

If anything fails it writes
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/NO_TRADE_TODAY`,
which stops the loop opening anything for the rest of the day, and messages you
with the names of the checks that failed. It writes the full answer to
`output/preflight_YYYY-MM-DD.json` either way.

## What an alert looks like

A real one, as it arrives in Slack:

```
[ERROR] Watchdog: gateway_process failed

No IB Gateway process is running on this Mac.

What to do: Start it with agent/start_gateway.sh and watch your phone,
IBKR Mobile may ask you to approve the login.
```

Three parts, always. The level in square brackets, the check that failed, and
one line of what to do about it.

`ERROR` means something is broken and the agent cannot work properly. `WARN`
means something is off but the machinery is fine: delayed quotes, a disk
filling up. `INFO` is almost always a recovery, the thing that was broken
working again.

The matching line in `output/alerts.log` looks like this:

```
2026-09-06 12:44:53 EDT | INFO | alerts test | This is a test from agent/alerts.py... | delivered=slack,macos
```

The `delivered=` part says which channels actually got it, which is how you tell
a quiet phone from a broken alerter.

## What to do when you get one

| Alert says | What is wrong | What to do |
|---|---|---|
| `gateway_process failed` | IB Gateway is not running | The watchdog has already tried once. If a second message follows, run `agent/start_gateway.sh` yourself and watch your phone for the IBKR approval prompt. |
| `gateway_port failed` while the process is up | Gateway has hung | `agent/stop_gateway.sh`, then `agent/start_gateway.sh`. The watchdog will not do this for you, because starting a second Gateway on top of a hung one gives two logins fighting over the same session. |
| `ib_connect failed` | Gateway is up but will not hand over the account | Look at the Gateway window. It is usually sitting on a login prompt or a two factor prompt. IBKR ends the session on Sundays at 1 AM Eastern, so one login a week is normal. |
| `market_data failed`, code 10197 | A competing live session. Your own quote screen, Client Portal watchlist or IBKR mobile app has taken the market data feed | Close it. IBKR allows one market data session per user and the paper account shares yours. |
| `market_data failed`, code 354, 10089 or 10168 | The real time subscription is not reaching the paper account | Client Portal, Settings, User Settings, Market Data Subscriptions. Check the US Securities Snapshot and Futures Value Bundle is on and that sharing with the paper account is ticked. See `docs/SETUP_IBKR_ACCOUNT.md`. |
| `loop_tick failed` | The loop has stopped waking up | Check `output/tick_YYYY-MM-DD.log` for the last thing it said, then `launchctl print gui/$(id -u)/com.mtalib.agentic-trading.tick` to see whether the job is still loaded. |
| `disk_free failed` | Under a gigabyte left | `output/ibc_logs/` is usually the culprit. Gateway writes a lot. |
| `Pre-flight failed: ...` | One of the 09:00 checks said no | Read `output/preflight_YYYY-MM-DD.json`, fix the named check, then `agent/reenable.sh` to clear NO_TRADE_TODAY. Until you do, the agent will not open anything today. |
| `Kill switch fired on account ...` | Somebody or something pulled the panic button | Read the message. It lists what was cancelled, what was closed, and what is left over. |
| `Kill switch fired on LIVE account ...` | The panic button was pulled on an account that is not the paper one | This needs the flag and the environment variable together, so somebody meant it. Check the account. |
| `Kill switch refused: ... is not a paper account` | The panic button was pulled on a live account without both permissions | Nothing was traded, but the loop IS stopped. Decide whether you really want that account flattened, and read the panic button section below. |
| `Kill switch could not read the account` | The panic button was pulled and IB Gateway did not answer | The loop is stopped anyway. Fix Gateway, then run it again. |
| `Loop is dead, pulling the kill switch` | The dead man's handle fired. The loop went quiet for three whole ticks while a book was holding something, which is fifteen minutes at the ordinary five minute cadence and never less than fifteen whatever the cadence | Nothing to do right now, it is already closing out. A second message follows with the result. Then find out why the loop stopped. |
| `Loop is dead and ... is a LIVE account` | The same, on an account that is not the paper one | It has NOT traded and will not. Close the positions yourself, or read the panic button section. |
| `The trading loop has stopped` | The loop went quiet for three whole ticks in market hours, and no book was holding anything | Nothing was traded and nothing needed to be. Find out why the loop stopped. |
| `Recovered: ...` | Nothing. It is over | Nothing. |

## The panic button

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/kill_switch.sh --really
```

In order, that:

1. writes `output/STOP` and `output/LOOP_DISABLED`, which stops the loop dead;
2. cancels every working order on the account in one go;
3. reads the orders back and cancels one by one anything that survived step 2;
4. sells every long and buys back every short, at the market, transmitted;
5. reads the account back, up to five times over thirty seconds, until it is
   flat and empty or until it can say exactly what is left;
6. messages you with all of it, and writes
   `output/kill_switch_YYYY-MM-DD_HHMMSS.json`.

Step 1 happens **whether or not you remember `--really`**. That is deliberate.
The worst possible outcome would be typing this in a hurry, leaving off the flag,
and walking away believing the agent was stopped when it was not. So the fast,
certain part is always real, and `--really` only controls the part that talks to
the broker. Both halves of the panic button write those two files: the shell
script before it starts Python, and Python again as its own first step. Either
one on its own stops the loop.

Step 3 is there because IBKR ignores a global cancel often enough to matter,
usually for an order placed by a different client id. An order still sitting
there after step 2 gets cancelled by its own id.

None of it goes through the trading loop. The kill switch talks straight to the
broker through `agent/broker.py`, never imports `agent/loop.py`, never reads a
book's state file, and never asks the guardrails for permission. Getting out is
always allowed, and a panic button that depends on the thing you are panicking
about is not a panic button.

The rehearsal is safe at any time:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/kill_switch.sh
```

That reads the account, prints exactly which orders it would cancel and which
positions it would close, and sends nothing to the broker. It still writes the
two stop files, so run `agent/reenable.sh` afterwards.

Market orders do not fill outside trading hours, they queue for the next open,
so a kill switch pulled at 8 in the evening leaves you with orders waiting
rather than a flat account. The script says so rather than pretending, and it
exits 1 rather than 0 when the account did not go flat.

### Pointing it at a live account

It refuses on any account id that does not start with `DU`, which is every
account except an IBKR paper one. To override that you need **both** of these,
together:

```
AGENTIC_TRADING_KILL_LIVE=yes \
  /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/kill_switch.sh \
  --really --live-account-ok
```

Two permissions rather than one, because they are hard to do by accident
together: a flag alone is one typo, and an environment variable alone is
something a shell profile could be carrying without you knowing. With both, it
flattens the account and the alert says in plain words that it was a live one.
With either missing it refuses, tells you which half is missing, and still
writes the two stop files, so the loop is stopped either way.

## The dead man's handle

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/deadman.py
```

The panic button above needs somebody to press it. This is the thing that
presses it when nobody is there.

Every other guard assumes something is still running. The watchdog tells you the
loop has stopped, which is useful at 10 in the morning and useless at 3 in the
afternoon when you are on a plane. The loop protects its own positions: it moves
the stops, it sells the momentum books at 15:55. All of that stops the moment the
loop stops. The one state nothing else covers: the loop is dead, the market is
open, and the books are still holding things.

Every five minutes from 09:30 to 16:00 on a weekday it asks three questions and
stops at the first no:

1. Has the loop written nothing for three whole ticks? That is
   `schedule.loop_minutes` times three out of
   `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/guardrails.yaml`,
   with a fifteen minute floor under it, so the ordinary five minute cadence
   means fifteen minutes and the thirty minute cadence the insider and Congress
   books run on means ninety.
2. Is the market actually open?
3. Does the broker hold a position, or a working order, that carries a `BOOK_`
   tag?

All three yes: it messages you, then runs the kill switch for real. Two messages
arrive, on purpose. The first says why, the second says what happened.

The first two yes and the third no: it sends one message saying the loop is dead
and trades nothing, because nothing at the broker was its business.

Question 3 is what stops it firing over nothing. Your one share of SPY, and
the market-on-open order sitting next to it, were not put there by a book. They
are orphans: they get listed in the output and named in the alert, and they never
cause an order. Only a book's exposure counts, because only a book's exposure was
being looked after by the thing that died.

A position is a book's when the broker tags it, or when a book's own state file
under `output/state_BOOK_*.json` says that book holds that symbol. The second
half matters: IBKR reports one netted account and nothing about which order put a
position there, so the book files are the only record of who owns what. The
newest file per book wins, today's if the loop got that far and the most recent
earlier one if it did not, because books C and D hold for weeks and a loop that
died before writing today's file has not stopped owning last Thursday's buy.

The heartbeat is the newest change time among these, all under `output/`:

```
heartbeat              wins outright if it exists. agent/loop.py touches it at
                       the end of every tick that got all the way through.
loop.log               one line per book per tick
tick_YYYY-MM-DD.log    everything one day's ticks printed
state_BOOK_*_*.json    one file per book per day
```

Change times, not the timestamps written inside the files. That is deliberately
different from the watchdog, which quotes the loop's own words because it is
reporting to a person. This one is deciding whether to trade, so it asks the
filesystem, which cannot be fooled by a loop that is still writing a stale
timestamp.

`output/deadman_state.json` is what stops it firing seventy-eight times in an
afternoon. It records which silence it acted on and what it did about it, so a
loop that stays dead gets one kill switch and not one every five minutes. When
the loop comes back and dies again the heartbeat has moved, so that is a new
silence and it can act again. `agent/reenable.sh` clears the file.

It is a dry run unless you pass `--really`, and a dry run sends nothing, trades
nothing and writes nothing:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
  /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/deadman.py
```

On an account that does not start with `DU` it alerts and stops there, unless
`AGENTIC_TRADING_KILL_LIVE=yes` is in its environment, which the job file
deliberately does not set. Flattening a live account because a log file looked
old is not a decision a scheduled job gets to make on its own.

**IT IS LOADED AND ARMED, as of 2026-09-07.** Mo approved the kill switch and
unattended operation on 2026-09-06, and the hub ruled the next day that this job
should go on watch, so it is now one of the nine generated jobs rather than a
hand written plist held back beside them. It runs with `--really`, which means it
can pull the kill switch on its own. `AGENTIC_TRADING_KILL_LIVE` is not set
anywhere in its job file and must stay that way, so it can only ever act on the
paper account.

Its definition is a normal template now:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/templates/deadman.template
```

It was a plist with the project folder left as a placeholder,
`deadman.plist.tmpl`, from before `scripts/gen_launchd.py` existed. That file is
gone. Edit the template and run the generator, never the plist.

Before it was loaded it was run once as a dry run by hand. It reported the loop
quiet with the market shut and stopped at question 2, which is the right answer
outside trading hours.

To take it off watch again:

```
launchctl bootout gui/$(id -u)/com.mtalib.agentic-trading.deadman
```

To keep it loaded but stop it trading, take `--really` out of the `[program]`
block in the template above and run
`python3 /Users/mtalib/workspace_repos/personal_repo/agentic_trading/scripts/gen_launchd.py --install`
again. It then still decides and still writes to the log, and it sends nothing
and trades nothing.

## Turning it back on

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/reenable.sh
```

It removes the three files that hold the agent back and tells you which ones
were actually there. It also clears `output/deadman_state.json`, the dead man's
handle's note of which silence it has already acted on, because starting the
agent again is starting over. It does not restart Gateway, reload any launchd
job, or buy back anything the kill switch sold.

## The three brakes

Three files, all in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/`, all
removed by `agent/reenable.sh`.

| File | Effect | Written by |
|---|---|---|
| `STOP` | The loop closes positions but opens none. Getting out is always allowed. | `kill_switch.sh` and `kill_switch.py`, or you, by hand |
| `LOOP_DISABLED` | `run_tick.sh` does not run a tick at all | `kill_switch.sh` and `kill_switch.py` |
| `NO_TRADE_TODAY` | Same as STOP: close, do not open | `preflight.py`, when a 09:00 check fails |

`NO_TRADE_TODAY` does not clear itself at midnight, on purpose. A morning that
failed its checks should need a person to look before the agent trades again.

To pause without stopping the launchd job at all, one line does it:

```
touch /Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/STOP
```

## Where the record actually lives

Everything the agent does goes into one SQLite database:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/data/trading.sqlite
```

That file is the record now. The Google Sheet is a picture of it, redrawn once a
night. So if the wifi is off, or Google is having a bad morning, nothing is
lost: the tick still writes to the database and the sheet catches up later. And
if the sheet is ever wrong, or somebody deletes it, that is not a loss either.
Run the sync again and it is rebuilt from the database.

Everything means everything: every quote the agent looked at, every scanner run,
every decision including the decisions to do nothing, every order sent, every
fill that came back, every alert, and every pre-flight and watchdog check. The
table by table explanation is in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/DATA.md`.

To look inside it without any chance of breaking it:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
  /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/db.py
```

That prints where the file is and how many rows are in each table, and writes
nothing.

The sheet is rewritten at 16:35 New York by
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/ledger/sync_sheet.py`,
and it is safe to run by hand at any time. `--dry-run` says what it would put in
the sheet and writes nothing. `--write` actually rewrites it.

The backup is a copy of that one file, once a night, into
`data/backups/trading_YYYY-MM-DD.sqlite`, written by
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/scripts/backup_db.sh`.
Thirty days are kept and older copies are deleted. If this Mac ever has to be
replaced, that is the one file to carry across.

**Neither of the two new jobs is loaded**, exactly like every other job in this
project. The nightly sheet sync and the nightly backup are definitions sitting
in the repo, at `config/launchd/templates/sheet_sync.plist.tmpl` and
`config/launchd/templates/backup_db.plist.tmpl`, until somebody loads them by
hand.

## Day-trading regime

Two rulebooks exist in 2026, and the code follows whichever one the account is
actually under.

The old one is the pattern day trader rule. Four or more round-trip day trades
inside five business days, in a margin account, makes that account a pattern day
trader, and from then on it has to hold at least 25,000 dollars. Drop below and
the broker stops it day trading for 90 days. Counting is the whole defence, and
the trade to avoid is the fourth one.

The new one is the intraday margin deficit framework. FINRA retired the pattern
day trader rule with effect from 2026-06-04 (Regulatory Notice 26-10, phase-in
running to 2027-10-20). A migrated account has no 25,000 dollar floor and no
four-in-five count, and the minimum for trading with leverage or shorting is
2,000 dollars. What it has instead is a condition on each order: the order must
not leave the account short of margin during the day. A deficit has to be cured
in about three business days, and four uncured ones in twelve months can still
bring a 90-day restriction.

Under `old_pdt`,
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/pdt.py`
behaves as it always has. The insider book (C) and the Congress book (D) are
refused a fourth day trade in five business days. The three momentum books are
never blocked, but every order the rule would have blocked is written down, so
the cost of the rule gets measured rather than guessed at.

Under `new_imd` the counter still records every fill, because the ledger still
wants the month's count, but it blocks nothing and flags nothing. Every entry
order goes through `imd_check()` in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/margin_regime.py`
instead, which asks two things: gross exposure after the order stays at or below
100 percent of book equity, and cash after the order stays at or above zero. A
book that never borrows cannot run a deficit. The 100 percent is written into
the code rather than read from the settings, and `assert_structurally_impossible()`
raises if a settings change ever lets the book borrow, so the promise breaks
loudly rather than quietly.

The setting is `regime` in the `pdt` block of
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/guardrails.yaml`,
with `treat_unknown_as` next to it. It ships as `unknown` and `old_pdt`, because
nobody has asked the account yet. Being counted when you need not be costs a
line in a log; not being counted when you must costs 90 days.

The 09:00 pre-flight asks. Its `day_trade_regime` check opens its own read only
connection on client id 282 and reads five account summary tags:
`DayTradesRemaining` and `DayTradesRemainingT+1` through `T+4`. Small
non-negative numbers mean the old rule is still counting the account down. A -1,
which is IBKR writing "unlimited", or no tags at all, means the new rulebook.
The answer goes into the day's report and the check never fails the morning; an
unknown answer prints a `warn` line. It opens its own connection because the MCP
server asks IBKR for 24 tags and none of the five is among them, so an answer
through
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/mcp_client.py`
could never tell "no limit" apart from "nobody asked". Only with the flag does
it write the answer back into the settings, changing that one line and leaving
every comment in the file alone:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
  /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/preflight.py \
  --write-regime
```

Read read only against the paper Gateway on 2026-09-06, with the market shut,
the paper account DUT077572 sent 74 account summary tags and not one of the five
was among them. A second read of the longer account values list, 184 rows, had
none either. By the rule above that is `new_imd`. It is also not evidence: IBKR
applies neither rulebook to simulated money, and the live account is U28440091.
The setting stays at `unknown` until a live account has been read.

## The nine scheduled jobs

The five guards above are what watches the money. These are the nine things
launchd wakes up, which is a different list: three of the guards are on it, and
so are the jobs that write rather than watch.

| Job | When | What it does |
|---|---|---|
| `tick` | every 5 min 09:25 to 16:05, plus 07:00, 07:30 and 16:30, weekdays | one tick of the loop for all five books |
| `watchdog` | every 5 min in market hours, hourly otherwise including weekends | the health check above |
| `preflight` | 09:00 weekdays | the morning check above |
| `recorder` | every 5 min 09:25 to 16:05 weekdays | records the day for the replay harness |
| `deadman` | every 5 min 09:30 to 16:00 weekdays | the dead man's handle above, armed |
| `learning` | 16:30 weekdays | writes the day's journal entry |
| `sheet_sync` | 16:35 weekdays | rebuilds the Google Sheet ledger from the database |
| `weekly` | 16:45 Friday | writes the week's review |
| `backup_db` | 17:00 every day | copies `data/trading.sqlite` into `data/backups/`, 30 days kept |

Six were loaded on 2026-09-06 and the last three, `deadman`, `sheet_sync` and
`backup_db`, on 2026-09-07. Those three had been held back because none of them
had ever run: the dead man's handle is the only job here that can place an
order, the sheet sync had never touched the real Google Sheet, and the backup
had never run on a schedule. All three were run once by hand first.

`deadman` is the one to think about, because it is the only job in this project
that can place an order. Read its own section above before changing anything
about it.

`learning` and `weekly` run Claude Code with no terminal attached and are told
what to do by a prompt file, not by the job. Change what they do by editing the
prompt:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/prompts/daily_learning_loop.md
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/prompts/weekly_review.md
```

Neither of them can place an order, connect to IB Gateway or the MCP server, or
touch a launchd job. They read files, write files and run a short list of git
commands, and that is the whole of it.

**The job files themselves are generated, so do not edit one by hand.** Each job
has a template in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/templates/`
holding its schedule in plain English, and this turns them into the plists:

```
python3 /Users/mtalib/workspace_repos/personal_repo/agentic_trading/scripts/gen_launchd.py
```

That writes the files and loads nothing. `--check` says whether they are up to
date, `--install` copies them into `~/Library/LaunchAgents` and starts them, and
`--uninstall` is the undo. The full explanation is in `docs/LAUNCHD.md`.

## Where to look when something is odd

```
output/alerts.log                every alert ever sent, one line each
output/watchdog.log              one line per watchdog run
output/watchdog_state.json       what the watchdog currently believes
output/preflight_YYYY-MM-DD.json the 09:00 answers, check by check
output/kill_switch_<when>.json   what one pull of the panic button did
output/deadman_state.json        which silence the dead man's handle acted on
output/loop.log                  one line per tick
output/tick_YYYY-MM-DD.log       everything a single day's ticks printed
output/ibc_logs/                 IB Gateway's own logs
output/mcp_logs/mcp_ibkr.log     the MCP server
output/launchd_*.out.log         anything that broke before a script started
data/trading.sqlite              every tick, decision, order and fill
data/backups/                    a copy a night, 30 days kept
```

All of those are under
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/`.

Two quick checks by hand:

```
nc -z 127.0.0.1 4002 && echo "Gateway is up"
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/mcp
```

Anything other than `000` from the second one means the MCP server is alive. A
bare request gets `406` back, which is the server correctly saying it wants a
proper MCP request.

## What is not switched on yet

As of 2026-09-07:

* All nine launchd jobs are loaded, the dead man's handle included. Six went on
  on 2026-09-06 and the last three on 2026-09-07. `launchctl list | grep agentic`
  shows them. Every book in `config/books.yaml` is still in dry run, so the tick
  job works out what it would trade and sends nothing.
* **This Mac is set to Pacific, not Eastern, and launchd fires on the Mac's own
  clock.** Checked with `date +%Z` on 2026-09-07 and it answered `PDT`, where
  `docs/LAUNCHD.md` had recorded `EDT` on 2026-09-02. Nothing in a plist can pin
  a time zone, so every one of the nine jobs currently wakes three hours late:
  the 09:30 tick fires at 12:30 New York. Setting the Mac back to Eastern in
  System Settings fixes all nine at once and needs no regeneration. Until that
  is done the schedules are wrong, whatever the plists say.
* iMessage alerts are off until `IMESSAGE_TO` exists in
  `.secrets/alerts.env`. Slack and the screen banner work now.
* Real time quotes are not arriving. The paper Gateway answered IBKR code
  10168 on 2026-09-06, which means the subscription is not reaching it. The
  pre-flight will fail on `market_data` and write NO_TRADE_TODAY until that is
  sorted. Details in `docs/SETUP_IBKR_ACCOUNT.md`.

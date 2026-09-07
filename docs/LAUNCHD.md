# The five minute wake up, and how to switch it on

Status: written 2026-09-02, updated 2026-09-07. The job described here **is
loaded**, along with all eight others. What was loaded and when is at the bottom
of this file.

## What this is

The trading loop has no timer of its own. It is a script that runs once, looks
at the clock, does the one thing that belongs to that moment, writes down what
it saw, and exits. Something outside it has to wake it up every five minutes.

On a Mac that something is launchd, the part of macOS that runs things on a
schedule. You hand it a file describing what to run and when, and it does that
in the background whether or not a Terminal window is open.

The file is here:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/com.mtalib.agentic-trading.tick.plist
```

It runs this, and nothing else:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/run_tick.sh
```

## Do not edit that file by hand

Every plist in `config/launchd/` is written by a generator from a short template.
Edit the template, run the generator, commit both. An edit made straight to a
plist is lost the next time anybody generates.

The templates are here, one per job:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/templates/
```

Every one of the nine is named `<job>.template` today. A second ending,
`<job>.plist.tmpl`, is still read, because three jobs used it until 2026-09-07
and a note or a checkout from before then should still work. The generator
globbed the first ending alone until 2026-09-06, which is how those three came
to have no plist at all: it never looked at them.

The generator is here:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/scripts/gen_launchd.py
```

Why it exists: a job that fires every five minutes needs one entry per wake up,
written out in full. The tick job has 550 of them and the watchdog has 533.
Nobody keeps that correct by hand, and every one of those entries used to have
this Mac's own home folder written into it, which is the thing that stopped the
project moving to another machine. Now the schedule is written once, in English,
in the template:

```
every 5 minutes from 09:25 to 16:05 on weekdays
```

and the generator turns that into the entries launchd wants, filling in the
project folder, the venv Python, the home folder and the path to `claude` from
wherever it is actually running.

The four commands:

```
python3 /Users/mtalib/workspace_repos/personal_repo/agentic_trading/scripts/gen_launchd.py
python3 /Users/mtalib/workspace_repos/personal_repo/agentic_trading/scripts/gen_launchd.py --check
python3 /Users/mtalib/workspace_repos/personal_repo/agentic_trading/scripts/gen_launchd.py --install
python3 /Users/mtalib/workspace_repos/personal_repo/agentic_trading/scripts/gen_launchd.py --uninstall
```

With no flags it rewrites every plist in `config/launchd/` and loads nothing.
`--check` says whether the files on disk already match the templates, changes
nothing, and exits non-zero if they do not. That is the one to run after editing
a template, and a test runs it too, so a template edit that was never generated
fails the suite.

`--check` fails three ways, and the words it prints say which:

| Word | What it means | What to do |
|---|---|---|
| `DIFFERS` | the plist no longer matches its template | run the script again with no flags |
| `NO PLIST` | a template nobody ever generated, so there is no plist to compare | run the script again with no flags |
| `ORPHAN` | a plist in `config/launchd/` whose template has gone | delete the plist by hand |

`NO PLIST` is the one that matters, because a check that walked the plists
instead of the templates could not see it, and that is exactly how three jobs
stayed missing. `ORPHAN` has to be a manual deletion on purpose: a loaded job's
file is not something this script should remove behind your back. A hand written
plist sitting in the templates folder counts as a template for the orphan check,
so a plist you rendered from one of them by hand is not condemned. There are
none of those left since 2026-09-07.

`--install` copies the plists to `~/Library/LaunchAgents` and asks launchd to
load them. **That starts the jobs running.** It is the only thing in the file
that does. `--uninstall` unloads them and removes the copies, leaving
`config/launchd/` alone.

The generator runs on any Python 3.9 or newer with nothing installed, on
purpose: on a fresh Mac it has to work before the project's own virtual
environment exists.

## The schedule

Every five minutes from 09:25 to 16:05, Monday to Friday, every minute from
09:00 to 09:26 for the pre-open run, plus three extra wake ups a day for the
filing sweeps. That is 110 wake ups a day and 550 entries in the file, one for
each time on each weekday. The two morning grids overlap at 09:25 and it is
written once, which is why the pre-open half hour adds 26 entries rather than
27.

The pre-open minutes are there for a pacing rule rather than for tidiness.
`agent/preopen.py` pulls each new candidate's history at no more than four
requests a minute, and IB Gateway allows about sixty historical requests in any
ten minutes. Twenty seven wake ups between 09:00 and 09:26 pay for about a
hundred requests, which is what the morning needs, and every one of them is
spent before the open rather than in the five minutes around it, where the data
budget is scarcest and where the pick is made. A tick lasts a second or two, so
waking every minute cannot overrun the four a minute rule. Waking every five
minutes buys about a fifth of what the morning needs, which is what was
happening until 2026-09-06. See `docs/PREOPEN_FLOW.md`.

09:25 rather than 09:30 on purpose: the first wake up of the trading grid is five
minutes before the market opens, so if IB Gateway is down or the MCP server
needs restarting, that shows up in the log before it costs anything. It ends at
16:05 rather than 16:00 because the tick at or after the close is the one that
writes each book's end of day line, and a job set to fire exactly on the close
can land a second early.

The three extra times, and which book each belongs to:

| Time | Book | What it does |
|---|---|---|
| 07:00 | C | sweeps SEC Form 4 insider filings, `agent/sweep_insider.py` |
| 07:30 | D | sweeps Congress disclosures, `agent/sweep_congress.py` |
| 16:30 | C | sweeps Form 4 again, for tomorrow morning |

All of that lives in `config/launchd/templates/tick.template`, in English, and
the generator does the counting.

launchd works in whatever time zone the Mac is set to, and there is no way to
pin a time zone inside the file.

**This Mac is in Pacific, and that is a live problem.** `date +%Z` answered
`EDT` on 2026-09-02 and `PDT` on 2026-09-07, so the Mac moved in between.
Nothing in a plist can pin a time zone, so every one of the nine jobs currently
fires three hours late against New York: the 09:30 wake up lands at 12:30
Eastern, after the open and after the pick.

The fix is one setting and no regeneration: put the Mac back on Eastern in
System Settings, General, Date and Time. Changing the times in the templates
instead would be the wrong fix, because it hides the problem in nine files and
breaks again the moment the Mac is corrected. Check with `date +%Z` before you
trust a tick log after any travel.

If the Mac is asleep at one of those times, launchd runs the job once when it
wakes up, and no setting turns that off. That does no harm, because the loop
reads the real clock and works out which part of the day it is actually in, so a
tick meant for 10:15 that lands at 14:00 does the 14:00 thing. But a sleeping
Mac is a Mac that is not trading, so keep it awake during market hours if you
want the loop to run the full day.

## Nothing here can trade

`run_tick.sh` has `--dry-run` written into it. Every tick works out what it
would do, prints it, writes it to the ledger as a decision, and sends nothing to
the broker. Loading this job does not put money at risk, on paper or otherwise.

Turning that off is a deliberate act with three separate locks on it, described
at the top of `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/loop.py`,
and it waits on you approving the numbers in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/STRATEGY.md`.

## Switching it on

```
launchctl bootstrap gui/$(id -u) /Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/com.mtalib.agentic-trading.tick.plist
```

`gui/$(id -u)` means "in my own logged in session", which is what you want: the
job runs as you, with your files, and only while you are logged in.

Nothing happens straight away. The job sits there until the next five minute
mark inside market hours. To check it landed:

```
launchctl print gui/$(id -u)/com.mtalib.agentic-trading.tick
```

That prints a long block. The useful lines are `state`, which should say
`waiting`, and `last exit code` after it has run once.

If `bootstrap` complains that the service already exists, it is already loaded.
Unload it first, then load it again.

## Switching it off

```
launchctl bootout gui/$(id -u)/com.mtalib.agentic-trading.tick
```

That is the reliable off switch. It stops the job and forgets it until you
bootstrap it again.

If you are in a hurry, use the kill switch instead. To stop the loop opening
anything right now, you do not need launchctl at all:

```
touch /Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/STOP
```

While that file exists, every tick refuses to open anything. It will still close
positions, which is the point: getting out is always allowed. Delete the file to
resume.

```
rm /Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/STOP
```

## Checking that it ran

Four places. Start at the top.

One line per tick, the whole month in one file:

```
tail -20 /Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/loop.log
```

Each line says the time, which phase it was in, what the account was worth, how
many positions were open, how many orders it would have placed, how many the
guardrails allowed and refused, and whether the kill switch was on.

Everything a single tick printed, one file per day. This is where you go when a
line in `loop.log` looks wrong.

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/tick_2026-09-02.log
```

It holds the plumbing checks as well as the tick itself, so a morning where
Gateway was down says so at the top.

What the loop is carrying today: the picks, their entry triggers, stops and
targets, and what has fired so far.

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/state_2026-09-02.json
```

Delete that file and the day starts over from scratch.

Anything that broke before the script even got going. Usually empty. A
permissions problem or a missing file shows up here and nowhere else.

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/launchd_tick.out.log
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/launchd_tick.err.log
```

## When it has clearly not run

Work down this list.

1. **Is it loaded?** `launchctl print gui/$(id -u)/com.mtalib.agentic-trading.tick`
   If that says the service could not be found, it is not loaded.
2. **Is today a weekday, and is it between 09:25 and 16:00?** Outside that, no
   tick is due.
3. **Is the Mac in Eastern?** `date +%Z`. If it says anything but `EST` or
   `EDT`, the times in the plist are pointing at the wrong hours.
4. **Was the Mac asleep?** Nothing runs while it sleeps.
5. **Is IB Gateway up?** `nc -z 127.0.0.1 4002`. Silence means it is down, and
   the day's tick log will say so. Start it with
   `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/start_gateway.sh`.
   Logging in needs a person, so this is the one thing the loop cannot fix
   itself. IBKR ends the session on Sundays at 1 AM Eastern, so expect one login
   a week.
6. **Is the MCP server up?** `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/mcp`
   Anything other than `000` means it is alive. `run_tick.sh` restarts it on its
   own if it is not, so this is rarely the problem. Its log is
   `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/mcp_logs/mcp_ibkr.log`.

## Running one tick by hand

Safe at any time, and the quickest way to see what the loop makes of right now:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/run_tick.sh
```

To see what it would make of a different moment, without waiting for it:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
  /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/loop.py \
  --dry-run --now "2026-09-03 09:36"
```

The time in `--now` is read as New York time. That is how the phases were tested
after the close.

---

# The nine job definitions, and all nine generate

`config/launchd/templates/` holds nine job definitions, and since 2026-09-07
every one of them is a template the generator can render. **All nine are
loaded.** `scripts/gen_launchd.py --install` is the one command that starts
them.

| Job | When | What runs | Wake ups a week |
|---|---|---|---|
| `tick` | every 5 min 09:25 to 16:05, plus every minute 09:00 to 09:26 and 07:00, 07:30, 16:30, weekdays | `agent/run_tick.sh` | 550 |
| `watchdog` | every 5 min in market hours, hourly the rest of the time including weekends | `agent/watchdog.py --once` | 533 |
| `preflight` | 09:00 weekdays | `agent/preflight.py` | 5 |
| `recorder` | every 5 min 09:25 to 16:05 weekdays | `agent/replay/record_day.py --once` | 405 |
| `deadman` | every 5 min 09:30 to 16:00 weekdays | `agent/deadman.py --really` | 395 |
| `learning` | 16:30 weekdays | headless `claude -p` on the daily prompt | 5 |
| `sheet_sync` | 16:35 weekdays | `ledger/sync_sheet.py --write` | 5 |
| `weekly` | 16:45 Friday | headless `claude -p` on the weekly prompt | 1 |
| `backup_db` | 17:00 every day | `scripts/backup_db.sh` | 7 |

Their full labels are `com.mtalib.agentic-trading.` plus the name in the first
column, which is what every `launchctl` command below wants.

Two jobs can send an order. The tick job can, and only once a book in
`config/books.yaml` is taken out of dry run by hand, which none is. The dead
man's handle can, and it is armed: the only orders it can cause are closing
orders from `agent/kill_switch.py`, and only on an account whose id starts with
`DU`. The other seven read, write files and send messages.

## What the last three do

| Job | What it does, in one line |
|---|---|
| `deadman` | the dead man's handle: if the loop has gone quiet for more than fifteen minutes while the market is open and a book still holds a position or has an order working, it messages you and pulls the kill switch |
| `sheet_sync` | rewrites the Google Sheet ledger from the database half an hour after the close, so the sheet is a picture of the database rather than a second record of its own |
| `backup_db` | copies `data/trading.sqlite` to `data/backups/trading_YYYY-MM-DD.sqlite` with SQLite's own online backup, and deletes copies over thirty days old |

These three were held back until 2026-09-07 and are worth knowing the history
of, because it is the sort of gap that hides for a week. They were not templates
at all: each was a whole finished plist with `{ROOT}` written through it, made by
hand before the generator existed, with its schedule spelled out entry by entry
and no line of English to expand. `deadman.plist.tmpl` was 2,079 lines and
carried its 395 wake ups one at a time. Handing one to the generator produced
`line 1: text before the first section`, off the XML declaration at the top. And
before 2026-09-06 the generator did not even look at files with that ending, so
nothing said anything at all.

Each of them also said inside itself that it was held back on purpose, because
none had ever run and putting an unwatched job in the same list as the ready
ones was thought worse than leaving it out. Mo approved the kill switch and
unattended operation on 2026-09-06 and the hub ruled on 2026-09-07 that all
three should be armed, so each was rewritten as
`config/launchd/templates/<job>.template`, its wake up count added to
`EXPECTED_WAKE_UPS` in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_paths.py`,
and the hand made file deleted.

**`deadman` is the one to think hardest about.** Every tick writes
`output/heartbeat`, and the dead man's handle is the only thing that reads it on
a schedule, so while this job did not exist that heartbeat had no reader and a
loop that died holding a position stayed dead and holding it. It is also the
only job in this project whose whole purpose is to place an order. Take
`--really` out of the `[program]` block in
`config/launchd/templates/deadman.template` and generate again, and it decides
and logs and sends nothing, which is the way to watch it for a week if you ever
want to.

## The recorder

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/com.mtalib.agentic-trading.recorder.plist
```

It wakes `agent/replay/record_day.py` every five minutes through the trading day
and records what the market was doing, so the whole loop can later be replayed
against a real day with a fake broker. That replay is the gate every book has to
pass before it is allowed to place a paper order for real. What it records, and
what the replay proves, is in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/REPLAY.md`.

It is meant for one day at a time. launchd has no way to say "just this one
Tuesday", so the template carries the weekday entries and you load it on the day
and unload it afterwards.

It connects to IB Gateway read only and asks for nothing but quotes and
historical bars, so it cannot place an order.

## The daily learning loop and the weekly review

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/com.mtalib.agentic-trading.learning.plist
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/com.mtalib.agentic-trading.weekly.plist
```

These two are different from the rest: they run Claude Code with no terminal
attached, `claude -p`, and feed it a prompt file on standard input.

**The learning loop, 16:30 on weekdays.** It reads the day's tick log, the five
book state files, the watchdog and alert logs, the pre-flight result and the
day's commits, and writes one journal entry at
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/journal/YYYY-MM-DD.md`
plus the five line `journal/latest_summary.md` that the hub relays to you.
Confirmed learnings graduate to `docs/LEARNINGS.md` and improvements go to
`docs/BACKLOG.md`.

**The weekly review, 16:45 on Friday.** Fifteen minutes after Friday's learning
loop, so the week's last journal entry already exists when it starts reading. It
reads the ledger's Books tab, the week's journal entries and last week's review,
and writes `docs/weekly/YYYY-WW.md` comparing the five books on return, alpha
against SPY, drawdown, trades, commissions, model cost, rule triggers and missed
ticks.

What they are allowed to do is a short list, written into the plist and repeated
in the prompt: read files, write files, and a handful of git commands. The
weekly one may also fetch the ledger sheet. Neither can run the trading loop,
reach IB Gateway or the MCP server, or place an order.

The prompts are the place to change what these two do, not the plists:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/prompts/daily_learning_loop.md
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/prompts/weekly_review.md
```

**What they need to work.** Claude Code installed and signed in as you on that
Mac, and the Mac logged in to the desktop. A user launchd job runs inside your
login session, and Claude reads its sign in from the login keychain. A locked
screen is fine. A logged out Mac is not. The generator writes the full path to
`claude` into the plist, because launchd starts a job with almost no PATH and
would never find it by name.

If nothing appears in `journal/` after 16:30, or in `docs/weekly/` after a
Friday, read these first:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/launchd_learning.err.log
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/launchd_weekly.err.log
```

A sign in that has expired shows up there.

---

# The watchdog and the pre-flight

Added 2026-09-06, and loaded the same day along with four others.

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/com.mtalib.agentic-trading.watchdog.plist
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/com.mtalib.agentic-trading.preflight.plist
```

Neither can trade. The watchdog opens a read only connection to IB Gateway, so
it cannot place an order even by accident, and the only thing it can start is
Gateway itself. The pre-flight reads the account and runs the scanner.

## The watchdog

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/watchdog.py --once
```

One run is one health check. It looks at six things: is IB Gateway running, is
port 4002 open, does a read only login come back with the paper account, are SPY
quotes real time rather than delayed, has the trading loop ticked recently, and
is there more than a gigabyte of disk free.

**Schedule.** Every five minutes from 09:25 to 16:05 on weekdays, which covers
the whole trading day plus five minutes either side, and once an hour the rest
of the time including weekends. That is 533 wake ups a week. The hourly overnight
runs are the point of the whole thing: on 2026-09-03 Gateway went down at 01:44
and nobody found out until Saturday.

**What it does when something is wrong.** It messages you once. If Gateway is
down it also starts it, once, and then leaves it alone. If the same thing is
still broken half an hour later it says so again, and not more often than that.
When it comes back you get one message saying so.

It keeps its memory in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/watchdog_state.json`
and writes one line per run to
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/watchdog.log`.

**Try it without consequences:**

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
  /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/watchdog.py --dry-run
```

That runs every check, prints what it found and what it would have done, and
sends nothing.

## The pre-flight

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/preflight.py
```

**Schedule.** 09:00 on weekdays, half an hour before the open, five wake ups a
week. It gets ten minutes to finish because it runs the scanner, which can take
four minutes when IBKR is slow.

It asks five questions: is Gateway logged into the paper account, are the quotes
real time, does the scanner run cleanly, do the books and the broker agree on
what is held, and do the day trade counter files load. If any answer is no it
writes
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/NO_TRADE_TODAY`,
which stops the loop opening anything that day, and messages you with the names
of the failing checks.

**Try it without consequences:**

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
  /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/preflight.py --dry-run
```

That writes `output/preflight_dryrun.json` instead of the dated report, creates
no NO_TRADE_TODAY, and sends no message.

## Switching them on and off

Same two commands as the tick job, with a different label:

```
launchctl bootstrap gui/$(id -u) /Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/com.mtalib.agentic-trading.watchdog.plist
launchctl bootstrap gui/$(id -u) /Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/com.mtalib.agentic-trading.preflight.plist

launchctl print gui/$(id -u)/com.mtalib.agentic-trading.watchdog
launchctl print gui/$(id -u)/com.mtalib.agentic-trading.preflight

launchctl bootout gui/$(id -u)/com.mtalib.agentic-trading.watchdog
launchctl bootout gui/$(id -u)/com.mtalib.agentic-trading.preflight
```

**Load the watchdog first, before the tick job.** It is the thing that tells you
the loop has stopped, so it is not much use arriving second.

To load all nine at once instead, on a machine where you want the lot:

```
python3 /Users/mtalib/workspace_repos/personal_repo/agentic_trading/scripts/gen_launchd.py --install
launchctl list | grep com.mtalib.agentic-trading
```

That copies every plist to `~/Library/LaunchAgents` and bootstraps it. The undo
is the same command with `--uninstall`. Loading one at a time with `bootstrap`
above is the safer habit while you are still watching each job's first run.

Their launchd logs, for anything that breaks before the script gets going:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/launchd_watchdog.out.log
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/launchd_watchdog.err.log
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/launchd_preflight.out.log
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/launchd_preflight.err.log
```

## One thing to know about the watchdog and the loop

The watchdog's heartbeat check stays quiet while the tick job is not loaded. It
has no way to tell a loop that has crashed from a loop that was never switched
on, so rather than guess it asks launchd whether the tick job exists and says
nothing when it does not. Load the tick job and the heartbeat check starts
working on its own.

Everything about what the guards do, what an alert looks like and what to do
when you get one is in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/OPERATIONS.md`.

---

## What was actually loaded, and when (2026-09-06)

Mo approved unattended operation, so the six generated jobs were bootstrapped
on this Mac rather than left as a hand step in the Tuesday runbook. Recorded
here because "it is loaded" is not a fact you can read off a plist.

The exact commands, run from
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading`:

```
launchctl bootstrap gui/$(id -u) /Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/com.mtalib.agentic-trading.learning.plist
launchctl bootstrap gui/$(id -u) /Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/com.mtalib.agentic-trading.preflight.plist
launchctl bootstrap gui/$(id -u) /Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/com.mtalib.agentic-trading.recorder.plist
launchctl bootstrap gui/$(id -u) /Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/com.mtalib.agentic-trading.tick.plist
launchctl bootstrap gui/$(id -u) /Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/com.mtalib.agentic-trading.watchdog.plist
launchctl bootstrap gui/$(id -u) /Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/launchd/com.mtalib.agentic-trading.weekly.plist
```

All six returned nothing, which is launchctl saying it worked. Confirmed with:

```
launchctl list | grep -i agentic
```

which printed all six, each as `-  0  com.mtalib.agentic-trading.<job>`. The `-`
is the process id column and means the job is not running this second, which is
correct for a job waiting on its schedule. The `0` is the last exit status.

To check one in detail, or after it has fired:

```
launchctl print gui/$(id -u)/com.mtalib.agentic-trading.tick
```

`state = waiting` is what you want, plus `last exit code` once it has run.

### The three jobs that were NOT loaded on 2026-09-06, and why

`backup_db`, `sheet_sync` and `deadman` stayed off that day because they were
not generated. They were hand written plists from before this generator existed,
each carrying `{ROOT}` and a full schedule and each saying inside itself that it
was held back on purpose. `gen_launchd.py --check` had started naming all three
rather than passing over them in silence, which is how they went unnoticed until
2026-09-06.

Arming them was a decision for Mo and not a rename, for one reason each:

- `deadman` is the ONLY job in this project whose purpose is to place an order.
  It runs `agent/deadman.py --really`, which pulls the kill switch and flattens
  the account when the loop dies holding a position. That is a protective action
  and it is still an order.
- `sheet_sync` had never run against the real Google Sheet, so its first
  scheduled run would have been its first run, against Mo's live sheet.
- `backup_db` had never run on a schedule.

## The last three loaded, 2026-09-07

Mo approved the kill switch and unattended operation on 2026-09-06 and the hub
ruled the next day that all three should go on. Each was first rewritten as a
proper template and each was run once by hand before anything was loaded.

The three by-hand runs, all from
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading`:

```
./venv312/bin/python ledger/sync_sheet.py --dry-run --limit 5
./venv312/bin/python ledger/sync_sheet.py --write
./scripts/backup_db.sh
./venv312/bin/python agent/deadman.py
```

The sheet sync wrote 4,544 cells to the Rules Log tab and 5 to Config, and the
sheet was read back afterwards through the Sheets REST API to check the headings
and the formula columns had survived. The backup wrote
`data/backups/trading_2026-09-07.sqlite` at 352K. The dead man's handle was run
as a dry run, with no `--really`, and stopped at question 2 saying the market was
shut, which is the right answer at that hour. **A dry run is the only way it
should ever be run by hand.**

Then the generator wrote all nine plists and loaded them:

```
python3 /Users/mtalib/workspace_repos/personal_repo/agentic_trading/scripts/gen_launchd.py
python3 /Users/mtalib/workspace_repos/personal_repo/agentic_trading/scripts/gen_launchd.py --check
python3 /Users/mtalib/workspace_repos/personal_repo/agentic_trading/scripts/gen_launchd.py --install
launchctl list | grep agentic
```

`--install` boots each job out before bootstrapping it, so running it with six
already loaded reloads those six rather than complaining. The last command
printed all nine:

```
-	0	com.mtalib.agentic-trading.backup_db
-	0	com.mtalib.agentic-trading.deadman
-	0	com.mtalib.agentic-trading.learning
-	0	com.mtalib.agentic-trading.preflight
-	0	com.mtalib.agentic-trading.recorder
-	0	com.mtalib.agentic-trading.sheet_sync
-	0	com.mtalib.agentic-trading.tick
-	0	com.mtalib.agentic-trading.watchdog
-	0	com.mtalib.agentic-trading.weekly
```

The `-` is the process id column and means the job is not running this second,
which is right for a job waiting on its schedule. The `0` is the last exit
status.

**One thing is wrong and is not fixed by any of this.** The Mac is set to
Pacific, so all nine fire three hours late against New York. See the time zone
note further up. Fixing the Mac's time zone fixes all nine and needs no
regeneration.

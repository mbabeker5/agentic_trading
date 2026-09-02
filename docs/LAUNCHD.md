# The five minute wake up, and how to switch it on

Status: written 2026-09-02. The job described here is **not loaded**. It is a
definition sitting in the repo waiting for you to decide.

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

## The schedule

Every five minutes from 09:25 to 16:00, Monday to Friday. That is 80 wake ups a
day, and 400 entries in the file, one for each time on each weekday.

09:25 rather than 09:30 on purpose: the first wake up of the day happens five
minutes before the market opens, so if IB Gateway is down or the MCP server
needs restarting, that shows up in the log before it costs anything.

launchd works in whatever time zone the Mac is set to, and there is no way to
pin a time zone inside the file. This Mac is in Eastern. That was checked with
`date +%Z` on 2026-09-02 and it answered `EDT`, so the times in the file are
already New York times and need no adjusting.

If the Mac ever moves to another time zone, every time in that file becomes
wrong and has to be regenerated, because the market keeps New York hours no
matter what the Mac thinks. Worth checking with `date +%Z` before you trust a
tick log after any travel.

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

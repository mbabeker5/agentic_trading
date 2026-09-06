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

## The four guards

| Guard | When it runs | What it can do |
|---|---|---|
| `agent/alerts.py` | whenever something calls it | send you a message four ways |
| `agent/watchdog.py` | every 5 minutes in market hours, hourly otherwise | check six things, message you, start IB Gateway once |
| `agent/preflight.py` | 09:00 on weekdays | check five things, stop the day's trading, message you |
| `agent/kill_switch.sh` | when you run it | stop the loop, cancel every order, close every position |

Only the last one can trade. The other three read.

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
| `Kill switch fired` | Somebody or something pulled the panic button | Read the message. It lists what was cancelled, what was closed, and what is left over. |
| `Recovered: ...` | Nothing. It is over | Nothing. |

## The panic button

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/kill_switch.sh --really
```

In order, that:

1. writes `output/STOP` and `output/LOOP_DISABLED`, which stops the loop dead;
2. cancels every working order on the account;
3. sells every long and buys back every short, at the market, transmitted;
4. reads the account back and prints what is actually left;
5. messages you with all of it.

Step 1 happens **whether or not you remember `--really`**. That is deliberate.
The worst possible outcome would be typing this in a hurry, leaving off the flag,
and walking away believing the agent was stopped when it was not. So the fast,
certain part is always real, and `--really` only controls the part that talks to
the broker.

The rehearsal is safe at any time:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/kill_switch.sh
```

That reads the account, prints exactly which orders it would cancel and which
positions it would close, and sends nothing to the broker. It still writes the
two stop files, so run `agent/reenable.sh` afterwards.

Two things to know. Market orders do not fill outside trading hours, they queue
for the next open, so a kill switch pulled at 8 in the evening leaves you with
orders waiting rather than a flat account. The script says so rather than
pretending. And it refuses outright on any account that does not start with DU,
so it cannot be pointed at a live account.

## Turning it back on

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/reenable.sh
```

It removes the three files that hold the agent back and tells you which ones
were actually there. It does not restart Gateway, reload any launchd job, or
buy back anything the kill switch sold.

## The three brakes

Three files, all in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/`, all
removed by `agent/reenable.sh`.

| File | Effect | Written by |
|---|---|---|
| `STOP` | The loop closes positions but opens none. Getting out is always allowed. | `kill_switch.sh`, or you, by hand |
| `LOOP_DISABLED` | `run_tick.sh` does not run a tick at all | `kill_switch.sh` |
| `NO_TRADE_TODAY` | Same as STOP: close, do not open | `preflight.py`, when a 09:00 check fails |

`NO_TRADE_TODAY` does not clear itself at midnight, on purpose. A morning that
failed its checks should need a person to look before the agent trades again.

To pause without stopping the launchd job at all, one line does it:

```
touch /Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/STOP
```

## Where to look when something is odd

```
output/alerts.log                every alert ever sent, one line each
output/watchdog.log              one line per watchdog run
output/watchdog_state.json       what the watchdog currently believes
output/preflight_YYYY-MM-DD.json the 09:00 answers, check by check
output/loop.log                  one line per tick
output/tick_YYYY-MM-DD.log       everything a single day's ticks printed
output/ibc_logs/                 IB Gateway's own logs
output/mcp_logs/mcp_ibkr.log     the MCP server
output/launchd_*.out.log         anything that broke before a script started
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

As of 2026-09-06:

* No launchd job is loaded. Not the tick, not the watchdog, not the
  pre-flight. All three are definitions sitting in the repo. Loading them is in
  `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/LAUNCHD.md`,
  and the watchdog is the one to load first.
* iMessage alerts are off until `IMESSAGE_TO` exists in
  `.secrets/alerts.env`. Slack and the screen banner work now.
* Real time quotes are not arriving. The paper Gateway answered IBKR code
  10168 on 2026-09-06, which means the subscription is not reaching it. The
  pre-flight will fail on `market_data` and write NO_TRADE_TODAY until that is
  sorted. Details in `docs/SETUP_IBKR_ACCOUNT.md`.

# Moving the shop to another Mac

Written 2026-09-06. This is the whole job of moving the trading agent from one
Mac to another, in the order you do it.

Read the rule below first. It is the one thing here that can cost you money
rather than an afternoon.

**IBKR shares live market data subscriptions with the paper account only when both sessions run on the same machine. After the move to the Mac Mini, Mo must not open a live IBKR session (Client Portal, Trader Workstation or the mobile app) on the laptop during market hours, or the Mini's paper session loses its data and the agent trades blind.** Source: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/data_sources/quote_feeds_2026-09-06.md`.

Never running on two machines at once: the Gateway paper login, and the trading loop.

## What actually has to move

Almost nothing. That is the point of the work that went before this page.

No file in this project has a home folder written into its code any more. Every
Python file asks
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/paths.py`
where things are, and every shell script works it out from where the script
itself is sitting. So a plain `git clone` on the new Mac, into any folder you
like, finds itself with nothing configured.

What does not come across in the clone is the rest of it, and that is mostly
what this page is about:

1. **Programs**, which are IB Gateway, IBC and Python 3.12. You install them.
2. **Secrets**, which are gitignored and never leave the old machine on their
   own. You recreate them by hand, file by file, and section 6 says where each
   value comes from.
3. **The launchd jobs**, which are per machine by nature. A generator writes
   them, so this is one command rather than six files.
4. **The database**, which is one file, `data/trading.sqlite` under the project
   root. The whole `data/` folder is gitignored, the same way `.secrets/` is,
   so the clone does not bring it. If the old machine has already traded, copy
   that one file across, and the simplest way is to copy the newest file out of
   `data/backups/`. If it has not traded yet, run
   `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/scripts/migrate_db.py`
   with the project's Python and you get an empty one. It is one file and
   nothing else.

Plan for an hour, most of which is waiting for downloads and for IBKR.

## The steps, in order

### 1. Clone the project

Anywhere you like. The project no longer cares where it lives.

```
git clone git@github.com:<your account>/agentic_trading.git ~/agentic_trading
cd ~/agentic_trading
```

From here on, `<root>` means wherever you just put it. If you want to check what
the project thinks its own root is at any point:

```
python3 <root>/agent/paths.py
```

That prints the root, the config folder, the secrets folder, the output folder,
the venv Python, the Gateway version and the Gateway folder, and touches nothing.
It is the quickest way to see that the new machine has understood itself.

If for some reason you want the project to run from a different folder than the
one it sits in, set `AGENTIC_TRADING_ROOT` in your environment and everything,
Python and shell alike, follows it. You will not normally need this. The launchd
jobs set it for their own runs regardless.

### 2. Install IB Gateway, the pinned version

The version is pinned in one place:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/gateway.env
```

Today that file says `IB_GATEWAY_VERSION=10.45`. Install that exact version, the
stable channel, and on Apple silicon take the native build. IBKR's installer
puts each version in its own folder under `~/Applications`, so you end up with:

```
~/Applications/IB Gateway 10.45/
```

which is where the project expects to find it, without being told. If your Mac
keeps Gateway somewhere else, `/Applications` for instance, set `IB_GATEWAY_DIR`
in the environment to the full folder path and both the shell scripts and
`agent/paths.py` will use it.

Do not install a newer Gateway and hope. IBC's auto-login is version aware, and
a mismatch between the number in `gateway.env` and the folder on disk stops
`start_gateway.sh` with a message naming both. Upgrading is a deliberate act:
install the new version, change the number in `gateway.env`, run
`start_gateway.sh` again.

### 3. Install IBC

IBC is the helper that logs Gateway in without a person clicking. It is a third
party download, not our source, so it is gitignored and absent from the clone.
One command fetches it:

```
<root>/agent/install_ibc.sh
```

That downloads the pinned IBC release, unpacks it into `<root>/ibc`, and makes
its scripts executable. The version is pinned inside the script.

### 4. Install Homebrew Python 3.12

Python 3.12 specifically. The MCP server refuses anything newer, which is the
whole reason this project carries a second environment.

```
brew install python@3.12
```

That gives you `/opt/homebrew/opt/python@3.12/bin/python3.12` on Apple silicon.
Check it before moving on:

```
/opt/homebrew/opt/python@3.12/bin/python3.12 -V
```

### 5. Build the virtual environment

```
/opt/homebrew/opt/python@3.12/bin/python3.12 -m venv <root>/venv312
<root>/venv312/bin/pip install -r <root>/requirements-312.txt
```

That file pins every version, including the MCP server itself, which is
installed straight from a pinned git commit rather than from PyPI. So the new
Mac gets the same code as the old one and not a newer release that behaves
differently.

Two checks that the environment is real:

```
<root>/venv312/bin/python -V          # expect 3.12.x
<root>/venv312/bin/python -m pytest -q
```

The test suite needs no broker, no network and no secrets. If it passes on the
new Mac, the code came across intact. If it does not, stop here and fix that
before touching anything to do with money.

### 6. Recreate the secrets, one file at a time

`<root>/.secrets/` is gitignored, so the clone gives you an empty folder. Nothing
in it is recoverable from GitHub, and nothing in it should ever be pasted into a
chat window.

Create the folder and lock it down first:

```
mkdir -p <root>/.secrets
chmod 700 <root>/.secrets
```

Then each file. The two marked **required** are the ones without which the agent
cannot work at all.

#### `.secrets/ibkr_paper.env` (required)

Two lines:

```
IBKR_PAPER_USER=...
IBKR_PAPER_PASSWORD=...
```

**Where the values come from.** Your Interactive Brokers login. The catch worth
knowing, because it looks like a mistake when you first see it: the username is
your **live** account username, and the password is your **paper** account
password. IBC is told to use paper mode, so it takes that pair to the paper
side. There is no separate paper username to hunt for. The full account opening
story is in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/SETUP_IBKR_ACCOUNT.md`.

**Read by** `<root>/agent/start_gateway.sh`, which sources it and writes a
throwaway launcher into `<root>/output/`. The password exists in that throwaway
copy and in memory, nowhere else, and `stop_gateway.sh` deletes it.

```
chmod 600 <root>/.secrets/ibkr_paper.env
```

#### `.secrets/slack_bot_token.txt` (required, and a per machine step)

A single line holding a Slack bot token, no key name, no newline needed.

**Where the value comes from.** The Slack app configuration page at
api.slack.com/apps, under OAuth and Permissions, the bot user OAuth token.

**This one needs a decision, because on the old Mac it is a symlink, not a
file.** It points at
`/Users/mtalib/workspace_repos/work_repo/.secrets/goldenstone_slack_bot_token.txt`,
a token that belongs to a different project and is borrowed here rather than
copied, so that there is only ever one of it. A symlink like that does not
survive a move on its own: clone the project onto a Mac that has no `work_repo`
and you get a link pointing at nothing.

So on the new Mac, pick one:

* If that other repository is also on the new Mac, recreate the same link:

  ```
  ln -s /Users/mtalib/workspace_repos/work_repo/.secrets/goldenstone_slack_bot_token.txt \
        <root>/.secrets/slack_bot_token.txt
  ```

* If it is not, put a real file there with the token in it, and remember that
  you now have two copies of one token and they can drift apart.

**Read by** `<root>/agent/alerts.py`. If the file is missing or the link dangles,
alerts do not stop, they quietly fall back to the screen banner and the log file.
That is easy not to notice, so check it. The test is harmless:

```
<root>/venv312/bin/python <root>/agent/alerts.py --test
```

Look at the `delivered=` part of the line it prints. If `slack` is not in that
list, the token is not working.

#### `.secrets/alerts.env`

```
SLACK_USER_ID=...
SLACK_USER_EMAIL=...
IMESSAGE_TO=+44...
```

**You mostly do not have to fill this one in.** The two Slack lines can be left
out entirely. `alerts.py` looks your Slack user up by email the first time and
writes the answer back into this file, so later alerts are one call instead of
two. It refills itself.

`IMESSAGE_TO` is your own mobile number and is the only line you actually type.
It switches on text alerts, and it is optional. Note that the first text will
make macOS ask permission to control Messages. That permission is per machine,
so the new Mac will ask again even though the old one already said yes.

**Read by** `<root>/agent/alerts.py`.

#### `.secrets/token_personal_drive.json` (per machine step)

A Google OAuth token, used to write the ledger spreadsheet.

**This is not a value you copy off a website.** It is minted by an OAuth consent
flow: a script opens a browser, you sign in as
**mtalib.personal@gmail.com**, and Google hands back a token file. On the old Mac
the script that does this is
`/Users/mtalib/workspace_repos/work_repo/.secrets/auth_personal_drive_write.py`,
and the client id and secret it uses come from an OAuth client in the Google
Cloud Console.

Like the Slack token, on the old Mac this is a symlink, pointing at
`/Users/mtalib/workspace_repos/work_repo/.secrets/token_personal_drive_write.json`.
Same two choices as before, but here **re-running the consent flow is the better
one.** A copied token carries a refresh token and an expiry that may already be
stale, and a token that expires quietly is worse than one that was never there.

**Read by** `<root>/ledger/ledger_writer.py` and
`<root>/ledger/create_ledger_sheet.py`, and needed by the Friday weekly review
job, which reads the ledger. If it is missing, ledger writes fail silently by
design so that a spreadsheet problem can never stop a trade. Silently is the
problem: check it deliberately rather than waiting to notice.

```
<root>/venv312/bin/python <root>/ledger/ledger_writer.py --dry-run
```

#### `.secrets/openrouter.env`

```
OPENROUTER_API_KEY=...
```

**Where the value comes from.** The Keys page of your OpenRouter account at
openrouter.ai. This particular key routes through bring your own key, so
OpenRouter reports a cost of zero and the real spend shows up only in that key's
own counters on the OpenRouter site. Details in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/MODELS.md`.

**Read by** `<root>/agent/models.py`.

#### `.secrets/anthropic.env` (does not exist yet)

```
ANTHROPIC_API_KEY=...
```

**Where the value comes from.** console.anthropic.com, Settings, API keys.

This file does not exist on the old Mac either, so there is nothing to carry
across. It is listed here so that the absence is on record rather than looking
like something lost in the move. It is needed before any book that calls Claude
directly can run.

**Read by** `<root>/agent/models.py`, which checks the environment variable
first, then this file, then whatever Anthropic credentials already exist on the
machine.

#### `.secrets/finviz.env` (does not exist, and is switched off)

```
FINVIZ_AUTH_TOKEN=...
```

Same situation. The scanner can use Finviz, but Finviz is set to `enabled:
false` in `<root>/config/guardrails.yaml`, so nothing wants this today. Ignore it
unless you turn Finviz on.

#### Last, check the permissions

```
chmod 600 <root>/.secrets/*
ls -la <root>/.secrets
```

Everything should be `-rw-------`, owned by you, and the two links should point
somewhere real rather than at nothing.

### 7. Sort out the market data before you trust a single quote

This is the step people skip, and it is the step that decides whether the agent
is looking at real prices or at nothing.

IBKR sells the market data subscription to your **live** account and then shares
it with the paper account, and that sharing has two conditions attached.

**First, the sharing toggle has to be on.** Client Portal, Settings, Account
Settings, Paper Trading Account, and tick "Share real-time market data
subscriptions with paper trading account". IBKR applies it overnight, so if you
turn it on today the first honest real time check is tomorrow morning after
09:30 Eastern.

**Second, and this is the rule at the top of this page, the live session and the
paper session have to be on the same machine.** IBKR allows one market data
session per user. Live and paper share it. So while the Mac Mini is running
Gateway on the paper login during market hours, opening Client Portal with a
watchlist, or Trader Workstation, or the IBKR mobile app, on the laptop takes the
data session away from the Mini. The Mini does not error out loudly. It gets
error 10197, "No market data during competing live session", its quotes go
stale, and the agent carries on deciding from prices that are not moving.

That is the failure to be afraid of. The agent does not stop, it just stops being
right.

The watchdog does catch it. `market_data failed` with code 10197 in an alert
means exactly this: something on the live login has stolen the feed, and closing
it gives the feed back. But it catches it after the fact, which is why the rule
is a rule and not a troubleshooting step.

The subscription itself, and which networks to buy, is in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/SETUP_IBKR_ACCOUNT.md`.
It does not change when the machine does. You are moving the session, not the
account.

### 8. Start Gateway and log in

```
<root>/agent/start_gateway.sh
```

Read the version out of `config/gateway.env`, find Gateway, fill in the login
from `.secrets/ibkr_paper.env`, and start it in paper mode on port 4002.

Watch your phone. IBKR often sends a two factor prompt to the IBKR Mobile app,
and a first login from a machine IBKR has never seen before is exactly when it
will. The script cannot answer that for you.

If it stops with a message rather than starting, the message names the problem:
a missing secrets file, a missing `ibc/` folder, or a Gateway folder that is not
where the version says it should be.

### 9. Smoke test the connection

```
<root>/venv312/bin/python <root>/agent/smoke_test.py
```

It connects to the paper API port, prints the account id, the cash, any open
positions, a SPY quote and one historical bar, then disconnects. It places no
orders and every request has its own timeout, so it always finishes.

Two things to look at in the output. The account id must start with `DU`, which
is how you know you are on the paper side. And the SPY quote says whether it came
back live or delayed. Delayed on the first evening is normal and means step 7 has
not finished settling. Delayed on a weekday after 09:30 Eastern means step 7 is
not done.

### 10. Run the pre-flight as a rehearsal

```
<root>/venv312/bin/python <root>/agent/preflight.py --dry-run
```

This is the morning check, run by hand and with its teeth removed. It asks the
same five questions the 09:00 job asks: is Gateway logged into the paper account,
are the quotes real time, does the scanner run cleanly, do the books and the
broker agree about what is held, and do the day trade counters load.

Because of `--dry-run` it writes `output/preflight_dryrun.json` instead of the
dated report, creates no `NO_TRADE_TODAY`, and sends you no message. So you can
run it as often as you like while you sort things out.

Give it a few minutes. The scanner is the slow part.

This is the real end of the migration. If the pre-flight is happy on the new
machine, the new machine can do the job.

### 11. Write and install the launchd jobs

The job files carry absolute paths by nature, so they are generated rather than
copied. On the new Mac:

```
python3 <root>/scripts/gen_launchd.py
```

That rewrites all six plists in `<root>/config/launchd/` with the new machine's
folders, its Python and its path to `claude`, and **loads nothing**. Read what it
printed. It tells you the root, the venv Python and the `claude` it found.

If it warns that `claude` was not found, install Claude Code and sign in as
yourself before generating again. The two headless jobs, the daily learning loop
and the Friday review, are the ones that need it, and launchd starts jobs with
almost no PATH, so the full path has to be baked in.

Then, and only when you mean it:

```
python3 <root>/scripts/gen_launchd.py --install
```

That copies the plists into `~/Library/LaunchAgents` and asks launchd to load
them. **This is the step that starts the agent running on a schedule.** It is the
only command in this whole page that does.

The undo is the same command with `--uninstall`.

### 12. Check the jobs are really loaded

```
launchctl list | grep com.mtalib.agentic-trading
```

Six lines, one per job: `tick`, `watchdog`, `preflight`, `recorder`, `learning`
and `weekly`. The middle column is the last exit code, and a `0` or a `-` there
is fine on a job that has not run yet.

For one job in detail:

```
launchctl print gui/$(id -u)/com.mtalib.agentic-trading.watchdog
```

`state` should say `waiting`.

One more check, and it matters more than it looks:

```
date +%Z
```

launchd works in the Mac's own local time zone and there is no setting inside a
plist that pins one. The market keeps New York hours whatever the Mac thinks. If
that command says anything other than `EST` or `EDT`, either set the new Mac to
Eastern or every time in every template is pointing at the wrong hour.

### 13. Stop everything on the old machine

Do this last, and do not skip it. Until you do, you have two of everything, and
section "What must never run twice" below is the list of what that breaks.

```
python3 /Users/mtalib/workspace_repos/personal_repo/agentic_trading/scripts/gen_launchd.py --uninstall
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/stop_mcp.sh
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/stop_gateway.sh
```

Then confirm nothing is left:

```
launchctl list | grep com.mtalib.agentic-trading      # expect no output
pgrep -f ibcalpha.ibc.IbcGateway                      # expect no output
nc -z 127.0.0.1 4002 || echo "port 4002 is closed, good"
```

If any launchd job survives the uninstall, take it out by hand:

```
launchctl bootout gui/$(id -u)/com.mtalib.agentic-trading.tick
launchctl bootout gui/$(id -u)/com.mtalib.agentic-trading.watchdog
launchctl bootout gui/$(id -u)/com.mtalib.agentic-trading.preflight
launchctl bootout gui/$(id -u)/com.mtalib.agentic-trading.recorder
launchctl bootout gui/$(id -u)/com.mtalib.agentic-trading.learning
launchctl bootout gui/$(id -u)/com.mtalib.agentic-trading.weekly
```

Leave the clone on the old Mac. It is a checkout of the same repository and
having it there costs nothing. It is the running jobs that must go, not the
files.

## What must never run twice

Five things, and each one breaks differently. This is the part to reread if you
ever find yourself with both machines awake.

### The Gateway paper login

**Why.** IBKR gives one market data session per user, and live and paper share
it. Two Gateways on the same login means two sessions fighting, and the loser
gets error 10197 and stale quotes. IBC's `ExistingSessionDetectedAction=primary`
setting means the second one to arrive can push the first one out, so it is not
even predictable which machine wins.

This is the same rule as the bold one at the top, seen from the other side. It
covers Client Portal with a watchlist open, Trader Workstation, and the IBKR
mobile app, not just Gateway.

**Stop it:**

```
<root>/agent/stop_gateway.sh
```

**Check it is stopped:**

```
pgrep -f ibcalpha.ibc.IbcGateway     # no output means stopped
```

### The trading loop

**Why.** Two loops means two sets of decisions against one account. Each one
reads positions the other opened, does not recognise them, and reacts. Position
sizes double, the guardrails on each machine count only their own orders, and
the ledger gets two versions of the same day.

**Stop it:**

```
launchctl bootout gui/$(id -u)/com.mtalib.agentic-trading.tick
```

**Or, if you want it stopped this second and are not in the mood for launchctl:**

```
<root>/agent/kill_switch.sh
```

That writes `output/STOP` and `output/LOOP_DISABLED` straight away, which stops
the loop dead whether or not you remembered `--really`. The undo is
`<root>/agent/reenable.sh`.

**Check it is stopped:**

```
launchctl print gui/$(id -u)/com.mtalib.agentic-trading.tick     # "could not find" means stopped
```

### The watchdog's restart logic

**Why.** This one is worse than it sounds. The watchdog is allowed to do exactly
one thing when it finds a problem: if Gateway is down, it starts Gateway. Two
watchdogs means two machines that will both notice the same Gateway being down
and both start one. You end up with exactly the competing session described
above, created by the very thing meant to be protecting you, at two in the
morning, while you are asleep.

Reading the watchdog on both machines would be harmless. It is the restart that
is not, and you cannot have one without the other.

**Stop it:**

```
launchctl bootout gui/$(id -u)/com.mtalib.agentic-trading.watchdog
```

### The recorder

**Why.** Both machines write market recordings into `output/` under the same
filenames, and the replay harness later reads them believing they are one
coherent day. Two half days interleaved into one file is a recorded day that
never happened, and every replay run against it is quietly meaningless. Since the
whole purpose of the recording is to be the gate a book must pass before it
trades for real, a corrupted recording is a gate that opens for the wrong reason.

**Stop it:**

```
launchctl bootout gui/$(id -u)/com.mtalib.agentic-trading.recorder
```

### The dead man trigger

**Why.** Anything that flattens the account when it stops hearing a heartbeat has
to be the only one of its kind. Two of them, and the second sees the first one's
flattening as more evidence that something is wrong.

**As of 2026-09-06 there is no dead man launchd job.** `config/launchd/templates/`
holds six templates and none of them is this, so nothing fires on its own today.
The kill switch is a button you press. A dead man handle is being written while
this page is being written, and the moment it gets a template in that folder the
generator picks it up with no change to the generator. The rule is written down
now so that it is already here when that happens, rather than being learned the
hard way afterwards.

**When it exists, stop it the same way as the rest:**

```
launchctl bootout gui/$(id -u)/com.mtalib.agentic-trading.deadman
```

### The two that are safe to run twice

For completeness, because "stop everything" is easier to follow than "stop
these four". The daily learning loop and the Friday review only read files and
write files inside their own checkout. Two of them running means two journals
that disagree about the day, which is untidy and harmless. Stop them anyway when
you finish the move, so that the journal on the new machine is the only one.

## If it goes wrong: rolling back

The clone on the old machine is still there and still works. Rolling back is
turning it on again and turning the new one off, in that order.

### Stop the new machine first

```
python3 <root>/scripts/gen_launchd.py --uninstall
<root>/agent/stop_mcp.sh
<root>/agent/stop_gateway.sh
```

Then check, because "I thought I had stopped it" is how you end up with two
Gateways:

```
launchctl list | grep com.mtalib.agentic-trading      # expect no output
pgrep -f ibcalpha.ibc.IbcGateway                      # expect no output
```

### Then start the old machine again

```
cd /Users/mtalib/workspace_repos/personal_repo/agentic_trading
git pull
python3 scripts/gen_launchd.py
./agent/start_gateway.sh
./venv312/bin/python agent/smoke_test.py
./venv312/bin/python agent/preflight.py --dry-run
python3 scripts/gen_launchd.py --install
launchctl list | grep com.mtalib.agentic-trading
```

The `git pull` and the regenerate matter. If anything was committed while the new
machine was in charge, the old checkout is behind, and the generated plists on
the old machine are only correct for the old machine's folders. Generating again
costs seconds and removes a whole category of confusion.

### If the account is in a strange state

If a book opened positions on the new machine and you are rolling back mid day,
flatten before you hand control back rather than leaving two half opinions about
what is held. The rehearsal first:

```
<root>/agent/kill_switch.sh
```

Read what it says it would cancel and close. If that is right:

```
<root>/agent/kill_switch.sh --really
```

Then run the reconciler on the old machine before you let it trade, so that its
idea of what is held and the broker's idea agree:

```
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
  /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/reconcile.py
```

One caution about the kill switch, which is in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/OPERATIONS.md`
too. Market orders do not fill outside trading hours, they queue for the next
open. So a kill switch pulled in the evening leaves you with orders waiting
rather than a flat account, and the script says so rather than pretending
otherwise.

### If you only want to pause, not roll back

Sometimes the honest answer is that neither machine should be trading while you
work it out. One file does that on whichever machine is in charge:

```
touch <root>/output/STOP
```

While it exists, every tick refuses to open anything. It will still close what is
open, which is the point: getting out is always allowed. Remove it with
`<root>/agent/reenable.sh`.

## What this page could not check

Written and verified on one Mac, so parts of it are reasoned from the code and
the documents rather than watched happening. So that none of it surprises you
later, this is what was never actually run end to end:

* **The whole thing on a second Mac.** Every step below step 5 was read out of
  the scripts rather than performed on a fresh machine. The steps that are proven
  are the ones that do not need one: the project finds its own root from any
  folder (there is a test that copies it somewhere else and imports it), the
  generator produces valid job files for any root you hand it (there is a test
  that gives it a made up home folder and checks this Mac's name appears nowhere
  in the output), and the six generated plists all pass `plutil -lint`.
* **The Gateway install on a machine that has never had it.** Only the version
  check was exercised, not IBKR's installer.
* **The two factor prompt on a new machine.** Expect one. IBKR has not seen the
  new Mac before.
* **Whether the market data subscription really does follow to a new machine the
  moment the old one stops.** The one machine rule comes from the research at
  `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/data_sources/quote_feeds_2026-09-06.md`,
  not from watching it happen. How quickly IBKR hands the session over after the
  old Gateway stops is unknown. Assume it is not instant and do the move outside
  market hours.
* **`launchctl bootstrap` on a second machine.** No job has been loaded anywhere,
  on either machine. Every launchctl command here is written out from the plists
  and from `docs/LAUNCHD.md` rather than from a job that has actually run.
* **The two headless Claude jobs.** They have never fired. Whether `claude -p`
  behaves under launchd, with no terminal and a prompt on standard input, is
  unproven on any machine. If they are silent, the first place to look is
  `output/launchd_learning.err.log` and `output/launchd_weekly.err.log`, and the
  most likely cause is a sign in that the login keychain will not hand over to a
  job.

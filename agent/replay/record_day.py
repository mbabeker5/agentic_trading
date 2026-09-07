#!/usr/bin/env python3
"""Record one real trading day, minute by minute, so the harness has a day to replay.

Why this file exists. Before any of the five books is allowed to place a live
paper order, the whole loop has to be replayed from end to end against recorded
market data, with a fake broker standing in for IBKR, so that every guardrail
gets exercised on a day that actually happened. You cannot do that without a
recording. This script makes the recording.

Three files share the replay work:

    agent/replay/fetch_history.py   pulls past bars, the background the day sits on
    agent/replay/record_day.py      this file, records one day as it happens
    agent/replay/fake_broker.py     replays what was recorded and pretends to fill

Nothing here can place, change or cancel an order. It connects with
readonly=True and calls exactly four things on the Gateway API, all of them
reads: qualifyContractsAsync, reqMarketDataType, reqTickersAsync and
reqHistoricalDataAsync. There is no order code in the file at all, and that is
deliberate rather than an oversight waiting to be fixed.

How it runs. Two shapes, and they are for different jobs.

    Normal, the real Tuesday run. The script itself loops from 09:25 to 16:05
    Eastern, waking on the five minute grid: 09:25, 09:30, 09:35 and so on to
    16:05. It sleeps in between. Every wake-up time is worked out from the grid
    itself, never as "now plus five minutes", so a slow tick cannot make the
    whole afternoon drift later and later.

    One tick and out, with --once. Does a single tick right now and exits. This
    is what you run to test the thing outside market hours, when every quote
    comes back stale or empty.

This is the one place in the project that does loop, which is the opposite of
agent/loop.py, where launchd wakes the script every five minutes and the script
exits again. The difference is on purpose. The trading loop must survive a
crash without losing the day, so it keeps its memory in a file on disk and lets
launchd own the clock. The recorder holds an open Gateway connection and a
market data subscription, and reopening those every five minutes would cost
more than it saves, so it stays up and owns its own clock. What it borrows from
the trading loop is the important half: a tick that throws is written down and
the next one still happens.

Missed ticks never get made up. If the Mac slept through an hour, or one tick
overran its slot, the script does not then fire twelve requests in a row to
catch up, because that is exactly how you get the whole Gateway connection
throttled for everyone. It writes down which slots it missed and carries on
from the next real one.

What one tick writes, all under

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/recordings/<YYYY-MM-DD>/

    snapshots.jsonl      one line per symbol per tick: bid, ask, last, close,
                         volume, and which kind of market data Gateway served
    bars_5m.jsonl        one line per symbol per tick: the newest five minute bar
    ticks.jsonl          one line per tick: what ran, how late it was, what broke
    scanner_0935.json    the 09:35 scanner run's own output, copied in
    scanner_0940.json    the 09:40 one
    manifest.json        rewritten every tick, the file a person reads to decide
                         whether the day is usable at all

output/ is gitignored, so none of this ever lands in git.

Run it for real on Tuesday like this:

    cd /Users/mtalib/workspace_repos/personal_repo/agentic_trading
    ./venv312/bin/python agent/replay/record_day.py

Or test one tick right now, into a folder that will not collide with a real
recording:

    ./venv312/bin/python agent/replay/record_day.py --once --symbols SPY,QQQ --date 2026-09-06

Exit code is 0 whenever the run finished or was stopped politely, including a
run where Gateway was down the whole time and every tick is a written-down
failure. It is 1 only when the arguments themselves made no sense.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import subprocess
import sys
import time
from datetime import date as date_type, datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any

from ib_async import IB, Stock

# The project root, three folders up from this file. Put on sys.path so that
# `from agent.replay import common` resolves the same way whether this file was
# started as a script (python agent/replay/record_day.py, where Python only
# knows about the agent/replay folder) or imported as part of the package
# (from agent.replay import record_day, where it is already resolvable). The
# repo has no __init__.py files, so these are namespace packages and the only
# thing that matters is that the root is findable.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.replay import common                            # noqa: E402

log = logging.getLogger("replay.record_day")


# --------------------------------------------------------------------- settings

#: The recording window, Eastern. Five minutes before the open so the first
#: tick catches the pre-open book, five minutes past the close so the last
#: prints and the closing auction land inside the recording.
DEFAULT_START = "09:25"
DEFAULT_END = "16:05"
DEFAULT_INTERVAL_MINUTES = 5

#: The two slots where the scanner is run as a subprocess, matching the times
#: agent/loop.py runs it on a real trading day.
SCANNER_SLOTS = ("09:35", "09:40")

#: How many symbols a single tick will ever touch. This is the number that
#: keeps the recorder inside Gateway's data ration, so it is a hard cap and not
#: a suggestion. The arithmetic, said out loud:
#:
#:     one historical request per symbol per tick
#:     25 symbols, one tick every 5 minutes  =  25 requests per 5 minutes
#:                                           =  50 requests per 10 minutes
#:
#: Gateway allows roughly 60 historical requests in any rolling ten minute
#: window, counted across every client on the connection, and our own budget
#: (HistoryPacer in common.py) sits at 55. So 25 symbols leaves five requests
#: of headroom for the whole rest of the machine. If fetch_history.py is also
#: running, or a Claude Code session is poking at Gateway, turn this down with
#: --max-symbols or turn the budget down with --history-budget. The pacer will
#: not break if you go over, it will just start making ticks run late.
DEFAULT_MAX_SYMBOLS = 25

#: How long to wait on one Gateway read before giving up on it. Neither call
#: has a timeout of its own in ib_async: reqTickersAsync in particular waits
#: forever for a snapshot that Gateway has quietly decided not to send, which
#: on a closed market is a real possibility. Without these numbers the whole
#: recorder would hang on the first bad symbol.
SNAPSHOT_TIMEOUT_SECONDS = 30.0
HISTORY_TIMEOUT_SECONDS = 60.0

#: Looking a symbol up is a Gateway round trip like any other, and
#: qualifyContractsAsync has no timeout of its own either. Twenty seconds, the
#: same bound the connection itself gets in agent/replay/common.py.
QUALIFY_TIMEOUT_SECONDS = 20.0

#: THE WHOLE OF ONE TICK. Under launchd every tick of the real day is its own
#: --once process on a five minute timetable, so a tick still going after four
#: minutes has already lost its slot and is now only in the way of the next one.
#: Past this it is written down as missed and the process exits, which is worth
#: far more than a tick that eventually succeeds an hour late.
#:
#: Why the number is needed at all: on 2026-09-07 IB Gateway was up and logged
#: in but had lost its own connection to IBKR (warning 2110), every read timed
#: out after a long wait, and one --once tick sat there for eighteen minutes.
TICK_TIMEOUT_SECONDS = 240.0

#: Snapshots go out in batches rather than all at once, so that one symbol
#: Gateway refuses to answer about only costs its batch and not the whole tick.
SNAPSHOT_BATCH_SIZE = 10

#: A ceiling on how many shares of one name can plausibly trade in one day.
#: A hundred billion is roughly a thousand times the busiest session any single
#: US name has ever had, so nothing real will ever be thrown out by this.
#:
#: It is here because IBKR's delayed feed sends nonsense in the volume field
#: when the market is shut. Measured on Sunday 2026-09-06 against the live paper
#: Gateway, delayed SPY came back with a volume of 34,054,225,730,979 shares
#: while its price, high, low and previous close were all perfectly sensible.
#: A number like that quietly wrecks anything downstream that sizes a position
#: or judges liquidity, so it is written out as null with the original kept
#: beside it in volume_raw, rather than passed on as if it were a share count.
MAX_PLAUSIBLE_VOLUME = 100_000_000_000.0

#: How many distinct warnings the manifest will carry. A fault that repeats
#: every five minutes for six and a half hours would otherwise make the manifest
#: too big to read, which defeats the whole point of having one.
MAX_MANIFEST_WARNINGS = 100

#: Gateway's ways of saying "you are not subscribed to live data for this".
#: Seeing one of these is how we know to stop asking for live data and ask for
#: delayed instead.
NO_LIVE_DATA_CODES = frozenset({354, 10089, 10091, 10167, 10168, 10197})

#: How long to wait after Gateway complains that we asked for history too fast.
PACING_PAUSE_SECONDS = 60.0

VENV_PYTHON = PROJECT_ROOT / "venv312" / "bin" / "python"
SCANNER_SCRIPT = PROJECT_ROOT / "agent" / "scanner.py"
SCANNER_TIMEOUT_SECONDS = 240


# ----------------------------------------------------------------- small helpers

def clean_number(value: Any) -> float | None:
    """Turn one number from IBKR into something json.dumps will not ruin.

    Two separate traps here, and both of them silently poison a recording.

    The first is NaN. ib_async fills every price field it has no value for with
    NaN, which is normal and means "nothing to tell you". But json.dumps writes
    NaN out bare, and bare NaN is not legal JSON, so every reader downstream
    (the fake broker, a notebook, jq) either blows up or quietly guesses. So NaN
    becomes null here, before it ever reaches a file.

    The second is minus one. IBKR uses -1 as its own "not available" marker on
    volume and on a bid or ask that does not exist, for instance when a stock is
    halted. A price of minus one dollar is not a thing, so anything negative
    becomes null too.
    """
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    # NaN is the only value that is not equal to itself, which is how you test
    # for it without importing math. Infinity is caught by the range check.
    if number != number or number in (float("inf"), float("-inf")):
        return None
    if number < 0:
        return None
    return number


def parse_clock(text: str) -> clock_time:
    """"09:25" into a time object, and a clear complaint if it is not one."""
    try:
        hour, minute = str(text).strip().split(":")
        return clock_time(int(hour), int(minute))
    except Exception:                                       # noqa: BLE001
        raise argparse.ArgumentTypeError(
            f"{text!r} is not a time of day. Write it as HH:MM, such as 09:25."
        ) from None


def parse_day(text: str) -> date_type:
    try:
        return datetime.strptime(str(text).strip(), "%Y-%m-%d").date()
    except Exception:                                       # noqa: BLE001
        raise argparse.ArgumentTypeError(
            f"{text!r} is not a date. Write it as YYYY-MM-DD, such as 2026-09-08."
        ) from None


def non_zero_client_id(value: str) -> int:
    """Refuse client id 0, the same way agent/scanner.py does.

    Connecting as client 0 asks Gateway to hand this session any orders that
    were placed by hand in the Gateway window. It places nothing, but it is a
    change rather than a read, and a read-only recorder has no business making
    one.
    """
    number = int(value)
    if number == 0:
        raise argparse.ArgumentTypeError(
            "client id 0 would bind manually placed orders to this session, "
            "which is not read only. Pick any other number, such as 261."
        )
    return number


def tick_grid(day: date_type, start: clock_time, end: clock_time,
              interval_minutes: int) -> list[datetime]:
    """Every moment the recorder is meant to wake up, as aware Eastern times.

    Worked out once, from the grid, and never touched again. That is the whole
    point: if the next wake-up were computed as "whenever the last tick finished
    plus five minutes", then a tick that took forty seconds would push every
    later tick forty seconds further from the five minute boundary, and by the
    afternoon the recording would no longer line up with anything.
    """
    first = datetime.combine(day, start, tzinfo=common.EASTERN)
    last = datetime.combine(day, end, tzinfo=common.EASTERN)
    step = timedelta(minutes=max(1, int(interval_minutes)))
    slots: list[datetime] = []
    moment = first
    while moment <= last:
        slots.append(moment)
        moment += step
    return slots


def slot_label(moment: datetime) -> str:
    """"09:35", the way a person says a slot."""
    return f"{moment:%H:%M}"


# ------------------------------------------------------------------ the recorder

class DayRecorder:
    """Everything one recording day needs to remember while it runs."""

    def __init__(self, args: argparse.Namespace, day: date_type,
                 day_folder: Path) -> None:
        self.args = args
        self.day = day
        self.folder = day_folder
        self.snapshots_path = day_folder / "snapshots.jsonl"
        self.bars_path = day_folder / "bars_5m.jsonl"
        self.ticks_path = day_folder / "ticks.jsonl"
        self.manifest_path = day_folder / "manifest.json"

        self.ib = IB()
        self.pacer = common.HistoryPacer(budget=args.history_budget)

        # What we ask Gateway for, and what it turns out to be willing to give.
        self.requested_data_type = int(args.market_data_type)
        self.saw_no_live_data = False
        self.saw_pacing_violation = False

        # Contracts are qualified once and kept, because a ticker's conId does
        # not change during the day and qualifying is a round trip we can skip.
        self.qualified: dict[str, Stock] = {}

        # Running totals, all of which end up in the manifest.
        self.slots_run: list[str] = []
        self.slots_missed: list[str] = []
        self.symbols_seen: list[str] = []
        self.market_data_types: dict[str, int] = {}
        self.counts = {"ticks": 0, "ticks_ok": 0, "ticks_failed": 0,
                       "snapshots": 0, "snapshots_with_prices": 0, "bars": 0,
                       "reconnects": 0, "scanner_runs": 0, "scanner_failures": 0}
        self.warnings: list[str] = []
        self.warnings_dropped = 0
        # Symbols already complained about for a nonsense volume, so the same
        # complaint is not made seventy nine times over the day.
        self.odd_volume_symbols: set[str] = set()
        self.grid: list[datetime] = []
        self.started_at = datetime.now(common.EASTERN)
        self.ending = "still running"

    # -- picking up a day that is already part recorded ---------------------

    def resume_from_disk(self) -> int:
        """Read back the ticks already recorded into this folder today.

        This is what makes the manifest true when launchd is the clock. The
        launchd job wakes this script with --once every five minutes, so each
        tick is its own process starting with empty counters, and a manifest
        built from those counters alone would describe the last tick and claim
        the other eighty never happened. Anyone reading it at the end of the day
        would conclude the recording was worthless.

        ticks.jsonl is the durable record, appended to and never rewritten, so
        replaying it back into the counters gives a fresh process the whole
        day's picture. It also means the looping mode survives being killed and
        restarted at noon without losing the morning.

        Returns how many earlier ticks it found.
        """
        earlier = [row for row in common.read_jsonl(self.ticks_path)
                   if isinstance(row, dict) and row.get("slot")]
        if not earlier:
            return 0

        started = []
        for row in earlier:
            slot = str(row["slot"])
            if row.get("status") == "missed":
                self.slots_missed.append(slot)
            else:
                self.slots_run.append(slot)
                self.counts["ticks"] += 1
                if row.get("status") == "ok":
                    self.counts["ticks_ok"] += 1
                else:
                    self.counts["ticks_failed"] += 1
            for name in ("snapshots_written", "snapshots_with_prices", "bars_written"):
                key = {"snapshots_written": "snapshots",
                       "snapshots_with_prices": "snapshots_with_prices",
                       "bars_written": "bars"}[name]
                self.counts[key] += int(row.get(name) or 0)
            if row.get("reconnected"):
                self.counts["reconnects"] += 1
            if row.get("scanner_ran"):
                self.counts["scanner_runs"] += 1
                scanner = row.get("scanner") or {}
                if isinstance(scanner, dict) and not scanner.get("ok", True):
                    self.counts["scanner_failures"] += 1
            for symbol in row.get("symbol_list") or []:
                if symbol not in self.symbols_seen:
                    self.symbols_seen.append(symbol)
            if row.get("ran_at"):
                started.append(str(row["ran_at"]))

        # Which data types Gateway actually served has to come from the
        # snapshots themselves, because a tick record does not carry it.
        for row in common.read_jsonl(self.snapshots_path):
            label = row.get("market_data_type_label")
            if label:
                self.market_data_types[label] = self.market_data_types.get(label, 0) + 1

        if started:
            try:
                self.started_at = datetime.fromisoformat(min(started))
            except ValueError:
                pass
        log.info("picking up a day already in progress: %d earlier tick(s) read "
                 "back from %s", len(earlier), self.ticks_path)
        return len(earlier)

    # -- plumbing ----------------------------------------------------------

    def on_error(self, req_id: int, code: int, message: str, contract: Any) -> None:
        """Gateway talks a lot. Sort the noise from the things that matter."""
        if code in NO_LIVE_DATA_CODES:
            self.saw_no_live_data = True
        if code == 162 and common.is_pacing_message(message):
            self.saw_pacing_violation = True
        text = f"Gateway code {code} (request {req_id}): {message}"
        if code in common.BENIGN_ERROR_CODES or code in NO_LIVE_DATA_CODES:
            log.debug(text)
        else:
            log.warning(text)

    def note(self, message: str) -> None:
        """A warning worth putting in the manifest, not just the log.

        Capped, because this runs for six and a half hours and a fault that
        repeats every five minutes would otherwise grow the manifest until
        nobody could read it. Repeats of the same sentence are dropped, and once
        there are MAX_MANIFEST_WARNINGS distinct ones the manifest says how many
        more there were and leaves the rest in the log.
        """
        log.warning(message)
        if message in self.warnings:
            return
        if len(self.warnings) < MAX_MANIFEST_WARNINGS:
            self.warnings.append(message)
        else:
            self.warnings_dropped += 1

    # -- which symbols this tick covers ------------------------------------

    def shortlist_symbols(self) -> list[str]:
        """The names on today's shortlist, reread from disk every single tick.

        Reread rather than remembered because the shortlist does not exist when
        the recorder starts at 09:25. The scanner writes it at about 09:35, and
        the recorder is meant to pick it up on the next tick without being
        restarted.
        """
        if self.args.symbols:
            return common.dedupe(self.args.symbols.split(","))
        dated = common.output_dir() / f"shortlist_{self.day:%Y-%m-%d}.json"
        path = dated if dated.exists() else common.latest_shortlist_path()
        if path is None:
            return []
        return common.symbols_from_shortlist(path)

    def symbols_for_tick(self) -> list[str]:
        """SPY and QQQ first, then the shortlist, capped so a tick stays cheap.

        The two benchmarks go in every tick whatever else is happening, because
        a replay of a single name is close to meaningless without knowing what
        the whole market was doing at the same moment.
        """
        symbols = common.dedupe(list(common.BENCHMARK_SYMBOLS) + self.shortlist_symbols())
        capped = symbols[: max(1, int(self.args.max_symbols))]
        if len(symbols) > len(capped):
            self.note(f"the shortlist had {len(symbols)} names, only the first "
                      f"{len(capped)} are being recorded, which is the "
                      f"--max-symbols cap that keeps us inside Gateway's data ration")
        for symbol in capped:
            if symbol not in self.symbols_seen:
                self.symbols_seen.append(symbol)
        return capped

    async def qualify(self, symbols: list[str]) -> list[Stock]:
        """Turn tickers into contracts Gateway will accept, once each per day."""
        missing = [s for s in symbols if s not in self.qualified]
        if missing:
            wanted = [Stock(symbol, "SMART", "USD") for symbol in missing]
            try:
                # Bounded, because ib_async does not bound this one. A Gateway
                # that has lost IBKR answers a contract lookup with silence.
                await asyncio.wait_for(self.ib.qualifyContractsAsync(*wanted),
                                       timeout=QUALIFY_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                self.note(f"looking up contracts for {', '.join(missing)} took "
                          f"more than {QUALIFY_TIMEOUT_SECONDS:.0f} seconds, so "
                          f"this tick carried on without them")
            except Exception as exc:                        # noqa: BLE001
                self.note(f"could not look up contracts for "
                          f"{', '.join(missing)}: {exc!r}")
            for symbol, contract in zip(missing, wanted):
                if getattr(contract, "conId", 0):
                    self.qualified[symbol] = contract
                else:
                    self.note(f"Gateway does not recognise {symbol}, skipping it")
        return [self.qualified[s] for s in symbols if s in self.qualified]

    # -- the two kinds of reading ------------------------------------------

    async def snapshot_pass(self, moment: datetime, contracts: list[Stock],
                           errors: list[str]) -> dict[str, dict]:
        """Ask Gateway for one quote per symbol and turn the answers into records.

        Sent in small batches rather than all at once, so one symbol Gateway
        refuses to answer about only costs its own batch.

        Two things about the numbers that matter when you read the recording
        back later.

        The first is staleness. ib_async keeps one Ticker object per contract
        and reuses it, so if Gateway sends nothing new this tick, last tick's
        numbers are still sitting on it. That is why quote_time goes into the
        record next to the prices: it is Gateway's own timestamp, and if it did
        not move between two ticks then neither did the data.

        The second is the market data type. ib_async starts every ticker at 1,
        meaning live, and only changes it when Gateway says otherwise. So a
        ticker that came back completely empty is not evidence of live data, it
        is evidence of no data, and writing "live" next to five nulls would be a
        lie sitting in the recording forever. An empty snapshot therefore gets a
        null type and the label "none served".
        """
        recorded_at = datetime.now(common.EASTERN)
        rows: dict[str, dict] = {}
        for start in range(0, len(contracts), SNAPSHOT_BATCH_SIZE):
            batch = contracts[start:start + SNAPSHOT_BATCH_SIZE]
            try:
                tickers = await asyncio.wait_for(
                    self.ib.reqTickersAsync(*batch),
                    timeout=SNAPSHOT_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                names = ", ".join(common.symbol_of(c) for c in batch)
                errors.append(f"snapshots timed out after "
                              f"{SNAPSHOT_TIMEOUT_SECONDS:.0f} seconds for {names}")
                continue
            except Exception as exc:                        # noqa: BLE001
                names = ", ".join(common.symbol_of(c) for c in batch)
                errors.append(f"snapshots failed for {names}: {exc!r}")
                continue

            for ticker in tickers:
                symbol = common.symbol_of(getattr(ticker, "contract", None))
                quote_time = getattr(ticker, "time", None)
                volume = clean_number(getattr(ticker, "volume", None))
                volume_raw = None
                if volume is not None and volume > MAX_PLAUSIBLE_VOLUME:
                    volume_raw = volume
                    volume = None
                    if symbol not in self.odd_volume_symbols:
                        self.odd_volume_symbols.add(symbol)
                        self.note(f"Gateway reported an impossible volume for "
                                  f"{symbol} ({volume_raw:,.0f} shares), so volume "
                                  "is null in this recording. This is what the "
                                  "delayed feed does when the market is shut. The "
                                  "original number is kept in volume_raw.")
                row = {
                    "tick": moment.isoformat(),
                    "recorded_at": recorded_at.isoformat(),
                    "symbol": symbol,
                    "bid": clean_number(getattr(ticker, "bid", None)),
                    "ask": clean_number(getattr(ticker, "ask", None)),
                    "last": clean_number(getattr(ticker, "last", None)),
                    "close": clean_number(getattr(ticker, "close", None)),
                    "volume": volume,
                    "market_data_type": None,
                    "market_data_type_label": "none served",
                    # Extras the fake broker needs to decide a realistic fill.
                    "bid_size": clean_number(getattr(ticker, "bidSize", None)),
                    "ask_size": clean_number(getattr(ticker, "askSize", None)),
                    "quote_time": (quote_time.isoformat()
                                   if isinstance(quote_time, datetime) else None),
                    "volume_raw": volume_raw,
                }
                if any(row[key] is not None for key in
                       ("bid", "ask", "last", "close", "volume")):
                    served = int(getattr(ticker, "marketDataType", 0) or 0)
                    row["market_data_type"] = served
                    row["market_data_type_label"] = common.MARKET_DATA_TYPE_LABELS.get(
                        served, "unknown")
                rows[row["symbol"]] = row
        return rows

    async def take_snapshots(self, moment: datetime, contracts: list[Stock],
                            errors: list[str]) -> tuple[int, int]:
        """One quote per symbol, written to snapshots.jsonl.

        We ask for live data first. On a paper account with no market data
        subscription Gateway refuses, says so with error 10089 or one of its
        cousins, and hands back an empty ticker. That refusal is the signal to
        ask for delayed data instead, which the account usually does have.

        The switch happens once and then sticks for the rest of the run, because
        asking Gateway for live quotes it has already refused, seventy nine
        times over six and a half hours, would fill the log with the same
        complaint and get us nothing. The tick where the switch happens gets one
        second attempt straight away, so the very first tick of the day is not
        thrown away learning something we then remember all day.

        Returns how many rows were written and how many of them actually had a
        number in them, because those two are very different things and the
        manifest needs to be honest about the difference.
        """
        self.ib.reqMarketDataType(self.requested_data_type)
        rows = await self.snapshot_pass(moment, contracts, errors)

        if self.saw_no_live_data and self.requested_data_type == 1:
            self.requested_data_type = 3
            self.saw_no_live_data = False
            self.note("Gateway will not serve live quotes on this account, so "
                      "the rest of the run asks for delayed data instead")
            self.ib.reqMarketDataType(self.requested_data_type)
            for symbol, row in (await self.snapshot_pass(moment, contracts, errors)).items():
                rows[symbol] = row

        written = 0
        with_prices = 0
        for row in rows.values():
            label = row["market_data_type_label"]
            self.market_data_types[label] = self.market_data_types.get(label, 0) + 1
            common.append_jsonl(self.snapshots_path, row)
            written += 1
            if row["market_data_type"] is not None:
                with_prices += 1
        return written, with_prices

    async def fetch_latest_bar(self, moment: datetime, contract: Stock,
                              errors: list[str]) -> bool:
        """The newest completed five minute bar for one symbol.

        One request, the whole day's five minute bars, and we keep the last one.
        Asking for the day and throwing most of it away sounds wasteful, but
        Gateway charges by the request and not by the bar, so this costs exactly
        the same as asking for a single bar and is far more forgiving about
        where the session boundary is.

        Every one of these goes through the pacer, which is the thing standing
        between this script and a throttled Gateway connection.

        One warning for whoever writes fake_broker.py. The newest bar is not
        always from today. Before the opening bell, and on any day the market
        never opened, Gateway hands back the previous session's last bar
        instead, and this file writes it down under today's tick because that is
        genuinely what Gateway said. So compare the bar's own time field against
        the tick time before treating it as current. Every bar carries its own
        timestamp for exactly that reason.
        """
        symbol = common.symbol_of(contract)
        async with self.pacer.slot():
            try:
                bars = await asyncio.wait_for(
                    self.ib.reqHistoricalDataAsync(
                        contract,
                        endDateTime="",
                        durationStr="1 D",
                        barSizeSetting="5 mins",
                        whatToShow="TRADES",
                        useRTH=True,
                        formatDate=1,
                    ),
                    timeout=HISTORY_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                errors.append(f"{symbol} bars timed out after "
                              f"{HISTORY_TIMEOUT_SECONDS:.0f} seconds")
                return False
            except Exception as exc:                        # noqa: BLE001
                errors.append(f"{symbol} bars failed: {exc!r}")
                return False

        # Gateway reports a pacing violation through the error stream rather
        # than by raising, so the flag is checked here, after the request.
        if self.saw_pacing_violation:
            self.saw_pacing_violation = False
            self.note("Gateway said we asked for history too fast, so the "
                      "recorder is pausing before it asks again")
            await self.pacer.wait_out_a_pacing_violation(PACING_PAUSE_SECONDS)

        if not bars:
            log.debug("%s returned no bars", symbol)
            return False
        common.append_jsonl(self.bars_path, {
            "tick": moment.isoformat(),
            "symbol": symbol,
            "bar": common.bar_to_dict(bars[-1]),
        })
        return True

    # -- the scanner, in its own process ------------------------------------

    async def run_scanner(self, moment: datetime) -> dict:
        """Run agent/scanner.py as a separate process and keep its JSON.

        Its own process on purpose, exactly as agent/loop.py does it: the
        scanner talks to IBKR's own scanner service, which can hang or fall
        over, and neither should be able to take the recorder down with it. It
        connects as client 201, so it does not fight the recorder's 261 for the
        Gateway connection.

        Run through asyncio.to_thread rather than called directly, because
        subprocess.run blocks until the child exits, and four minutes of a
        blocked event loop would mean four minutes of nobody answering Gateway's
        heartbeat on our own connection.
        """
        out_path = self.folder / f"scanner_{moment:%H%M}.json"
        result: dict[str, Any] = {"ran": True, "ok": False, "out": str(out_path),
                                  "returncode": None, "stderr_tail": "",
                                  "seconds": 0.0}
        if not SCANNER_SCRIPT.exists():
            result["stderr_tail"] = f"{SCANNER_SCRIPT} does not exist"
            return result
        if not VENV_PYTHON.exists():
            result["stderr_tail"] = f"{VENV_PYTHON} does not exist"
            return result

        command = [str(VENV_PYTHON), str(SCANNER_SCRIPT), "--out", str(out_path)]
        began = time.monotonic()
        self.counts["scanner_runs"] += 1
        try:
            finished = await asyncio.to_thread(
                subprocess.run, command, cwd=str(PROJECT_ROOT),
                capture_output=True, text=True, timeout=SCANNER_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            result["seconds"] = round(time.monotonic() - began, 1)
            result["stderr_tail"] = (f"the scanner ran for more than "
                                     f"{SCANNER_TIMEOUT_SECONDS} seconds and was stopped")
            self.counts["scanner_failures"] += 1
            self.note(result["stderr_tail"])
            return result
        except Exception as exc:                            # noqa: BLE001
            result["seconds"] = round(time.monotonic() - began, 1)
            result["stderr_tail"] = f"the scanner would not start: {exc!r}"
            self.counts["scanner_failures"] += 1
            self.note(result["stderr_tail"])
            return result

        result["seconds"] = round(time.monotonic() - began, 1)
        result["returncode"] = finished.returncode
        tail = (finished.stderr or finished.stdout or "").strip().splitlines()
        result["stderr_tail"] = "\n".join(tail[-5:])
        result["ok"] = finished.returncode == 0 and out_path.exists()
        if not result["ok"]:
            self.counts["scanner_failures"] += 1
            self.note(f"the scanner exited with code {finished.returncode} at "
                      f"{slot_label(moment)}")
        else:
            log.info("the scanner finished in %.0f seconds and wrote %s",
                     result["seconds"], out_path)
        return result

    # -- one tick -----------------------------------------------------------

    async def one_tick(self, moment: datetime, run_scanner: bool) -> dict:
        """Everything that happens at one point on the grid.

        Never raises. Whatever goes wrong ends up as text in the tick record,
        because a recording with a hole in it and a note explaining the hole is
        worth a great deal more than a recorder that stopped at 10:15.
        """
        began = time.monotonic()
        ran_at = datetime.now(common.EASTERN)
        late = max(0.0, (ran_at - moment).total_seconds())
        errors: list[str] = []
        record: dict[str, Any] = {
            "tick": moment.isoformat(),
            "slot": slot_label(moment),
            "ran_at": ran_at.isoformat(),
            "late_seconds": round(late, 1),
            "status": "ok",
            "connected": False,
            "reconnected": False,
            "symbols": 0,
            "symbol_list": [],
            "snapshots_written": 0,
            "snapshots_with_prices": 0,
            "bars_written": 0,
            "scanner_ran": False,
            "scanner": None,
            "market_data_type_requested": self.requested_data_type,
            "history_requests_used": self.pacer.granted,
            "duration_seconds": 0.0,
            "errors": errors,
        }

        # A Gateway restart is a normal thing to live through, not a reason to
        # stop recording. Reconnect at the top of every tick.
        was_connected = self.ib.isConnected()
        connected = await common.ensure_connected(
            self.ib, self.args.host, self.args.port, self.args.client_id)
        record["connected"] = connected
        if connected and not was_connected:
            record["reconnected"] = True
            self.counts["reconnects"] += 1
        if not connected:
            record["status"] = "gateway down"
            errors.append("could not reach IB Gateway, nothing recorded for this slot")
            record["duration_seconds"] = round(time.monotonic() - began, 1)
            return record

        try:
            symbols = self.symbols_for_tick()
            record["symbol_list"] = symbols
            record["symbols"] = len(symbols)
            contracts = await self.qualify(symbols)

            written, with_prices = await self.take_snapshots(
                moment, contracts, errors)
            record["snapshots_written"] = written
            record["snapshots_with_prices"] = with_prices

            bars = 0
            for contract in contracts:
                if await self.fetch_latest_bar(moment, contract, errors):
                    bars += 1
            record["bars_written"] = bars

            if run_scanner:
                record["scanner_ran"] = True
                record["scanner"] = await self.run_scanner(moment)
        except Exception as exc:                            # noqa: BLE001
            log.exception("tick %s blew up", slot_label(moment))
            record["status"] = "error"
            errors.append(f"the tick failed partway through: {exc!r}")

        if errors and record["status"] == "ok":
            record["status"] = "ok with problems"
        # Left as the type this tick asked for at the start, not the type the
        # run has ended up on, because that is what these numbers came from.
        record["history_requests_used"] = self.pacer.granted
        record["duration_seconds"] = round(time.monotonic() - began, 1)

        self.counts["ticks"] += 1
        self.counts["snapshots"] += record["snapshots_written"]
        self.counts["snapshots_with_prices"] += record["snapshots_with_prices"]
        self.counts["bars"] += record["bars_written"]
        if record["status"] == "ok":
            self.counts["ticks_ok"] += 1
        else:
            self.counts["ticks_failed"] += 1
        return record

    def write_tick(self, record: dict) -> None:
        common.append_jsonl(self.ticks_path, record)
        if record["status"] == "missed":
            self.slots_missed.append(record["slot"])
        else:
            self.slots_run.append(record["slot"])
        log.info("%s %s, %d symbols, %d snapshots, %d bars, %.0f seconds late, "
                 "%s", record["slot"], record["status"], record["symbols"],
                 record["snapshots_written"], record["bars_written"],
                 record["late_seconds"],
                 f"{len(record['errors'])} problem(s)" if record["errors"] else "clean")

    def record_missed(self, moment: datetime, why: str) -> None:
        """Write down a slot the recorder never got to, and move on.

        Deliberately never tries to make it up. Firing a backlog of ticks at
        once is how you get Gateway to throttle the connection for everyone,
        and the recording would be wrong anyway, because the quotes would all
        carry the wrong timestamp.
        """
        self.write_tick(self.missed_record(moment, why))

    def missed_record(self, moment: datetime, why: str) -> dict:
        """The shape of a slot that did not happen, without writing it down yet.

        Split out from record_missed above so that a tick killed by the cap can
        be handed back to the caller exactly like a real one, and written by the
        same line of code.
        """
        return {
            "tick": moment.isoformat(),
            "slot": slot_label(moment),
            "ran_at": None,
            "late_seconds": round(max(0.0, (datetime.now(common.EASTERN) - moment)
                                      .total_seconds()), 1),
            "status": "missed",
            "connected": self.ib.isConnected(),
            "reconnected": False,
            "symbols": 0,
            "symbol_list": [],
            "snapshots_written": 0,
            "snapshots_with_prices": 0,
            "bars_written": 0,
            "scanner_ran": False,
            "scanner": None,
            "market_data_type_requested": self.requested_data_type,
            "history_requests_used": self.pacer.granted,
            "duration_seconds": 0.0,
            "errors": [why],
        }

    # -- the manifest -------------------------------------------------------

    def verdict(self) -> str:
        """One sentence saying whether this recording is worth replaying.

        The whole point of the manifest is that a person can open it and know
        in one line whether Tuesday is usable, so this has to be willing to say
        no. Note that an empty snapshot still counts as a written snapshot, so
        the test that matters is how many of them had a number in them.
        """
        if not self.counts["ticks"]:
            return "Nothing was recorded. There is no day here to replay."
        if self.counts["snapshots_with_prices"] == 0 and self.counts["bars"] == 0:
            return ("Ticks ran but no quotes and no bars came back, so the "
                    "recording is empty. Check that Gateway was logged in and "
                    "that the market was actually open.")
        if self.counts["snapshots_with_prices"] == 0:
            return ("Bars came back but every single quote was empty, so there "
                    "is no bid or ask anywhere in this recording. Usable for "
                    "bar-driven replay only. The cause is almost always a "
                    "missing market data subscription on the IBKR account.")
        missed = len(self.slots_missed)
        total = len(self.grid) or 1
        if missed > total * 0.1:
            return (f"{missed} of {total} slots were missed, which is more than "
                    "one in ten. Usable, but expect visible gaps in the replay.")
        if self.counts["snapshots_with_prices"] < self.counts["snapshots"] * 0.5:
            return (f"Recorded, but only {self.counts['snapshots_with_prices']} "
                    f"of {self.counts['snapshots']} quotes had any numbers in "
                    "them. Check which symbols came back empty before trusting "
                    "a spread.")
        if self.counts["ticks_failed"]:
            return (f"Recorded, with {self.counts['ticks_failed']} tick(s) that "
                    "hit a problem. Read ticks.jsonl before trusting a gap.")
        return "Recorded cleanly. This day is ready to replay."

    def write_manifest(self) -> None:
        """Rewrite manifest.json, atomically, so a reader never sees it half done."""
        done = set(self.slots_run) | set(self.slots_missed)
        common.write_json(self.manifest_path, {
            "date": f"{self.day:%Y-%m-%d}",
            "verdict": self.verdict(),
            "started_at": self.started_at.isoformat(),
            "updated_at": datetime.now(common.EASTERN).isoformat(),
            "ended": self.ending,
            "schedule": {
                "start": self.args.start.strftime("%H:%M"),
                "end": self.args.end.strftime("%H:%M"),
                "interval_minutes": self.args.interval_minutes,
                "timezone": "America/New_York",
                "slots_total": len(self.grid),
                "grid": [slot_label(m) for m in self.grid],
            },
            "slots_run": list(self.slots_run),
            "slots_missed": list(self.slots_missed),
            "slots_not_reached": [slot_label(m) for m in self.grid
                                  if slot_label(m) not in done],
            "counts": dict(self.counts),
            "symbols": list(self.symbols_seen),
            "market_data_types_seen": dict(self.market_data_types),
            "market_data_type_requested": self.requested_data_type,
            "history_requests": {
                "granted": self.pacer.granted,
                "budget_per_10_minutes": self.pacer.budget,
                "seconds_spent_waiting": round(self.pacer.waited_seconds, 1),
            },
            "gateway": {"host": self.args.host, "port": self.args.port,
                        "client_id": self.args.client_id, "readonly": True},
            "files": {
                "snapshots": str(self.snapshots_path),
                "bars_5m": str(self.bars_path),
                "ticks": str(self.ticks_path),
                "manifest": str(self.manifest_path),
                "scanner": sorted(str(p) for p in self.folder.glob("scanner_*.json")),
            },
            "warnings": list(self.warnings),
            "warnings_not_listed": self.warnings_dropped,
            "symbols_with_unusable_volume": sorted(self.odd_volume_symbols),
        })


# ----------------------------------------------------------------------- running

async def sleep_until(moment: datetime, stop: asyncio.Event) -> bool:
    """Wait until a moment on the clock. True if we were asked to stop instead.

    Waits on the stop event rather than plain sleeping so that a Ctrl-C or a
    SIGTERM from launchd is acted on straight away, and not four and a half
    minutes later when the sleep happens to finish.
    """
    seconds = (moment - datetime.now(common.EASTERN)).total_seconds()
    while seconds > 0:
        try:
            await asyncio.wait_for(stop.wait(), timeout=min(seconds, 30.0))
            return True
        except asyncio.TimeoutError:
            pass
        seconds = (moment - datetime.now(common.EASTERN)).total_seconds()
    return stop.is_set()


def is_scanner_slot(moment: datetime) -> bool:
    return slot_label(moment) in SCANNER_SLOTS


async def capped_tick(recorder: DayRecorder, moment: datetime,
                      run_scanner: bool) -> dict:
    """One tick, with a cap on the whole of it. Comes back with a record either way.

    one_tick already bounds each kind of read it does. This is the cap over all
    of them together, for the case they queue up behind one another on a Gateway
    that has stopped answering: on 2026-09-07 a single --once tick ran for
    eighteen minutes that way. A tick that overruns is written down as a missed
    slot, which is what the manifest already knows how to describe, and the
    recorder carries on to the next one.
    """
    try:
        return await asyncio.wait_for(
            recorder.one_tick(moment, run_scanner=run_scanner),
            timeout=TICK_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        why = (f"the tick was still waiting on IB Gateway after "
               f"{TICK_TIMEOUT_SECONDS:.0f} seconds, so it was written off as "
               f"missed rather than left running into the next slot")
        log.error("%s %s", slot_label(moment), why)
        return recorder.missed_record(moment, why)


async def run_once(recorder: DayRecorder) -> None:
    """A single tick, right now, for testing outside market hours.

    The slot is this exact second rather than the nearest five minute boundary,
    so the tick does not report itself as late by however far into the minute
    you happened to start it.
    """
    moment = datetime.now(common.EASTERN).replace(microsecond=0)

    # Which grid the manifest should describe depends on why we are here. Under
    # launchd every tick of the real day arrives as its own --once process, and
    # the manifest has to know there are eighty one slots so it can say which
    # ones are still to come. Someone testing at twenty past one is not
    # recording a day at all, and telling them they missed eighty slots would be
    # nonsense. So: land on the configured grid and we are the real thing, land
    # anywhere else and this tick is the whole grid.
    full_grid = tick_grid(recorder.day, recorder.args.start, recorder.args.end,
                          recorder.args.interval_minutes)
    on_the_grid = slot_label(moment) in {slot_label(m) for m in full_grid}
    recorder.grid = full_grid if on_the_grid else [moment]
    log.info("one tick only, standing in for the %s slot%s", slot_label(moment),
             f", slot {slot_label(moment)} of the {len(full_grid)} slot day"
             if on_the_grid else ", outside the recording window, so a test tick")
    record = await capped_tick(recorder, moment,
                               run_scanner=bool(recorder.args.run_scanner))
    recorder.write_tick(record)
    recorder.ending = "finished, single tick"
    recorder.write_manifest()


async def run_day(recorder: DayRecorder, stop: asyncio.Event) -> None:
    """Walk the grid from the first slot to the last, skipping what we missed."""
    args = recorder.args
    recorder.grid = tick_grid(recorder.day, args.start, args.end,
                              args.interval_minutes)
    interval = timedelta(minutes=args.interval_minutes)
    log.info("recording %s, %d slots from %s to %s Eastern, every %d minutes",
             recorder.day, len(recorder.grid), args.start.strftime("%H:%M"),
             args.end.strftime("%H:%M"), args.interval_minutes)
    recorder.write_manifest()

    for moment in recorder.grid:
        if stop.is_set():
            break
        now = datetime.now(common.EASTERN)

        # Already a whole interval past this slot, so its own window has closed
        # and the next slot is what is due. Write it off and move on, rather
        # than running it now and stamping stale quotes with an old timestamp.
        if now >= moment + interval:
            recorder.record_missed(
                moment, f"the recorder was still busy or asleep at "
                        f"{slot_label(moment)}, so this slot was skipped rather "
                        f"than run late")
            recorder.write_manifest()
            continue

        if now < moment:
            if await sleep_until(moment, stop):
                break

        record = await capped_tick(recorder, moment,
                                   run_scanner=is_scanner_slot(moment))
        recorder.write_tick(record)
        recorder.write_manifest()

    if stop.is_set():
        recorder.ending = "stopped early, someone sent it a stop signal"
        log.warning("stopping early on a stop signal, writing the manifest first")
    else:
        recorder.ending = "finished, reached the end of the grid"
    recorder.write_manifest()


# ------------------------------------------------------------------ entry point

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record one trading day of quotes and five minute bars, so "
                    "the replay harness has a real day to replay against.")
    parser.add_argument("--once", action="store_true",
                        help="Do exactly one tick right now and exit, instead of "
                             "looping all day. This is the testing mode.")
    parser.add_argument("--date", type=parse_day, default=None,
                        help="Which day folder to write into, as YYYY-MM-DD. "
                             "Default: today in New York.")
    parser.add_argument("--start", type=parse_clock, default=parse_clock(DEFAULT_START),
                        help=f"First slot, Eastern. Default: {DEFAULT_START}")
    parser.add_argument("--end", type=parse_clock, default=parse_clock(DEFAULT_END),
                        help=f"Last slot, Eastern. Default: {DEFAULT_END}")
    parser.add_argument("--interval-minutes", type=int, default=DEFAULT_INTERVAL_MINUTES,
                        help="Minutes between slots. Default: %(default)s")
    parser.add_argument("--out-dir", default=None,
                        help="The recordings folder that holds the dated day "
                             "folders. Default: output/recordings under the "
                             "project root.")
    parser.add_argument("--symbols", default=None,
                        help="Comma separated tickers to record instead of the "
                             "shortlist. SPY and QQQ are always added.")
    parser.add_argument("--max-symbols", type=int, default=DEFAULT_MAX_SYMBOLS,
                        help="Hard cap on symbols per tick, which is what keeps "
                             "the recorder inside Gateway's data ration. "
                             "Default: %(default)s")
    parser.add_argument("--host", default=common.DEFAULT_HOST, help="IB Gateway host")
    parser.add_argument("--port", type=int, default=common.DEFAULT_PORT,
                        help="IB Gateway port (4002 is paper). Default: %(default)s")
    parser.add_argument("--client-id", type=non_zero_client_id,
                        default=common.RECORDER_CLIENT_ID,
                        help="API client id. Must not be 0, and must not clash "
                             "with the fetcher's 260 or the scanner's 201. "
                             "Default: %(default)s")
    parser.add_argument("--history-budget", type=int,
                        default=common.HISTORY_BUDGET_PER_WINDOW,
                        help="Historical requests allowed per ten minutes, "
                             "shared with everything else on this Gateway. "
                             "Default: %(default)s")
    parser.add_argument("--market-data-type", type=int, default=1, choices=[1, 2, 3, 4],
                        help="What to ask Gateway for: 1 live, 2 frozen, "
                             "3 delayed, 4 delayed frozen. It falls back to "
                             "delayed on its own if the account has no live "
                             "subscription. Default: %(default)s")
    parser.add_argument("--run-scanner", action="store_true",
                        help="With --once, also run the scanner. Ignored on a "
                             "full day run, where the 09:35 and 09:40 slots run "
                             "it anyway.")
    parser.add_argument("--verbose", action="store_true", help="Chattier logging")
    return parser.parse_args(argv)


async def main_async(args: argparse.Namespace) -> int:
    day = args.date or datetime.now(common.EASTERN).date()
    if args.out_dir:
        folder = Path(args.out_dir).expanduser().resolve() / f"{day:%Y-%m-%d}"
        folder.mkdir(parents=True, exist_ok=True)
    else:
        folder = common.day_dir(day, create=True)

    recorder = DayRecorder(args, day, folder)
    # Read back anything already recorded into this folder, so a manifest
    # written by a --once tick describes the whole day and not just itself.
    recorder.resume_from_disk()
    recorder.ib.errorEvent += recorder.on_error
    log.info("writing into %s", folder)

    # Ctrl-C from a person and SIGTERM from launchd both mean the same thing:
    # stop tidily, write a last manifest saying so, and exit 0. Exiting non-zero
    # would make launchd think the recorder had crashed and restart it.
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, ValueError):
            loop.add_signal_handler(sig, stop.set)

    connected = await common.connect_ib(recorder.ib, args.host, args.port,
                                        args.client_id)
    if not connected:
        # Not an error to give up on. Gateway may come back mid morning, and a
        # day full of written-down failures is still a truthful record.
        recorder.note(f"could not reach IB Gateway at {args.host}:{args.port} at "
                      "startup, the run will keep trying at every slot")

    try:
        if args.once:
            await run_once(recorder)
        else:
            await run_day(recorder, stop)
    except Exception as exc:                                # noqa: BLE001
        log.exception("the recorder stopped on an unexpected error")
        recorder.note(f"the recorder stopped on an unexpected error: {exc!r}")
        recorder.ending = f"stopped on an unexpected error: {exc!r}"
        recorder.write_manifest()
    finally:
        with contextlib.suppress(Exception):
            recorder.ib.disconnect()

    log.info("%s", recorder.verdict())
    log.info("wrote %d snapshot(s) and %d bar(s) across %d tick(s) into %s",
             recorder.counts["snapshots"], recorder.counts["bars"],
             recorder.counts["ticks"], folder)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )
    # ib_async narrates every Gateway status note at info level, which drowns
    # out our one line per tick. Quiet unless someone asked for the noise.
    logging.getLogger("ib_async").setLevel(
        logging.DEBUG if args.verbose else logging.ERROR)

    if args.interval_minutes < 1:
        log.error("--interval-minutes has to be at least 1")
        return 1
    if not args.once and args.end < args.start:
        log.error("--end (%s) is before --start (%s), so there is nothing to record",
                  args.end.strftime("%H:%M"), args.start.strftime("%H:%M"))
        return 1

    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        log.warning("interrupted")
        return 0


if __name__ == "__main__":
    sys.exit(main())

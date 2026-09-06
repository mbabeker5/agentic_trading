#!/usr/bin/env python3
"""Pull the recent past out of IB Gateway so the replay harness has something to replay.

None of Mo's five trading books is allowed to place a live paper order until the
whole loop has been run end to end against recorded market data, with a fake
broker standing in for IBKR. This script goes and fetches that recorded past.
It is the first of three files in the harness:

  * agent/replay/fetch_history.py   this file, fetches past bars
  * agent/replay/record_day.py      records one live trading day as it happens
  * agent/replay/fake_broker.py     replays either recording and pretends to fill

Three kinds of bar come back for every symbol, because the books need three
different things from the past:

  * five minute bars for the last ten trading days. That is the shape of the day
    the books actually reason over.
  * one minute bars covering 09:30 to 09:40 Eastern on each of those same days,
    so the fake broker has a real opening range to work with rather than an
    invented one.
  * daily bars for the last forty sessions, which is where dollar volume and the
    "is this name liquid enough to trade" test come from.

That is one request for the five minute bars, one request per day for the
opening ranges, and one request for the daily bars: 1 + 10 + 1 = 12 requests per
symbol at the defaults. Gateway only allows about sixty historical requests in
any ten minute window, counted across every client on the connection, so a run
over twenty two symbols is more than four of those windows and will spend most
of its time deliberately waiting. The startup log says how long to expect.

This script is read only by construction. It connects with readonly=True and the
only two things it ever calls on Gateway are reqHistoricalDataAsync and
reqMarketDataType, both of which are reads. There is no order code in the file at
all, and that is not an oversight waiting to be fixed later.

Run it like this, from the project folder:

    venv312/bin/python agent/replay/fetch_history.py --symbols SPY,QQQ

or, with no --symbols, for the two benchmarks plus whatever the last real scan
shortlisted:

    venv312/bin/python agent/replay/fetch_history.py

Everything lands in output/recordings/history/: one JSONL file per symbol, plus a
shared manifest.json saying what was fetched and what is missing. That whole tree
is gitignored, so recordings never end up in git.

Exit code is 0 whenever the fetch ran, even if some symbols came back empty. It
is 1 only when Gateway could not be reached at all.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys
from datetime import date as date_type, datetime, time as clock_time
from pathlib import Path
from typing import Any

# The project root, two folders up from agent/replay/. Putting it on sys.path is
# what lets this file be run directly (python agent/replay/fetch_history.py) and
# also imported (from agent.replay import fetch_history). The repo has no
# __init__.py files anywhere, so "agent.replay" is a namespace package and all it
# needs is for the root to be somewhere Python looks.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ib_async import IB, Stock                                       # noqa: E402

from agent.replay import common                                      # noqa: E402
from agent.replay.common import (                                    # noqa: E402
    BENCHMARK_SYMBOLS,
    BENIGN_ERROR_CODES,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_UNIVERSE,
    EASTERN,
    FETCHER_CLIENT_ID,
    HistoryPacer,
    MARKET_DATA_TYPE_LABELS,
    append_jsonl,
    bar_moment,
    bar_to_dict,
    connect_ib,
    dedupe,
    history_dir,
    ib_end_datetime,
    is_pacing_message,
    latest_shortlist_path,
    previous_trading_days,
    read_json,
    stock_contract_dict,
    symbols_from_shortlist,
    write_json,
)

log = logging.getLogger("replay.fetch_history")


# ---------------------------------------------------------------------------
# What we ask for
# ---------------------------------------------------------------------------

#: How many past trading days of five minute bars and opening ranges.
DEFAULT_DAYS = 10
#: How many past sessions of daily bars, for the dollar volume test.
DEFAULT_DAILY_DAYS = 40

#: The three kinds of bar that share one file per symbol. The envelope around
#: each bar carries this so the fake broker can tell them apart on the way back in.
KIND_5M = "bars_5m"
KIND_1M_OPEN = "bars_1m_open"
KIND_1D = "bars_1d"
#: Records are written in this order so the file is the same every run and a
#: diff between two runs shows real changes rather than reshuffling.
KIND_ORDER = (KIND_5M, KIND_1M_OPEN, KIND_1D)

#: The opening range request ends at 09:40 Eastern and asks for 900 seconds of
#: trading. That is not the same as fifteen minutes of clock. IB counts a
#: duration in trading time, so the window skips straight over the overnight gap
#: and reaches back into the previous afternoon, handing back five extra bars
#: from around yesterday's close. useRTH does not drop those, because 15:55 the
#: day before is perfectly ordinary regular trading hours. fetch_symbol throws
#: away anything not dated on the day being asked about, which leaves exactly the
#: ten bars 09:30 through 09:39.
OPENING_RANGE_END = clock_time(9, 40)
OPENING_RANGE_DURATION = "900 S"

#: When Gateway says we asked too fast, wait this long and try that one request
#: again, at most this many extra times.
PACING_PAUSE_SECONDS = 60.0
PACING_RETRIES = 2

#: Codes in the 2100s are Gateway talking about itself, "market data farm
#: connection is OK" and the like. They arrive with request id -1 and have
#: nothing to do with whichever request happens to be in flight.
CONNECTION_CHATTER = range(2100, 2200)


# ---------------------------------------------------------------------------
# Which symbols to fetch
# ---------------------------------------------------------------------------

def choose_symbols(requested: str | None) -> tuple[list[str], str]:
    """Work out which tickers to fetch, and say in plain words where they came from.

    In order of preference: whatever --symbols asked for, then the benchmarks
    plus the newest real shortlist the scanner wrote, then the benchmarks plus
    the fallback universe in common.py. SPY and QQQ always come first, because
    the fake broker uses them as the market's own pulse and wants them present
    whatever else is in the file.
    """
    if requested:
        symbols = dedupe(part for part in str(requested).split(","))
        if symbols:
            return symbols, "the --symbols argument"

    shortlist = latest_shortlist_path()
    from_shortlist = symbols_from_shortlist(shortlist) if shortlist else []
    if from_shortlist:
        symbols = dedupe(list(BENCHMARK_SYMBOLS) + from_shortlist)
        return symbols, f"the benchmarks plus the {len(from_shortlist)} names in {shortlist}"

    symbols = dedupe(list(BENCHMARK_SYMBOLS) + list(DEFAULT_UNIVERSE))
    return symbols, "the benchmarks plus the fallback universe, since there is no shortlist yet"


def estimate_the_run(symbol_count: int, days: int) -> tuple[int, float]:
    """How many historical requests this run needs, and roughly how many minutes.

    The first budget's worth of requests go out one second apart. Every further
    budget's worth has to sit and wait for Gateway's ten minute window to roll
    forward, which is where the time actually goes on a long run.
    """
    requests = symbol_count * (2 + days)
    budget = max(1, common.HISTORY_BUDGET_PER_WINDOW)
    windows_of_waiting = max(0, (requests - 1) // budget)
    seconds = requests * common.HISTORY_MIN_GAP_SECONDS
    seconds += windows_of_waiting * common.HISTORY_WINDOW_SECONDS
    return requests, seconds / 60.0


# ---------------------------------------------------------------------------
# The fetcher
# ---------------------------------------------------------------------------

class HistoryFetcher:
    """Asks Gateway for past bars, one request at a time, and writes them down.

    Requests go out one after another rather than in parallel. There is nothing
    to gain from overlapping them, since the pacer would only make them queue
    anyway, and running them serially means an error that arrives on the wire can
    be matched to the request that caused it without any guessing.
    """

    def __init__(self, ib: IB, pacer: HistoryPacer, days: int, daily_days: int) -> None:
        self.ib = ib
        self.pacer = pacer
        self.days = days
        self.daily_days = daily_days
        # Every single thing Gateway complained about, in arrival order. Kept in
        # full because error 162 is the historical data service's catch all and
        # its wording is the only way to tell "no data" from "you asked too fast".
        self.errors: list[dict[str, Any]] = []
        self.requests_made = 0
        self.requests_refused = 0

    # -- plumbing ----------------------------------------------------------

    def on_error(self, req_id: int, code: int, message: str, contract: Any = None) -> None:
        """Gateway's error channel. Everything it says gets written down here."""
        entry = {"reqId": int(req_id), "code": int(code), "message": str(message)}
        self.errors.append(entry)
        text = f"Gateway code {code} (request {req_id}): {message}"
        if int(code) in BENIGN_ERROR_CODES or int(code) in CONNECTION_CHATTER:
            log.debug(text)
        else:
            log.warning(text)

    def complaint_since(self, mark: int) -> tuple[int, str] | None:
        """The last real complaint Gateway made after position `mark` in the log.

        Skips the connection chatter and anything carrying request id -1, since
        neither of those is Gateway answering the request we just sent.
        """
        for entry in reversed(self.errors[mark:]):
            if entry["reqId"] < 0 or entry["code"] in CONNECTION_CHATTER:
                continue
            return entry["code"], entry["message"]
        return None

    # -- one request -------------------------------------------------------

    async def request_bars(self, contract: Stock, end_date_time: str, duration: str,
                           bar_size: str, label: str) -> tuple[list[Any], str | None]:
        """One historical request. Returns the bars, plus why there are none.

        The second half of that pair is the point of this function. ib_async does
        not raise when Gateway refuses a historical request, it just hands back an
        empty list, so "no bars" on its own is ambiguous: it could be a market
        holiday, a symbol Gateway has no data for, or a pacing violation that a
        retry would fix. Reading the error that arrived while this request was in
        flight is what tells those apart, and the reason string is what ends up in
        the manifest's gaps list for Mo to read later.
        """
        for attempt in range(1, PACING_RETRIES + 2):
            mark = len(self.errors)
            async with self.pacer.slot():
                self.requests_made += 1
                try:
                    bars = await self.ib.reqHistoricalDataAsync(
                        contract,
                        endDateTime=end_date_time,
                        durationStr=duration,
                        barSizeSetting=bar_size,
                        whatToShow="TRADES",
                        useRTH=True,
                        formatDate=1,
                    )
                except Exception as exc:                       # noqa: BLE001
                    # A single failed request must never take the run down with
                    # it. Write down why, and carry on to the next one.
                    self.requests_refused += 1
                    log.warning("%s failed: %s", label, exc)
                    return [], f"request failed: {exc}"

            if bars:
                return list(bars), None

            complaint = self.complaint_since(mark)
            if complaint is None:
                # Gateway answered politely with nothing at all, which is what a
                # market holiday looks like.
                return [], "no bars returned"

            code, message = complaint
            self.requests_refused += 1
            if code == 162 and is_pacing_message(message):
                if attempt <= PACING_RETRIES:
                    log.warning("%s hit a pacing violation, waiting %.0f seconds "
                                "and trying again (attempt %d of %d)", label,
                                PACING_PAUSE_SECONDS, attempt, PACING_RETRIES + 1)
                    await self.pacer.wait_out_a_pacing_violation(PACING_PAUSE_SECONDS)
                    continue
                return [], "error 162: Gateway still says we are asking too fast"
            return [], f"error {code}: {short_reason(message)}"

        return [], "gave up after retrying a pacing violation"

    # -- one symbol --------------------------------------------------------

    async def fetch_symbol(self, symbol: str, sessions: list[date_type]) -> dict[str, Any]:
        """Everything we want for one ticker: 5 minute, opening range, and daily bars."""
        contract = Stock(symbol, "SMART", "USD")
        session_names = [f"{day:%Y-%m-%d}" for day in sessions]
        records: list[dict[str, Any]] = []
        gaps: list[dict[str, Any]] = []
        started_with = self.requests_made

        # (a) Five minute bars for the whole window, in one request. An empty
        # endDateTime means "up to now", which on a Sunday means up to Friday's
        # close.
        bars, reason = await self.request_bars(
            contract, "", f"{self.days} D", "5 mins", f"{symbol} five minute bars")
        five_minute = [envelope(symbol, KIND_5M, bar) for bar in bars]
        records.extend(five_minute)
        covered = sorted({record["session"] for record in five_minute if record["session"]})
        if not five_minute:
            for name in session_names:
                gaps.append({"kind": KIND_5M, "session": name,
                             "reason": reason or "no bars returned"})
        else:
            for name in session_names:
                if name not in covered:
                    gaps.append({"kind": KIND_5M, "session": name,
                                 "reason": "no five minute bars for this day, most "
                                           "likely a market holiday"})

        # (b) The opening range, one request per day. Each one ends at 09:40
        # Eastern and reaches back fifteen minutes; useRTH throws away the part
        # before the bell, leaving 09:30 through 09:39.
        now = datetime.now(EASTERN)
        for day, name in zip(sessions, session_names):
            deadline = datetime.combine(day, OPENING_RANGE_END, tzinfo=EASTERN)
            if deadline > now:
                # Asking for a moment that has not happened yet only earns an
                # error, so skip it and say so.
                gaps.append({"kind": KIND_1M_OPEN, "session": name,
                             "reason": "09:40 Eastern has not happened yet on this day"})
                continue
            bars, reason = await self.request_bars(
                contract, ib_end_datetime(deadline), OPENING_RANGE_DURATION, "1 min",
                f"{symbol} opening range for {name}")
            if not bars:
                gaps.append({"kind": KIND_1M_OPEN, "session": name,
                             "reason": reason or "no bars returned"})
                continue
            # Only the bars dated on the day we asked about. See the note beside
            # OPENING_RANGE_DURATION: the rest are yesterday's close, and filing
            # those as today's opening range would hand the fake broker an entry
            # trigger taken from the wrong session.
            opening = [record for record
                       in (envelope(symbol, KIND_1M_OPEN, bar) for bar in bars)
                       if record["session"] == name]
            if not opening:
                gaps.append({"kind": KIND_1M_OPEN, "session": name,
                             "reason": "bars came back but none of them fall on "
                                       "this day, so the market was shut"})
                continue
            records.extend(opening)

        # (c) Daily bars, for dollar volume and the liquidity test.
        bars, reason = await self.request_bars(
            contract, "", f"{self.daily_days} D", "1 day", f"{symbol} daily bars")
        if bars:
            records.extend(envelope(symbol, KIND_1D, bar) for bar in bars)
        else:
            # Not tied to any one session, so it is filed against the whole run.
            gaps.append({"kind": KIND_1D, "session": None,
                         "reason": reason or "no bars returned"})

        return {
            "symbol": symbol,
            "records": records,
            "gaps": gaps,
            "sessions_covered": covered,
            "requests": self.requests_made - started_with,
        }


def envelope(symbol: str, kind: str, bar: Any) -> dict[str, Any]:
    """Wrap one bar so all three kinds can live in one file per symbol.

    The session is the Eastern calendar day the bar belongs to, which is what
    the fake broker slices on when it replays a day.
    """
    bar_dict = bar_to_dict(bar)
    moment = bar_moment(bar_dict)
    return {
        "symbol": symbol,
        "kind": kind,
        "session": f"{moment:%Y-%m-%d}" if moment else "",
        "bar": bar_dict,
    }


def short_reason(message: str, limit: int = 120) -> str:
    """Gateway's wording, trimmed to something that reads well in a manifest."""
    text = " ".join(str(message or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# Writing it all down
# ---------------------------------------------------------------------------

def sort_key(record: dict[str, Any]) -> tuple[int, datetime]:
    """Kind first, then time. Keeps the file byte for byte stable between runs."""
    try:
        kind_rank = KIND_ORDER.index(record.get("kind", ""))
    except ValueError:
        kind_rank = len(KIND_ORDER)
    moment = bar_moment(record.get("bar") or {})
    return kind_rank, moment or datetime.min.replace(tzinfo=EASTERN)


def write_symbol_file(path: Path, records: list[dict[str, Any]]) -> None:
    """Rewrite one symbol's JSONL file from scratch, sorted.

    From scratch rather than appended to, because a second run over the same
    symbol would otherwise leave the file holding two copies of every bar and
    nothing downstream would notice.
    """
    if path.exists():
        path.unlink()
    for record in sorted(records, key=sort_key):
        append_jsonl(path, record)


def count_by_kind(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """How many bars of each kind, and the first and last time in each."""
    summary: dict[str, dict[str, Any]] = {}
    for kind in KIND_ORDER:
        of_kind = sorted((r for r in records if r.get("kind") == kind), key=sort_key)
        if not of_kind:
            summary[kind] = {"count": 0, "first": None, "last": None}
            continue
        summary[kind] = {
            "count": len(of_kind),
            "first": of_kind[0]["bar"].get("time"),
            "last": of_kind[-1]["bar"].get("time"),
        }
    return summary


def merge_manifest(path: Path, header: dict[str, Any],
                   entries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Update the shared manifest without losing symbols fetched on an earlier run.

    Fetching SPY and QQQ today and the other twenty on Monday has to leave one
    complete manifest, not Monday's overwriting today's. So the per symbol block
    is merged and everything else describes the run that just finished. Each
    symbol carries its own fetched_at, which is how you tell how stale one is.
    """
    existing = read_json(path)
    previous = {}
    if isinstance(existing, dict) and isinstance(existing.get("symbols"), dict):
        previous = existing["symbols"]
    merged = dict(previous)
    merged.update(entries)
    payload = dict(header)
    payload["symbols"] = merged
    write_json(path, payload)
    return payload


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def non_zero_client_id(value: str) -> int:
    """Refuse client id 0.

    Connecting as client 0 asks Gateway to bind manually placed orders to this
    session. It places nothing, but it is a change rather than a read, and a
    script that is read only by construction has no business making one.
    """
    number = int(value)
    if number == 0:
        raise argparse.ArgumentTypeError(
            "client id 0 would bind manually placed orders to this session, "
            "which is not read only. Pick any other number, such as 260."
        )
    return number


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch past bars from IB Gateway so the replay harness has "
                    "something to replay. Read only: it can fetch bars and "
                    "nothing else."
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help="Comma separated tickers, for example SPY,QQQ. Default: the two "
             "benchmarks plus the newest shortlist, or the fallback universe.",
    )
    parser.add_argument(
        "--days", type=int, default=DEFAULT_DAYS,
        help="How many past trading days of five minute bars and opening "
             "ranges. Default: %(default)s",
    )
    parser.add_argument(
        "--daily-days", type=int, default=DEFAULT_DAILY_DAYS,
        help="How many past sessions of daily bars, for dollar volume. "
             "Default: %(default)s",
    )
    parser.add_argument(
        "--out-dir", default=None,
        help="Where the JSONL files and the manifest go. Default: "
             "output/recordings/history/ under the project root.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="IB Gateway host")
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help="IB Gateway port (4002 is paper). Default: %(default)s",
    )
    parser.add_argument(
        "--client-id", type=non_zero_client_id, default=FETCHER_CLIENT_ID,
        help="API client id. Must not be 0. Default: %(default)s",
    )
    parser.add_argument("--verbose", action="store_true", help="Chattier logging")
    return parser.parse_args(argv)


async def main_async(args: argparse.Namespace) -> int:
    symbols, where_from = choose_symbols(args.symbols)
    if not symbols:
        log.error("No symbols to fetch. Pass --symbols SPY,QQQ or run the scanner first.")
        return 1

    days = max(1, int(args.days))
    daily_days = max(1, int(args.daily_days))
    sessions = previous_trading_days(days)
    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else history_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    requests, minutes = estimate_the_run(len(symbols), days)
    log.info("Fetching %d symbol(s) from %s", len(symbols), where_from)
    log.info("Sessions: %s to %s (%d trading days)",
             sessions[0], sessions[-1], len(sessions))
    if requests <= common.HISTORY_BUDGET_PER_WINDOW:
        log.info("That is %d requests per symbol, %d in total, which fits inside "
                 "Gateway's allowance of %d per %.0f minutes. Expect about %.0f "
                 "second(s), just the spacing between requests.",
                 2 + days, requests, common.HISTORY_BUDGET_PER_WINDOW,
                 common.HISTORY_WINDOW_SECONDS / 60.0, minutes * 60.0)
    else:
        log.info("That is %d requests per symbol, %d in total. Gateway only "
                 "allows %d in every %.0f minutes, so expect roughly %.0f "
                 "minute(s), most of it spent waiting on purpose.",
                 2 + days, requests, common.HISTORY_BUDGET_PER_WINDOW,
                 common.HISTORY_WINDOW_SECONDS / 60.0, minutes)

    ib = IB()
    pacer = HistoryPacer()
    fetcher = HistoryFetcher(ib, pacer, days, daily_days)
    ib.errorEvent += fetcher.on_error

    if not await connect_ib(ib, args.host, args.port, args.client_id):
        log.error("Could not reach IB Gateway at %s:%s as client %s. Nothing was "
                  "fetched.", args.host, args.port, args.client_id)
        return 1

    # Historical TRADES bars do not need a live market data subscription, so
    # strictly this line is not required. It is here because it costs one read
    # and it stops Gateway falling back on a live subscription it does not have
    # when a request runs outside market hours, which is when this script is
    # meant to be run. It is also on the short list of calls this file is allowed
    # to make at all.
    ib.reqMarketDataType(3)
    log.info("Market data type set to 3 (%s), which historical bars do not "
             "actually need", MARKET_DATA_TYPE_LABELS.get(3, "unknown"))

    entries: dict[str, dict[str, Any]] = {}
    try:
        for position, symbol in enumerate(symbols, start=1):
            result = await fetcher.fetch_symbol(symbol, sessions)
            path = out_dir / f"{symbol}.jsonl"
            write_symbol_file(path, result["records"])
            bars = count_by_kind(result["records"])
            entries[symbol] = {
                "fetched_at": datetime.now(EASTERN).isoformat(timespec="seconds"),
                "path": str(path),
                "contract": stock_contract_dict(symbol),
                "bars": bars,
                "sessions_covered": result["sessions_covered"],
                "gaps": result["gaps"],
                "requests": result["requests"],
            }
            log.info("%-6s (%d of %d)  %4d five minute, %3d opening range, %3d daily"
                     "  %d gap(s)  -> %s",
                     symbol, position, len(symbols),
                     bars[KIND_5M]["count"], bars[KIND_1M_OPEN]["count"],
                     bars[KIND_1D]["count"], len(result["gaps"]), path)
    except Exception as exc:                                # noqa: BLE001
        # Whatever went wrong, the symbols already finished are worth keeping,
        # so fall through to the manifest rather than dying here.
        log.exception("The fetch stopped early: %s", exc)
    finally:
        with contextlib.suppress(Exception):
            ib.disconnect()

    header = {
        "fetched_at": datetime.now(EASTERN).isoformat(timespec="seconds"),
        "arguments": {
            "symbols": args.symbols,
            "days": days,
            "daily_days": daily_days,
            "out_dir": str(out_dir),
            "host": args.host,
            "port": int(args.port),
            "client_id": int(args.client_id),
        },
        "symbols_requested": symbols,
        "symbols_source": where_from,
        "sessions_requested": [f"{day:%Y-%m-%d}" for day in sessions],
        "totals": {
            "requests_made": fetcher.requests_made,
            # Requests Gateway answered with an error instead of bars. Note that
            # the pacer itself never refuses anything: when the ten minute window
            # is full it waits, so nothing is ever dropped for want of budget.
            "requests_refused": fetcher.requests_refused,
            "pacing_seconds_waited": round(pacer.waited_seconds, 1),
            "gateway_messages": len(fetcher.errors),
        },
    }
    manifest_path = out_dir / "manifest.json"
    merge_manifest(manifest_path, header, entries)

    total_bars = sum(
        kind["count"] for entry in entries.values() for kind in entry["bars"].values()
    )
    total_gaps = sum(len(entry["gaps"]) for entry in entries.values())
    log.info("Wrote %d bar(s) across %d symbol(s) to %s", total_bars, len(entries), out_dir)
    log.info("Manifest: %s", manifest_path)
    log.info("%d request(s) made, %d refused, %.1f second(s) spent waiting on "
             "pacing, %d gap(s) recorded",
             fetcher.requests_made, fetcher.requests_refused,
             pacer.waited_seconds, total_gaps)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )
    # ib_async logs every Gateway status note at info level, which drowns ours.
    logging.getLogger("ib_async").setLevel(
        logging.DEBUG if args.verbose else logging.ERROR
    )
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        log.warning("Interrupted")
        return 0


if __name__ == "__main__":
    sys.exit(main())

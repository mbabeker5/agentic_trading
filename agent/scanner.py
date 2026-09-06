#!/usr/bin/env python3
"""Opening-momentum scanner for the agentic trading project.

Asks IB Gateway which US stocks and ETFs are gaining hard and trading unusually
heavily, checks each one against the strategy's rules, and writes a shortlist of
at most twenty names to a JSON file. Claude reads that file at 9:35 AM and
decides which names, if any, are worth trading.

Two of the filters are Mo's decisions of 2026-09-06 and are worth knowing about
before reading the code. The liquidity floor is 20 million dollars of average
daily trading over 30 completed sessions, worked out as close times volume per
session and averaged. It replaced a floor of a million shares a day, because a
million shares of a 6 dollar stock and a million shares of a 600 dollar stock
are not the same amount of money and only one of them can absorb our order. And
the relative volume floor of 2 times normal is anchored at 09:35 Eastern, five
minutes after the open, which is the moment the strategy makes its picks. When
the data does not reach 09:35 the run says so in its warnings rather than
quietly measuring the ratio somewhere else.

This script is read-only by construction. It calls exactly four things on the
Gateway API, all of them reads: the scanner, historical bars, contract details
and the market data type. There is no order code in the file at all.

It also connects with readonly=True, which stops the client library touching
orders when it connects. Worth being precise about that flag though: it does not
make Gateway refuse an order, it only keeps this client from asking about them.
The belt-and-braces version of that is Gateway's own ReadOnlyApi setting, which
is a separate switch in config/ibc.ini and is currently off.

Run it like this, from the project folder:

    venv312/bin/python agent/scanner.py --out output/shortlist_2026-09-02.json

Exit code is 0 whenever the scan ran, even if nothing survived the filters.
It is 1 only when the Gateway connection itself failed.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import math
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ib_async import IB, ScannerSubscription, Stock

try:
    import yaml
except ImportError:  # pragma: no cover - pyyaml is in requirements-312.txt
    yaml = None


PROJECT_ROOT = Path(__file__).resolve().parent.parent
GUARDRAILS_PATH = PROJECT_ROOT / "config" / "guardrails.yaml"

EASTERN = ZoneInfo("America/New_York")

# The regular US session, 9:30 AM to 4:00 PM Eastern, is 390 minutes long.
SESSION_MINUTES = 390
OPEN_HOUR, OPEN_MINUTE = 9, 30

# Defaults. Anything present in config/guardrails.yaml wins over these.
DEFAULT_PRICE_FLOOR = 5.0
DEFAULT_MIN_AVG_DOLLAR_VOLUME = 20_000_000.0
DEFAULT_DOLLAR_VOLUME_SESSIONS = 30
DEFAULT_REL_VOLUME_MIN = 2.0
DEFAULT_MAX_CANDIDATES = 20

# The relative volume test is anchored at 9:35 AM Eastern, five minutes after
# the open. That is the moment the strategy makes its picks, and Mo's rule of
# 2026-09-06 is about that moment: the volume traded by 9:35 has to be at least
# twice the stock's normal pace for that point in the day. Written down as a
# real time rather than left implicit in whenever the script happens to run.
REL_VOLUME_ANCHOR_HOUR, REL_VOLUME_ANCHOR_MINUTE = 9, 35
REL_VOLUME_ANCHOR_LABEL = "09:35"
REL_VOLUME_ANCHOR_MINUTES = 5.0

# How many names we are willing to pull extra data for. Kept low on purpose:
# IB Gateway rations historical-data requests (roughly 60 in any ten minutes),
# and blowing through that ration gets the whole connection throttled.
# The arithmetic: one reference request, plus one daily request per name we
# enrich, plus one intraday request per name that makes the shortlist. That is
# 1 + 40 + 20 = 61 in the worst case, which is why the budget sits just under
# Gateway's sixty. A normal run lands in the low fifties because the filters
# thin the shortlist well below twenty.
ENRICHMENT_CAP = 40
HISTORY_REQUEST_BUDGET = 58
HISTORY_CONCURRENCY = 4
HISTORY_MIN_GAP_SECONDS = 0.25

# How many completed sessions a name needs before we trust its "normal" volume.
# A stock listed last week has no normal, and averaging its first three days
# would make a wild number look settled.
MIN_DAILY_BARS_FOR_AVERAGE = 10

# How many sessions of daily bars to ask Gateway for. The dollar volume average
# covers 30 completed sessions, which is about 44 calendar days, so a 40 day
# request would come up short. 60 calendar days is roughly 42 sessions, which
# leaves room for holidays and for today's own part-formed bar.
DAILY_HISTORY_DURATION = "60 D"

# How many completed sessions the share volume average behind relative volume
# covers. That one stays at 20: it is a ratio of shares against shares, and a
# shorter window tracks a change in a stock's normal pace more quickly.
REL_VOLUME_AVERAGE_SESSIONS = 20

SCAN_CODES = ("TOP_PERC_GAIN", "HOT_BY_VOLUME")
SCAN_INSTRUMENT = "STK"
SCAN_LOCATION = "STK.US.MAJOR"
SCAN_ROWS = 50

# Plain-English labels for the scan codes, for the "reasons" field.
SCAN_CODE_LABELS = {
    "TOP_PERC_GAIN": "IBKR's biggest percentage gainers list",
    "HOT_BY_VOLUME": "IBKR's unusually heavy volume list",
}

# Where a real US listing trades. Anything else is a foreign line and is dropped.
ALLOWED_PRIMARY_EXCHANGES = frozenset(
    {"NYSE", "NASDAQ", "NASDAQ.NMS", "ARCA", "AMEX", "BATS", "IEX"}
)

# Leveraged and inverse funds move two or three times the market and are not what
# this strategy is looking for. Two ways of catching them: a list of the usual
# suspects by ticker, and a set of giveaway words in the fund's full name.
LEVERAGED_INVERSE_TICKERS = frozenset(
    {
        "TQQQ", "SQQQ", "SPXU", "SPXL", "UPRO", "SDOW", "UDOW", "SOXL", "SOXS",
        "UVXY", "SVXY", "VIXY", "TZA", "TNA", "LABU", "LABD", "FAS", "FAZ",
        "NUGT", "DUST", "JNUG", "JDST", "YINN", "YANG", "ERX", "ERY", "GUSH",
        "DRIP", "BOIL", "KOLD", "UCO", "SCO", "AGQ", "ZSL", "UGL", "GLL",
        "TMF", "TMV", "TYD", "TYO", "SSO", "SDS", "QLD", "QID", "DDM", "DXD",
        "MIDU", "URTY", "SRTY", "TECL", "TECS", "CURE", "DPST", "WEBL", "WEBS",
        "NAIL", "RETL", "PILL", "HIBL", "HIBS", "BNKU", "BNKD", "TSLL", "TSLQ",
        "NVDL", "NVDD", "CONL", "MSTU", "MSTZ", "AAPU", "AAPD", "AMZU", "AMZD",
        "GGLL", "GGLS", "MSFU", "MSFD", "METU", "METD",
    }
)

# Word patterns that give away a leveraged or inverse fund in its long name.
# ULTRA is matched as a prefix so ULTRAPRO and ULTRASHORT are caught too.
LEVERAGED_NAME_PATTERNS = (
    (r"(?<![A-Z0-9])[23]X(?![A-Z0-9])", "2X or 3X"),
    (r"\bULTRA", "Ultra"),
    (r"\bINVERSE\b", "Inverse"),
    (r"\bBEAR\b", "Bear"),
    (r"\bBULL\b", "Bull"),
    (r"\bLEVERAGED\b", "Leveraged"),
    (r"\bSHORT\b", "Short"),
)
COMPILED_NAME_PATTERNS = tuple(
    (re.compile(pattern), label) for pattern, label in LEVERAGED_NAME_PATTERNS
)

# The name check is aimed at funds, so ordinary company shares are spared it.
# Otherwise a company genuinely called something like "Bull Horn Holdings"
# would be thrown out for no good reason.
NAME_CHECK_EXEMPT_STOCK_TYPES = frozenset({"COMMON"})

# Gateway chatter that is either a status note or the normal end of a snapshot
# scan. Logged quietly so the real problems stand out.
BENIGN_ERROR_CODES = frozenset({162, 165, 202, 300, 365, 366, 492, 2104, 2106, 2107, 2108, 2137, 2158})

# Codes Gateway uses to say "you are not subscribed to live data for this".
# 492 is the scanner's own version: the scan still runs, but the ranking is
# built from delayed prices, so the results are approximate.
NO_LIVE_DATA_CODES = frozenset({354, 492, 10089, 10091, 10167, 10168, 10197})

MARKET_DATA_TYPE_LABELS = {1: "live", 2: "frozen", 3: "delayed", 4: "delayed frozen"}

log = logging.getLogger("scanner")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@dataclass
class Thresholds:
    """The numbers the scanner filters on.

    min_avg_dollar_volume is the liquidity floor Mo settled on 2026-09-06: a
    name has to have traded at least this many dollars a day on average, over
    dollar_volume_sessions completed sessions, before it is worth looking at.
    It replaced a floor of a million shares a day. Dollars are the honest unit,
    because a million shares of a 6 dollar stock and a million shares of a 600
    dollar stock are not remotely the same amount of money, and how much we can
    trade without moving the price depends on the money.

    universe.min_avg_volume, the old share count, is still read out of the
    settings file so an older file loads, but nothing in here filters on it any
    more. It is carried into the output so a run can be read back later.
    """

    price_floor: float = DEFAULT_PRICE_FLOOR
    min_avg_dollar_volume: float = DEFAULT_MIN_AVG_DOLLAR_VOLUME
    dollar_volume_sessions: int = DEFAULT_DOLLAR_VOLUME_SESSIONS
    rel_volume_min: float = DEFAULT_REL_VOLUME_MIN
    max_candidates: int = DEFAULT_MAX_CANDIDATES
    source: str = "built-in defaults"
    deprecated_min_avg_volume: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "price_floor": self.price_floor,
            "min_avg_dollar_volume": self.min_avg_dollar_volume,
            "dollar_volume_sessions": self.dollar_volume_sessions,
            "rel_volume_min": self.rel_volume_min,
            "rel_volume_anchor_eastern": REL_VOLUME_ANCHOR_LABEL,
            "rel_volume_anchor_minutes": REL_VOLUME_ANCHOR_MINUTES,
            "max_candidates": self.max_candidates,
            "source": self.source,
            "deprecated_min_avg_volume": self.deprecated_min_avg_volume,
        }


def load_thresholds(path: Path) -> Thresholds:
    """Read thresholds from guardrails.yaml if it is there, else use defaults.

    This script never creates or edits that file. Another part of the project
    owns it. A missing file, or a missing key inside it, just falls back.
    """
    thresholds = Thresholds()
    if not path.exists():
        log.info("No %s, using built-in default thresholds", path)
        return thresholds
    if yaml is None:
        log.warning("pyyaml is not installed, ignoring %s and using defaults", path)
        return thresholds

    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except Exception as exc:
        log.warning("Could not read %s (%s), using defaults", path, exc)
        return thresholds

    if not isinstance(raw, dict):
        log.warning("%s is not a mapping, using defaults", path)
        return thresholds

    universe = raw.get("universe") or {}
    scanner = raw.get("scanner") or {}
    if not isinstance(universe, dict):
        universe = {}
    if not isinstance(scanner, dict):
        scanner = {}

    def pick(section: dict[str, Any], key: str, current: float, cast) -> float:
        value = section.get(key)
        if value is None:
            return current
        try:
            return cast(value)
        except (TypeError, ValueError):
            log.warning("Ignoring bad value for %s in %s: %r", key, path, value)
            return current

    thresholds.price_floor = pick(universe, "price_floor", thresholds.price_floor, float)
    thresholds.min_avg_dollar_volume = pick(
        universe,
        "min_avg_dollar_volume",
        thresholds.min_avg_dollar_volume,
        float,
    )
    thresholds.dollar_volume_sessions = int(
        pick(
            universe,
            "dollar_volume_sessions",
            thresholds.dollar_volume_sessions,
            int,
        )
    )
    if thresholds.dollar_volume_sessions < MIN_DAILY_BARS_FOR_AVERAGE:
        log.warning(
            "Averaging dollar volume over %d session(s) is too few to mean "
            "anything, using %d instead",
            thresholds.dollar_volume_sessions,
            MIN_DAILY_BARS_FOR_AVERAGE,
        )
        thresholds.dollar_volume_sessions = MIN_DAILY_BARS_FOR_AVERAGE
    # Read but never filtered on. Mo replaced this share count with the dollar
    # figure above on 2026-09-06. It is kept so an older settings file still
    # loads, and it is written into the output so a run can be read back later.
    thresholds.deprecated_min_avg_volume = pick(
        universe, "min_avg_volume", thresholds.deprecated_min_avg_volume, float
    )
    thresholds.rel_volume_min = pick(
        scanner, "rel_volume_min", thresholds.rel_volume_min, float
    )
    thresholds.max_candidates = int(
        pick(scanner, "max_candidates", thresholds.max_candidates, int)
    )
    if thresholds.max_candidates < 1:
        log.warning(
            "A shortlist length of %d makes no sense, using 1 instead",
            thresholds.max_candidates,
        )
        thresholds.max_candidates = 1
    thresholds.source = str(path)
    log.info("Loaded thresholds from %s", path)
    return thresholds


# ---------------------------------------------------------------------------
# Request pacing
# ---------------------------------------------------------------------------


class HistoryPacer:
    """Keeps historical-data requests slow enough that Gateway stays friendly.

    Gateway allows roughly sixty historical-data requests in any ten-minute
    window. Go over and it starts refusing requests for everyone on the
    connection, so this counts every request and spaces them out.
    """

    def __init__(self, budget: int, concurrency: int, min_gap: float) -> None:
        self.budget = budget
        self.used = 0
        self._semaphore = asyncio.Semaphore(concurrency)
        self._min_gap = min_gap
        self._last_start = 0.0
        self._lock = asyncio.Lock()

    @property
    def remaining(self) -> int:
        return max(0, self.budget - self.used)

    @contextlib.asynccontextmanager
    async def slot(self):
        """Claim one request slot. Yields True if there was budget left.

        The check and the increment both happen under the lock. Doing the check
        outside it would let a whole batch of waiting requests look at the same
        stale count, all decide there was room, and sail past the budget
        together.
        """
        granted = False
        async with self._semaphore:
            async with self._lock:
                if self.used < self.budget:
                    wait = self._min_gap - (time.monotonic() - self._last_start)
                    if wait > 0:
                        await asyncio.sleep(wait)
                    self._last_start = time.monotonic()
                    self.used += 1
                    granted = True
            yield granted


# ---------------------------------------------------------------------------
# Candidate record
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    symbol: str
    con_id: int
    exchange: str = "SMART"
    primary_exchange: str = ""
    currency: str = ""
    long_name: str = ""
    stock_type: str = ""
    flagged_by: list[str] = field(default_factory=list)

    last: float | None = None
    prev_close: float | None = None
    gain_pct: float | None = None
    volume_today: float | None = None
    avg_volume_20d: float | None = None
    avg_volume_days: int | None = None
    avg_dollar_volume: float | None = None
    avg_dollar_volume_sessions: int | None = None
    rel_volume: float | None = None
    rel_volume_minutes_elapsed: float | None = None
    opening_range_high: float | None = None
    opening_range_low: float | None = None
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def contract(self) -> Stock:
        stock = Stock(self.symbol, "SMART", "USD")
        stock.conId = self.con_id
        if self.primary_exchange:
            stock.primaryExchange = self.primary_exchange
        return stock

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "conId": self.con_id,
            "primaryExchange": self.primary_exchange,
            "last": round2(self.last),
            "gain_pct": round2(self.gain_pct),
            "opening_range_high": round2(self.opening_range_high),
            "opening_range_low": round2(self.opening_range_low),
            "volume_today": to_int(self.volume_today),
            "avg_volume_20d": to_int(self.avg_volume_20d),
            "avg_dollar_volume": to_int(self.avg_dollar_volume),
            "avg_dollar_volume_sessions": self.avg_dollar_volume_sessions,
            "rel_volume": round2(self.rel_volume),
            "rel_volume_minutes_elapsed": round2(self.rel_volume_minutes_elapsed),
            "flagged_by": list(self.flagged_by),
            "reasons": list(self.reasons),
            "score": round2(self.score),
            "long_name": self.long_name,
            "stock_type": self.stock_type,
        }


def round2(value: float | None) -> float | None:
    return None if value is None else round(float(value), 2)


def to_int(value: float | None) -> int | None:
    return None if value is None else int(round(float(value)))


def human_millions(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f} million"
    if value >= 1_000:
        return f"{value / 1_000:.0f} thousand"
    return f"{value:.0f}"


def human_dollars(value: float | None) -> str:
    """A dollar figure a person can read, so 20000000.0 reads as 20.0 million dollars."""
    if value is None:
        return "unknown"
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f} billion dollars"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f} million dollars"
    if value >= 1_000:
        return f"{value / 1_000:.0f} thousand dollars"
    return f"{value:.0f} dollars"


# ---------------------------------------------------------------------------
# Bar helpers
# ---------------------------------------------------------------------------


def bar_date(bar: Any) -> date | None:
    """Daily bars carry a date, intraday bars carry a timestamp. Normalise."""
    value = getattr(bar, "date", None)
    if isinstance(value, datetime):
        return value.astimezone(EASTERN).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        for fmt in ("%Y%m%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(value[:10], fmt).date()
            except ValueError:
                continue
    return None


def bar_time_eastern(bar: Any) -> datetime | None:
    value = getattr(bar, "date", None)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=EASTERN)
        return value.astimezone(EASTERN)
    return None


def minutes_into_session(moment: datetime) -> float:
    """How far past 9:30 AM Eastern a moment is, clamped to the session."""
    session_open = moment.replace(
        hour=OPEN_HOUR, minute=OPEN_MINUTE, second=0, microsecond=0
    )
    elapsed = (moment - session_open).total_seconds() / 60.0
    return max(0.0, min(float(SESSION_MINUTES), elapsed))


def bar_dollar_volume(bar: Any) -> float | None:
    """What one session's trading was worth in dollars: close times volume.

    Close times volume is the rough and standard way to do this. It is not the
    true average price of the day's trades, but over 30 sessions the difference
    washes out, and it is the only version that can be worked out from a daily
    bar. None comes back when the bar has no usable close or volume.
    """
    close = getattr(bar, "close", None)
    volume = getattr(bar, "volume", None)
    if close is None or volume is None:
        return None
    try:
        close = float(close)
        volume = float(volume)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(close) or not math.isfinite(volume):
        return None
    if close <= 0 or volume < 0:
        return None
    return close * volume


def average_dollar_volume(
    bars: list[Any],
    sessions: int = DEFAULT_DOLLAR_VOLUME_SESSIONS,
    min_sessions: int = MIN_DAILY_BARS_FOR_AVERAGE,
) -> tuple[float | None, int]:
    """Average daily dollar volume over the most recent completed sessions.

    Hand in completed daily bars, oldest first, with today's part-formed bar
    already taken out. The answer is the average of close times volume over the
    last `sessions` of them, and how many sessions that average actually used.

    A name with fewer than min_sessions completed sessions gets None back, the
    same way the share average always worked. A stock listed last week has no
    normal to be measured against, and averaging its first three days would
    dress a wild number up as a settled one. None fails the liquidity floor,
    which is the safe answer.
    """
    if sessions < 1:
        raise ValueError(
            f"average_dollar_volume was asked for {sessions} sessions, and it needs "
            "at least one."
        )
    usable = [value for value in (bar_dollar_volume(b) for b in bars) if value is not None]
    recent = usable[-sessions:]
    if len(recent) < min_sessions:
        return None, len(recent)
    return sum(recent) / len(recent), len(recent)


def expected_volume_by(
    avg_daily_volume: float | None,
    minutes_elapsed: float,
    session_minutes: int = SESSION_MINUTES,
) -> float | None:
    """How many shares a normal day would have traded by this point.

    The normal daily volume, scaled by how much of the 390 minute session has
    gone by. At 9:35, five minutes in, that is five 390ths of a normal day.
    """
    if not avg_daily_volume or avg_daily_volume <= 0:
        return None
    fraction = max(0.0, min(1.0, float(minutes_elapsed) / float(session_minutes)))
    if fraction <= 0:
        return None
    return float(avg_daily_volume) * fraction


def relative_volume(
    volume_so_far: float | None,
    avg_daily_volume: float | None,
    minutes_elapsed: float,
    session_minutes: int = SESSION_MINUTES,
) -> float | None:
    """How many times its normal pace a name is trading at right now.

    2.0 means twice the volume a normal day would have shown by this point.
    Mo's floor of 2026-09-06 is 2.0 measured at 9:35, five minutes after the
    open, which is REL_VOLUME_ANCHOR_MINUTES above.

    None comes back when there is nothing to divide by, and that fails the
    floor, which is the safe answer.
    """
    if volume_so_far is None:
        return None
    expected = expected_volume_by(avg_daily_volume, minutes_elapsed, session_minutes)
    if not expected:
        return None
    return float(volume_so_far) / expected


# ---------------------------------------------------------------------------
# The scanner
# ---------------------------------------------------------------------------


class OpeningMomentumScanner:
    def __init__(
        self,
        ib: IB,
        thresholds: Thresholds,
        enrichment_cap: int = ENRICHMENT_CAP,
        history_budget: int = HISTORY_REQUEST_BUDGET,
    ) -> None:
        self.ib = ib
        self.thresholds = thresholds
        self.enrichment_cap = enrichment_cap
        self.pacer = HistoryPacer(
            history_budget, HISTORY_CONCURRENCY, HISTORY_MIN_GAP_SECONDS
        )
        self.counts: dict[str, int] = {}
        self.warnings: list[str] = []
        self.market_data_type = 1
        self.saw_no_live_data = False
        self.session_minutes_elapsed: float | None = None
        self.data_as_of: str | None = None
        self.skipped_for_budget = 0

    # -- plumbing ----------------------------------------------------------

    def on_error(self, req_id: int, code: int, message: str, contract: Any) -> None:
        if code in NO_LIVE_DATA_CODES:
            self.saw_no_live_data = True
        text = f"Gateway code {code} (request {req_id}): {message}"
        if code in BENIGN_ERROR_CODES or code in NO_LIVE_DATA_CODES:
            log.debug(text)
        else:
            log.warning(text)

    def note(self, message: str) -> None:
        log.warning(message)
        self.warnings.append(message)

    async def set_market_data_type(self, data_type: int) -> None:
        self.ib.reqMarketDataType(data_type)
        self.market_data_type = data_type
        log.info(
            "Market data type set to %s (%s)",
            data_type,
            MARKET_DATA_TYPE_LABELS.get(data_type, "unknown"),
        )

    # -- step 1: run the scans --------------------------------------------

    async def run_one_scan(self, scan_code: str) -> list[Any]:
        subscription = ScannerSubscription(
            instrument=SCAN_INSTRUMENT,
            locationCode=SCAN_LOCATION,
            scanCode=scan_code,
            numberOfRows=SCAN_ROWS,
            abovePrice=self.thresholds.price_floor,
        )
        # No volume filter is sent to Gateway any more. Gateway's scanner can
        # filter on a share count and has no dollar volume filter at all, and a
        # share count cannot stand in for one: 20 million dollars is 4 million
        # shares at 5 dollars and 40 thousand shares at 500, so any share floor
        # loose enough to keep the expensive names would let through everything
        # else as well. The liquidity floor is applied further down instead,
        # against 30 sessions of real daily bars. The price floor is still sent,
        # in abovePrice above, because that one means the same thing either way.
        try:
            rows = await self.ib.reqScannerDataAsync(subscription)
        except Exception as exc:
            self.note(f"Scan {scan_code} failed outright: {exc}")
            return []
        log.info("Scan %s returned %d rows", scan_code, len(rows))
        return list(rows)

    async def collect_candidates(self) -> list[Candidate]:
        """Run both scans and merge them, taking turns between the two lists.

        Taking turns matters. If we simply stacked one list on top of the other,
        the cap further down would chop the second scan off completely and we
        would only ever look at the biggest gainers, never the heavy volume
        names. Alternating means the top of both lists survives the cap, and
        anything both scans flagged floats to the front.
        """
        by_con_id: dict[int, Candidate] = {}
        per_scan: list[list[int]] = []
        for scan_code in SCAN_CODES:
            rows = await self.run_one_scan(scan_code)
            self.counts[f"scanned_{scan_code.lower()}"] = len(rows)
            ranked: list[int] = []
            for row in rows:
                contract = getattr(getattr(row, "contractDetails", None), "contract", None)
                if contract is None or not contract.symbol:
                    continue
                existing = by_con_id.get(contract.conId)
                if existing is None:
                    existing = Candidate(
                        symbol=contract.symbol,
                        con_id=contract.conId,
                        primary_exchange=contract.primaryExchange or "",
                        currency=contract.currency or "",
                    )
                    by_con_id[contract.conId] = existing
                if scan_code not in existing.flagged_by:
                    existing.flagged_by.append(scan_code)
                ranked.append(contract.conId)
            per_scan.append(ranked)

        # Names both scans flagged go first, then alternate down the two lists.
        both = [
            con_id
            for con_id, candidate in by_con_id.items()
            if len(candidate.flagged_by) > 1
        ]
        order: list[int] = list(both)
        seen = set(both)
        for position in range(max((len(r) for r in per_scan), default=0)):
            for ranked in per_scan:
                if position < len(ranked) and ranked[position] not in seen:
                    seen.add(ranked[position])
                    order.append(ranked[position])
        return [by_con_id[con_id] for con_id in order]

    # -- step 2: how far into the day is the data? ------------------------

    async def measure_session_progress(self, reference_symbol: str) -> None:
        """Work out how much of the trading day the data actually covers.

        Delayed data runs about fifteen minutes behind the clock, so asking the
        clock would make every stock look like it had traded less than normal.
        Instead, look at how far a always-busy reference symbol's bars reach.
        """
        now_eastern = datetime.now(EASTERN)
        fallback = minutes_into_session(now_eastern)
        bars = await self.fetch_bars(
            Stock(reference_symbol, "SMART", "USD"),
            duration="1 D",
            bar_size="5 mins",
            label=f"{reference_symbol} reference bars",
        )
        if bars:
            last_time = bar_time_eastern(bars[-1])
            if last_time is not None and last_time.date() != now_eastern.date():
                self.note(
                    f"{reference_symbol}'s most recent bar is from "
                    f"{last_time.date()}, not today, so today's session has "
                    "probably not started yet"
                )
                last_time = None
            if last_time is not None:
                bar_end = last_time + timedelta(minutes=5)
                # The newest bar may still be forming, and delayed data can
                # never be fresher than the clock, so never claim more progress
                # than the clock allows.
                covered = min(minutes_into_session(bar_end), fallback)
                self.session_minutes_elapsed = max(5.0, covered)
                self.data_as_of = bar_end.isoformat()
                log.info(
                    "Data covers %.0f of the session's %d minutes (through %s Eastern)",
                    self.session_minutes_elapsed,
                    SESSION_MINUTES,
                    self.data_as_of,
                )
                return
        self.session_minutes_elapsed = max(5.0, fallback)
        self.data_as_of = now_eastern.isoformat()
        self.note(
            f"Could not read {reference_symbol} bars, falling back to the wall clock "
            f"({self.session_minutes_elapsed:.0f} minutes into the session)"
        )

    def check_rel_volume_anchor(self) -> None:
        """Say so plainly when the data has not reached 9:35 yet.

        The relative volume floor is a statement about one moment: by 9:35, five
        minutes after the open, a name has to have traded at least twice its
        normal volume for that point in the day. If the data does not reach 9:35
        the ratio is being measured somewhere else, and the shortlist should not
        pretend otherwise. Delayed market data runs about fifteen minutes
        behind, so a 9:35 run on a delayed feed lands here every time.
        """
        elapsed = self.session_minutes_elapsed
        if elapsed is None:
            return
        if elapsed + 1e-9 < REL_VOLUME_ANCHOR_MINUTES:
            self.note(
                f"The data only reaches {elapsed:.0f} minute(s) into the session, and "
                f"the relative volume floor is anchored at {REL_VOLUME_ANCHOR_LABEL}, "
                f"which is {REL_VOLUME_ANCHOR_MINUTES:.0f} minutes in. Relative volume "
                "below that point is measured on a sliver of trading and should not be "
                "trusted."
            )

    # -- step 3: per-name data --------------------------------------------

    async def fetch_bars(
        self, contract: Stock, duration: str, bar_size: str, label: str
    ) -> list[Any]:
        async with self.pacer.slot() as granted:
            if not granted:
                self.skipped_for_budget += 1
                log.warning(
                    "Skipped %s, the run's %d request budget is spent",
                    label,
                    self.pacer.budget,
                )
                return []
            try:
                bars = await self.ib.reqHistoricalDataAsync(
                    contract,
                    endDateTime="",
                    durationStr=duration,
                    barSizeSetting=bar_size,
                    whatToShow="TRADES",
                    useRTH=True,
                    formatDate=1,
                )
            except Exception as exc:
                log.warning("%s failed: %s", label, exc)
                return []
        if not bars:
            log.debug("%s returned no bars", label)
        return list(bars)

    async def load_daily_stats(self, candidate: Candidate) -> None:
        """Fill in price, gain, today's volume and the two averages.

        Two averages, because they answer two different questions. The dollar
        volume average over 30 sessions says whether the name is liquid enough
        to trade at all, which is Mo's floor of 20 million dollars a day. The
        share volume average over 20 sessions is the bottom half of the relative
        volume ratio, which is shares against shares and so has to stay in
        shares.
        """
        bars = await self.fetch_bars(
            candidate.contract(),
            duration=DAILY_HISTORY_DURATION,
            bar_size="1 day",
            label=f"{candidate.symbol} daily bars",
        )
        if not bars:
            return

        today_eastern = datetime.now(EASTERN).date()
        today_bar = None
        completed = []
        for bar in bars:
            if bar_date(bar) == today_eastern:
                today_bar = bar
            else:
                completed.append(bar)

        if today_bar is not None:
            candidate.last = float(today_bar.close)
            candidate.volume_today = float(today_bar.volume or 0.0)
        elif completed:
            # Before the open, or on a day with no trades yet.
            candidate.last = float(completed[-1].close)
            candidate.volume_today = 0.0

        if completed:
            candidate.prev_close = float(completed[-1].close)

            # The liquidity floor: 30 sessions of close times volume, averaged.
            candidate.avg_dollar_volume, candidate.avg_dollar_volume_sessions = (
                average_dollar_volume(
                    completed, self.thresholds.dollar_volume_sessions
                )
            )
            if candidate.avg_dollar_volume is None:
                # Too new to have a normal. Leaving this empty makes the name
                # fail the liquidity floor, which is the safe answer.
                log.debug(
                    "%s has only %d completed session(s), too new to judge",
                    candidate.symbol,
                    candidate.avg_dollar_volume_sessions or 0,
                )

            # The bottom half of the relative volume ratio, still in shares.
            recent = completed[-REL_VOLUME_AVERAGE_SESSIONS:]
            if len(recent) >= MIN_DAILY_BARS_FOR_AVERAGE:
                volumes = [float(b.volume or 0.0) for b in recent]
                candidate.avg_volume_20d = sum(volumes) / len(volumes)
                candidate.avg_volume_days = len(recent)

        if candidate.last is not None and candidate.prev_close:
            candidate.gain_pct = (
                (candidate.last - candidate.prev_close) / candidate.prev_close * 100.0
            )

        elapsed = self.session_minutes_elapsed or float(SESSION_MINUTES)
        candidate.rel_volume_minutes_elapsed = elapsed
        candidate.rel_volume = relative_volume(
            candidate.volume_today, candidate.avg_volume_20d, elapsed
        )

    async def load_contract_details(self, candidate: Candidate) -> None:
        try:
            details = await self.ib.reqContractDetailsAsync(candidate.contract())
        except Exception as exc:
            log.warning("%s contract details failed: %s", candidate.symbol, exc)
            return
        if not details:
            log.debug("%s returned no contract details", candidate.symbol)
            return
        detail = details[0]
        candidate.long_name = (detail.longName or "").strip()
        candidate.stock_type = (getattr(detail, "stockType", "") or "").strip()
        candidate.primary_exchange = (
            detail.contract.primaryExchange or candidate.primary_exchange or ""
        )
        candidate.currency = detail.contract.currency or candidate.currency
        candidate.exchange = detail.contract.exchange or candidate.exchange

    async def load_opening_range(self, candidate: Candidate) -> None:
        """Get the high and low of the first five minutes of trading."""
        bars = await self.fetch_bars(
            candidate.contract(),
            duration="1 D",
            bar_size="5 mins",
            label=f"{candidate.symbol} 5-minute bars",
        )
        if not bars:
            return
        # A one day request can reach back into the previous session, and
        # publishing yesterday's high as "the first five minutes" would hand
        # Claude a stale entry trigger. So only today's bars count.
        today_eastern = datetime.now(EASTERN).date()
        todays_bars = []
        for bar in bars:
            moment = bar_time_eastern(bar)
            if moment is not None and moment.date() == today_eastern:
                todays_bars.append((moment, bar))
        if not todays_bars:
            log.warning(
                "%s has no bars from today, so it gets no opening range",
                candidate.symbol,
            )
            return
        todays_bars.sort(key=lambda pair: pair[0])
        for moment, bar in todays_bars:
            if moment.hour == OPEN_HOUR and moment.minute == OPEN_MINUTE:
                candidate.opening_range_high = float(bar.high)
                candidate.opening_range_low = float(bar.low)
                return
        moment, bar = todays_bars[0]
        candidate.opening_range_high = float(bar.high)
        candidate.opening_range_low = float(bar.low)
        log.warning(
            "%s had no 9:30 bar, used today's first bar at %s instead",
            candidate.symbol,
            moment.strftime("%H:%M"),
        )

    # -- step 4: filters ---------------------------------------------------

    def leverage_verdict(self, candidate: Candidate) -> str | None:
        """Return a reason to drop this name as leveraged or inverse, else None."""
        if candidate.symbol.upper() in LEVERAGED_INVERSE_TICKERS:
            return "on the known leveraged and inverse ticker list"
        if candidate.stock_type.upper() in NAME_CHECK_EXEMPT_STOCK_TYPES:
            return None
        name = candidate.long_name.upper()
        if not name:
            return None
        for pattern, label in COMPILED_NAME_PATTERNS:
            if pattern.search(name):
                return f'fund name contains "{label}"'
        return None

    def build_reasons(self, candidate: Candidate) -> list[str]:
        reasons = []
        for scan_code in candidate.flagged_by:
            reasons.append(
                f"Showed up on {SCAN_CODE_LABELS.get(scan_code, scan_code)}"
            )
        if candidate.gain_pct is not None:
            direction = "Up" if candidate.gain_pct >= 0 else "Down"
            move = f"{direction} {abs(candidate.gain_pct):.1f} percent on the day"
            if candidate.prev_close and candidate.last:
                move += (
                    f", from {candidate.prev_close:.2f} to {candidate.last:.2f} dollars"
                )
            reasons.append(move)
        if candidate.rel_volume is not None:
            reasons.append(
                f"Trading {candidate.rel_volume:.1f} times its normal volume for this "
                f"point in the day, measured against the {REL_VOLUME_ANCHOR_LABEL} "
                f"anchor and {candidate.rel_volume_minutes_elapsed:.0f} minutes of data"
                if candidate.rel_volume_minutes_elapsed is not None
                else f"Trading {candidate.rel_volume:.1f} times its normal volume for "
                f"this point in the day"
            )
        if candidate.volume_today is not None and candidate.avg_volume_20d:
            reasons.append(
                f"{human_millions(candidate.volume_today)} shares traded so far "
                f"against a {human_millions(candidate.avg_volume_20d)} share daily average"
            )
        if candidate.avg_dollar_volume is not None:
            reasons.append(
                f"Normally trades {human_dollars(candidate.avg_dollar_volume)} a day "
                f"over the last {candidate.avg_dollar_volume_sessions} sessions, "
                f"against a floor of "
                f"{human_dollars(self.thresholds.min_avg_dollar_volume)}"
            )
        if candidate.opening_range_high is not None and candidate.opening_range_low is not None:
            reasons.append(
                f"First five minutes ranged {candidate.opening_range_low:.2f} to "
                f"{candidate.opening_range_high:.2f} dollars, so a break above "
                f"{candidate.opening_range_high:.2f} is the entry to watch"
            )
        if candidate.stock_type:
            reasons.append(f"Listed on {candidate.primary_exchange or 'a US venue'} as {candidate.stock_type.lower()}")
        return reasons

    def compute_score(self, candidate: Candidate) -> float:
        """Gain multiplied by the log of relative volume.

        A big move on normal volume is suspicious, and heavy volume with no move
        is not a momentum trade. Multiplying the two rewards names that have both.
        """
        gain = candidate.gain_pct or 0.0
        rel = max(candidate.rel_volume or 1.0, 1.0001)
        return gain * math.log(rel)

    # -- the whole run -----------------------------------------------------

    async def run(self, reference_symbol: str) -> dict[str, Any]:
        candidates = await self.collect_candidates()
        self.counts["merged_unique"] = len(candidates)

        if self.saw_no_live_data and self.market_data_type == 1:
            log.info("No live data entitlement, retrying the scans on delayed data")
            await self.set_market_data_type(3)
            self.saw_no_live_data = False
            candidates = await self.collect_candidates()
            self.counts["merged_unique"] = len(candidates)

        # Drop the obvious leveraged and inverse tickers now, before spending
        # any data requests on them.
        kept = []
        for candidate in candidates:
            if candidate.symbol.upper() in LEVERAGED_INVERSE_TICKERS:
                log.debug("Dropped %s, known leveraged or inverse fund", candidate.symbol)
                continue
            kept.append(candidate)
        candidates = kept
        self.counts["after_known_leveraged_tickers"] = len(candidates)

        candidates = candidates[: self.enrichment_cap]
        self.counts["capped_for_enrichment"] = len(candidates)

        if not candidates:
            self.counts["daily_bars_ok"] = 0
            self.counts["passed_price_floor"] = 0
            self.counts["passed_dollar_volume"] = 0
            self.counts["passed_rel_volume"] = 0
            self.counts["passed_moving_up"] = 0
            self.counts["passed_us_listing"] = 0
            self.counts["passed_leverage_name_filter"] = 0
            self.counts["opening_range_ok"] = 0
            self.counts["final"] = 0
            return self.build_output([])

        await self.measure_session_progress(reference_symbol)
        self.check_rel_volume_anchor()

        await asyncio.gather(
            *(self.load_daily_stats(c) for c in candidates), return_exceptions=True
        )
        with_data = [c for c in candidates if c.last is not None]
        self.counts["daily_bars_ok"] = len(with_data)
        if len(with_data) < len(candidates):
            missing = sorted(c.symbol for c in candidates if c.last is None)
            self.note(
                f"No daily bars for {len(missing)} name(s), skipped: {', '.join(missing[:12])}"
            )

        survivors = [c for c in with_data if (c.last or 0.0) > self.thresholds.price_floor]
        self.counts["passed_price_floor"] = len(survivors)

        # The liquidity floor. Dollars a day, not shares a day (Mo, 2026-09-06).
        # A name with no dollar average at all is too new to judge and fails
        # here, which is the safe answer.
        survivors = [
            c
            for c in survivors
            if (c.avg_dollar_volume or 0.0) >= self.thresholds.min_avg_dollar_volume
        ]
        self.counts["passed_dollar_volume"] = len(survivors)

        survivors = [
            c
            for c in survivors
            if (c.rel_volume or 0.0) > self.thresholds.rel_volume_min
        ]
        self.counts["passed_rel_volume"] = len(survivors)

        # The strategy only ever buys, so a name that is down on the day is not
        # a candidate however heavily it is trading. The volume scan flags
        # plenty of hard fallers, and pairing one with a "break above the
        # opening high" trigger would be a nonsense instruction.
        survivors = [c for c in survivors if (c.gain_pct or 0.0) > 0]
        self.counts["passed_moving_up"] = len(survivors)

        if survivors:
            await asyncio.gather(
                *(self.load_contract_details(c) for c in survivors),
                return_exceptions=True,
            )

        unknown = sorted(
            c.symbol for c in survivors if not c.long_name and not c.stock_type
        )
        if unknown:
            self.note(
                f"Could not look up {len(unknown)} name(s), so they were dropped "
                f"without being checked: {', '.join(unknown[:12])}"
            )

        us_listed = []
        for candidate in survivors:
            if candidate.currency and candidate.currency.upper() != "USD":
                log.debug(
                    "Dropped %s, priced in %s not USD", candidate.symbol, candidate.currency
                )
                continue
            venue = (candidate.primary_exchange or "").upper()
            if venue and venue not in ALLOWED_PRIMARY_EXCHANGES:
                log.debug("Dropped %s, primary exchange %s", candidate.symbol, venue)
                continue
            if not venue:
                log.debug("Dropped %s, no primary exchange reported", candidate.symbol)
                continue
            us_listed.append(candidate)
        self.counts["passed_us_listing"] = len(us_listed)

        clean = []
        for candidate in us_listed:
            verdict = self.leverage_verdict(candidate)
            if verdict:
                log.debug("Dropped %s, %s", candidate.symbol, verdict)
                continue
            clean.append(candidate)
        self.counts["passed_leverage_name_filter"] = len(clean)

        # Rank first, then only fetch opening ranges for the names that will
        # actually make the shortlist. Saves scarce historical-data requests.
        for candidate in clean:
            candidate.score = self.compute_score(candidate)
        clean.sort(key=lambda c: c.score, reverse=True)
        shortlist = clean[: self.thresholds.max_candidates]

        if shortlist:
            await asyncio.gather(
                *(self.load_opening_range(c) for c in shortlist),
                return_exceptions=True,
            )
        self.counts["opening_range_ok"] = sum(
            1 for c in shortlist if c.opening_range_high is not None
        )
        no_range = sorted(c.symbol for c in shortlist if c.opening_range_high is None)
        if no_range:
            self.note(
                f"No opening range for {len(no_range)} shortlisted name(s), so "
                f"they have no entry trigger: {', '.join(no_range)}"
            )

        for candidate in shortlist:
            candidate.reasons = self.build_reasons(candidate)
        self.counts["final"] = len(shortlist)
        return self.build_output(shortlist)

    def build_output(self, shortlist: list[Candidate]) -> dict[str, Any]:
        now = datetime.now(EASTERN)
        if self.skipped_for_budget:
            self.note(
                f"Ran out of the run's {self.pacer.budget} request budget and "
                f"skipped {self.skipped_for_budget} data request(s), so some "
                "names are missing numbers"
            )
        elif self.pacer.used >= self.pacer.budget:
            self.note(
                f"Used the whole data request budget of {self.pacer.budget}, so "
                "another run straight away may be refused by Gateway"
            )
        return {
            "timestamp": now.isoformat(),
            "timestamp_utc": now.astimezone(ZoneInfo("UTC")).isoformat(),
            "trade_date": now.date().isoformat(),
            "market_data_type": self.market_data_type,
            "market_data_type_label": MARKET_DATA_TYPE_LABELS.get(
                self.market_data_type, "unknown"
            ),
            "data_as_of_eastern": self.data_as_of,
            "session_minutes_elapsed": (
                round(self.session_minutes_elapsed, 1)
                if self.session_minutes_elapsed is not None
                else None
            ),
            "session_minutes_total": SESSION_MINUTES,
            "rel_volume_anchor_eastern": REL_VOLUME_ANCHOR_LABEL,
            "rel_volume_anchor_minutes": REL_VOLUME_ANCHOR_MINUTES,
            "rel_volume_anchor_reached": (
                None
                if self.session_minutes_elapsed is None
                else self.session_minutes_elapsed + 1e-9 >= REL_VOLUME_ANCHOR_MINUTES
            ),
            "scan_codes": list(SCAN_CODES),
            "thresholds": self.thresholds.as_dict(),
            "counts": dict(self.counts),
            "historical_requests_used": self.pacer.used,
            "warnings": list(self.warnings),
            "candidates": [c.as_dict() for c in shortlist],
        }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def non_zero_client_id(value: str) -> int:
    """Refuse client id 0.

    Connecting as client 0 makes ib_async ask Gateway to bind manually placed
    orders to this session. It places nothing, but it is a change rather than a
    read, and this script has no business making one.
    """
    number = int(value)
    if number == 0:
        raise argparse.ArgumentTypeError(
            "client id 0 would bind manually placed orders to this session, "
            "which is not read-only. Pick any other number, such as 201."
        )
    return number


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    today = datetime.now(EASTERN).date().isoformat()
    default_out = PROJECT_ROOT / "output" / f"shortlist_{today}.json"
    parser = argparse.ArgumentParser(
        description="Find US stocks and ETFs with an unusually strong, high volume open."
    )
    parser.add_argument(
        "--out",
        default=str(default_out),
        help="Where to write the shortlist JSON. Default: %(default)s",
    )
    parser.add_argument("--host", default="127.0.0.1", help="IB Gateway host")
    parser.add_argument("--port", type=int, default=4002, help="IB Gateway port (4002 is paper)")
    parser.add_argument(
        "--client-id",
        type=non_zero_client_id,
        default=201,
        help="API client id. Must not be 0. Default: %(default)s",
    )
    parser.add_argument(
        "--config",
        default=str(GUARDRAILS_PATH),
        help="Guardrails YAML to read thresholds from, if it exists. Default: %(default)s",
    )
    parser.add_argument(
        "--enrichment-cap",
        type=int,
        default=ENRICHMENT_CAP,
        help="How many scan hits to pull extra data for. Default: %(default)s",
    )
    parser.add_argument(
        "--history-budget",
        type=int,
        default=HISTORY_REQUEST_BUDGET,
        help="Cap on data requests per run, to stay under Gateway's sixty per "
        "ten minutes. Default: %(default)s",
    )
    parser.add_argument(
        "--reference-symbol",
        default="SPY",
        help="Liquid symbol used to see how far the data reaches. Default: %(default)s",
    )
    parser.add_argument("--verbose", action="store_true", help="Chattier logging")
    return parser.parse_args(argv)


async def main_async(args: argparse.Namespace) -> int:
    thresholds = load_thresholds(Path(args.config))
    log.info(
        "Thresholds: price above %.2f, average daily dollar volume of %s or more over "
        "%d sessions, relative volume above %.2f measured at the %s anchor, at most "
        "%d names (%s)",
        thresholds.price_floor,
        human_dollars(thresholds.min_avg_dollar_volume),
        thresholds.dollar_volume_sessions,
        thresholds.rel_volume_min,
        REL_VOLUME_ANCHOR_LABEL,
        thresholds.max_candidates,
        thresholds.source,
    )

    ib = IB()
    scanner = OpeningMomentumScanner(
        ib, thresholds, args.enrichment_cap, args.history_budget
    )
    ib.errorEvent += scanner.on_error

    try:
        await ib.connectAsync(
            args.host, args.port, clientId=args.client_id, readonly=True, timeout=20
        )
    except Exception as exc:
        log.error(
            "Could not reach IB Gateway at %s:%s as client %s: %s",
            args.host,
            args.port,
            args.client_id,
            exc,
        )
        return 1

    if not ib.isConnected():
        log.error("Connected call returned but the session is not up")
        return 1

    log.info("Connected to IB Gateway at %s:%s, read-only", args.host, args.port)

    try:
        await scanner.set_market_data_type(1)
        result = await scanner.run(args.reference_symbol)
    except Exception as exc:
        log.exception("Scan blew up after connecting: %s", exc)
        result = scanner.build_output([])
        result["warnings"].append(f"Scan failed partway through: {exc}")
    finally:
        with contextlib.suppress(Exception):
            ib.disconnect()

    out_path = Path(args.out).expanduser()
    if not out_path.is_absolute():
        out_path = (Path.cwd() / out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2) + "\n")

    counts = result.get("counts", {})
    log.info("Filter counts: %s", json.dumps(counts))
    log.info(
        "Wrote %d candidate(s) to %s using %s data",
        len(result.get("candidates", [])),
        out_path,
        result.get("market_data_type_label"),
    )
    for candidate in result.get("candidates", [])[:5]:
        log.info(
            "  %-6s gain %6s%%  rel vol %5s  last %8s  range %s to %s",
            candidate["symbol"],
            candidate["gain_pct"],
            candidate["rel_volume"],
            candidate["last"],
            candidate["opening_range_low"],
            candidate["opening_range_high"],
        )
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

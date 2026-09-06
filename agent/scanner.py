#!/usr/bin/env python3
"""Opening-momentum scanner for the agentic trading project.

Asks IB Gateway which US stocks and ETFs are moving hard and trading unusually
heavily, checks each one against the strategy's rules, and writes a shortlist of
at most twenty names to a JSON file, ranked by relative volume with the heaviest
first. Claude reads that file at 9:35 AM and decides which names, if any, are
worth trading. Both directions: a name whose first five minute candle closed
above where it opened is a long candidate, one that closed below is a short
candidate, and one that opened and closed at the same price is no trade at all.

WE DO NOT TRUST IBKR'S SCANNER FILTERS (Mo, 2026-09-06)
-------------------------------------------------------
On this account every scanner filter we tried, priceAbove, stVolume5MinAbove,
marketCapAbove and volumeAbove, made the scan return ZERO rows while Gateway
quietly logged error 162, "Scanner filter X is disabled", followed by 365 on the
same request. Nothing raised. An unfiltered scan of the same code returned 50
rows in under a second. So a filtered scan on this account looks exactly like a
morning when nothing gapped, and a loop that believed it would sit idle for a
month and never know why.

So this script sends NO filters to Gateway, ever. Every scan is unfiltered, and
every rule in docs/STRATEGY.md is applied here in our own code against real
daily bars: the 5 dollar price floor, the 20 million dollar liquidity floor, the
30 session history requirement, the volatility floor of a 14 day average true
range above 50 cents and above 1.5 percent of price, the 2 times relative volume
floor at 09:35, the US listing test, the leveraged and inverse fund test and the
hard exclusions on SPACs, warrants, rights and preferred shares. Filters that
are checked here cannot be silently switched off by a subscription we do not
have.

Every scan also goes through agent/scan_truth.py before its rows are believed:
errors are captured against the scan's own request id, an unfiltered control
scan has to come back with real rows, and the end-of-scan signal has to arrive
inside the timeout. A scan that fails any of those raises ScanFailure, and this
script then exits 3 and writes nothing, leaving yesterday's shortlist where it
is. An empty shortlist and a broken scanner must never look the same.

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

Exit codes:
    0   the scan ran and was believed, even if nothing survived the filters
    1   the Gateway connection itself failed
    3   a scan could not be trusted (ScanFailure). Nothing was written
"""

# THE FINVIZ CROSS-CHECK WAS REMOVED ON 2026-09-06, ON PURPOSE
# ------------------------------------------------------------
# This file used to be able to fetch a Finviz Elite CSV export and fold those
# tickers into the union as a second opinion on what had gapped. Mo decided not
# to buy Finviz Elite (39.50 dollars a month), so decision D7 of
# research/momentum_spec_critique_2026-09-06.md took the whole path out: the
# settings, the download, the CSV reader and the "finviz" tag. It was deleted
# rather than left switched off, because a dead code path that talks to the
# network is a thing somebody eventually turns on by accident. This note is here
# so nobody puts it back thinking its absence was an oversight. IBKR's own four
# scans plus the control scan are the whole source of names now.

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

from ib_async import IB, ScannerSubscription, Stock, TagValue

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GUARDRAILS_PATH = PROJECT_ROOT / "config" / "guardrails.yaml"

# The project folder goes on the import path so that "agent.scan_truth" means the
# same module here as it does in the tests. Importing it as a bare "scan_truth"
# instead would make a second copy of the class, and an "except ScanFailure" in
# one copy would not catch a ScanFailure raised by the other.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.scan_truth import (  # noqa: E402
    DEFAULT_TIMEOUT_S,
    ErrorCapture,
    ScanFailure,
    ScanResult,
    assert_trustworthy,
    run_scan_async,
)

try:
    import yaml
except ImportError:  # pragma: no cover - pyyaml is in requirements-312.txt
    yaml = None

#: What the CLI returns when a scan could not be trusted. Distinct from 1, which
#: is a connection failure, so the pre-flight can tell the two apart and say so.
EXIT_SCAN_FAILURE = 3

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

# THE VOLATILITY FLOOR (change A3, approved 2026-09-06)
# -----------------------------------------------------
# A name has to actually move enough in a normal day for a five minute breakout
# to mean anything. The measure is the average true range over the last 14
# completed sessions, which is the average of how far the stock travelled in a
# session, and a candidate has to clear BOTH halves of the floor: at least 50
# cents of daily range, and at least 1.5 percent of its own price.
#
# Both halves are needed because either one alone lets the wrong names through.
# 50 cents on a 400 dollar stock is dead quiet, so the percentage catches that.
# 1.5 percent of a 6 dollar stock is 9 cents, which is inside the spread, so the
# dollar floor catches that. Without this filter the shortlist fills up with
# large, quiet names whose whole five minute range is noise.
DEFAULT_ATR_DAYS = 14
DEFAULT_MIN_ATR_USD = 0.50
DEFAULT_MIN_ATR_PCT_OF_PRICE = 1.5

# Written into the output for the record, not used for arithmetic in this file.
# The published edge ranks names by the volume traded between 9:30 and 9:35
# against the same five minutes over the prior 14 sessions. That true
# measurement is built from streaming ticks by
# /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/preopen.py.
# This scanner's own relative volume is the same idea measured from daily bars,
# which is the fallback for a morning when the pre-open run did not happen.
DEFAULT_REL_VOLUME_WINDOW = "09:30-09:35"
DEFAULT_REL_VOLUME_BASELINE_DAYS = 14

# THE HARD EXCLUSIONS (change A12, approved 2026-09-06)
# -----------------------------------------------------
# Names that get dropped before the model ever sees them, because they are
# structurally not what this strategy trades: leveraged and inverse funds, blank
# cheque companies (SPACs), warrants, rights, preferred shares, anything not
# listed on a US venue, and anything in a trading halt.
#
# Deliberately NOT on this list: any rule about how recently a name listed. Mo
# rejected the 90 day listing age rule. What replaced it is a demand for enough
# history to measure the name at all, which is min_history_sessions below (the
# 30 completed sessions the dollar volume average needs) together with the 14
# sessions the average true range needs. A name that has traded long enough to
# be measured has traded long enough to be traded.
DEFAULT_EXCLUDE_SPACS = True
DEFAULT_EXCLUDE_WARRANTS_AND_RIGHTS = True
DEFAULT_EXCLUDE_PREFERRED = True
DEFAULT_REQUIRE_US_PRIMARY_LISTING = True
DEFAULT_EXCLUDE_HALTED = True
DEFAULT_MIN_HISTORY_SESSIONS = 30

# The relative volume test is anchored at 9:35 AM Eastern, five minutes after
# the open. That is the moment the strategy makes its picks, and Mo's rule of
# 2026-09-06 is about that moment: the volume traded by 9:35 has to be at least
# twice the stock's normal pace for that point in the day. Written down as a
# real time rather than left implicit in whenever the script happens to run.
REL_VOLUME_ANCHOR_HOUR, REL_VOLUME_ANCHOR_MINUTE = 9, 35
REL_VOLUME_ANCHOR_LABEL = "09:35"
REL_VOLUME_ANCHOR_MINUTES = 5.0

# THE PACING BUDGET, WORKED OUT IN FULL
# -------------------------------------
# Gateway rations requests to roughly sixty in any ten minutes, counted across
# the whole connection, and going over gets everything on that connection
# throttled, not just this script. Since 2026-09-06 the run makes five scanner
# requests rather than two, so the arithmetic was redone:
#
#      5   scanner requests: TOP_PERC_GAIN, TOP_PERC_LOSE, HOT_BY_VOLUME,
#          HIGH_STVOLUME_5MIN, plus the unfiltered control scan
#     55   left over for historical data, which is HISTORY_REQUEST_BUDGET
#      1   SPY reference bars, to see how far today's data actually reaches
#     35   daily bars, one per enriched name, which is ENRICHMENT_CAP
#     19   opening ranges left, against a shortlist that can hold twenty
#   ----
#     60   the whole ration
#
# So the only way to run out is for all 35 enriched names to survive every
# filter and fill a shortlist of twenty, in which case the twentieth name loses
# its opening range and the run says so in its warnings rather than quietly
# publishing a name with no entry trigger. A normal run spends about 45, because
# the filters thin the shortlist well below twenty.
#
# The enrichment cap came down from 40 to 35 to pay for the three extra scans.
# The names that lose their place are the lowest ranked across all four scans,
# which are the ones least likely to have survived anyway.
SCANNER_REQUESTS_PER_RUN = 5
ENRICHMENT_CAP = 35
HISTORY_REQUEST_BUDGET = 55
HISTORY_CONCURRENCY = 4
HISTORY_MIN_GAP_SECONDS = 0.25
TOTAL_REQUEST_RATION = 60

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

SCAN_INSTRUMENT = "STK"
SCAN_LOCATION = "STK.US.MAJOR"
SCAN_ROWS = 50
SCAN_TIMEOUT_S = DEFAULT_TIMEOUT_S

DIRECTION_LONG = "long"
DIRECTION_SHORT = "short"

# Scan codes we will never ask for, and why. TOP_OPEN_PERC_GAIN and its mirror
# sound like exactly what a 9:35 gap scan wants, but IBKR staff confirmed they
# return nothing before the regular session is properly under way, so they hand
# back an empty list at the one moment we care about. TOP_PERC_GAIN is the code
# that actually answers at 9:35. A test asserts these never appear in a request.
FORBIDDEN_SCAN_CODES = frozenset({"TOP_OPEN_PERC_GAIN", "TOP_OPEN_PERC_LOSE"})


@dataclass(frozen=True)
class ScanSpec:
    """One scan we ask Gateway for, and what a hit on it means.

    direction is "long" for a list of gainers, "short" for a list of fallers,
    and None for a volume list, which says a name is busy without saying which
    way it is going. A name flagged only by a volume scan takes its direction
    from the sign of its own move once the daily bars are in.
    """

    code: str
    direction: str | None
    label: str


# Confirmed present on this Gateway on 2026-09-06 by reading ib.reqScannerParameters(),
# which listed 527 scan codes including all four of these.
SCAN_SPECS = (
    ScanSpec("TOP_PERC_GAIN", DIRECTION_LONG, "IBKR's biggest percentage gainers list"),
    ScanSpec("TOP_PERC_LOSE", DIRECTION_SHORT, "IBKR's biggest percentage fallers list"),
    ScanSpec("HOT_BY_VOLUME", None, "IBKR's unusually heavy volume list"),
    ScanSpec("HIGH_STVOLUME_5MIN", None,
             "IBKR's heaviest five minute volume list"),
)
SCAN_CODES = tuple(spec.code for spec in SCAN_SPECS)

# The control scan. It has no filters, like all the others, and it exists only to
# answer one question: is the scanner service actually answering this account? The
# market is never empty, so a control that comes back with fewer than twenty rows
# means the scan results cannot be believed, whatever the other four returned.
CONTROL_SCAN_CODE = "MOST_ACTIVE"

# Plain-English labels for the scan codes, for the "reasons" field.
SCAN_CODE_LABELS = {spec.code: spec.label for spec in SCAN_SPECS}
SCAN_CODE_LABELS[CONTROL_SCAN_CODE] = "IBKR's most active list (the control scan)"

# Sending a forbidden code would be a silent nothing at 9:35, so refuse at import.
assert not (set(SCAN_CODES) | {CONTROL_SCAN_CODE}) & FORBIDDEN_SCAN_CODES, (
    "a forbidden scan code is in SCAN_SPECS or CONTROL_SCAN_CODE"
)

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

# ---------------------------------------------------------------------------
# What each hard exclusion looks like in the words IBKR gives us
# ---------------------------------------------------------------------------
#
# All we get from a contract details lookup is the ticker, the company or fund's
# full name, and IBKR's own stock type. So every test below is built out of
# those three things and nothing else. Each one is a separate small function so
# it can be read on its own and tested on its own.

# A blank cheque company: a shell that raised money to buy a business it has not
# named yet. Almost all of them are called "<Something> Acquisition Corp".
SPAC_NAME_PHRASES = ("ACQUISITION CORP", "ACQUISITION CO", "ACQUISITION HOLDINGS")
SPAC_WORD = re.compile(r"\bSPAC\b")

# A warrant is a right to buy the share later. It trades separately, it is far
# thinner than the share, and it is not what this strategy is buying.
WARRANT_NAME_PHRASES = (" WARRANT", "WARRANTS")
WARRANT_STOCK_TYPES = frozenset({"WAR", "WARRANT", "WARRANTS"})
# Ticker shapes. The ones with a separator in them (BRK.WS, ABC-WS, ABC+) are
# unambiguous, so they count on their own. A bare trailing W is different: it is
# the NASDAQ convention of a fifth letter bolted onto a four letter root, so it
# only counts on a five character ticker. Reading a bare trailing W on any
# length of ticker would throw out Lowe's (LOW), Dow (DOW) and Corning (GLW),
# which are ordinary companies, every single morning.
WARRANT_SUFFIXES_WITH_SEPARATOR = (".WS", "-WS", "/WS", ".W", "-W", "/W", "+")
WARRANT_BARE_SUFFIX_LENGTHS = {"W": 5, "WS": 6}

# A right is a short lived entitlement handed to existing holders. Same story as
# a warrant: separate, thin, not the share itself.
RIGHT_SUFFIXES = (".RT", "-RT", "/RT", "RT", "R")
RIGHT_NAME_PHRASE = " RIGHT"

# Preferred shares behave like bonds. They do not gap and run with the market.
PREFERRED_NAME_PHRASES = (" PREFERRED", " PFD", "PREF SHS")
PREFERRED_STOCK_TYPES = frozenset({"PREFERRED", "PFD"})
# BAC.PRK and BAC-PRB are preferred lines of Bank of America. The separator is
# what makes this safe: plain "PR" inside a ticker would catch PRU (Prudential).
PREFERRED_TICKER_PATTERN = re.compile(r"[.\-/]PR")

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

    The atr_ fields are the volatility floor of change A3, and the exclude_ and
    require_ fields are the hard exclusions of change A12, both approved by Mo
    on 2026-09-06. min_history_sessions is what replaced the rejected rule about
    how recently a name listed.
    """

    price_floor: float = DEFAULT_PRICE_FLOOR
    min_avg_dollar_volume: float = DEFAULT_MIN_AVG_DOLLAR_VOLUME
    dollar_volume_sessions: int = DEFAULT_DOLLAR_VOLUME_SESSIONS
    rel_volume_min: float = DEFAULT_REL_VOLUME_MIN
    max_candidates: int = DEFAULT_MAX_CANDIDATES
    atr_days: int = DEFAULT_ATR_DAYS
    min_atr_usd: float = DEFAULT_MIN_ATR_USD
    min_atr_pct_of_price: float = DEFAULT_MIN_ATR_PCT_OF_PRICE
    #: Written into the output for the record only. The real 9:30 to 9:35
    #: measurement against the prior 14 days is built by agent/preopen.py from
    #: streaming ticks; nothing in this file does arithmetic with these two.
    rel_volume_window: str = DEFAULT_REL_VOLUME_WINDOW
    rel_volume_baseline_days: int = DEFAULT_REL_VOLUME_BASELINE_DAYS
    exclude_spacs: bool = DEFAULT_EXCLUDE_SPACS
    exclude_warrants_and_rights: bool = DEFAULT_EXCLUDE_WARRANTS_AND_RIGHTS
    exclude_preferred: bool = DEFAULT_EXCLUDE_PREFERRED
    require_us_primary_listing: bool = DEFAULT_REQUIRE_US_PRIMARY_LISTING
    exclude_halted: bool = DEFAULT_EXCLUDE_HALTED
    min_history_sessions: int = DEFAULT_MIN_HISTORY_SESSIONS
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
            "rel_volume_window": self.rel_volume_window,
            "rel_volume_baseline_days": self.rel_volume_baseline_days,
            "max_candidates": self.max_candidates,
            "atr_days": self.atr_days,
            "min_atr_usd": self.min_atr_usd,
            "min_atr_pct_of_price": self.min_atr_pct_of_price,
            "exclude_spacs": self.exclude_spacs,
            "exclude_warrants_and_rights": self.exclude_warrants_and_rights,
            "exclude_preferred": self.exclude_preferred,
            "require_us_primary_listing": self.require_us_primary_listing,
            "exclude_halted": self.exclude_halted,
            "min_history_sessions": self.min_history_sessions,
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

    def pick_flag(section: dict[str, Any], key: str, current: bool) -> bool:
        """A yes or no switch. Written out in words, so "no" has to mean no.

        YAML already turns true and false into real booleans, but somebody
        editing the file by hand may well write "off" or "no", and bool("no") is
        True in Python, which would silently turn a switch back on.
        """
        value = section.get(key)
        if value is None:
            return current
        if isinstance(value, str):
            text = value.strip().lower()
            if text in {"true", "yes", "on", "1"}:
                return True
            if text in {"false", "no", "off", "0"}:
                return False
            log.warning("Ignoring bad value for %s in %s: %r", key, path, value)
            return current
        return bool(value)

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

    # The volatility floor (change A3). All three live under universe:.
    thresholds.atr_days = int(
        pick(universe, "atr_days", thresholds.atr_days, int)
    )
    if thresholds.atr_days < 1:
        log.warning(
            "An average true range over %d session(s) means nothing, using %d",
            thresholds.atr_days,
            DEFAULT_ATR_DAYS,
        )
        thresholds.atr_days = DEFAULT_ATR_DAYS
    thresholds.min_atr_usd = pick(
        universe, "min_atr_usd", thresholds.min_atr_usd, float
    )
    thresholds.min_atr_pct_of_price = pick(
        universe, "min_atr_pct_of_price", thresholds.min_atr_pct_of_price, float
    )

    # Read for the record, not used for arithmetic here. See agent/preopen.py.
    value = scanner.get("rel_volume_window")
    if value is not None:
        thresholds.rel_volume_window = str(value).strip()
    thresholds.rel_volume_baseline_days = int(
        pick(
            scanner,
            "rel_volume_baseline_days",
            thresholds.rel_volume_baseline_days,
            int,
        )
    )

    # The hard exclusions (change A12). All under universe:, all on by default.
    thresholds.exclude_spacs = pick_flag(
        universe, "exclude_spacs", thresholds.exclude_spacs)
    thresholds.exclude_warrants_and_rights = pick_flag(
        universe, "exclude_warrants_and_rights",
        thresholds.exclude_warrants_and_rights)
    thresholds.exclude_preferred = pick_flag(
        universe, "exclude_preferred", thresholds.exclude_preferred)
    thresholds.require_us_primary_listing = pick_flag(
        universe, "require_us_primary_listing",
        thresholds.require_us_primary_listing)
    thresholds.exclude_halted = pick_flag(
        universe, "exclude_halted", thresholds.exclude_halted)
    thresholds.min_history_sessions = int(
        pick(
            universe,
            "min_history_sessions",
            thresholds.min_history_sessions,
            int,
        )
    )

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
    #: What industry IBKR says this name is in. The sector cap in
    #: agent/guardrails.py counts gross exposure per industry against 25 percent
    #: of the book, and it refuses an entry outright when nobody can say what
    #: industry a name is in, so an empty string here means the name cannot be
    #: traded. Always a string, never None, so the check has one thing to read.
    sector: str = ""
    #: IBKR's finer grain under the industry. Nothing filters on these two; they
    #: are in the shortlist so the month end review can group trades properly.
    category: str = ""
    subcategory: str = ""
    flagged_by: list[str] = field(default_factory=list)

    #: "long" from a gainers scan, "short" from a fallers scan, and for a name
    #: only ever seen on a volume scan it is filled in from the sign of its own
    #: move once the daily bars are in. Never None by the time it is written out.
    direction: str | None = None
    #: The directions the scans themselves implied, before the move decided it.
    directions_flagged: list[str] = field(default_factory=list)
    #: Best place this name took on any scan, 0 being the top of a list. Used to
    #: decide which names are worth spending a data request on.
    scan_rank: int | None = None

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
    #: How many completed daily sessions of history this name actually has. The
    #: hard exclusions demand at least min_history_sessions of them.
    completed_sessions: int | None = None
    #: The average true range: how far this name travels in a normal session,
    #: in dollars, over the last atr_days completed sessions. None means it
    #: could not be worked out, which fails the volatility floor.
    atr: float | None = None
    atr_days_used: int | None = None
    atr_pct_of_price: float | None = None
    opening_range_high: float | None = None
    opening_range_low: float | None = None
    #: The open and close of the 9:30 to 9:35 candle itself. The sign of this
    #: candle is what decides long or short (change A5), so it is published.
    opening_range_open: float | None = None
    opening_range_close: float | None = None
    score: float = 0.0
    #: Where this name came on the shortlist, 1 being the heaviest relative
    #: volume. Filled in once the sort has happened.
    rank: int | None = None
    reasons: list[str] = field(default_factory=list)

    def contract(self) -> Stock:
        stock = Stock(self.symbol, "SMART", "USD")
        # Every name now arrives from an IBKR scan, so it always has a contract
        # id. Setting conId to 0 would make Gateway look for contract zero
        # instead of looking the ticker up, so an empty id is left unset.
        if self.con_id:
            stock.conId = self.con_id
        if self.primary_exchange:
            stock.primaryExchange = self.primary_exchange
        return stock

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "conId": self.con_id,
            "primaryExchange": self.primary_exchange,
            # Both spellings on purpose. agent/decide.py reads "side" or
            # "direction", and agent/loop.py reads "side", so writing both means
            # a short is never quietly read as a long by whichever reads it next.
            "direction": self.direction,
            "side": self.direction,
            "last": round2(self.last),
            "gain_pct": round2(self.gain_pct),
            "opening_range_high": round2(self.opening_range_high),
            "opening_range_low": round2(self.opening_range_low),
            "opening_range_open": round2(self.opening_range_open),
            "opening_range_close": round2(self.opening_range_close),
            "volume_today": to_int(self.volume_today),
            "avg_volume_20d": to_int(self.avg_volume_20d),
            "avg_dollar_volume": to_int(self.avg_dollar_volume),
            "avg_dollar_volume_sessions": self.avg_dollar_volume_sessions,
            "completed_sessions": self.completed_sessions,
            "atr": round2(self.atr),
            "atr_days_used": self.atr_days_used,
            "atr_pct_of_price": round2(self.atr_pct_of_price),
            "rel_volume": round2(self.rel_volume),
            "rel_volume_minutes_elapsed": round2(self.rel_volume_minutes_elapsed),
            "flagged_by": list(self.flagged_by),
            "scan_rank": self.scan_rank,
            "rank": self.rank,
            "reasons": list(self.reasons),
            "score": round2(self.score),
            "long_name": self.long_name,
            "stock_type": self.stock_type,
            "sector": self.sector,
            "category": self.category,
            "subcategory": self.subcategory,
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
# The hard exclusions (change A12)
# ---------------------------------------------------------------------------
#
# Each of these takes the three things IBKR's contract details actually give us
# and answers one question: is this the kind of listing we refuse to trade? A
# sentence comes back saying why, or None meaning it is fine. Separate functions
# on purpose, so each one can be read and tested on its own.


def spac_reason(symbol: str, long_name: str, stock_type: str) -> str | None:
    """Is this a blank cheque company, a SPAC?

    A SPAC is a shell that has raised money to buy some business it has not
    named yet. Its price moves on rumours about a deal, not on trading momentum,
    and it is one of the traps the red team ranked as a top source of loss.
    Nearly all of them are named "<Something> Acquisition Corp".

    SPAC is matched as a whole word so that SPACE and SPACEX are left alone.
    """
    name = (long_name or "").upper()
    if not name:
        return None
    for phrase in SPAC_NAME_PHRASES:
        if phrase in name:
            return f'looks like a SPAC, its name contains "{phrase.title()}"'
    if SPAC_WORD.search(name):
        return 'looks like a SPAC, its name contains the word "SPAC"'
    return None


def warrant_reason(symbol: str, long_name: str, stock_type: str) -> str | None:
    """Is this a warrant rather than the share itself?

    Three separate signals, any one of which is enough: IBKR's own stock type,
    the word warrant in the full name, and the ticker shape.

    The ticker shape needs care. BRK.WS and ABC+ are unmistakable because of the
    separator. A bare trailing W is not: it only means a warrant in the NASDAQ
    convention of a fifth letter bolted onto a four letter root, so it is only
    read that way on a five character ticker. Reading a trailing W on any ticker
    would throw out Lowe's (LOW), Dow (DOW) and Corning (GLW) every morning,
    which is exactly the mistake the rights rule below warns about.
    """
    if (stock_type or "").strip().upper() in WARRANT_STOCK_TYPES:
        return "IBKR calls it a warrant"
    name = (long_name or "").upper()
    for phrase in WARRANT_NAME_PHRASES:
        if phrase in name:
            return "the name says it is a warrant, not the share"
    ticker = (symbol or "").strip().upper()
    for suffix in WARRANT_SUFFIXES_WITH_SEPARATOR:
        if ticker.endswith(suffix) and len(ticker) > len(suffix):
            return f'the ticker ends in "{suffix}", which is a warrant line'
    for suffix, exact_length in WARRANT_BARE_SUFFIX_LENGTHS.items():
        if len(ticker) == exact_length and ticker.endswith(suffix):
            return (
                f'the ticker is {exact_length} characters ending in "{suffix}", '
                "which is how NASDAQ writes a warrant"
            )
    return None


def right_reason(symbol: str, long_name: str, stock_type: str) -> str | None:
    """Is this a rights line rather than the share itself?

    A right is a short lived entitlement handed to existing holders. It trades
    separately and thinly, like a warrant.

    The ticker suffix alone is NOT enough here and never will be. Plenty of
    ordinary companies have tickers ending in R, so dropping on the letter alone
    would throw out real businesses. The full name has to say "right" as well,
    and only then is the name dropped.
    """
    name = (long_name or "").upper()
    says_right = " RIGHT" in name or name.startswith("RIGHT")
    if not says_right:
        return None
    ticker = (symbol or "").strip().upper()
    for suffix in RIGHT_SUFFIXES:
        if ticker.endswith(suffix) and len(ticker) > len(suffix):
            return (
                f'the name says rights and the ticker ends in "{suffix}", so this '
                "is the rights line, not the share"
            )
    return None


def preferred_reason(symbol: str, long_name: str, stock_type: str) -> str | None:
    """Is this a preferred share?

    Preferred shares pay a fixed dividend and behave far more like bonds than
    like the ordinary stock. They do not gap and run, so they are not what this
    strategy is looking for.

    The ticker test wants a separator in front of the PR, as in BAC.PRK or
    BAC-PRB. Looking for a plain PR anywhere in a ticker would catch PRU,
    Prudential, which is an ordinary company.
    """
    if (stock_type or "").strip().upper() in PREFERRED_STOCK_TYPES:
        return "IBKR calls it a preferred share"
    name = (long_name or "").upper()
    for phrase in PREFERRED_NAME_PHRASES:
        if phrase in name:
            return "the name says it is a preferred share"
    if PREFERRED_TICKER_PATTERN.search((symbol or "").strip().upper()):
        return "the ticker is a preferred line, not the ordinary share"
    return None


def halt_flag_from_details(detail: Any) -> bool | None:
    """What IBKR's contract details say about a trading halt.

    Which on this account today is nothing at all. Contract details carry no
    halt field, so this looks for one on the detail and on the contract inside
    it and returns None when there is none to find. None means "not known", not
    "not halted", and the run says so in its warnings rather than pretending it
    checked. The halt check that really runs is on the order path, in
    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/guardrails.py
    under rule id `halted`, which reads IBKR's tick type 49.
    """
    for holder in (detail, getattr(detail, "contract", None)):
        if holder is None:
            continue
        value = getattr(holder, "halted", None)
        if value is None:
            continue
        if isinstance(value, bool):
            return value
        try:
            # Tick type 49 is a number: 0 is trading, 1 and 2 are halted.
            return float(value) > 0
        except (TypeError, ValueError):
            return bool(value)
    return None


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


def true_range(bar: Any, previous_close: float | None) -> float | None:
    """How far one session actually travelled, in dollars.

    Not simply high minus low, because that misses the gap. A stock that closed
    at 20 and opened at 24 and then traded between 24 and 25 only has a one
    dollar high-to-low range, but anyone holding it overnight lived through a
    five dollar move. So the true range is the largest of three numbers:

        high minus low
        the distance from the high to yesterday's close
        the distance from the low to yesterday's close

    None comes back when the bar has no usable high or low, or when there is no
    previous close to measure the gap against.
    """
    high = getattr(bar, "high", None)
    low = getattr(bar, "low", None)
    if high is None or low is None or previous_close is None:
        return None
    try:
        high = float(high)
        low = float(low)
        previous_close = float(previous_close)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(high) and math.isfinite(low)
            and math.isfinite(previous_close)):
        return None
    if high <= 0 or low <= 0 or previous_close <= 0 or high < low:
        return None
    return max(
        high - low,
        abs(high - previous_close),
        abs(low - previous_close),
    )


def average_true_range(
    bars: list[Any], days: int = DEFAULT_ATR_DAYS
) -> tuple[float | None, int]:
    """The average true range: how far this name moves in a normal session.

    Hand in completed daily bars, oldest first, with today's part-formed bar
    already taken out. The answer is the plain mean of the true ranges of the
    last `days` sessions, in dollars, and how many sessions that mean used.

    The very first bar in the list can only ever be a previous close for the
    second one, because a true range needs the session before it to measure the
    gap against. So a run of 15 bars yields 14 true ranges.

    Fewer than `days` usable true ranges gets None back along with however many
    there were. None fails the volatility floor, which is the safe answer: a
    name we cannot measure is a name we should not trade.
    """
    if days < 1:
        raise ValueError(
            f"average_true_range was asked for {days} days, and it needs at least one."
        )
    ranges: list[float] = []
    previous_close: float | None = None
    for bar in bars:
        value = true_range(bar, previous_close)
        if value is not None:
            ranges.append(value)
        close = getattr(bar, "close", None)
        try:
            close = float(close) if close is not None else None
        except (TypeError, ValueError):
            close = None
        if close is not None and math.isfinite(close) and close > 0:
            previous_close = close
    recent = ranges[-days:]
    if len(recent) < days:
        return None, len(recent)
    return sum(recent) / len(recent), len(recent)


def direction_from_candle(
    open_price: float | None, close_price: float | None
) -> str | None:
    """Which way the 9:30 to 9:35 candle points, which is the entry rule (A5).

    The published strategy takes its side from the sign of that first five
    minute candle and nothing else: closed above where it opened, go long;
    closed below, go short; opened and closed at exactly the same price, do not
    trade it at all. A flat candle is a genuine no, not a shrug, so None here
    means the name is dropped rather than guessed at.

    None also comes back when either price is missing, for the same reason.
    """
    if open_price is None or close_price is None:
        return None
    try:
        open_price = float(open_price)
        close_price = float(close_price)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(open_price) and math.isfinite(close_price)):
        return None
    if close_price > open_price:
        return DIRECTION_LONG
    if close_price < open_price:
        return DIRECTION_SHORT
    return None


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
        self.scan_diagnostics: dict[str, dict[str, Any]] = {}
        self.scanner_requests = 0
        #: What IBKR's contract details said about a halt, per symbol, when they
        #: said anything at all. Empty means nothing was on offer, which is the
        #: normal state on this account and is reported in the warnings.
        self.halt_flags: dict[str, bool] = {}

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

    def make_subscription(self, scan_code: str) -> ScannerSubscription:
        """One scanner request, with no filters on it whatsoever.

        Deliberately no abovePrice, no aboveVolume, no marketCapAbove. Every
        filter tag we tried on this account made Gateway return zero rows and
        log "Scanner filter X is disabled" into a callback, which is
        indistinguishable from a quiet morning. Whatever we ask Gateway to
        filter on, it can decline to filter on without telling us. So we ask for
        the raw list and do the filtering here, where nothing can switch it off.
        """
        if scan_code in FORBIDDEN_SCAN_CODES:
            raise ValueError(
                f"{scan_code} returns nothing before the session is under way, "
                "which is the one moment this scanner runs. Use TOP_PERC_GAIN."
            )
        return ScannerSubscription(
            instrument=SCAN_INSTRUMENT,
            locationCode=SCAN_LOCATION,
            scanCode=scan_code,
            numberOfRows=SCAN_ROWS,
        )

    def record_scan(self, result: ScanResult, role: str,
                    direction: str | None = None) -> None:
        """Write one scan's own numbers into the diagnostics block."""
        self.scanner_requests += 1
        self.scan_diagnostics[result.scan_code] = {
            "role": role,
            "direction": direction,
            "rows": len(result.rows),
            "elapsed_s": round(result.elapsed_s, 3),
            "completed": result.completed,
            "req_id": result.req_id,
            "filters": [{"tag": tag, "value": value} for tag, value in result.filters],
            "errors": [{"code": code, "message": message}
                       for code, message in result.errors],
        }
        log.info(
            "Scan %s (%s) returned %d rows in %.2fs%s",
            result.scan_code,
            role,
            len(result.rows),
            result.elapsed_s,
            f", errors {[c for c, _ in result.errors]}" if result.errors else "",
        )

    async def run_all_scans(self) -> list[tuple[ScanSpec, ScanResult]]:
        """Run the control scan and the four real ones, and believe none of them
        until agent/scan_truth.py says they can be believed.

        Sequential on purpose. ib_async hands out request ids from a counter, and
        reading that counter to know which errors belong to which scan only works
        while one request is in flight at a time. Five scans at well under a
        second each is a few seconds in total, which is a cheap price for knowing
        whose error is whose.

        Raises ScanFailure when any scan cannot be trusted. The caller turns that
        into exit code 3 and writes nothing.
        """
        capture = ErrorCapture(self.ib)
        try:
            control = await run_scan_async(
                self.ib, self.make_subscription(CONTROL_SCAN_CODE), [], capture,
                SCAN_TIMEOUT_S)
            self.record_scan(control, "control")

            results: list[tuple[ScanSpec, ScanResult]] = []
            for spec in SCAN_SPECS:
                result = await run_scan_async(
                    self.ib, self.make_subscription(spec.code), [], capture,
                    SCAN_TIMEOUT_S)
                self.record_scan(result, "candidate source", spec.direction)
                results.append((spec, result))
        except ScanFailure:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ScanFailure(f"a scanner request blew up: {exc!r}") from exc
        finally:
            capture.close()

        # Judge every scan against the same control. The first one that cannot be
        # believed stops the run, because a shortlist built from part of a broken
        # set of scans is worse than no shortlist at all.
        for _, result in results:
            assert_trustworthy(result, control)
        return results

    async def collect_candidates(self) -> list[Candidate]:
        """Run every scan, merge the results, and tag each name long or short.

        Merging takes turns down the four lists rather than stacking them. That
        matters: stacking would let the enrichment cap chop the last scan off
        entirely, so we would only ever look at the biggest gainers and never at
        the fallers or the heavy volume names. Alternating keeps the top of all
        four, and anything more than one scan flagged floats to the front,
        because two scans agreeing is a stronger signal than one.

        Keyed on the ticker purely so that the same name showing up on two of
        the four scans merges into one entry instead of two.
        """
        results = await self.run_all_scans()

        by_symbol: dict[str, Candidate] = {}
        per_scan: list[list[str]] = []
        for spec, result in results:
            self.counts[f"scanned_{spec.code.lower()}"] = len(result.rows)
            ranked: list[str] = []
            for position, row in enumerate(result.rows):
                contract = getattr(
                    getattr(row, "contractDetails", None), "contract", None)
                if contract is None or not contract.symbol:
                    continue
                symbol = str(contract.symbol).upper()
                candidate = by_symbol.get(symbol)
                if candidate is None:
                    candidate = Candidate(
                        symbol=symbol,
                        con_id=int(getattr(contract, "conId", 0) or 0),
                        primary_exchange=contract.primaryExchange or "",
                        currency=contract.currency or "",
                    )
                    by_symbol[symbol] = candidate
                if spec.code not in candidate.flagged_by:
                    candidate.flagged_by.append(spec.code)
                rank = int(getattr(row, "rank", position) or position)
                if candidate.scan_rank is None or rank < candidate.scan_rank:
                    candidate.scan_rank = rank
                if spec.direction and spec.direction not in candidate.directions_flagged:
                    candidate.directions_flagged.append(spec.direction)
                ranked.append(symbol)
            per_scan.append(ranked)

        # Names more than one source flagged go first, in their best rank order,
        # then take turns down the lists.
        many = sorted(
            (symbol for symbol, c in by_symbol.items() if len(c.flagged_by) > 1),
            key=lambda s: (by_symbol[s].scan_rank if by_symbol[s].scan_rank is not None
                           else SCAN_ROWS),
        )
        order: list[str] = list(many)
        seen = set(many)
        for position in range(max((len(r) for r in per_scan), default=0)):
            for ranked in per_scan:
                if position < len(ranked) and ranked[position] not in seen:
                    seen.add(ranked[position])
                    order.append(ranked[position])
        return [by_symbol[symbol] for symbol in order]

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
        """Fill in price, gain, today's volume, the two averages and the ATR.

        Two averages, because they answer two different questions. The dollar
        volume average over 30 sessions says whether the name is liquid enough
        to trade at all, which is Mo's floor of 20 million dollars a day. The
        share volume average over 20 sessions is the bottom half of the relative
        volume ratio, which is shares against shares and so has to stay in
        shares.

        The average true range comes off the same bars, so it costs no extra
        data request. It says how far this name travels in a normal session,
        which is the volatility floor of change A3.
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

        candidate.completed_sessions = len(completed)

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

            # The volatility floor: how far the name moves in a normal session.
            candidate.atr, candidate.atr_days_used = average_true_range(
                completed, self.thresholds.atr_days
            )
            if candidate.atr is None:
                # Not enough sessions to measure the range. Leaving this empty
                # makes the name fail the volatility floor, which is the safe
                # answer: a name we cannot measure is one we should not trade.
                log.debug(
                    "%s has only %d usable session range(s), too few for an ATR",
                    candidate.symbol,
                    candidate.atr_days_used or 0,
                )

        if candidate.last is not None and candidate.prev_close:
            candidate.gain_pct = (
                (candidate.last - candidate.prev_close) / candidate.prev_close * 100.0
            )

        # The same range said as a share of the price, which is the second half
        # of the volatility floor. Measured against the current price where
        # there is one, and yesterday's close otherwise.
        price = candidate.last or candidate.prev_close
        if candidate.atr is not None and price:
            candidate.atr_pct_of_price = candidate.atr / float(price) * 100.0

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
        # What industry this name is in, for the sector cap in
        # agent/guardrails.py. IBKR names the same idea three ways and does not
        # always fill all three in, so take the first one that actually says
        # something: industry, then category, then subcategory. getattr with a
        # default because the pinned ib_async may not carry all three fields.
        candidate.category = str(getattr(detail, "category", "") or "").strip()
        candidate.subcategory = str(getattr(detail, "subcategory", "") or "").strip()
        industry = str(getattr(detail, "industry", "") or "").strip()
        candidate.sector = industry or candidate.category or candidate.subcategory
        candidate.primary_exchange = (
            detail.contract.primaryExchange or candidate.primary_exchange or ""
        )
        candidate.currency = detail.contract.currency or candidate.currency
        candidate.exchange = detail.contract.exchange or candidate.exchange
        # Contract details carry no halt field on this account, so this almost
        # always finds nothing and the run says so in its warnings. Nothing here
        # invents an answer: no field means not known, not "not halted".
        halted = halt_flag_from_details(detail)
        if halted is not None:
            self.halt_flags[candidate.symbol] = halted

    async def load_opening_range(self, candidate: Candidate) -> None:
        """Get the first five minutes of trading: high, low, open and close.

        The high and low are the entry trigger and one of the two candidates for
        the stop. The open and the close are what decides long or short under
        change A5, so they are recorded on the candidate and published.
        """
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
                self.record_opening_bar(candidate, bar)
                return
        moment, bar = todays_bars[0]
        self.record_opening_bar(candidate, bar)
        log.warning(
            "%s had no 9:30 bar, used today's first bar at %s instead",
            candidate.symbol,
            moment.strftime("%H:%M"),
        )

    @staticmethod
    def record_opening_bar(candidate: Candidate, bar: Any) -> None:
        """Copy one five minute bar onto the candidate, all four prices."""
        candidate.opening_range_high = float(bar.high)
        candidate.opening_range_low = float(bar.low)
        open_price = getattr(bar, "open", None)
        close_price = getattr(bar, "close", None)
        candidate.opening_range_open = (
            None if open_price is None else float(open_price)
        )
        candidate.opening_range_close = (
            None if close_price is None else float(close_price)
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

    def exclusion_verdict(self, candidate: Candidate) -> str | None:
        """The first reason to refuse this name outright, or None to keep it.

        Change A12, approved by Mo on 2026-09-06. These are structural refusals,
        made before the model ever sees the name: a SPAC, a warrant, a rights
        line or a preferred share is simply not the thing this strategy trades,
        whatever its price did this morning. Each switch can be turned off in
        config/guardrails.yaml, and all of them ship on.

        The leveraged and inverse fund test is separate and older, and it stays
        where it is in leverage_verdict.
        """
        symbol = candidate.symbol
        name = candidate.long_name
        stock_type = candidate.stock_type

        checks = []
        if self.thresholds.exclude_spacs:
            checks.append(spac_reason)
        if self.thresholds.exclude_warrants_and_rights:
            checks.append(warrant_reason)
            checks.append(right_reason)
        if self.thresholds.exclude_preferred:
            checks.append(preferred_reason)
        for check in checks:
            reason = check(symbol, name, stock_type)
            if reason:
                return reason

        if self.thresholds.exclude_halted and self.halt_flags.get(symbol):
            return "IBKR reported it as halted"
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
        if candidate.atr is not None:
            line = (
                f"Moves about {candidate.atr:.2f} dollars in a normal session, "
                f"averaged over {candidate.atr_days_used} sessions"
            )
            if candidate.atr_pct_of_price is not None:
                line += (
                    f", which is {candidate.atr_pct_of_price:.1f} percent of its "
                    f"price, against floors of {self.thresholds.min_atr_usd:.2f} "
                    f"dollars and {self.thresholds.min_atr_pct_of_price:.1f} percent"
                )
            reasons.append(line)
        if candidate.opening_range_high is not None and candidate.opening_range_low is not None:
            if candidate.direction == DIRECTION_SHORT:
                reasons.append(
                    f"First five minutes ranged {candidate.opening_range_low:.2f} to "
                    f"{candidate.opening_range_high:.2f} dollars, so a break below "
                    f"{candidate.opening_range_low:.2f} is the entry to watch on the "
                    "short side"
                )
            else:
                reasons.append(
                    f"First five minutes ranged {candidate.opening_range_low:.2f} to "
                    f"{candidate.opening_range_high:.2f} dollars, so a break above "
                    f"{candidate.opening_range_high:.2f} is the entry to watch"
                )
        if candidate.stock_type:
            reasons.append(f"Listed on {candidate.primary_exchange or 'a US venue'} as {candidate.stock_type.lower()}")
        if candidate.sector:
            reasons.append(
                f"IBKR puts it in the {candidate.sector} industry, which is what "
                "the sector cap counts against"
            )
        return reasons

    def resolve_direction(self, candidate: Candidate) -> str | None:
        """Long or short for one name, or None when nothing says which.

        A gainers scan says long, a fallers scan says short, and a volume scan
        says nothing about direction at all. So a name only ever seen on a volume
        scan takes its direction from the sign of its own move, and a name the
        scans disagree about does the same, because its own price is better
        evidence than a list it appeared on.
        """
        flagged = candidate.directions_flagged
        if len(flagged) == 1:
            return flagged[0]
        if candidate.gain_pct is None:
            return None
        if candidate.gain_pct > 0:
            return DIRECTION_LONG
        if candidate.gain_pct < 0:
            return DIRECTION_SHORT
        return None

    def compute_score(self, candidate: Candidate) -> float:
        """The score is now simply the name's relative volume (change A4).

        It used to be the size of the day's move multiplied by the log of
        relative volume. That was our own invention. The published result this
        strategy is copying came from ranking candidates by relative volume
        alone and taking the top few, and it was the ranking that carried the
        result, not the size of the gap. So the size of the move no longer
        decides who goes first.

        The 2 times normal floor has not gone anywhere. It still runs earlier,
        as a filter: a name below twice its normal pace never reaches this
        ranking at all. What changed is only the order of the survivors.

        The method keeps its old name so that the rest of this file, and the
        "score" field in the shortlist that other tools read, carry on working.
        """
        return float(candidate.rel_volume or 0.0)

    # -- the whole run -----------------------------------------------------

    async def run(self, reference_symbol: str) -> dict[str, Any]:
        candidates = await self.collect_candidates()
        self.counts["merged_unique"] = len(candidates)

        if self.saw_no_live_data and self.market_data_type == 1:
            # Switch the rest of the run to delayed data so the historical
            # requests below come back with something. The scans are NOT run
            # again: five more scanner requests is a quarter of the whole ten
            # minute ration, and a scan that could not be believed has already
            # raised ScanFailure by this point rather than quietly returning a
            # worse answer.
            log.info(
                "No live data entitlement seen, switching the rest of this run to "
                "delayed data. The scans are not repeated.")
            await self.set_market_data_type(3)
            self.saw_no_live_data = False

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
            for stage in ("daily_bars_ok", "passed_history", "passed_price_floor",
                          "passed_dollar_volume", "passed_volatility",
                          "passed_rel_volume", "passed_direction_agrees",
                          "passed_us_listing", "passed_leverage_name_filter",
                          "passed_hard_exclusions", "opening_range_ok",
                          "passed_direction_candle", "final", "final_long",
                          "final_short"):
                self.counts[stage] = 0
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

        # Enough history to be measured at all. This is what Mo put in place of
        # the 90 day listing age rule he rejected: rather than asking how old a
        # listing is, ask whether it has traded long enough for its own numbers
        # to mean anything. 30 completed sessions is what the dollar volume
        # average wants, and the 14 the average true range wants sit inside it.
        enough_history = [
            c
            for c in with_data
            if (c.completed_sessions or 0) >= self.thresholds.min_history_sessions
        ]
        self.counts["passed_history"] = len(enough_history)
        survivors = enough_history

        # The price floor. At or above 5 dollars, not strictly above it, which is
        # what "price floor: 5" in docs/STRATEGY.md means. Applied here rather
        # than sent to Gateway as abovePrice, because a filter Gateway can
        # disable without telling us is not a filter.
        survivors = [
            c for c in survivors if (c.last or 0.0) >= self.thresholds.price_floor
        ]
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

        # The volatility floor (change A3). Both halves have to clear: at least
        # 50 cents of average daily range AND at least 1.5 percent of the price.
        # A name whose ATR could not be worked out has no measurable range, so
        # it fails here, which is the safe answer. Without this filter the
        # shortlist fills with quiet large caps whose whole five minute range is
        # noise, and a breakout on noise is not a trade.
        survivors = [
            c
            for c in survivors
            if c.atr is not None
            and c.atr >= self.thresholds.min_atr_usd
            and (c.atr_pct_of_price or 0.0) >= self.thresholds.min_atr_pct_of_price
        ]
        self.counts["passed_volatility"] = len(survivors)

        # At or above 2 times normal, measured at the 09:35 anchor.
        survivors = [
            c
            for c in survivors
            if (c.rel_volume or 0.0) >= self.thresholds.rel_volume_min
        ]
        self.counts["passed_rel_volume"] = len(survivors)

        # Which way is each name going, and does its own price agree with the
        # list it came off? A name from the gainers scan that is somehow down on
        # the day, or one from the fallers scan that is up, is contradicting
        # itself and gets dropped rather than shortlisted with a trigger that
        # points the wrong way. A name from a volume scan alone has its direction
        # decided here, by the sign of its own move.
        directional = []
        for candidate in survivors:
            candidate.direction = self.resolve_direction(candidate)
            move = candidate.gain_pct
            if candidate.direction is None or move is None:
                log.debug("Dropped %s, nothing says which way it is going",
                          candidate.symbol)
                continue
            if candidate.direction == DIRECTION_LONG and move <= 0:
                log.debug("Dropped %s, flagged as a gainer but down %.2f percent",
                          candidate.symbol, move)
                continue
            if candidate.direction == DIRECTION_SHORT and move >= 0:
                log.debug("Dropped %s, flagged as a faller but up %.2f percent",
                          candidate.symbol, move)
                continue
            directional.append(candidate)
        survivors = directional
        self.counts["passed_direction_agrees"] = len(survivors)

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

        if survivors and self.thresholds.exclude_halted and not self.halt_flags:
            # Part of change A12. IBKR's contract details carry no halt flag on
            # this account, so this check cannot be made here and the run says
            # so out loud rather than implying it looked and found nothing.
            self.note(
                "The halt check could not be made from contract details, because "
                "IBKR does not put a halt flag on them for this account. The live "
                "halt check is the one on the order path in "
                "/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/"
                "guardrails.py, rule id `halted`, which reads IBKR's tick type 49."
            )

        # The US listing test, gated by universe.require_us_primary_listing.
        # This is the rule that keeps OTC lines and foreign listings out: a name
        # priced in anything but dollars, or whose home venue is not one of the
        # US exchanges, is not a US primary listing and is not traded here.
        if self.thresholds.require_us_primary_listing:
            us_listed = []
            for candidate in survivors:
                if candidate.currency and candidate.currency.upper() != "USD":
                    log.debug(
                        "Dropped %s, priced in %s not USD, so it is not a US primary "
                        "listing. This is the test that keeps OTC and non-US lines out",
                        candidate.symbol, candidate.currency,
                    )
                    continue
                venue = (candidate.primary_exchange or "").upper()
                if venue and venue not in ALLOWED_PRIMARY_EXCHANGES:
                    log.debug(
                        "Dropped %s, its home venue is %s, which is not a US primary "
                        "listing. This is the test that keeps OTC and non-US lines out",
                        candidate.symbol, venue,
                    )
                    continue
                if not venue:
                    log.debug(
                        "Dropped %s, no home venue reported, so it cannot be shown to "
                        "be a US primary listing. This is the test that keeps OTC and "
                        "non-US lines out",
                        candidate.symbol,
                    )
                    continue
                us_listed.append(candidate)
        else:
            log.info(
                "universe.require_us_primary_listing is off, so OTC and non-US "
                "lines are NOT being kept out")
            us_listed = list(survivors)
        self.counts["passed_us_listing"] = len(us_listed)

        clean = []
        for candidate in us_listed:
            verdict = self.leverage_verdict(candidate)
            if verdict:
                log.debug("Dropped %s, %s", candidate.symbol, verdict)
                continue
            clean.append(candidate)
        self.counts["passed_leverage_name_filter"] = len(clean)

        # The rest of the hard exclusions (change A12): SPACs, warrants, rights,
        # preferred shares and anything IBKR said was halted.
        allowed = []
        for candidate in clean:
            verdict = self.exclusion_verdict(candidate)
            if verdict:
                log.debug("Dropped %s, %s", candidate.symbol, verdict)
                continue
            allowed.append(candidate)
        clean = allowed
        self.counts["passed_hard_exclusions"] = len(clean)

        # Rank by relative volume, heaviest first (change A4), then only fetch
        # opening ranges for the names that will actually make the shortlist.
        # Fetching last saves scarce historical-data requests.
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

        # Direction from the opening candle (change A5), which can only happen
        # now, once the opening ranges are actually in. The sign of the 9:30 to
        # 9:35 candle is the published rule and it overrules the scan list and
        # the day's move for any name whose candle we know. A candle that opened
        # and closed at exactly the same price is a no trade, so that name comes
        # off the list rather than falling back to a weaker answer. A name with
        # no candle yet keeps the direction the earlier cheap check gave it.
        decided = []
        flat = []
        for candidate in shortlist:
            from_candle = direction_from_candle(
                candidate.opening_range_open, candidate.opening_range_close
            )
            if from_candle is not None:
                candidate.direction = from_candle
                decided.append(candidate)
                continue
            known_candle = (
                candidate.opening_range_open is not None
                and candidate.opening_range_close is not None
            )
            if known_candle:
                flat.append(candidate.symbol)
                continue
            decided.append(candidate)
        shortlist = decided
        self.counts["passed_direction_candle"] = len(shortlist)
        if flat:
            self.note(
                f"Dropped {len(flat)} name(s) whose 9:30 to 9:35 candle opened and "
                f"closed at the same price, which is a no trade under the strategy "
                f"rule: {', '.join(sorted(flat))}"
            )

        # Numbered after the flat candle drop so the published list reads 1, 2,
        # 3 with no holes in it. The order is still relative volume, heaviest
        # first, because the sort above happened first and nothing reorders it.
        for position, candidate in enumerate(shortlist, start=1):
            candidate.rank = position

        # A name whose industry IBKR would not name cannot be entered at all:
        # the sector cap in agent/guardrails.py refuses an order it cannot file
        # under an industry. So say which names those are rather than letting
        # them sit on the shortlist looking tradeable.
        no_sector = sorted(c.symbol for c in shortlist if not c.sector)
        if no_sector:
            self.note(
                f"No industry from IBKR for {len(no_sector)} shortlisted name(s), so "
                f"the sector cap in agent/guardrails.py will refuse an entry in them: "
                f"{', '.join(no_sector)}"
            )

        for candidate in shortlist:
            candidate.reasons = self.build_reasons(candidate)
        self.counts["final"] = len(shortlist)
        self.counts["final_long"] = sum(
            1 for c in shortlist if c.direction == DIRECTION_LONG)
        self.counts["final_short"] = sum(
            1 for c in shortlist if c.direction == DIRECTION_SHORT)
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
            "control_scan_code": CONTROL_SCAN_CODE,
            "scan_filters_sent": [],
            "scan_diagnostics": dict(self.scan_diagnostics),
            "thresholds": self.thresholds.as_dict(),
            "counts": dict(self.counts),
            "scanner_requests_used": self.scanner_requests,
            "historical_requests_used": self.pacer.used,
            "total_requests_used": self.scanner_requests + self.pacer.used,
            "total_request_ration": TOTAL_REQUEST_RATION,
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
        help="How many scan hits to pull extra data for, best ranked first. "
        "Default: %(default)s",
    )
    parser.add_argument(
        "--history-budget",
        type=int,
        default=HISTORY_REQUEST_BUDGET,
        help="Cap on historical data requests per run. The five scanner requests "
        "are counted separately, and the two together stay under Gateway's sixty "
        "per ten minutes. Default: %(default)s",
    )
    parser.add_argument(
        "--reference-symbol",
        default="SPY",
        help="Liquid symbol used to see how far the data reaches. Default: %(default)s",
    )
    parser.add_argument("--verbose", action="store_true", help="Chattier logging")
    return parser.parse_args(argv)


#: The line agent/preflight.py looks for on stderr when the scanner exits 3. One
#: line of JSON, so the codes and messages survive the trip between processes
#: without anyone having to parse English out of a log.
SCAN_FAILURE_MARKER = "SCAN_FAILURE_JSON "


def report_scan_failure(failure: ScanFailure, scanner: OpeningMomentumScanner,
                        out: str) -> None:
    """Say loudly what went wrong, on stderr, and write no shortlist."""
    codes = sorted({code for code, _ in failure.errors})
    log.error("The scan could not be trusted, so nothing was written: %s", failure)
    log.error(
        "Gateway error codes on this run: %s",
        ", ".join(str(c) for c in codes) or "none, so it was a short control or a timeout")
    log.error(
        "%s was left exactly as it was. An empty shortlist and a broken scanner "
        "must never look the same.", out)
    payload = {
        "message": str(failure),
        "codes": codes,
        "errors": [{"code": code, "message": message}
                   for code, message in failure.errors],
        "scan_diagnostics": scanner.scan_diagnostics,
        "out": str(out),
        "wrote_anything": False,
    }
    print(SCAN_FAILURE_MARKER + json.dumps(payload), file=sys.stderr, flush=True)


async def main_async(args: argparse.Namespace) -> int:
    thresholds = load_thresholds(Path(args.config))
    log.info(
        "Thresholds: price at or above %.2f, average daily dollar volume of %s or more "
        "over %d sessions, %d day average true range of at least %.2f dollars and "
        "%.1f percent of price, at least %d completed sessions of history, relative "
        "volume at or above %.2f measured at the %s anchor, top %d by relative "
        "volume (%s)",
        thresholds.price_floor,
        human_dollars(thresholds.min_avg_dollar_volume),
        thresholds.dollar_volume_sessions,
        thresholds.atr_days,
        thresholds.min_atr_usd,
        thresholds.min_atr_pct_of_price,
        thresholds.min_history_sessions,
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
    except ScanFailure as failure:
        # The one thing this script must never do is write an empty shortlist
        # because a scan broke. An empty file and a broken scanner look the same
        # to everything downstream, so nothing is written at all: whatever was
        # there before is left exactly where it is, and the exit code says why.
        report_scan_failure(failure, scanner, args.out)
        return EXIT_SCAN_FAILURE
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
            "  %-6s %-5s move %6s%%  rel vol %5s  last %8s  range %s to %s",
            candidate["symbol"],
            candidate.get("direction") or "?",
            candidate["gain_pct"],
            candidate["rel_volume"],
            candidate["last"],
            candidate["opening_range_low"],
            candidate["opening_range_high"],
        )
    log.info(
        "Requests used: %d scanner + %d historical = %d of the %d per ten minutes",
        result.get("scanner_requests_used", 0),
        result.get("historical_requests_used", 0),
        result.get("total_requests_used", 0),
        result.get("total_request_ration", TOTAL_REQUEST_RATION),
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

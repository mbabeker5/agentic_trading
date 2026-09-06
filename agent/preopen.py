"""The pre-open run for the three momentum books, A, B and E.

WHAT THIS IS FOR

At 9:35 the momentum books have to know two things about every name they might
buy: how heavily it traded in the first five minutes against how heavily it
normally trades in those same five minutes, and how far it moves on an ordinary
day. Both answers come from historical data, and IB Gateway rations historical
data to roughly sixty requests in any ten minutes across the whole connection.
Asking for all of it at 9:35 spends that ration in the five minutes when it is
scarcest, and the pick arrives late.

So the work is moved earlier. From 9:00 this module scans the pre-market for
gappers, pulls each new name's history slowly and evenly, and writes every
answer to disk. By 9:26 the expensive part is done. At 9:35 the ranking is
arithmetic on data that is already sitting in a file, which takes about a
second.

The whole timeline, in New York time, is written down in
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/PREOPEN_FLOW.md
and this file follows it step for step.

ONE TICK AT A TIME, NOT A RESIDENT PROCESS

There is no long running process in this project. launchd wakes
agent/loop.py, the loop does the one thing that belongs to that minute, and the
process exits. This module is written the same way. step() looks at the clock
and at what is already on disk, works out what this one tick owes, does that
much, saves its state and returns. There is no `while` loop and nothing sleeps.

Everything that has to survive between ticks lives in one file per day:

    output/preopen_state_YYYY-MM-DD.json

That file remembers the candidate list, which names already have their history
cached, when each historical request went out (so the pacing rule holds across
processes as well as inside one), the watch list, and the shortlist once it is
made.

THE PACING NEEDS A WAKE UP EVERY MINUTE

The rule below is four historical requests a minute. A tick cannot send more
than that, because the tick lasts a second or two and then the process is gone.
So the pre-open wants a wake up every minute from 9:00 to 9:26, not every five
minutes. Twenty six ticks at four requests each pays for about a hundred
requests, which is the arithmetic in the design document. With five minute wake
ups the same window only pays for about twenty, and most of the candidate list
would reach 9:35 with no history at all.

Two requests are needed per name, the five minute bars and the daily bars, so
about a hundred requests covers about fifty names rather than a hundred. The
candidate list still holds up to a hundred names, ordered biggest gap first, and
the ones that never get their history are recorded as not rankable rather than
quietly dropped.

THIS FILE ONLY READS

It is handed a Broker (see agent/broker.py) and calls six methods on it:
account_summary, portfolio, open_orders, executions, snapshot and
historical_bars. It never sends, changes or pulls an order, and there is a test
that reads this file's own text to prove it.

Run it by hand, with the market shut, like this:

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/preopen.py \
      --now "2026-09-08 09:12"

That prints the phase the clock is in and what this tick would do. With no
broker attached it makes no network call at all.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import sys
from dataclasses import dataclass, asdict
from datetime import date, datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import alerts  # noqa: E402
from paths import config_dir, output_dir  # noqa: E402

try:
    import yaml
except ImportError:                                               # pragma: no cover
    yaml = None


# ---------------------------------------------------------------------------
# The numbers
# ---------------------------------------------------------------------------

#: Every time in this file is New York time, because the market is.
EASTERN = ZoneInfo("America/New_York")

#: How many historical data requests may go out in any one minute.
#:
#: IB Gateway rations historical requests to roughly sixty in any ten minutes,
#: counted across the whole connection rather than per script, and going over
#: gets everything on that connection throttled. Four a minute for the twenty
#: five minutes between 9:00 and 9:25 is about a hundred requests, which fits
#: with room to spare. It is deliberately slower than the cap allows, because
#: the scanner and the loop share the same connection.
HISTORY_REQUESTS_PER_MINUTE = 4

#: How many names the pre-open candidate list may hold. The feed allows a
#: hundred streaming lines, so a hundred is as many as could ever be watched.
MAX_CANDIDATES_TRACKED = 100

#: What we keep when Gateway reports fewer than a hundred lines available. Sixty
#: is the fallback Mo settled on: enough names to still have a real choice at
#: 9:35, few enough that a thinner feed can carry them.
STREAMING_LINES_FALLBACK = 60

#: How many lines we expect to have. Anything less triggers the fallback above.
STREAMING_LINES_WANTED = 100

#: How often the gap scan runs during the pre-open. Every three minutes is often
#: enough to catch a name that starts moving at 9:07, and rare enough that the
#: scan is not most of what the tick does.
SCAN_EVERY_MINUTES = 3

#: How many contracts go into one snapshot call. A hundred names in one call is
#: a single request but a large answer. Fifty at a time keeps each answer small
#: and each call quick, so the whole scan stays inside its five second budget.
SNAPSHOT_CHUNK = 50

#: How much history to ask for, in IBKR's own phrasing.
#:
#: The relative volume baseline needs the 9:30 to 9:35 bar from each of the
#: prior fourteen completed sessions. Fourteen sessions is about twenty calendar
#: days once weekends are counted, so "20 D" of five minute bars covers it with
#: a little slack for a holiday.
#:
#: The average true range needs fourteen daily true ranges, and a true range
#: needs the previous session's close, so that is fifteen daily bars at least.
#: The liquidity floor is an average over thirty completed sessions on top of
#: that. Sixty calendar days is about forty two sessions, which covers both.
BARS5M_DURATION = "20 D"
BARS5M_SIZE = "5 mins"
DAILY_DURATION = "60 D"
DAILY_SIZE = "1 day"

#: How many opening bars the 9:35 fallback will fetch when no live subscription
#: is held. See the honesty note on the subscribe step below. By 9:35 the
#: pre-open pulls have been finished for nine minutes, so the ten minute ration
#: is almost empty again and a burst of forty is safe. It is still a cap,
#: because a burst of a hundred would not be.
OPENING_BAR_FALLBACK_CAP = 40

#: How long after the pick time it is still worth ranking. Ten minutes. Past
#: that the orders were due long ago and the five minute bars are stale, so the
#: honest answer is that the morning was missed, not to trade on old numbers.
PICK_WINDOW_MINUTES = 10

# Defaults for everything read out of config/guardrails.yaml. Anything present
# in that file wins over these. They exist so this module works on a checkout
# where the file is missing a key, and so the numbers are written down in one
# place a reader can find.
DEFAULT_PRICE_FLOOR = 5.0
DEFAULT_MIN_AVG_DOLLAR_VOLUME = 20_000_000.0
DEFAULT_DOLLAR_VOLUME_SESSIONS = 30
DEFAULT_MIN_HISTORY_SESSIONS = 30
DEFAULT_ATR_DAYS = 14
DEFAULT_MIN_ATR_USD = 0.50
DEFAULT_MIN_ATR_PCT_OF_PRICE = 1.5
DEFAULT_REL_VOLUME_MIN = 2.0
DEFAULT_REL_VOLUME_WINDOW = "09:30-09:35"
DEFAULT_REL_VOLUME_BASELINE_DAYS = 14
DEFAULT_MAX_CANDIDATES = 20
DEFAULT_PREOPEN_START = "09:00"
DEFAULT_HISTORY_DONE_BY = "09:26"
DEFAULT_SUBSCRIBE_DONE_BY = "09:29"
DEFAULT_PICK_TIME = "09:35"
DEFAULT_TIMEZONE = "America/New_York"

#: What each step of the pre-open is allowed to take.
#:
#: Two kinds of thing live in here, and they are told apart by their type.
#: A number is a duration in seconds: the step itself must not take longer than
#: that. A string is a wall clock deadline in New York time: the step must be
#: finished by then, however long it took. Three of the six are durations
#: (scan, rank and model) and three are deadlines (history_done_by,
#: subscribe_done_by and orders_by).
#:
#: The model and orders budgets belong to agent/loop.py rather than to this
#: file, which never asks a model anything and never sends an order. They are
#: written down here so that all six live in one place and so the loop can stamp
#: its own two steps into the same timings file.
BUDGETS: dict[str, float | str] = {
    "scan": 5.0,
    "history_done_by": "09:26",
    "subscribe_done_by": "09:29",
    "rank": 2.0,
    "model": 45.0,
    "orders_by": "09:36:30",
}

#: The phases of the morning, in order. step() works out which one the clock is
#: in and does that phase's work.
PHASE_TOO_EARLY = "too_early"
PHASE_GATHER = "gather"
PHASE_SUBSCRIBE = "subscribe"
PHASE_WATCH = "watch"
PHASE_RANK = "rank"
PHASE_DONE = "done"

#: The two kinds of thing the cache holds, one file each per symbol per day.
CACHE_BARS5M = "bars5m"
CACHE_DAILY = "daily"

DIRECTION_LONG = "long"
DIRECTION_SHORT = "short"


# ---------------------------------------------------------------------------
# Small helpers with no broker and no clock in them
# ---------------------------------------------------------------------------


def _number(value: Any) -> float | None:
    """Turn whatever we were handed into a real number, or into None.

    None comes back for text that is not a number, for None itself, and for the
    not-a-number and infinity values that arithmetic on bad data produces. Every
    caller here treats None as "we do not know", which is always the safe
    answer.
    """
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def bar_get(bar: Any, *names: str) -> Any:
    """One field out of a bar, whether the bar is a dictionary or an object.

    The MCP server hands bars back as plain dictionaries. ib_async hands them
    back as objects with attributes. A recorded day in a test file is a
    dictionary again. Rather than make every caller care, this tries each name
    as a key and then as an attribute, and returns the first one that is there.
    """
    for name in names:
        if isinstance(bar, dict):
            if name in bar and bar[name] is not None:
                return bar[name]
        else:
            value = getattr(bar, name, None)
            if value is not None:
                return value
    return None


#: The shapes a bar's timestamp arrives in. IBKR with formatDate=1 sends
#: "20260908 09:35:00" for an intraday bar and "20260908" for a daily one. The
#: MCP server and the replay files use the dashed shapes. All of them appear.
_BAR_TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y%m%d %H:%M:%S",
    "%Y-%m-%d",
    "%Y%m%d",
)


def bar_moment(bar: Any) -> datetime | None:
    """When a bar starts, as a New York time, or None when it cannot be read.

    A bar with no readable timestamp is useless to us, because every question
    here is about a particular five minutes of a particular day. None is the
    honest answer and the caller skips the bar.
    """
    raw = bar_get(bar, "time", "date", "datetime")
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=EASTERN)
        return raw.astimezone(EASTERN)
    if isinstance(raw, date):
        return datetime.combine(raw, clock_time(0, 0), tzinfo=EASTERN)
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    # IBKR sometimes adds the zone name as a third field, as in
    # "20260908 09:35:00 US/Eastern". We already know the zone, so drop it.
    parts = text.split()
    if len(parts) >= 3:
        text = " ".join(parts[:2])
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None
    if parsed is None:
        for shape in _BAR_TIME_FORMATS:
            try:
                parsed = datetime.strptime(text, shape)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=EASTERN)
    return parsed.astimezone(EASTERN)


def parse_clock(text: str, fallback: clock_time | None = None) -> clock_time | None:
    """Read "09:35" or "09:36:30" into a time. Anything unreadable falls back.

    Times come out of config/guardrails.yaml, which a person edits, so a typo
    has to land somewhere soft rather than stopping the morning.
    """
    raw = str(text or "").strip()
    for shape in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(raw, shape).time()
        except ValueError:
            continue
    return fallback


def parse_window(text: str) -> tuple[clock_time, clock_time]:
    """Read "09:30-09:35" into its two ends.

    Anything unreadable falls back to 9:30 and 9:35, which is the window the
    strategy is actually about, so a bad line in the settings file cannot
    quietly move the measurement somewhere else.
    """
    default_start, default_end = clock_time(9, 30), clock_time(9, 35)
    parts = str(text or "").split("-")
    if len(parts) != 2:
        return default_start, default_end
    start = parse_clock(parts[0], default_start)
    end = parse_clock(parts[1], default_end)
    return start or default_start, end or default_end


def gap_percent(last: float | None, previous_close: float | None) -> float | None:
    """How far a name has moved before the bell, as a percent of yesterday.

    Positive means it is up on yesterday's close, negative means down. None
    comes back when either price is missing or yesterday's close is not a real
    price, because a gap measured against nothing is not a gap.
    """
    now_price = _number(last)
    base = _number(previous_close)
    if now_price is None or base is None or base <= 0:
        return None
    return (now_price - base) / base * 100.0


# ---------------------------------------------------------------------------
# The arithmetic, all of it testable on paper
# ---------------------------------------------------------------------------


def relative_volume_open_window(
    today_window_volume: float | None,
    baseline_window_volumes: Sequence[float | None],
) -> tuple[float | None, int]:
    """How busy the first five minutes were against the same five minutes before.

    Hand in the shares traded between 9:30 and 9:35 today, and the shares traded
    in that same window on each of the prior sessions. The answer is how many
    times its own normal that name is trading at, and how many baseline days
    went into working it out.

    2.0 means twice as busy as usual for that time of day, which is the floor
    the strategy uses. This is change A4 in
    research/momentum_spec_critique_2026-09-06.md: the published edge came from
    ranking on this number, not from the breakout.

    Days with no volume at all in that window are dropped rather than averaged
    in. A liquid name that traded nothing in the first five minutes of a session
    is missing data, not a quiet morning, and leaving the zero in would drag the
    average down and make today look busier than it was.

    None comes back when there is nothing to divide by, and None fails the
    floor, which is the safe answer.
    """
    usable = [value for value in (_number(v) for v in baseline_window_volumes)
              if value is not None and value > 0]
    days_used = len(usable)
    today = _number(today_window_volume)
    if today is None or days_used == 0:
        return None, days_used
    average = sum(usable) / days_used
    if average <= 0:
        return None, days_used
    return today / average, days_used


def average_true_range(daily_bars: Sequence[Any], days: int = DEFAULT_ATR_DAYS
                       ) -> tuple[float | None, int]:
    """How far a name moves on an ordinary day, in dollars.

    Hand in daily bars, oldest first. The answer is the average true range over
    the last `days` sessions, and how many sessions that average actually used.

    True range is not just the day's high minus its low. A name that closed at
    100 and opened at 110 the next morning moved ten dollars, even if it then
    traded in a fifty cent range all day. So each session's true range is the
    largest of three numbers:

        today's high minus today's low
        today's high minus yesterday's close, ignoring the sign
        today's low minus yesterday's close, ignoring the sign

    That second and third term are the reason the oldest bar handed in cannot
    have a true range of its own: there is no session before it to have closed.
    It is used as the previous close for the next bar and nothing else, so
    fifteen bars give fourteen true ranges.

    This is what the volatility filter, change A3 in the critique, is measured
    on. None comes back when there are fewer than two usable bars.
    """
    rows: list[tuple[float, float, float]] = []
    for bar in daily_bars or []:
        high = _number(bar_get(bar, "high", "High"))
        low = _number(bar_get(bar, "low", "Low"))
        close = _number(bar_get(bar, "close", "Close"))
        if high is None or low is None or close is None:
            continue
        rows.append((high, low, close))
    if len(rows) < 2:
        return None, 0

    ranges: list[float] = []
    for previous, current in zip(rows, rows[1:]):
        previous_close = previous[2]
        high, low, _ = current
        ranges.append(max(high - low,
                          abs(high - previous_close),
                          abs(low - previous_close)))
    wanted = max(1, int(days))
    recent = ranges[-wanted:]
    if not recent:
        return None, 0
    return sum(recent) / len(recent), len(recent)


def direction_from_candle(open_price: float | None,
                          close_price: float | None) -> str | None:
    """Which way the first five minutes went: "long", "short", or nothing.

    This is the paper's own rule, change A5 in the critique. The trade follows
    the sign of the 9:30 to 9:35 candle, not the overnight gap, because a name
    can gap up and then be sold from the first tick.

    A flat candle, where the close is exactly the open, gives None, and None
    means no trade in that name. There is no tie break and no rounding: if the
    five minutes said nothing, we do not guess.
    """
    opened = _number(open_price)
    closed = _number(close_price)
    if opened is None or closed is None:
        return None
    if closed > opened:
        return DIRECTION_LONG
    if closed < opened:
        return DIRECTION_SHORT
    return None


def passes_volatility(atr: float | None, price: float | None,
                      min_atr_usd: float = DEFAULT_MIN_ATR_USD,
                      min_atr_pct_of_price: float = DEFAULT_MIN_ATR_PCT_OF_PRICE) -> bool:
    """Does this name move enough in a day to be worth trading in five minutes.

    Both tests have to pass. The dollar test keeps out names whose whole daily
    range is smaller than a normal spread. The percent test keeps out quiet
    large caps, where fifty cents is a rounding error on a three hundred dollar
    share. Change A3 in the critique: without this the scan fills up with names
    whose five minute range is noise.

    A missing average true range or a missing price fails, because a filter that
    passes on unknown data is not a filter.
    """
    range_now = _number(atr)
    price_now = _number(price)
    if range_now is None or price_now is None or price_now <= 0:
        return False
    if range_now < _number(min_atr_usd or 0.0):
        return False
    return (range_now / price_now * 100.0) >= _number(min_atr_pct_of_price or 0.0)


def rank_candidates(rows: Iterable[dict]) -> list[dict]:
    """Sort the shortlist by relative volume, busiest first, and number it.

    Each row comes back as a copy with a `rank` key on it, counting from 1, so
    that the number written into the ledger later means the same thing as the
    order on the page. The rows handed in are not touched.

    A row with no relative volume sorts to the bottom rather than blowing up.
    Ties are broken by symbol so that two runs on the same data produce the same
    order, which matters when a run has to be explained afterwards.
    """
    copies = [dict(row) for row in rows or []]

    def sort_key(row: dict) -> tuple[float, str]:
        value = _number(row.get("relative_volume"))
        return (-(value if value is not None else -math.inf),
                str(row.get("symbol") or ""))

    copies.sort(key=sort_key)
    for position, row in enumerate(copies, start=1):
        row["rank"] = position
    return copies


def average_dollar_volume(daily_bars: Sequence[Any],
                          sessions: int = DEFAULT_DOLLAR_VOLUME_SESSIONS
                          ) -> tuple[float | None, int]:
    """What this name trades in an average day, in dollars.

    Close times volume, averaged over the last `sessions` completed daily bars.
    Dollars rather than shares, because a million shares of a six dollar stock
    and a million shares of a six hundred dollar stock are nothing like the same
    amount of money, and how much we can trade without moving the price depends
    on the money.

    The same arithmetic lives in agent/scanner.py. It is written out again here
    rather than imported because importing that file opens a Gateway connection,
    and this one must import with no network at all.
    """
    values: list[float] = []
    for bar in daily_bars or []:
        close = _number(bar_get(bar, "close", "Close"))
        volume = _number(bar_get(bar, "volume", "Volume"))
        if close is None or volume is None or close <= 0 or volume < 0:
            continue
        values.append(close * volume)
    wanted = max(1, int(sessions))
    recent = values[-wanted:]
    if not recent:
        return None, 0
    return sum(recent) / len(recent), len(recent)


def window_bar(bars: Sequence[Any], day: date,
               start: clock_time, end: clock_time) -> dict | None:
    """Roll every bar inside one day's window up into a single candle.

    With five minute bars the 9:30 to 9:35 window is one bar, stamped at its
    own start. Rolling them up anyway means the same function works if the bar
    size ever changes, and it means a missing bar in the middle of the window
    does not silently become the whole answer.

    The window includes its start and excludes its end, so a bar stamped 9:35
    belongs to the next window, not this one.

    Comes back as open, high, low, close and volume, or None when the day has
    no bars in that window at all.
    """
    opened = closed = None
    high = low = None
    volume = 0.0
    seen = False
    for bar in bars or []:
        moment = bar_moment(bar)
        if moment is None or moment.date() != day:
            continue
        at = moment.time()
        if at < start or at >= end:
            continue
        bar_open = _number(bar_get(bar, "open", "Open"))
        bar_high = _number(bar_get(bar, "high", "High"))
        bar_low = _number(bar_get(bar, "low", "Low"))
        bar_close = _number(bar_get(bar, "close", "Close"))
        bar_volume = _number(bar_get(bar, "volume", "Volume"))
        if not seen:
            opened = bar_open
            seen = True
        if bar_close is not None:
            closed = bar_close
        if bar_high is not None:
            high = bar_high if high is None else max(high, bar_high)
        if bar_low is not None:
            low = bar_low if low is None else min(low, bar_low)
        if bar_volume is not None:
            volume += bar_volume
    if not seen:
        return None
    return {"open": opened, "high": high, "low": low, "close": closed,
            "volume": volume}


def baseline_window_volumes(bars: Sequence[Any], before_day: date,
                            start: clock_time, end: clock_time,
                            days: int = DEFAULT_REL_VOLUME_BASELINE_DAYS
                            ) -> list[float]:
    """The same five minutes, on each of the sessions before today.

    Hand in a run of five minute bars covering the last few weeks. The answer is
    one volume per session, oldest first, for the most recent `days` sessions
    that came before `before_day`. Today itself is left out, which is the whole
    point: today is the thing being measured against them.
    """
    per_day: dict[date, float] = {}
    for bar in bars or []:
        moment = bar_moment(bar)
        if moment is None:
            continue
        day = moment.date()
        if day >= before_day:
            continue
        at = moment.time()
        if at < start or at >= end:
            continue
        volume = _number(bar_get(bar, "volume", "Volume"))
        if volume is None:
            continue
        per_day[day] = per_day.get(day, 0.0) + volume
    ordered = [per_day[key] for key in sorted(per_day)]
    wanted = max(1, int(days))
    return ordered[-wanted:]


# ---------------------------------------------------------------------------
# The settings, read from config/guardrails.yaml
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    """Every number the pre-open filters and schedules on.

    Read out of config/guardrails.yaml. This file never writes that one: another
    part of the project owns it. A missing file, or a missing key inside it,
    falls back to the default beside the field, so a checkout where the settings
    have not caught up still runs.
    """

    price_floor: float = DEFAULT_PRICE_FLOOR
    min_avg_dollar_volume: float = DEFAULT_MIN_AVG_DOLLAR_VOLUME
    dollar_volume_sessions: int = DEFAULT_DOLLAR_VOLUME_SESSIONS
    min_history_sessions: int = DEFAULT_MIN_HISTORY_SESSIONS
    atr_days: int = DEFAULT_ATR_DAYS
    min_atr_usd: float = DEFAULT_MIN_ATR_USD
    min_atr_pct_of_price: float = DEFAULT_MIN_ATR_PCT_OF_PRICE
    rel_volume_min: float = DEFAULT_REL_VOLUME_MIN
    rel_volume_window: str = DEFAULT_REL_VOLUME_WINDOW
    rel_volume_baseline_days: int = DEFAULT_REL_VOLUME_BASELINE_DAYS
    max_candidates: int = DEFAULT_MAX_CANDIDATES
    preopen_start: str = DEFAULT_PREOPEN_START
    preopen_history_done_by: str = DEFAULT_HISTORY_DONE_BY
    preopen_subscribe_done_by: str = DEFAULT_SUBSCRIBE_DONE_BY
    pick_time: str = DEFAULT_PICK_TIME
    timezone: str = DEFAULT_TIMEZONE
    source: str = "built-in defaults"

    @property
    def window(self) -> tuple[clock_time, clock_time]:
        """The two ends of the relative volume window, 9:30 and 9:35."""
        return parse_window(self.rel_volume_window)

    def as_dict(self) -> dict:
        return asdict(self)


def guardrails_path() -> Path:
    """config/guardrails.yaml, the file this module reads and never writes."""
    return config_dir() / "guardrails.yaml"


def load_settings(path: Path | None = None) -> Settings:
    """Read the numbers from guardrails.yaml, falling back key by key.

    Every problem is soft. A missing file, a file that is not a mapping, a value
    that is not a number: each of them leaves that one field at its default and
    the rest of the file still loads. The pre-open running on slightly stale
    defaults is much better than the pre-open not running.
    """
    settings_path = Path(path) if path is not None else guardrails_path()
    values: dict[str, Any] = {}
    if yaml is None or not settings_path.exists():
        return Settings(**values)
    try:
        raw = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    except Exception:                                             # noqa: BLE001
        return Settings(**values)
    if not isinstance(raw, dict):
        return Settings(**values)

    universe = raw.get("universe") if isinstance(raw.get("universe"), dict) else {}
    scanner = raw.get("scanner") if isinstance(raw.get("scanner"), dict) else {}
    schedule = raw.get("schedule") if isinstance(raw.get("schedule"), dict) else {}

    def take(section: dict, key: str, cast, field_name: str) -> None:
        if key not in section or section.get(key) is None:
            return
        try:
            values[field_name] = cast(section[key])
        except (TypeError, ValueError):
            return

    take(universe, "price_floor", float, "price_floor")
    take(universe, "min_avg_dollar_volume", float, "min_avg_dollar_volume")
    take(universe, "dollar_volume_sessions", int, "dollar_volume_sessions")
    take(universe, "min_history_sessions", int, "min_history_sessions")
    take(universe, "atr_days", int, "atr_days")
    take(universe, "min_atr_usd", float, "min_atr_usd")
    take(universe, "min_atr_pct_of_price", float, "min_atr_pct_of_price")
    take(scanner, "rel_volume_min", float, "rel_volume_min")
    take(scanner, "rel_volume_window", str, "rel_volume_window")
    take(scanner, "rel_volume_baseline_days", int, "rel_volume_baseline_days")
    take(scanner, "max_candidates", int, "max_candidates")
    take(schedule, "preopen_start", str, "preopen_start")
    take(schedule, "preopen_history_done_by", str, "preopen_history_done_by")
    take(schedule, "preopen_subscribe_done_by", str, "preopen_subscribe_done_by")
    take(schedule, "pick_time", str, "pick_time")
    take(schedule, "timezone", str, "timezone")
    values["source"] = str(settings_path)
    return Settings(**values)


def budgets_from_settings(settings: Settings | None = None) -> dict[str, float | str]:
    """The budget table, with the deadlines moved to wherever the settings put them.

    The durations never move: five seconds for a scan is five seconds whatever
    the schedule says. The two pre-open deadlines come from the schedule block,
    so changing the timetable in one file changes what counts as late.
    """
    budgets = dict(BUDGETS)
    if settings is None:
        return budgets
    budgets["history_done_by"] = settings.preopen_history_done_by
    budgets["subscribe_done_by"] = settings.preopen_subscribe_done_by
    return budgets


# ---------------------------------------------------------------------------
# The disk cache
# ---------------------------------------------------------------------------


def cache_dir(create: bool = True) -> Path:
    """output/preopen_cache/, one small JSON file per symbol per day per kind.

    On disk rather than in memory because every tick is its own process. A
    restart at 9:14, or a tick that crashes, must not send the same hundred
    requests again.
    """
    path = output_dir(create=create) / "preopen_cache"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def cache_path(symbol: str, day: date, kind: str) -> Path:
    """Where one cached answer lives, for example AAPL_2026-09-08_bars5m.json."""
    clean = "".join(ch for ch in str(symbol or "").upper()
                    if ch.isalnum() or ch in "._-") or "UNKNOWN"
    return cache_dir(create=False) / f"{clean}_{day.isoformat()}_{kind}.json"


def read_cache(symbol: str, day: date, kind: str) -> dict | None:
    """What we saved earlier, or None when there is nothing usable saved.

    This never raises. A file that is missing, half written by a tick that was
    killed, or unreadable for any other reason is treated exactly like a file
    that was never there: a miss. The worst that costs is one more request,
    which is much better than a crash at 9:12 that stops the whole pre-open.
    """
    try:
        text = cache_path(symbol, day, kind).read_text(encoding="utf-8")
        loaded = json.loads(text)
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def write_cache(symbol: str, day: date, kind: str, bars: list) -> bool:
    """Save one answer. True when it was written, False when the disk refused.

    Written to a temporary file beside the real one and then moved into place,
    so a tick that dies mid write leaves either the old file or the new one, and
    never half of either.
    """
    path = cache_path(symbol, day, kind)
    payload = {
        "symbol": str(symbol or "").upper(),
        "day": day.isoformat(),
        "kind": kind,
        "written_at": datetime.now(EASTERN).isoformat(timespec="seconds"),
        "bars": list(bars or []),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.part")
        temporary.write_text(json.dumps(payload, indent=2, default=str),
                             encoding="utf-8")
        temporary.replace(path)
        return True
    except (OSError, TypeError, ValueError):
        return False


def cached_bars(symbol: str, day: date, kind: str) -> list:
    """Just the bars out of a cached file, or an empty list on a miss."""
    loaded = read_cache(symbol, day, kind)
    if not loaded:
        return []
    bars = loaded.get("bars")
    return bars if isinstance(bars, list) else []


# ---------------------------------------------------------------------------
# The pacer
# ---------------------------------------------------------------------------


class Pacer:
    """Counts historical data requests so four a minute is never exceeded.

    The shape is the same idea as HistoryPacer in agent/scanner.py, with one
    difference that matters: that one lives inside a single long running scan
    and can wait its turn. This one has to work across processes, because every
    tick is its own process and the pre-open is twenty six of them. So instead
    of sleeping, it remembers when each request went out, and a tick that has no
    allowance left simply does less and leaves the rest for the next minute.

    The memory is a plain list of times which is saved into the day's state file
    and handed back in on the next tick.
    """

    def __init__(self, per_minute: int = HISTORY_REQUESTS_PER_MINUTE,
                 sent: Iterable[datetime] | None = None) -> None:
        self.per_minute = max(1, int(per_minute))
        self.sent: list[datetime] = sorted(sent or [])

    @classmethod
    def from_stamps(cls, stamps: Iterable[str] | None,
                    per_minute: int = HISTORY_REQUESTS_PER_MINUTE) -> "Pacer":
        """Rebuild the pacer from what the state file remembered.

        A stamp that cannot be read is dropped rather than raising. Dropping one
        makes the pacer think it has slightly more room than it really has, so
        the file is written by this same class and the case should never arise.
        """
        moments: list[datetime] = []
        for stamp in stamps or []:
            try:
                moment = datetime.fromisoformat(str(stamp))
            except (TypeError, ValueError):
                continue
            moments.append(moment if moment.tzinfo else moment.replace(tzinfo=EASTERN))
        return cls(per_minute=per_minute, sent=moments)

    def used_in_last_minute(self, now: datetime) -> int:
        """How many requests went out in the sixty seconds ending now."""
        edge = now - timedelta(seconds=60)
        return sum(1 for moment in self.sent if moment > edge)

    def remaining(self, now: datetime) -> int:
        """How many more requests this minute can still carry."""
        return max(0, self.per_minute - self.used_in_last_minute(now))

    def take(self, now: datetime) -> bool:
        """Claim one request slot. True when there was room, False when not.

        A False is not an error. It means this tick has done its share for the
        minute and the next tick will pick the work up.
        """
        if self.remaining(now) <= 0:
            return False
        self.sent.append(now)
        self.sent.sort()
        return True

    def as_stamps(self, now: datetime | None = None) -> list[str]:
        """The memory, ready to be saved into the state file.

        Only the last ten minutes are kept. Anything older cannot affect a
        rolling sixty second window, and the file has no reason to grow all
        morning.
        """
        edge = (now or datetime.now(EASTERN)) - timedelta(minutes=10)
        return [moment.isoformat() for moment in self.sent if moment > edge]


# ---------------------------------------------------------------------------
# The timings file
# ---------------------------------------------------------------------------


def timings_path(day: date) -> Path:
    """output/preopen_timings_YYYY-MM-DD.json, one file a day."""
    return output_dir() / f"preopen_timings_{day.isoformat()}.json"


class Timings:
    """Every step's start, end, duration and whether it broke its budget.

    One file a day, rewritten each time a step finishes, because the process
    that recorded step one is long gone by the time step four runs.

    Crossing a budget raises an alert naming the step, through agent/alerts.py,
    which is the channel everything else in this project already uses: iMessage,
    Slack, a macOS banner and output/alerts.log. No new channel was invented
    here. An alert Mo has to check in a second place is an alert he will miss.
    The alert line is also written into the timings file itself, so the record
    survives even on a morning when every channel is down.
    """

    def __init__(self, day: date, budgets: dict[str, float | str] | None = None,
                 zone: ZoneInfo = EASTERN) -> None:
        self.day = day
        self.budgets = dict(budgets if budgets is not None else BUDGETS)
        self.zone = zone
        self.path = timings_path(day)
        self.data = self._load()

    def _load(self) -> dict:
        """Today's file, or a fresh one. An unreadable file starts again."""
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            loaded = None
        if not isinstance(loaded, dict):
            loaded = {"day": self.day.isoformat(), "steps": [], "alerts": []}
        loaded.setdefault("day", self.day.isoformat())
        loaded.setdefault("steps", [])
        loaded.setdefault("alerts", [])
        loaded["budgets"] = {key: value for key, value in self.budgets.items()}
        return loaded

    @property
    def steps(self) -> list[dict]:
        return self.data["steps"]

    def already_recorded(self, name: str) -> bool:
        """True when this step has been written down once already today."""
        return any(row.get("name") == name for row in self.steps)

    def deadline_moment(self, name: str) -> datetime | None:
        """When a step with a wall clock budget is due, as a real moment.

        Turns the "09:26" in the budget table into 9:26 on the day this file
        belongs to. None comes back for a step whose budget is a duration
        rather than a deadline, and for a step with no budget at all.
        """
        budget = self.budgets.get(name)
        if not isinstance(budget, str):
            return None
        wanted = parse_clock(budget)
        if wanted is None:
            return None
        return datetime.combine(self.day, wanted, tzinfo=self.zone)

    def record(self, name: str, started_at: datetime, finished_at: datetime,
               budget_name: str | None = None, detail: str = "") -> dict:
        """Write one step down, check its budget, and alert if it was crossed.

        The budget is looked up by name. A number in the budget table is a
        duration in seconds and is checked against how long the step took. A
        string is a wall clock deadline and is checked against when the step
        finished. A step with no budget is still recorded, just never late.
        """
        key = budget_name or name
        budget = self.budgets.get(key)
        duration = (finished_at - started_at).total_seconds()

        budget_seconds: float | None = None
        budget_deadline: str | None = None
        over = False
        if isinstance(budget, (int, float)):
            budget_seconds = float(budget)
            over = duration > budget_seconds
        elif isinstance(budget, str) and budget.strip():
            budget_deadline = budget.strip()
            moment = self.deadline_moment(key)
            over = moment is not None and finished_at > moment

        row = {
            "name": name,
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "duration_seconds": round(duration, 3),
            "budget_seconds": budget_seconds,
            "budget_deadline": budget_deadline,
            "over_budget": bool(over),
            "detail": detail,
        }
        self.steps.append(row)
        if over:
            self._raise_alert(row)
        self.save()
        return row

    @contextlib.contextmanager
    def timing(self, name: str, at: datetime, clock=None,
               budget_name: str | None = None, detail: str = ""):
        """Time a block of work and record it, even when the work raises.

        `at` is the tick's own time, which may be a pretend time from --now. How
        long the block took is measured on the real clock, because that is what
        a duration budget is actually about, and then added to `at`. So the step
        lands on the day the timings file belongs to, and a rehearsal on a shut
        market still produces a file that reads correctly.

        Used for the two steps that happen entirely inside one tick, the gap
        scan and the ranking. The steps that span several ticks cannot use this,
        because nothing is still running between them, so they call record()
        with a start time read back out of the day's state file.
        """
        tick = clock or (lambda: datetime.now(self.zone))
        started = tick()
        try:
            yield
        finally:
            elapsed = (tick() - started).total_seconds()
            self.record(name, at, at + timedelta(seconds=elapsed),
                        budget_name=budget_name, detail=detail)

    def _raise_alert(self, row: dict) -> None:
        """Tell Mo that a step went past its budget, naming the step."""
        if row.get("budget_deadline"):
            body = (f"The pre-open step {row['name']} was supposed to be finished by "
                    f"{row['budget_deadline']} New York time and finished at "
                    f"{row['finished_at']}.")
        else:
            body = (f"The pre-open step {row['name']} was allowed "
                    f"{row['budget_seconds']} seconds and took "
                    f"{row['duration_seconds']}.")
        if row.get("detail"):
            body = f"{body} {row['detail']}"
        body = f"{body} Written down in {self.path}."
        self.data["alerts"].append(
            {"at": row["finished_at"], "step": row["name"], "body": body})
        try:
            alerts.alert("warn", f"pre-open budget crossed: {row['name']}", body)
        except Exception:                                         # noqa: BLE001
            # An alert that cannot be delivered must never take down the
            # pre-open. The line is already in the timings file above, so the
            # record survives either way.
            pass

    def save(self) -> None:
        """Write the file. A disk that refuses does not stop the morning."""
        self.data["updated_at"] = datetime.now(self.zone).isoformat(timespec="seconds")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=2, default=str),
                                 encoding="utf-8")
        except (OSError, TypeError, ValueError):
            pass


# ---------------------------------------------------------------------------
# The day's state, the only thing that survives between ticks
# ---------------------------------------------------------------------------


def state_path(day: date) -> Path:
    """output/preopen_state_YYYY-MM-DD.json, one file a day."""
    return output_dir() / f"preopen_state_{day.isoformat()}.json"


def new_state(day: date) -> dict:
    """An empty morning."""
    return {
        "day": day.isoformat(),
        "candidates": {},
        "history_started_at": None,
        "history_requests": [],
        "history_recorded": False,
        "last_scan_at": None,
        "scans": 0,
        "watch_list": [],
        "lines_available": None,
        "lines_claimed": 0,
        "subscribed_at": None,
        "subscribe_recorded": False,
        "late": [],
        "shortlist": [],
        "dropped": [],
        "ranked_at": None,
        "notes": [],
    }


def read_state(day: date) -> dict:
    """Today's state, or a fresh one when there is nothing readable on disk.

    Like the cache, this never raises. A state file that cannot be read means
    the morning starts again from whatever the cache still holds, which is
    slower but correct. A crash here would mean no pre-open at all.
    """
    try:
        loaded = json.loads(state_path(day).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return new_state(day)
    if not isinstance(loaded, dict):
        return new_state(day)
    base = new_state(day)
    base.update(loaded)
    base["day"] = day.isoformat()
    if not isinstance(base.get("candidates"), dict):
        base["candidates"] = {}
    return base


def write_state(state: dict, day: date, now: datetime | None = None) -> bool:
    """Save the state. True when it was written."""
    state["updated_at"] = (now or datetime.now(EASTERN)).isoformat(timespec="seconds")
    path = state_path(day)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.part")
        temporary.write_text(json.dumps(state, indent=2, default=str),
                             encoding="utf-8")
        temporary.replace(path)
        return True
    except (OSError, TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Which part of the morning are we in
# ---------------------------------------------------------------------------


def phase_for(now: datetime, settings: Settings | None = None) -> str:
    """Work out from the clock alone what this tick owes.

    Nothing here asks whether the market is open today. The loop already knows
    about weekends and holidays and does not call this on a day the market is
    shut, and two places deciding the same thing is two places to get it wrong.
    """
    settings = settings or Settings()
    at = now.time()
    start = parse_clock(settings.preopen_start, clock_time(9, 0))
    history_by = parse_clock(settings.preopen_history_done_by, clock_time(9, 26))
    subscribe_by = parse_clock(settings.preopen_subscribe_done_by, clock_time(9, 29))
    pick = parse_clock(settings.pick_time, clock_time(9, 35))

    if at < start:
        return PHASE_TOO_EARLY
    if at < history_by:
        return PHASE_GATHER
    if at < subscribe_by:
        return PHASE_SUBSCRIBE
    if at < pick:
        return PHASE_WATCH
    pick_moment = datetime.combine(now.date(), pick, tzinfo=now.tzinfo)
    if now < pick_moment + timedelta(minutes=PICK_WINDOW_MINUTES):
        return PHASE_RANK
    return PHASE_DONE


def contract_for(symbol: str) -> dict:
    """One ordinary US share, in IBKR's own words."""
    return {"symbol": str(symbol).upper(), "secType": "STK",
            "exchange": "SMART", "currency": "USD"}


# ---------------------------------------------------------------------------
# The gap scan
# ---------------------------------------------------------------------------


def universe_path() -> Path:
    """output/preopen_universe.json, the list of names to look at before the bell.

    A plain JSON list of symbols, or an object with a "symbols" list in it. The
    pre-open does not build this list itself: agent/broker.py's protocol has no
    scanner call in it, so the names come either from the caller or from this
    file, which whatever builds the morning universe writes.
    """
    return output_dir() / "preopen_universe.json"


def load_universe() -> list[str]:
    """The symbols to gap scan, or an empty list when nobody has said.

    Never raises. An empty list means this tick's scan looks at nothing and says
    so in its notes, which is a great deal easier to understand at 9:05 than a
    traceback.
    """
    try:
        loaded = json.loads(universe_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return []
    if isinstance(loaded, dict):
        loaded = loaded.get("symbols")
    if not isinstance(loaded, list):
        return []
    out: list[str] = []
    for item in loaded:
        symbol = str(item or "").strip().upper()
        if symbol and symbol not in out:
            out.append(symbol)
    return out


def gap_scan(broker: Any, symbols: Sequence[str],
             price_floor: float = DEFAULT_PRICE_FLOOR) -> list[dict]:
    """Snapshot the universe and work out how far each name has gapped.

    One snapshot call per fifty names, so a hundred names is two calls and the
    whole scan finishes inside its five second budget. A snapshot is not a
    historical request, so none of this touches the pacing ration.

    Comes back biggest move first, measured as a percent of yesterday's close
    and ignoring the sign, so a name down nine percent ranks with a name up nine
    percent. Names below the price floor and names with no readable gap are left
    out.
    """
    rows: list[dict] = []
    wanted = [str(symbol).upper() for symbol in symbols or []]
    floor = _number(price_floor) or 0.0
    for start in range(0, len(wanted), SNAPSHOT_CHUNK):
        chunk = wanted[start:start + SNAPSHOT_CHUNK]
        try:
            answer = broker.snapshot([contract_for(symbol) for symbol in chunk]) or {}
        except Exception:                                         # noqa: BLE001
            # A snapshot that fails costs us this chunk and nothing else. The
            # next tick asks again three minutes later.
            continue
        for row in (answer.get("snapshots") or []):
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").upper()
            if not symbol:
                continue
            last = _number(row.get("last")) or _number(row.get("marketPrice"))
            previous_close = _number(row.get("close")) or _number(row.get("prevClose"))
            gap = gap_percent(last, previous_close)
            if gap is None or last is None or last < floor:
                continue
            rows.append({"symbol": symbol, "last": last,
                         "previous_close": previous_close,
                         "gap_pct": round(gap, 3)})
    rows.sort(key=lambda item: (-abs(item["gap_pct"]), item["symbol"]))
    return rows


def consider_late_gapper(state: dict, symbol: str, now: datetime,
                         row: dict | None = None) -> tuple[bool, str]:
    """Can a name that only started moving after 9:28 still be traded today.

    It joins if a streaming line is free, and otherwise it is turned away and
    the reason is written down. That is rule five of the design document. The
    reason matters: at the end of the month the question "did we miss anything
    good" has to be answerable, and a name that silently never appeared cannot
    be counted.

    Comes back as (joined, reason).
    """
    symbol = str(symbol).upper()
    watch = list(state.get("watch_list") or [])
    if symbol in watch:
        return True, "already on the watch list"

    claimed = len(watch)
    available = state.get("lines_available")
    available = int(available) if isinstance(available, int) else STREAMING_LINES_WANTED
    if claimed >= available:
        reason = (f"no streaming line free, {claimed} of {available} already "
                  "claimed at 9:28")
        state.setdefault("late", []).append(
            {"symbol": symbol, "at": now.isoformat(timespec="seconds"),
             "joined": False, "reason": reason})
        return False, reason

    watch.append(symbol)
    state["watch_list"] = watch
    state["lines_claimed"] = len(watch)
    reason = f"joined late on a free line, {len(watch)} of {available} now claimed"
    state.setdefault("late", []).append(
        {"symbol": symbol, "at": now.isoformat(timespec="seconds"),
         "joined": True, "reason": reason})
    if row:
        state.setdefault("candidates", {})[symbol] = {
            "symbol": symbol, "last": row.get("last"),
            "previous_close": row.get("previous_close"),
            "gap_pct": row.get("gap_pct"),
            "first_seen": now.isoformat(timespec="seconds"),
            "late": True, CACHE_BARS5M: False, CACHE_DAILY: False}
    return True, reason


# ---------------------------------------------------------------------------
# The history pulls
# ---------------------------------------------------------------------------


def pull_history(broker: Any, state: dict, day: date, now: datetime,
                 pacer: Pacer, symbols: Sequence[str] | None = None) -> dict:
    """Fetch what the 9:35 ranking will need, slowly, and write it to disk.

    Two requests per name: the five minute bars behind the relative volume
    baseline, and the daily bars behind the average true range and the liquidity
    floor. Biggest gap first, because if the budget runs out it should run out
    on the names least likely to be picked.

    A name whose file is already in the cache costs nothing. That is what makes
    a restart cheap: the second run of the morning finds most of its work
    already done.

    Comes back as a small summary of what this tick managed.
    """
    candidates = state.setdefault("candidates", {})
    order = list(symbols) if symbols is not None else [
        item["symbol"] for item in sorted(
            candidates.values(),
            key=lambda row: (-abs(_number(row.get("gap_pct")) or 0.0),
                             str(row.get("symbol"))))]

    pulled = 0
    skipped_for_pacing = 0
    failures: list[str] = []
    for symbol in order:
        record = candidates.get(symbol)
        if record is None:
            continue
        for kind, duration, size in ((CACHE_BARS5M, BARS5M_DURATION, BARS5M_SIZE),
                                     (CACHE_DAILY, DAILY_DURATION, DAILY_SIZE)):
            if record.get(kind):
                continue
            if read_cache(symbol, day, kind) is not None:
                record[kind] = True
                continue
            if not pacer.take(now):
                skipped_for_pacing += 1
                state["history_requests"] = pacer.as_stamps(now)
                return {"pulled": pulled, "waiting": skipped_for_pacing,
                        "failures": failures}
            if state.get("history_started_at") is None:
                state["history_started_at"] = now.isoformat(timespec="seconds")
            try:
                answer = broker.historical_bars(contract_for(symbol), duration, size,
                                                what="TRADES", use_rth=True) or {}
                bars = answer.get("bars") or []
            except Exception as problem:                          # noqa: BLE001
                failures.append(f"{symbol} {kind}: {problem}")
                continue
            if write_cache(symbol, day, kind, bars):
                record[kind] = True
                pulled += 1
            else:
                failures.append(f"{symbol} {kind}: could not be written to the cache")

    state["history_requests"] = pacer.as_stamps(now)
    return {"pulled": pulled, "waiting": skipped_for_pacing, "failures": failures}


def history_outstanding(state: dict) -> list[str]:
    """Which candidates still have a piece of their history missing."""
    missing: list[str] = []
    for symbol, record in (state.get("candidates") or {}).items():
        if not record.get(CACHE_BARS5M) or not record.get(CACHE_DAILY):
            missing.append(symbol)
    return sorted(missing)


# ---------------------------------------------------------------------------
# The subscribe step, and the honest limit on it
# ---------------------------------------------------------------------------


def opening_range_path(day: date) -> Path:
    """Where a resident streaming process would write the real opening range.

    Nothing writes this file today. See the note in subscribe() below.
    """
    return output_dir() / f"preopen_opening_range_{day.isoformat()}.json"


def read_opening_range(day: date) -> dict[str, dict]:
    """The streamed 9:30 to 9:35 candles, when something built them. Never raises."""
    try:
        loaded = json.loads(opening_range_path(day).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    if isinstance(loaded, dict) and isinstance(loaded.get("symbols"), dict):
        loaded = loaded["symbols"]
    if not isinstance(loaded, dict):
        return {}
    return {str(key).upper(): value for key, value in loaded.items()
            if isinstance(value, dict)}


def subscribe(state: dict, now: datetime,
              lines_available: int | None = None) -> dict:
    """Settle the final watch list and record which streaming lines it claims.

    THE HONEST LIMIT, WORTH READING BEFORE TRUSTING THIS

    A streaming subscription belongs to a process. This process exits a second
    from now, and the moment it does, every line it opened is closed by the
    Gateway. So nothing here actually subscribes to anything, and pretending
    otherwise would be the worst kind of lie to leave in a trading system: the
    kind that only shows up as a wrong number in a real trade.

    What this step really does is decide and write down which hundred names the
    9:35 ranking is about, and which of them would have claimed a line. Building
    the 9:30 to 9:35 candle from live ticks needs a process that stays alive
    from 9:28 to 9:35, and there is not one yet. Until there is, the ranking
    reads the 9:30 five minute bar back out of history instead, which is one
    request per name and is capped, see OPENING_BAR_FALLBACK_CAP above. That is
    the halfway version, and it is honest about being one.

    When a resident process is eventually built, it writes the streamed candles
    to output/preopen_opening_range_YYYY-MM-DD.json and the ranking below reads
    them from there in preference to asking for bars. That hook is already in
    place, so the change is one process, not a rewrite.
    """
    available = (int(lines_available) if lines_available is not None
                 else STREAMING_LINES_WANTED)
    candidates = state.get("candidates") or {}
    ready = [record for record in candidates.values()
             if record.get(CACHE_BARS5M) and record.get(CACHE_DAILY)]
    ready.sort(key=lambda row: (-abs(_number(row.get("gap_pct")) or 0.0),
                                str(row.get("symbol"))))

    note = ""
    if available < STREAMING_LINES_WANTED:
        keep = min(STREAMING_LINES_FALLBACK, available)
        note = (f"Gateway reported {available} streaming lines, not "
                f"{STREAMING_LINES_WANTED}, so the watch list was cut to the top "
                f"{keep} names by gap.")
    else:
        keep = min(MAX_CANDIDATES_TRACKED, available)

    watch = [str(row["symbol"]).upper() for row in ready[:keep]]
    state["watch_list"] = watch
    state["lines_available"] = available
    state["lines_claimed"] = len(watch)
    state["subscribed_at"] = now.isoformat(timespec="seconds")
    if note:
        state.setdefault("notes", []).append(note)
    return {"watch_list": len(watch), "lines_available": available, "note": note}


# ---------------------------------------------------------------------------
# The 9:35 ranking
# ---------------------------------------------------------------------------


def opening_window_for(symbol: str, day: date, settings: Settings,
                       streamed: dict[str, dict], broker: Any,
                       fetches_left: int) -> tuple[dict | None, str, int]:
    """Today's 9:30 to 9:35 candle for one name, from the best source we have.

    In order: the streamed file if a resident process ever wrote one, then the
    cached five minute bars if the pull that happened before the bell already
    reaches into today, then one fresh request for today's bars.

    Comes back as (candle, where it came from, how many fetches are left).
    """
    start, end = settings.window
    streamed_row = streamed.get(symbol.upper())
    if streamed_row:
        return dict(streamed_row), "streamed ticks", fetches_left

    cached = cached_bars(symbol, day, CACHE_BARS5M)
    candle = window_bar(cached, day, start, end)
    if candle is not None:
        return candle, "cached five minute bars", fetches_left

    if broker is None or fetches_left <= 0:
        return None, "no source", fetches_left
    try:
        answer = broker.historical_bars(contract_for(symbol), "1 D", BARS5M_SIZE,
                                        what="TRADES", use_rth=True) or {}
        bars = answer.get("bars") or []
    except Exception:                                             # noqa: BLE001
        return None, "the request for today's bars failed", fetches_left - 1
    candle = window_bar(bars, day, start, end)
    return candle, "today's five minute bars", fetches_left - 1


def rank(state: dict, day: date, settings: Settings, broker: Any = None) -> dict:
    """Score every name on the watch list and cut it down to the shortlist.

    Four tests, in the order the strategy states them:

        relative volume on the 9:30 to 9:35 window against the same window over
            the prior fourteen sessions, with a floor of 2.0
        the volatility filter, average true range above fifty cents and above
            1.5 percent of the price
        the direction rule, which takes its side from the sign of that same
            candle and refuses to trade a flat one
        the plain universe floors, price and average dollar volume and enough
            history to have a normal at all

    Everything a name fails is written down with its reason, because at month
    end the names that were nearly picked are as interesting as the ones that
    were.
    """
    watch = [str(symbol).upper() for symbol in (state.get("watch_list") or [])]
    streamed = read_opening_range(day)
    fetches_left = OPENING_BAR_FALLBACK_CAP
    start, end = settings.window

    rows: list[dict] = []
    dropped: list[dict] = []
    for symbol in watch:
        candle, source, fetches_left = opening_window_for(
            symbol, day, settings, streamed, broker, fetches_left)
        if candle is None:
            dropped.append({"symbol": symbol,
                            "reason": f"no 9:30 to 9:35 candle ({source})"})
            continue

        five_minute = cached_bars(symbol, day, CACHE_BARS5M)
        daily = cached_bars(symbol, day, CACHE_DAILY)
        baseline = baseline_window_volumes(five_minute, day, start, end,
                                           settings.rel_volume_baseline_days)
        ratio, baseline_days = relative_volume_open_window(candle.get("volume"), baseline)
        atr, atr_sessions = average_true_range(daily, settings.atr_days)
        dollars, daily_sessions = average_dollar_volume(daily,
                                                        settings.dollar_volume_sessions)
        price = _number(candle.get("close"))
        direction = direction_from_candle(candle.get("open"), candle.get("close"))

        row = {
            "symbol": symbol,
            "relative_volume": None if ratio is None else round(ratio, 3),
            "baseline_days": baseline_days,
            "direction": direction,
            "atr": None if atr is None else round(atr, 4),
            "atr_sessions": atr_sessions,
            "price": price,
            "open_window_volume": _number(candle.get("volume")),
            "open_window_open": _number(candle.get("open")),
            "open_window_close": price,
            "avg_dollar_volume": None if dollars is None else round(dollars, 2),
            "daily_sessions": daily_sessions,
            "gap_pct": (state.get("candidates") or {}).get(symbol, {}).get("gap_pct"),
            "opening_range_source": source,
        }

        if daily_sessions < settings.min_history_sessions:
            dropped.append({"symbol": symbol,
                            "reason": f"only {daily_sessions} sessions of history, "
                                      f"{settings.min_history_sessions} needed"})
            continue
        if price is None or price < settings.price_floor:
            dropped.append({"symbol": symbol,
                            "reason": f"price {price} is under the floor of "
                                      f"{settings.price_floor}"})
            continue
        if dollars is None or dollars < settings.min_avg_dollar_volume:
            dropped.append({"symbol": symbol,
                            "reason": "average dollar volume is under the floor of "
                                      f"{settings.min_avg_dollar_volume:,.0f}"})
            continue
        if ratio is None or ratio < settings.rel_volume_min:
            dropped.append({"symbol": symbol,
                            "reason": f"relative volume {ratio} is under the floor of "
                                      f"{settings.rel_volume_min}"})
            continue
        if not passes_volatility(atr, price, settings.min_atr_usd,
                                 settings.min_atr_pct_of_price):
            dropped.append({"symbol": symbol,
                            "reason": f"average true range {atr} fails the volatility "
                                      "filter"})
            continue
        if direction is None:
            dropped.append({"symbol": symbol,
                            "reason": "the 9:30 to 9:35 candle was flat, so there is "
                                      "no side to take"})
            continue
        rows.append(row)

    ranked = rank_candidates(rows)[:max(1, settings.max_candidates)]
    state["shortlist"] = ranked
    state["dropped"] = dropped
    return {"shortlist": ranked, "dropped": dropped, "looked_at": len(watch),
            "fetches_used": OPENING_BAR_FALLBACK_CAP - fetches_left}


# ---------------------------------------------------------------------------
# The one entry point the loop calls
# ---------------------------------------------------------------------------


def step(now: datetime, broker: Any = None, universe: Sequence[str] | None = None,
         settings: Settings | None = None, lines_available: int | None = None,
         timings: Timings | None = None) -> dict:
    """Do whatever this one minute of the morning owes, then save and return.

    now is the time in New York. broker is anything matching the Broker protocol
    in agent/broker.py; only its read methods are ever called. universe is the
    list of symbols to gap scan, and when it is not given the list is read from
    output/preopen_universe.json.

    Nothing here loops and nothing here sleeps. The tick that runs at 9:05 does
    one gap scan and up to four historical requests and then the process ends.
    The tick at 9:06 picks the work up from the state file.
    """
    settings = settings or load_settings()
    day = now.date()
    state = read_state(day)
    timings = timings or Timings(day, budgets_from_settings(settings))
    phase = phase_for(now, settings)
    did: list[str] = []
    notes: list[str] = []

    symbols = list(universe) if universe is not None else load_universe()
    pacer = Pacer.from_stamps(state.get("history_requests"), HISTORY_REQUESTS_PER_MINUTE)

    if phase == PHASE_TOO_EARLY:
        notes.append(f"nothing to do before {settings.preopen_start}")

    elif phase == PHASE_GATHER:
        if broker is None:
            notes.append("no broker was handed in, so nothing was fetched")
        else:
            if _scan_is_due(state, now):
                with timings.timing("scan", now):
                    found = gap_scan(broker, symbols, settings.price_floor)
                added = _remember_candidates(state, found, now)
                state["last_scan_at"] = now.isoformat(timespec="seconds")
                state["scans"] = int(state.get("scans") or 0) + 1
                did.append(f"gap scan looked at {len(symbols)} names, kept "
                           f"{len(state['candidates'])}, {added} of them new")
            else:
                notes.append("the last gap scan was less than "
                             f"{SCAN_EVERY_MINUTES} minutes ago")
            summary = pull_history(broker, state, day, now, pacer)
            did.append(f"pulled {summary['pulled']} history file(s), "
                       f"{len(history_outstanding(state))} name(s) still waiting")
            for failure in summary["failures"]:
                notes.append(f"history problem: {failure}")
            if not history_outstanding(state) and state.get("history_started_at"):
                _close_history_step(state, timings, now, "every candidate has its history")

    elif phase == PHASE_SUBSCRIBE:
        _close_history_step(state, timings, now,
                            f"{len(history_outstanding(state))} name(s) never got "
                            "their history")
        if state.get("subscribed_at"):
            notes.append("the watch list was already settled on an earlier tick")
        else:
            with timings.timing("subscribe", now,
                                budget_name="subscribe_done_by"):
                summary = subscribe(state, now, lines_available)
            state["subscribe_recorded"] = True
            did.append(f"settled a watch list of {summary['watch_list']} name(s)")
            if summary["note"]:
                notes.append(summary["note"])

    elif phase == PHASE_WATCH:
        _close_history_step(state, timings, now, "the history window has closed")
        _close_subscribe_step(state, timings, now)
        if broker is None:
            notes.append("no broker was handed in, so no late gapper was looked for")
        elif _scan_is_due(state, now):
            with timings.timing("scan", now):
                found = gap_scan(broker, symbols, settings.price_floor)
            state["last_scan_at"] = now.isoformat(timespec="seconds")
            state["scans"] = int(state.get("scans") or 0) + 1
            joined: list[str] = []
            for row in found[:MAX_CANDIDATES_TRACKED]:
                symbol = row["symbol"]
                if symbol in (state.get("candidates") or {}):
                    continue
                accepted, reason = consider_late_gapper(state, symbol, now, row)
                (joined.append(symbol) if accepted else notes.append(
                    f"{symbol} arrived late and was skipped: {reason}"))
            if joined:
                did.append(f"{len(joined)} late gapper(s) joined: {', '.join(joined)}")
                pull_history(broker, state, day, now, pacer, symbols=joined)
            else:
                did.append("gap scan found no new name with a line free")
        else:
            notes.append("nothing to do but wait for the bell")

    elif phase == PHASE_RANK:
        _close_history_step(state, timings, now, "the history window has closed")
        _close_subscribe_step(state, timings, now)
        if state.get("ranked_at"):
            notes.append("the shortlist was already made on an earlier tick")
        else:
            with timings.timing("rank", now):
                summary = rank(state, day, settings, broker)
            state["ranked_at"] = now.isoformat(timespec="seconds")
            did.append(f"ranked {summary['looked_at']} name(s) down to a shortlist of "
                       f"{len(summary['shortlist'])}")
            if summary["fetches_used"]:
                notes.append(f"{summary['fetches_used']} opening bar(s) had to be "
                             "fetched, because no process was holding a live "
                             "subscription")

    else:
        if not state.get("ranked_at"):
            notes.append("the pick window has closed and no shortlist was made today")
        else:
            notes.append("the pre-open is finished for today")

    write_state(state, day, now)
    return {
        "day": day.isoformat(),
        "phase": phase,
        "did": did,
        "notes": notes,
        "candidates": len(state.get("candidates") or {}),
        "watch_list": len(state.get("watch_list") or []),
        "shortlist": list(state.get("shortlist") or []),
        "state_path": str(state_path(day)),
        "timings_path": str(timings.path),
        "cache_dir": str(cache_dir(create=False)),
    }


def _scan_is_due(state: dict, now: datetime) -> bool:
    """Has it been long enough since the last gap scan."""
    last = state.get("last_scan_at")
    if not last:
        return True
    try:
        moment = datetime.fromisoformat(str(last))
    except (TypeError, ValueError):
        return True
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=EASTERN)
    return (now - moment) >= timedelta(minutes=SCAN_EVERY_MINUTES)


def _remember_candidates(state: dict, found: Sequence[dict], now: datetime) -> int:
    """Fold a scan's answers into the candidate list. Returns how many are new.

    The list is capped at a hundred names, biggest gap first. A name already on
    the list keeps the moment it was first seen, because that is what tells a
    late arrival from an early one.
    """
    candidates = state.setdefault("candidates", {})
    added = 0
    for row in found:
        symbol = row["symbol"]
        existing = candidates.get(symbol)
        if existing is None:
            candidates[symbol] = {
                "symbol": symbol, "last": row.get("last"),
                "previous_close": row.get("previous_close"),
                "gap_pct": row.get("gap_pct"),
                "first_seen": now.isoformat(timespec="seconds"),
                "late": False, CACHE_BARS5M: False, CACHE_DAILY: False}
            added += 1
        else:
            existing["last"] = row.get("last")
            existing["previous_close"] = row.get("previous_close")
            existing["gap_pct"] = row.get("gap_pct")

    if len(candidates) > MAX_CANDIDATES_TRACKED:
        ordered = sorted(candidates.values(),
                         key=lambda item: (-abs(_number(item.get("gap_pct")) or 0.0),
                                           str(item.get("symbol"))))
        state["candidates"] = {row["symbol"]: row
                               for row in ordered[:MAX_CANDIDATES_TRACKED]}
    return added


def _close_history_step(state: dict, timings: Timings, now: datetime,
                        detail: str) -> None:
    """Write the history step into the timings file, once, with its deadline.

    The step spans about twenty six ticks, so nothing is still running when it
    ends. The start time is read back out of the state file and the finish time
    is now. Called both when the pulls finish early and when the deadline
    arrives with work outstanding, which is exactly when the budget alert should
    fire.
    """
    if state.get("history_recorded") or timings.already_recorded("history"):
        state["history_recorded"] = True
        return
    started = state.get("history_started_at")
    if not started and not history_outstanding(state):
        # A morning where the gap scan found nothing, or where the cache already
        # held everything, never started this step at all. There is nothing to
        # be late for, so it is written down as done on time rather than waking
        # Mo up over work that did not need doing. An alert that cries wolf is
        # an alert that gets ignored on the morning it matters.
        due = timings.deadline_moment("history_done_by") or now
        moment = min(now, due)
        timings.record("history", moment, moment, budget_name="history_done_by",
                       detail="no name needed a history pull this morning")
        state["history_recorded"] = True
        return
    try:
        began = datetime.fromisoformat(str(started)) if started else now
    except (TypeError, ValueError):
        began = now
    if began.tzinfo is None:
        began = began.replace(tzinfo=EASTERN)
    timings.record("history", began, now, budget_name="history_done_by", detail=detail)
    state["history_recorded"] = True


def _close_subscribe_step(state: dict, timings: Timings, now: datetime) -> None:
    """Write the subscribe step down when the deadline passed without one.

    A morning where the subscribe tick never ran leaves no watch list, and that
    has to be visible rather than showing up later as an empty shortlist.
    """
    if state.get("subscribe_recorded") or timings.already_recorded("subscribe"):
        state["subscribe_recorded"] = True
        return
    timings.record("subscribe", now, now, budget_name="subscribe_done_by",
                   detail="the subscribe tick never ran, so there is no watch list")
    state["subscribe_recorded"] = True


# ---------------------------------------------------------------------------
# Running it by hand
# ---------------------------------------------------------------------------


def parse_now(text: str | None, zone: ZoneInfo = EASTERN) -> datetime:
    """The current time, or the pretend time from --now, in New York.

    The same shapes agent/loop.py accepts, so the two can be driven with the
    same argument on the same morning.
    """
    if not text:
        return datetime.now(zone)
    raw = text.strip()
    for shape in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S",
                  "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(raw, shape).replace(tzinfo=zone)
        except ValueError:
            continue
    for shape in ("%H:%M:%S", "%H:%M"):
        try:
            wanted = datetime.strptime(raw, shape).time()
            return datetime.combine(datetime.now(zone).date(), wanted, tzinfo=zone)
        except ValueError:
            continue
    raise SystemExit(f'preopen: cannot read --now {text!r}. '
                     'Try --now "2026-09-08 09:12"')


def main(argv: list[str] | None = None) -> int:
    """A dry run: say what this minute owes, touch nothing but output/."""
    parser = argparse.ArgumentParser(
        description="The pre-open run for the momentum books. Reads only: it "
                    "never sends, changes or pulls an order.")
    parser.add_argument("--now", metavar="WHEN",
                        help='pretend it is this time, New York time, for example '
                             '"2026-09-08 09:12". Lets a phase be tried after hours.')
    parser.add_argument("--universe", metavar="SYMBOLS", default="",
                        help="comma separated symbols to pretend the gap scan sees. "
                             "Without it the list comes from "
                             "output/preopen_universe.json.")
    args = parser.parse_args(argv)

    now = parse_now(args.now)
    settings = load_settings()
    universe = [part.strip().upper() for part in args.universe.split(",") if part.strip()]

    print("=" * 78)
    print(f"Pre-open dry run at {now:%Y-%m-%d %H:%M:%S} {now.tzname()}"
          + ("  (pretend time from --now)" if args.now else ""))
    print(f"Settings from {settings.source}")
    print("=" * 78)

    # No broker is attached, so nothing here can reach the network. What it
    # shows is the clock arithmetic and the paths, which is what a person
    # checking the schedule on a shut market actually wants to see.
    answer = step(now, broker=None, universe=universe or None, settings=settings)

    print(f"\nPhase: {answer['phase']}")
    for line in answer["did"]:
        print(f"  did:  {line}")
    for line in answer["notes"]:
        print(f"  note: {line}")
    print(f"\nCandidates so far: {answer['candidates']}")
    print(f"Watch list:        {answer['watch_list']}")
    print(f"Shortlist:         {len(answer['shortlist'])}")
    print("\nWhere everything is written:")
    print(f"  state:   {answer['state_path']}")
    print(f"  timings: {answer['timings_path']}")
    print(f"  cache:   {answer['cache_dir']}")
    print("\nBudgets, three durations in seconds and three wall clock deadlines:")
    for name, budget in budgets_from_settings(settings).items():
        kind = "seconds" if isinstance(budget, (int, float)) else "New York time"
        print(f"  {name:<22} {budget} {kind}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

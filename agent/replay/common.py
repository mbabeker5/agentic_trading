"""Shared plumbing for the replay harness.

Three scripts sit on top of this file:

  * agent/replay/fetch_history.py   pulls past bars from IB Gateway
  * agent/replay/record_day.py      records one live trading day
  * agent/replay/fake_broker.py     replays what they recorded, with fills

What lives here is only the boring shared parts: where files go, how a line is
appended to a JSONL file, how a manifest is written, how the historical-data
budget is rationed, and how a read-only connection to IB Gateway is opened and
reopened when Gateway restarts.

Nothing in this file can place an order. It opens the connection with
readonly=True and never calls anything but reads. That is deliberate and is not
an oversight to be fixed later: the whole point of the replay harness is that
the loop can be exercised end to end without a live order existing anywhere.

File layout, all under the project root
(/Users/mtalib/workspace_repos/personal_repo/agentic_trading unless the
environment variable AGENTIC_TRADING_ROOT says otherwise):

    output/recordings/history/SPY.jsonl        past bars, one file per symbol
    output/recordings/history/manifest.json    what was fetched and what is missing
    output/recordings/2026-09-08/snapshots.jsonl   one line per symbol per tick
    output/recordings/2026-09-08/bars_5m.jsonl     the latest five minute bar
    output/recordings/2026-09-08/ticks.jsonl       one line per tick, for gaps
    output/recordings/2026-09-08/scanner_0935.json the scanner's own output
    output/recordings/2026-09-08/manifest.json     counts, gaps, how it ended

output/ is gitignored, so recordings never land in git.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from contextlib import asynccontextmanager
from datetime import date as date_type, datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

log = logging.getLogger("replay.common")

#: Everything in this project is timed in New York, including the recorder.
EASTERN = ZoneInfo("America/New_York")

#: The environment variable that moves the whole project somewhere else.
ROOT_ENV_VAR = "AGENTIC_TRADING_ROOT"

#: Where the project lives when nothing overrides it.
DEFAULT_ROOT = Path("/Users/mtalib/workspace_repos/personal_repo/agentic_trading")

#: IB Gateway, paper account. The live port is 4001 and is never used here.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4002

#: One client id per program, so two of them can run at once without one
#: kicking the other off the Gateway connection.
FETCHER_CLIENT_ID = 260
RECORDER_CLIENT_ID = 261

#: The two benchmarks recorded every single tick, whatever else is going on.
BENCHMARK_SYMBOLS = ("SPY", "QQQ")

#: The fallback universe for fetch_history.py when there is no shortlist to
#: read. Twenty liquid US names, chosen so every one of them trades far more
#: than the strategy's 20 million dollar a day floor and so a replay day has
#: real spreads in it rather than one tick of noise.
DEFAULT_UNIVERSE = (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "NFLX",
    "AVGO", "INTC", "MU", "PLTR", "COIN", "SOFI", "F", "BAC", "XLF", "IWM",
    "SMCI",
)

# IB Gateway rations historical-data requests at roughly sixty in any ten
# minute window, counted across every client on the connection. Go over and it
# starts refusing requests, and the refusals last well past the window. The
# numbers below sit under that on purpose.
HISTORY_LIMIT_PER_WINDOW = 60
HISTORY_WINDOW_SECONDS = 600.0
#: What we actually allow ourselves. Five requests of headroom for the scanner
#: or a Claude Code session sharing the same Gateway.
HISTORY_BUDGET_PER_WINDOW = 55
#: Never fire two requests closer together than this, even with budget left.
HISTORY_MIN_GAP_SECONDS = 1.0

#: Gateway chatter that means "nothing to send you", not "something broke".
#: 162 is the historical data service's catch-all and covers both a genuine
#: pacing violation and a plain "no data for this contract", so its message
#: text has to be read rather than just its number.
BENIGN_ERROR_CODES = frozenset({162, 165, 200, 202, 300, 354, 366, 2104, 2106,
                                2107, 2108, 2119, 2137, 2158})

#: Error 162 with these words in it means we asked too fast, not that the data
#: is missing. The right answer is to wait and try again.
PACING_PHRASES = ("pacing violation", "max number of requests", "too many requests")

MARKET_DATA_TYPE_LABELS = {1: "live", 2: "frozen", 3: "delayed", 4: "delayed frozen"}


# ------------------------------------------------------------------- folders

def project_root() -> Path:
    """The project folder, from AGENTIC_TRADING_ROOT or the default."""
    raw = (os.environ.get(ROOT_ENV_VAR) or "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_ROOT


def output_dir(create: bool = True) -> Path:
    path = project_root() / "output"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def recordings_dir(create: bool = True) -> Path:
    """output/recordings/, the root of everything the harness writes."""
    path = output_dir(create) / "recordings"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def history_dir(create: bool = True) -> Path:
    """output/recordings/history/, one JSONL file per symbol of past bars."""
    path = recordings_dir(create) / "history"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def day_dir(day: date_type | str, create: bool = True) -> Path:
    """output/recordings/YYYY-MM-DD/, one live trading day as it happened."""
    name = day if isinstance(day, str) else f"{day:%Y-%m-%d}"
    path = recordings_dir(create) / name
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


# --------------------------------------------------------------------- JSONL

def append_jsonl(path: Path, record: dict) -> None:
    """Add one record to a JSONL file, creating it if it is not there.

    Opened, written and closed on every call rather than held open. A recorder
    that runs for six and a half hours will be killed at some point, by a
    reboot or by a person, and a file that was flushed after every line loses
    nothing when that happens. The cost is one open per record, which at a few
    dozen records every five minutes is nothing at all.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, default=str, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_jsonl(path: Path) -> Iterator[dict]:
    """Every record in a JSONL file, skipping any line that is not JSON.

    A half written last line is normal when a recorder was killed mid write,
    so it is skipped rather than treated as a disaster.
    """
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                log.warning("skipping a line in %s that is not JSON", path)


def write_json(path: Path, payload: Any) -> None:
    """Write one JSON file, all at once, through a temporary file.

    Through a temporary file so a manifest that is rewritten every five minutes
    is never found half written by whatever is reading it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    temporary.replace(path)


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        log.warning("%s is not readable JSON", path)
        return None


# ------------------------------------------------------------------ contracts

def stock_contract_dict(symbol: str, con_id: Any = None,
                        primary_exchange: str | None = None) -> dict:
    """One US stock, in IBKR's own field names.

    The same shape agent/mcp_client.py and agent/loop.py pass around, so a
    contract can travel between the real client and the fake broker untouched.
    """
    contract: dict[str, Any] = {"symbol": str(symbol).upper(), "secType": "STK",
                                "exchange": "SMART", "currency": "USD"}
    if con_id:
        contract["conId"] = con_id
    if primary_exchange:
        contract["primaryExchange"] = primary_exchange
    return contract


def symbol_of(contract: Any) -> str:
    """The ticker out of a contract, whether it is a dict, an object or a string."""
    if contract is None:
        return ""
    if isinstance(contract, str):
        return contract.upper()
    if isinstance(contract, dict):
        return str(contract.get("symbol") or "").upper()
    return str(getattr(contract, "symbol", "") or "").upper()


# ------------------------------------------------------------------ shortlists

def latest_shortlist_path(folder: Path | None = None) -> Path | None:
    """The newest output/shortlist_*.json, or None when there is not one.

    Files named shortlist_test.json and the like are ignored: only the dated
    ones written by a real scan count, because a test file could quietly send
    the fetcher after the wrong twenty names.
    """
    folder = folder or output_dir()
    if not folder.exists():
        return None
    dated = []
    for path in folder.glob("shortlist_*.json"):
        stem = path.stem[len("shortlist_"):]
        try:
            datetime.strptime(stem, "%Y-%m-%d")
        except ValueError:
            continue
        dated.append(path)
    if not dated:
        return None
    return max(dated, key=lambda p: p.stem)


def symbols_from_shortlist(path: Path | None) -> list[str]:
    """Every ticker in one scanner output file, in the order the scanner ranked them."""
    payload = read_json(path) if path else None
    if not isinstance(payload, dict):
        return []
    symbols: list[str] = []
    for candidate in payload.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        symbol = str(candidate.get("symbol") or "").upper().strip()
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols


def dedupe(symbols) -> list[str]:
    """Uppercase, strip, drop blanks and repeats, keep the original order."""
    seen: list[str] = []
    for raw in symbols or []:
        symbol = str(raw or "").upper().strip()
        if symbol and symbol not in seen:
            seen.append(symbol)
    return seen


# --------------------------------------------------------------------- pacing

class HistoryPacer:
    """Rations historical-data requests so Gateway stays friendly.

    Gateway counts requests in a sliding ten minute window and starts refusing
    everything on the connection once the count passes sixty. The window is a
    sliding one, so a fixed sleep between requests is not enough on a long run:
    this keeps the timestamp of every request it granted and, when the window
    is full, waits exactly long enough for the oldest one to fall out of it.

    Used from async code:

        async with pacer.slot():
            bars = await ib.reqHistoricalDataAsync(...)
    """

    def __init__(self, budget: int = HISTORY_BUDGET_PER_WINDOW,
                 window_seconds: float = HISTORY_WINDOW_SECONDS,
                 min_gap: float = HISTORY_MIN_GAP_SECONDS) -> None:
        self.budget = int(budget)
        self.window_seconds = float(window_seconds)
        self.min_gap = float(min_gap)
        self.granted = 0
        self.waited_seconds = 0.0
        self._times: list[float] = []
        self._lock = asyncio.Lock()

    def _forget_old(self, now: float) -> None:
        cutoff = now - self.window_seconds
        self._times = [t for t in self._times if t > cutoff]

    @property
    def used_in_window(self) -> int:
        self._forget_old(asyncio.get_event_loop().time())
        return len(self._times)

    @asynccontextmanager
    async def slot(self):
        """Wait until a request is allowed, then let one through."""
        loop = asyncio.get_running_loop()
        async with self._lock:
            while True:
                now = loop.time()
                self._forget_old(now)
                if len(self._times) >= self.budget:
                    oldest = min(self._times)
                    wait = max(0.05, oldest + self.window_seconds - now + 0.5)
                    log.info("pacing: %d requests used in the last %.0f seconds, "
                             "waiting %.0f seconds", len(self._times),
                             self.window_seconds, wait)
                    self.waited_seconds += wait
                    await asyncio.sleep(wait)
                    continue
                if self._times:
                    gap = self.min_gap - (now - max(self._times))
                    if gap > 0:
                        self.waited_seconds += gap
                        await asyncio.sleep(gap)
                        now = loop.time()
                self._times.append(now)
                self.granted += 1
                break
        yield

    async def wait_out_a_pacing_violation(self, seconds: float = 60.0) -> None:
        """Gateway said we asked too fast. Stop asking for a while.

        Also charges the window as full, so the next slot() does not sail
        straight back into another violation.
        """
        log.warning("Gateway reported a pacing violation, pausing %.0f seconds", seconds)
        self.waited_seconds += seconds
        await asyncio.sleep(seconds)


def is_pacing_message(message: str) -> bool:
    """True when an error 162 is really "you asked too fast"."""
    lowered = str(message or "").lower()
    return any(phrase in lowered for phrase in PACING_PHRASES)


# ---------------------------------------------------------------- connections

async def connect_ib(ib, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                     client_id: int = FETCHER_CLIENT_ID, attempts: int = 5,
                     first_wait: float = 2.0, timeout: float = 20.0) -> bool:
    """Open a read-only connection to IB Gateway, retrying with backoff.

    readonly=True keeps this client from touching orders. Worth being precise
    about what that flag is: it stops the client library asking about orders,
    it does not make Gateway refuse one. The belt and braces version is
    Gateway's own ReadOnlyApi setting in config/ibc.ini.

    Returns True when it connected and False when it gave up, rather than
    raising, because both callers want to carry on and write down that they
    could not connect rather than die.
    """
    wait = float(first_wait)
    for attempt in range(1, int(attempts) + 1):
        if ib.isConnected():
            return True
        try:
            await ib.connectAsync(host, port, clientId=client_id,
                                  readonly=True, timeout=timeout)
        except Exception as exc:                       # noqa: BLE001
            log.warning("attempt %d of %d: cannot reach IB Gateway at %s:%s as "
                        "client %s (%s)", attempt, attempts, host, port, client_id, exc)
        if ib.isConnected():
            log.info("connected to IB Gateway at %s:%s as client %s, read only",
                     host, port, client_id)
            return True
        if attempt < attempts:
            # A little randomness so two programs that both lost Gateway at the
            # same moment do not march back in step and collide again.
            jitter = wait * random.uniform(0.8, 1.2)
            log.info("waiting %.1f seconds before trying Gateway again", jitter)
            await asyncio.sleep(jitter)
            wait = min(wait * 2.0, 60.0)
    log.error("gave up connecting to IB Gateway at %s:%s after %d attempts",
              host, port, attempts)
    return False


async def ensure_connected(ib, host: str, port: int, client_id: int,
                           attempts: int = 5) -> bool:
    """Reconnect if the connection dropped. Cheap and safe to call every tick."""
    if ib.isConnected():
        return True
    log.warning("the Gateway connection is down, reconnecting")
    try:
        ib.disconnect()
    except Exception:                                  # noqa: BLE001
        pass
    return await connect_ib(ib, host, port, client_id, attempts=attempts)


# ------------------------------------------------------------------ bar shapes

def bar_to_dict(bar: Any) -> dict:
    """One ib_async BarData turned into the plain dictionary we store.

    Same field names the MCP server uses in agent/mcp_client.py, so a bar out
    of a recording and a bar out of the live client are the same thing to
    everything downstream, including the fake broker.
    """
    when = getattr(bar, "date", None)
    if isinstance(when, datetime):
        moment = when if when.tzinfo else when.replace(tzinfo=EASTERN)
        time_text = moment.astimezone(EASTERN).isoformat()
    elif isinstance(when, date_type):
        time_text = f"{when:%Y-%m-%d}"
    else:
        time_text = str(when or "")
    return {
        "time": time_text,
        "open": _float(getattr(bar, "open", None)),
        "high": _float(getattr(bar, "high", None)),
        "low": _float(getattr(bar, "low", None)),
        "close": _float(getattr(bar, "close", None)),
        "volume": _float(getattr(bar, "volume", None)),
        "average": _float(getattr(bar, "average", None)),
        "barCount": _int(getattr(bar, "barCount", None)),
    }


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    # IBKR sends -1 for "not available" on volume and average.
    return None if number < 0 else number


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def bar_moment(bar: dict) -> datetime | None:
    """The timestamp of a stored bar, as an aware Eastern datetime.

    Handles both shapes we store: a full ISO timestamp for intraday bars and a
    bare YYYY-MM-DD for daily ones. A daily bar is dated at the close, 16:00
    Eastern, so that daily and intraday bars sort against each other sensibly.
    """
    text = str(bar.get("time") or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        try:
            day = datetime.strptime(text[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
        return datetime.combine(day, clock_time(16, 0), tzinfo=EASTERN)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=EASTERN)
    return moment.astimezone(EASTERN)


def previous_trading_days(count: int, ending: date_type | None = None) -> list[date_type]:
    """The last `count` weekdays up to and including `ending`.

    Weekdays, not trading days: this does not know about Thanksgiving or the
    Fourth of July. A holiday simply comes back with no bars, which the
    fetcher records as a gap, so the manifest tells the truth either way.
    """
    day = ending or datetime.now(EASTERN).date()
    days: list[date_type] = []
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    return sorted(days)


def ib_end_datetime(moment: datetime) -> str:
    """A datetime in the exact wording reqHistoricalData wants for endDateTime.

    IBKR accepts two spellings of this field and they are not interchangeable:

        "YYYYMMDD HH:MM:SS US/Eastern"   space between date and time, named zone
        "YYYYMMDD-HH:MM:SS"              hyphen, UTC only, no zone allowed after

    Mixing them, which is to say a hyphen with a time zone on the end, is thrown
    out by Gateway with error 10314 and no useful explanation. This was found the
    hard way on 2026-09-06, when the first history fetch lost every one of its
    twenty opening range requests to it, so the wording here is deliberate and
    the hyphen is not coming back.

    We use the named zone form. Written out in full rather than left to the local
    clock, because a launchd job runs with almost no environment and its idea of
    local time is not something to bet the opening range on.
    """
    eastern = moment.astimezone(EASTERN)
    return f"{eastern:%Y%m%d %H:%M:%S} US/Eastern"

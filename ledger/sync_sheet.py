"""Rewrite the Google Sheet from the database, once a night after the close.

WHAT THIS IS FOR

The database is the truth. The Google Sheet is a picture of it that Mo can
open on a phone. Until now the Sheet was written a row at a time, live, while
the market was open, which made it both the record and a thing that could fail
mid write. From here it is neither: it is rebuilt from scratch every evening
from data/trading.sqlite, and if it is ever wrong the fix is to run this again.

    <root>/venv312/bin/python <root>/ledger/sync_sheet.py --dry-run
    <root>/venv312/bin/python <root>/ledger/sync_sheet.py --write

On this machine today that is

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      /Users/mtalib/workspace_repos/personal_repo/agentic_trading/ledger/sync_sheet.py --dry-run

Nothing is written without --write. --dry-run prints every row it would send,
and reads the live sheet to check the headers still line up, which is the way
to prove the read side works without risking the sheet.

    --date 2026-09-08   only that day's trades and rules, instead of everything
    --tab Trades        only that tab, may be given more than once
    --limit 20          in a dry run, show at most this many rows per tab

WHEN IT RUNS

16:35 New York, every weekday, five minutes after the close and after the
positions have settled. config/launchd/templates/sheet_sync.plist.tmpl is the
job, and like every other job in this project it is not loaded until Mo loads
it by hand.

WHAT IT REWRITES, AND WHAT IT REFUSES TO TOUCH

The sheet is full of live formulas that took a long time to get right, and a
blank sent to one of those cells deletes it for good with no error anywhere. So
this only ever clears and rewrites the columns the agent owns:

  Trades      A to T. Columns U and V are the slippage formulas, pre-filled
              from row 2 to row 1000, and are never read or written here.
  Daily       A, B, C, then G, then K to N. D, E, F, H, I and J work out daily
              and cumulative profit, SPY's return and alpha, and are left alone.
  Rules Log   A to H. No formulas on that tab at all.
  Books       E Equity, I Max DD, N Missed Ticks. Those three are the only ones
              the sheet cannot work out for itself, because its Daily tab
              follows the one paper account all five books share rather than
              five separate equity curves. Everything else on the tab is either
              typed in once (Book, Strategy, Model, Capital) or a live formula.
  Config      Column B only, the values. The setting names and the notes stay.
  Summary     Nothing. Every value on it is a formula over Daily and Trades, so
              there is nothing to write and writing anything would break it.
              It is listed in the run anyway, saying so, because a tab silently
              skipped is a tab nobody checks.

Config is the one tab that does not come from the database, and cannot: those
are settings, and they live in config/guardrails.yaml and config/books.yaml.
This reads them from there and says so in the output.

HOW IT STAYS IDEMPOTENT

Every tab is cleared over the columns it owns and then written from the top.
Running it twice in a row gives the same sheet, and running it after a crash
halfway through fixes the sheet rather than doubling it up. It never appends,
so there is no bottom of the table to get wrong.

Auth is the same as ledger/ledger_writer.py: the OAuth token at
.secrets/token_personal_drive.json, Google account mtalib.personal@gmail.com,
and the sheet id read at run time from config/ledger.json.

No connection is held open while talking to Google. Every row is read out of
SQLite into plain dictionaries first, the database connection is closed, and
only then does the network work start.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import quote

_ROOT = Path(__file__).resolve().parent.parent
_AGENT_DIR = _ROOT / "agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

import db as database  # noqa: E402
from paths import config_dir, project_root, secrets_dir  # noqa: E402

SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
HTTP_TIMEOUT = 60
LEDGER_CONFIG = config_dir() / "ledger.json"
TOKEN_PATH = secrets_dir() / "token_personal_drive.json"

TRADES_TAB = "Trades"
DAILY_TAB = "Daily"
RULES_TAB = "Rules Log"
CONFIG_TAB = "Config"
SUMMARY_TAB = "Summary"
BOOKS_TAB = "Books"
TAB_ORDER = [TRADES_TAB, DAILY_TAB, RULES_TAB, BOOKS_TAB, CONFIG_TAB, SUMMARY_TAB]

#: The first row of data on every tab. Row 1 is the frozen header.
FIRST_ROW = 2

#: How far down the Trades tab the slippage formulas in U and V reach. Written
#: once by ledger/create_ledger_sheet.py, from row 2 to row 1000. A trade
#: written below this line would have no slippage worked out for it, silently,
#: so this is a hard ceiling rather than something to grow past.
TRADES_FORMULA_LAST_ROW = 1000

#: How far down the Daily tab its formulas reach, for the same reason.
DAILY_FORMULA_LAST_ROW = 41

#: The Trades tab, A to T, in order. Deliberately the same twenty columns
#: ledger/ledger_writer.py writes, and deliberately stopping before U and V.
TRADES_HEADERS = [
    "Timestamp (ET)", "Date", "Symbol", "Side", "Qty", "Fill Price", "Notional",
    "Commission", "Order Type", "Order Id", "Strategy Signal", "Reason",
    "Realised P&L", "Notes", "Book", "Model", "Model Cost USD", "Prompt Hash",
    "Decision Price", "Decision Time (ET)",
]
RULES_HEADERS = ["Timestamp", "Rule", "Detail", "Action Taken", "Book", "Model",
                 "Model Cost USD", "Prompt Hash"]


class SyncError(RuntimeError):
    """Something the run cannot sensibly carry on past."""


def _warn(message: str) -> None:
    print(f"sync_sheet: {message}", file=sys.stderr)


# ------------------------------------------------------------------ values

def _cost(value: Any) -> Any:
    """A model cost as a cell, blank when it is not known.

    None, an unparseable value and 0 all come back empty. 0 is included on
    purpose and for the same reason ledger/ledger_writer.py does it: OpenRouter
    reports 0 in the immediate reply and settles the real figure seconds later,
    so a 0 in the ledger would claim a call was free when nobody yet knows what
    it cost. A blank still adds up as nothing inside the Books tab totals, so no
    figure anywhere is thrown off.
    """
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return "" if number == 0 else number


def _cell(value: Any) -> Any:
    """One value on its way into the sheet.

    A piece of free text that happens to start with "=", "+" or "@" would
    otherwise land as a broken formula, so it gets a leading apostrophe, which
    tells Google Sheets "this is text" and is not displayed.
    """
    if value is None:
        return ""
    if isinstance(value, str) and value[:1] in ("=", "+", "@"):
        return "'" + value
    return value


def _round(value: Any, places: int = 2) -> Any:
    if value is None:
        return ""
    try:
        return round(float(value), places)
    except (TypeError, ValueError):
        return value


# ------------------------------------------------------------------ the rows

def trades_rows(date: str | None = None) -> list[list[Any]]:
    """The Trades tab, A to T, one row per fill, oldest first.

    Realised P&L and Notes come out blank. Nothing in the database works out
    the profit on a closed position yet, and a made up number there would flow
    straight into the Summary tab's win rate, average win and average loss. A
    blank is the honest answer until something computes it properly.

    Strategy Signal is the order's purpose, entry or stop or target, which is
    the nearest thing the database holds to "which signal fired".
    """
    rows = []
    for fill in database.trades_for_date(date):
        qty = fill.get("qty")
        price = fill.get("price")
        notional = ""
        if qty is not None and price is not None:
            notional = round(abs(float(qty)) * float(price), 2)
        rows.append([
            fill.get("ts") or "",
            fill.get("date") or "",
            fill.get("symbol") or "",
            fill.get("side") or "",
            qty if qty is not None else "",
            _round(price),
            notional,
            _round(fill.get("commission"), 4),
            fill.get("order_type") or "",
            fill.get("broker_order_id") or "",
            fill.get("purpose") or "",
            fill.get("rationale") or "",
            "",                                    # Realised P&L, see above
            "",                                    # Notes
            fill.get("book_id") or "",
            fill.get("model") or "",
            _cost(fill.get("cost_usd")),
            fill.get("prompt_hash") or "",
            _round(fill.get("decision_price")),
            fill.get("decision_ts") or "",
        ])
    return rows


def daily_rows(date: str | None = None) -> list[dict[str, Any]]:
    """The Daily tab, one row per trading day for the whole account.

    Three separate stretches of columns, because the ones in between are
    formulas: A to C, then G on its own, then K to N. Each row comes back as a
    dict of those three lists so the writer can send them as three ranges
    without ever addressing a formula cell.

    There is no book column here on purpose. This tab follows the one paper
    account all five books share, so the equities are added up across books.
    """
    out = []
    for day in database.account_days(date):
        out.append({
            "date": day["date"],
            "books": int(day.get("books") or 0),
            "abc": [day["date"], _round(day.get("start_equity")),
                    _round(day.get("end_equity"))],
            "g": [_round(day.get("spy_close"))],
            "klmn": [
                day.get("trades") if day.get("trades") is not None else "",
                day.get("rule_triggers") if day.get("rule_triggers") is not None else "",
                f"{day.get('books') or 0} books, "
                f"{day.get('missed_ticks') or 0} missed ticks",
                _cost(day.get("model_cost_usd")),
            ],
        })
    return out


def books_expected(dailies: Sequence[dict]) -> int:
    """How many books a full day should have, taken as the most any day had.

    There is nothing in the database that says "five books", and hard coding
    five would go stale the moment a sixth is added or one is switched off. The
    fullest day in the data is the honest answer, and it makes a day that is
    missing a book stand out without anybody having to configure anything.
    """
    return max((row.get("books", 0) for row in dailies), default=0)


def rules_rows(date: str | None = None) -> list[list[Any]]:
    """The Rules Log, A to H, decisions and alerts together, oldest first."""
    rows = []
    for row in database.rules_log_rows(date):
        rows.append([
            row.get("ts") or "",
            row.get("rule") or "",
            row.get("detail") or "",
            row.get("action") or "",
            row.get("book_id") or "",
            row.get("model") or "",
            _cost(row.get("cost_usd")),
            row.get("prompt_hash") or "",
        ])
    return rows


def books_rows() -> list[dict[str, Any]]:
    """The three Books tab columns the sheet cannot work out for itself.

    Equity, Max DD and Missed Ticks, keyed by book id so the writer can put
    each one on the row that already carries that book's name. Everything else
    on that tab is either typed in once or a live formula, and is left alone.
    """
    out = []
    for row in database.books_summary():
        out.append({
            "book_id": str(row.get("book_id") or ""),
            "equity": _round(row.get("equity")),
            "max_drawdown_pct": _round(row.get("max_drawdown_pct"), 6),
            "missed_ticks": (row.get("missed_ticks")
                             if row.get("missed_ticks") is not None else ""),
        })
    return out


def config_rows() -> list[list[Any]]:
    """The Config tab, read from the config files rather than the database.

    These are settings, not results. They live in config/guardrails.yaml and
    config/books.yaml, which is where they are edited and where the code reads
    them, so that is where this reads them too. Putting them in the database
    would mean two copies of the same number and one of them going stale.

    Anything missing comes back blank rather than guessed at.
    """
    settings: dict = {}
    books: dict = {}
    try:
        import yaml
        settings = yaml.safe_load((config_dir() / "guardrails.yaml").read_text()) or {}
        books = yaml.safe_load((config_dir() / "books.yaml").read_text()) or {}
    except Exception as exc:  # noqa: BLE001
        _warn(f"could not read the config files, the Config tab will be blank: {exc!r}")

    money = settings.get("money") or {}
    universe = settings.get("universe") or {}
    schedule = settings.get("schedule") or {}
    entries = [b for b in (books.get("books") or []) if b.get("enabled")]

    capital = sum(float(b.get("capital_usd") or 0) for b in entries)
    if entries and capital:
        equity = f"{len(entries)} books, ${capital:,.0f} in total"
    else:
        equity = money.get("starting_equity", "")

    floor = universe.get("price_floor")
    volume = universe.get("min_avg_dollar_volume")
    if floor is not None and volume is not None:
        where = (f"US listed stocks over ${floor} a share trading at least "
                 f"${float(volume):,.0f} a day")
    else:
        where = ""

    minutes = schedule.get("loop_minutes")
    start, close = schedule.get("scan_start"), schedule.get("market_close")
    cadence = (f"every {minutes} minutes, {start} to {close} New York"
               if minutes and start and close else "")

    return [
        ["Starting equity", equity, "config/books.yaml, capital_usd per book"],
        ["Max position %", money.get("max_position_pct", ""),
         "config/guardrails.yaml, money.max_position_pct"],
        ["Daily loss cap %", money.get("max_daily_loss_pct", ""),
         "config/guardrails.yaml, money.max_daily_loss_pct"],
        ["Universe", where, "config/guardrails.yaml, universe"],
        ["Cadence", cadence, "config/guardrails.yaml, schedule"],
    ]


# ------------------------------------------------------------------ Google

def spreadsheet_id() -> str:
    try:
        return json.loads(LEDGER_CONFIG.read_text())["spreadsheet_id"]
    except Exception as exc:  # noqa: BLE001
        raise SyncError(f"cannot read the ledger id from {LEDGER_CONFIG}: {exc!r}") from exc


def session():
    """A signed in HTTP session. Imported in here so a dry run needs no packages."""
    try:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2.credentials import Credentials
    except Exception as exc:  # noqa: BLE001
        raise SyncError(
            f"google-auth is not installed in this venv: {exc!r}. Fix with "
            f"{project_root()}/venv312/bin/pip install google-auth requests") from exc
    try:
        return AuthorizedSession(Credentials.from_authorized_user_file(str(TOKEN_PATH)))
    except Exception as exc:  # noqa: BLE001
        raise SyncError(f"cannot sign in with the token at {TOKEN_PATH}: {exc!r}") from exc


def _get(http, url: str) -> dict:
    response = http.get(url, timeout=HTTP_TIMEOUT)
    if response.status_code >= 400:
        raise SyncError(f"Google refused a read: HTTP {response.status_code} "
                        f"{response.text[:300]}")
    return response.json()


def _post(http, url: str, body: dict) -> dict:
    response = http.post(url, json=body, timeout=HTTP_TIMEOUT)
    if response.status_code >= 400:
        raise SyncError(f"Google refused a write: HTTP {response.status_code} "
                        f"{response.text[:300]}")
    return response.json()


def tab_shapes(http, sheet_id: str) -> dict[str, dict]:
    """Each tab's row count, column count and header row, read in two calls.

    Read before anything is written, so a header that has moved is caught while
    the sheet is still untouched rather than halfway through a rewrite.
    """
    meta = _get(http, f"{SHEETS_API}/{sheet_id}"
                      "?fields=sheets.properties(sheetId,title,gridProperties)")
    shapes: dict[str, dict] = {}
    for sheet in meta.get("sheets", []):
        properties = sheet["properties"]
        grid = properties.get("gridProperties", {})
        shapes[properties["title"]] = {
            "sheet_id": properties["sheetId"],
            "rows": grid.get("rowCount", 0),
            "columns": grid.get("columnCount", 0),
            "header": [],
        }
    if not shapes:
        raise SyncError("that spreadsheet has no tabs, which cannot be right")

    ranges = "&".join("ranges=" + quote(f"'{title}'!1:1", safe="") for title in shapes)
    values = _get(http, f"{SHEETS_API}/{sheet_id}/values:batchGet?{ranges}")
    for title, entry in zip(shapes, values.get("valueRanges", [])):
        shapes[title]["header"] = (entry.get("values") or [[]])[0]
    return shapes


def check_headers(shapes: dict[str, dict]) -> list[str]:
    """Complain about anything that would make a write land in the wrong column.

    Returns a list of problems in plain words, empty when all is well. This is
    the whole point of reading before writing: the column letters below are
    hard coded, so a column inserted into the sheet by hand has to stop the run
    rather than quietly shift every value one to the left.
    """
    problems = []
    for title in TAB_ORDER:
        if title not in shapes:
            problems.append(f"the tab {title} is missing from the spreadsheet")
    if problems:
        return problems

    trades = shapes[TRADES_TAB]["header"]
    if trades[:len(TRADES_HEADERS)] != TRADES_HEADERS:
        problems.append(
            f"the {TRADES_TAB} tab's first {len(TRADES_HEADERS)} headings are not "
            f"the ones this writes. Found: {trades[:len(TRADES_HEADERS)]}")
    if len(trades) < 22 or trades[20:22] != ["Slippage $", "Slippage bps"]:
        problems.append(
            f"the {TRADES_TAB} tab should have Slippage $ and Slippage bps in "
            f"columns U and V, which this never writes to. Found: {trades[20:22]}")

    rules = shapes[RULES_TAB]["header"]
    if rules[:len(RULES_HEADERS)] != RULES_HEADERS:
        problems.append(f"the {RULES_TAB} tab's headings are not the ones this "
                        f"writes. Found: {rules[:len(RULES_HEADERS)]}")

    daily = shapes[DAILY_TAB]["header"]
    wanted = {0: "Date", 1: "Starting Equity", 2: "Ending Equity", 6: "SPY Close",
              10: "Trades Count", 11: "Rules Triggered", 12: "Notes",
              13: "Model Cost USD"}
    for index, name in wanted.items():
        if len(daily) <= index or daily[index] != name:
            found = daily[index] if len(daily) > index else "nothing"
            problems.append(f"the {DAILY_TAB} tab should have {name} in column "
                            f"{chr(65 + index)}, found {found}")

    books = shapes[BOOKS_TAB]["header"]
    for index, name in {0: "Book", 4: "Equity", 8: "Max DD", 13: "Missed Ticks"}.items():
        if len(books) <= index or books[index] != name:
            found = books[index] if len(books) > index else "nothing"
            problems.append(f"the {BOOKS_TAB} tab should have {name} in column "
                            f"{chr(65 + index)}, found {found}")
    return problems


def book_row_numbers(http, sheet_id: str) -> dict[str, int]:
    """Which row on the Books tab belongs to which book, read from column A."""
    target = quote(f"{BOOKS_TAB}!A{FIRST_ROW}:A50", safe="")
    values = _get(http, f"{SHEETS_API}/{sheet_id}/values/{target}")
    out = {}
    for offset, cell in enumerate(values.get("values", [])):
        name = str(cell[0]).strip() if cell and cell[0] not in (None, "") else ""
        if name:
            out[name] = FIRST_ROW + offset
    return out


def grow_tab(http, sheet_id: str, shape: dict, rows_needed: int) -> bool:
    """Add rows to a tab that is too short to hold what is about to go into it.

    The Rules Log arrives 300 rows deep, and a month of five books deciding
    every five minutes is a great deal more than that. Growing it is safe: the
    tab has no formulas anywhere, so new rows are simply blank.
    """
    if shape["rows"] >= rows_needed:
        return False
    _post(http, f"{SHEETS_API}/{sheet_id}:batchUpdate", {"requests": [{
        "appendDimension": {"sheetId": shape["sheet_id"], "dimension": "ROWS",
                            "length": rows_needed - shape["rows"]}}]})
    shape["rows"] = rows_needed
    return True


def clear(http, sheet_id: str, ranges: Sequence[str]) -> None:
    """Empty the given ranges. Only ever the columns this file owns."""
    _post(http, f"{SHEETS_API}/{sheet_id}/values:batchClear", {"ranges": list(ranges)})


def write(http, sheet_id: str, data: Sequence[dict]) -> int:
    """Send several ranges of values in one round trip. Returns cells written."""
    if not data:
        return 0
    result = _post(http, f"{SHEETS_API}/{sheet_id}/values:batchUpdate",
                   {"valueInputOption": "USER_ENTERED", "data": list(data)})
    return int(result.get("totalUpdatedCells", 0))


def _values(rows: Iterable[Sequence[Any]]) -> list[list[Any]]:
    return [[_cell(cell) for cell in row] for row in rows]


# ------------------------------------------------------------------ the plan

def build_plan(date: str | None = None) -> dict[str, dict]:
    """Everything that would go into the sheet, worked out before any network.

    The database is read here, in full, and closed. From this point on nothing
    holds a connection, which is the rule: a SQLite lock must never be held
    while waiting on Google.
    """
    trades = trades_rows(date)
    dailies = daily_rows(date)
    rules = rules_rows(date)
    books = books_rows()
    config = config_rows()

    notes = {}
    room = TRADES_FORMULA_LAST_ROW - FIRST_ROW + 1
    if len(trades) > room:
        notes[TRADES_TAB] = (
            f"{len(trades)} fills but the sheet only has slippage formulas down "
            f"to row {TRADES_FORMULA_LAST_ROW}, so the oldest {room} are written "
            f"and {len(trades) - room} are left out. The database still has them "
            f"all. To fix, raise TRADES_FORMULA_ROWS in "
            f"ledger/create_ledger_sheet.py and rebuild the sheet.")
        trades = trades[:room]
    if len(dailies) > DAILY_FORMULA_LAST_ROW - FIRST_ROW + 1:
        room = DAILY_FORMULA_LAST_ROW - FIRST_ROW + 1
        notes[DAILY_TAB] = (
            f"{len(dailies)} days but the sheet only has formulas down to row "
            f"{DAILY_FORMULA_LAST_ROW}, so {len(dailies) - room} are left out.")
        dailies = dailies[:room]

    # A day where one book never wrote its summary would show up on the Daily
    # tab as the whole account losing that book's equity overnight, and the
    # Summary tab would read that as a real drawdown. The equity on this tab is
    # a sum across books, so it is only meaningful when every book is there.
    short = [row["date"] for row in dailies if row["books"] < books_expected(dailies)]
    if short:
        notes[DAILY_TAB] = (notes.get(DAILY_TAB, "") + " " if notes.get(DAILY_TAB) else "") + (
            f"CAREFUL: these days have fewer books than the fullest day, so their "
            f"equity is not the whole account and the drawdown on the Summary tab "
            f"will be wrong: {', '.join(short)}. A book with no row for a day "
            f"never wrote its daily summary.")

    return {
        TRADES_TAB: {"rows": trades, "note": notes.get(TRADES_TAB, "")},
        DAILY_TAB: {"rows": dailies, "note": notes.get(DAILY_TAB, "")},
        RULES_TAB: {"rows": rules, "note": ""},
        BOOKS_TAB: {"rows": books, "note": ""},
        CONFIG_TAB: {"rows": config,
                     "note": "read from config/guardrails.yaml and "
                             "config/books.yaml, not from the database"},
        SUMMARY_TAB: {"rows": [],
                      "note": "every value on this tab is a formula over Daily "
                              "and Trades, so there is nothing to write"},
    }


def apply_plan(http, sheet_id: str, plan: dict, shapes: dict,
               tabs: Sequence[str]) -> dict[str, int]:
    """Clear and rewrite each tab. Returns how many cells each one took."""
    written: dict[str, int] = {}

    if TRADES_TAB in tabs:
        rows = plan[TRADES_TAB]["rows"]
        clear(http, sheet_id, [f"{TRADES_TAB}!A{FIRST_ROW}:T{TRADES_FORMULA_LAST_ROW}"])
        data = []
        if rows:
            data.append({"range": f"{TRADES_TAB}!A{FIRST_ROW}:T{FIRST_ROW + len(rows) - 1}",
                         "values": _values(rows)})
        written[TRADES_TAB] = write(http, sheet_id, data)

    if DAILY_TAB in tabs:
        rows = plan[DAILY_TAB]["rows"]
        last = shapes[DAILY_TAB]["rows"]
        clear(http, sheet_id, [f"{DAILY_TAB}!A{FIRST_ROW}:C{last}",
                               f"{DAILY_TAB}!G{FIRST_ROW}:G{last}",
                               f"{DAILY_TAB}!K{FIRST_ROW}:N{last}"])
        data = []
        if rows:
            end = FIRST_ROW + len(rows) - 1
            data = [
                {"range": f"{DAILY_TAB}!A{FIRST_ROW}:C{end}",
                 "values": _values(row["abc"] for row in rows)},
                {"range": f"{DAILY_TAB}!G{FIRST_ROW}:G{end}",
                 "values": _values(row["g"] for row in rows)},
                {"range": f"{DAILY_TAB}!K{FIRST_ROW}:N{end}",
                 "values": _values(row["klmn"] for row in rows)},
            ]
        written[DAILY_TAB] = write(http, sheet_id, data)

    if RULES_TAB in tabs:
        rows = plan[RULES_TAB]["rows"]
        grow_tab(http, sheet_id, shapes[RULES_TAB], FIRST_ROW + len(rows))
        last = shapes[RULES_TAB]["rows"]
        clear(http, sheet_id, [f"'{RULES_TAB}'!A{FIRST_ROW}:H{last}"])
        data = []
        if rows:
            data.append({"range": f"'{RULES_TAB}'!A{FIRST_ROW}:H{FIRST_ROW + len(rows) - 1}",
                         "values": _values(rows)})
        written[RULES_TAB] = write(http, sheet_id, data)

    if BOOKS_TAB in tabs:
        rows = plan[BOOKS_TAB]["rows"]
        where = book_row_numbers(http, sheet_id)
        data = []
        for row in rows:
            number = where.get(row["book_id"])
            if number is None:
                _warn(f"the Books tab has no row for book {row['book_id']}, skipped")
                continue
            data.append({"range": f"{BOOKS_TAB}!E{number}",
                         "values": [[_cell(row["equity"])]]})
            data.append({"range": f"{BOOKS_TAB}!I{number}",
                         "values": [[_cell(row["max_drawdown_pct"])]]})
            data.append({"range": f"{BOOKS_TAB}!N{number}",
                         "values": [[_cell(row["missed_ticks"])]]})
        written[BOOKS_TAB] = write(http, sheet_id, data)

    if CONFIG_TAB in tabs:
        rows = plan[CONFIG_TAB]["rows"]
        data = []
        if rows:
            data.append({"range": f"{CONFIG_TAB}!B{FIRST_ROW}:B{FIRST_ROW + len(rows) - 1}",
                         "values": [[_cell(row[1])] for row in rows]})
        written[CONFIG_TAB] = write(http, sheet_id, data)

    if SUMMARY_TAB in tabs:
        written[SUMMARY_TAB] = 0

    return written


# ------------------------------------------------------------------ printing

def show(plan: dict, tabs: Sequence[str], limit: int) -> None:
    """Print what would be written, tab by tab."""
    for title in TAB_ORDER:
        if title not in tabs:
            continue
        entry = plan[title]
        rows = entry["rows"]
        print(f"\n--- {title}: {len(rows)} row{'' if len(rows) == 1 else 's'} ---")
        if entry["note"]:
            print(f"    note: {entry['note']}")
        if title == DAILY_TAB:
            for row in rows[:limit]:
                print(f"    A:C {row['abc']}  G {row['g']}  K:N {row['klmn']}")
        elif title == BOOKS_TAB:
            for row in rows[:limit]:
                print(f"    book {row['book_id']}: E equity={row['equity']} "
                      f"I max dd={row['max_drawdown_pct']} "
                      f"N missed ticks={row['missed_ticks']}")
        elif title == CONFIG_TAB:
            for row in rows[:limit]:
                print(f"    B  {row[0]} = {row[1]}")
        else:
            for row in rows[:limit]:
                print("    " + " | ".join("" if c is None else str(c) for c in row))
        if len(rows) > limit:
            print(f"    ... and {len(rows) - limit} more, "
                  f"pass --limit to see further")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rewrite the Google Sheet ledger from the SQLite system of "
                    "record. Writes nothing unless you pass --write.")
    parser.add_argument("--write", action="store_true",
                        help="actually rewrite the sheet")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the rows and read the live sheet's headers, "
                             "writing nothing. This is the default.")
    parser.add_argument("--date", default=None,
                        help="only this day, as 2026-09-08, instead of everything")
    parser.add_argument("--tab", action="append", default=None,
                        choices=TAB_ORDER, help="only this tab, may be repeated")
    parser.add_argument("--limit", type=int, default=10,
                        help="in a dry run, rows to print per tab (default 10)")
    parser.add_argument("--offline", action="store_true",
                        help="in a dry run, skip reading the live sheet as well")
    args = parser.parse_args(argv)

    tabs = args.tab or TAB_ORDER
    path = database.db_path()
    print(f"database: {path}")
    if not path.exists():
        print("\nThat database does not exist yet. Build it with:")
        print(f"  {project_root()}/venv312/bin/python "
              f"{project_root()}/scripts/migrate_db.py")
        return 1

    try:
        sheet_id = spreadsheet_id()
    except SyncError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"sheet:    https://docs.google.com/spreadsheets/d/{sheet_id}/edit")
    print(f"token:    {TOKEN_PATH}")
    print(f"scope:    {args.date or 'every day in the database'}")
    print(f"tabs:     {', '.join(tabs)}")
    print(f"mode:     {'WRITING to the live sheet' if args.write else 'dry run, nothing is written'}")

    plan = build_plan(args.date)
    show(plan, tabs, max(0, args.limit))

    if not args.write and args.offline:
        print("\nDRY RUN, offline. Nothing was read from Google and nothing written.")
        return 0

    try:
        http = session()
        shapes = tab_shapes(http, sheet_id)
    except SyncError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1

    print("\n--- the live sheet ---")
    for title in TAB_ORDER:
        shape = shapes.get(title)
        if shape is None:
            print(f"    {title}: MISSING")
            continue
        print(f"    {title}: {shape['rows']} rows, {shape['columns']} columns, "
              f"{len(shape['header'])} headings")

    problems = check_headers(shapes)
    if problems:
        print("\nThe sheet is not the shape this writes into, so nothing was "
              "written:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2
    print("    headers all match, so the column letters below are safe")

    if not args.write:
        print("\nDRY RUN. Nothing was written. Add --write to really rewrite it.")
        return 0

    written = apply_plan(http, sheet_id, plan, shapes, tabs)
    print("\n--- written ---")
    for title, cells in written.items():
        print(f"    {title}: {cells} cells")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Write rows into the paper trading ledger, the Google Sheet that scores the test.

The sheet lives here:
  https://docs.google.com/spreadsheets/d/18_lzOTkoiJn1tc_WCHE5MheigyfhNc2dQcaZJjUBiP8/edit
and its id is read at run time from
  /Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/ledger.json
so that rebuilding the sheet never means editing this file.

Sign in uses the Google token at
  /Users/mtalib/workspace_repos/personal_repo/agentic_trading/.secrets/token_personal_drive.json
which is a symlink to
  /Users/mtalib/workspace_repos/work_repo/.secrets/token_personal_drive_write.json
(Google account mtalib.personal@gmail.com). Never committed.

Four ways in:

  log_trade(row)        one fill, onto the Trades tab
  log_decision(...)     one judgement call, onto the Rules Log tab
  log_rule(...)         one guardrail firing, onto the Rules Log tab
  upsert_daily(...)     one trading day, onto the Daily tab

Five books share the one paper account, so every row has to say which book it
belongs to and which model decided it. log_trade, log_decision and log_rule all
take the same four extras, and all four default to None so an older call still
works:

  book_id         "A" to "E", the book the row belongs to
  model           the model that made the call, or "none" for the rules only book
  model_cost_usd  what that call cost, in dollars
  prompt_hash     sha256 hex of the rendered system prompt, so a prompt change
                  mid-month is visible in the ledger rather than invisible

model_cost_usd is left blank when it is not known. OpenRouter finalises the cost
of a call a few seconds after answering, so a 0 in hand at write time usually
means "not settled yet" rather than "free", and writing that 0 would be a lie the
month end cost comparison then repeats.

Two promises every one of them keeps:

1. It never raises. If the wifi is off, the token has expired or Google is
   having a bad morning, it complains to stderr and returns False. A ledger
   write must never be the reason the trading loop falls over, because the loop
   is the thing holding the risk limits.
2. Pass dry_run=True and it prints the row it would have written and touches
   nothing. That is how the loop is run today.

Self test, writes nothing:

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      /Users/mtalib/workspace_repos/personal_repo/agentic_trading/ledger/ledger_writer.py --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote
from zoneinfo import ZoneInfo

_AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from paths import config_dir, project_root, secrets_dir  # noqa: E402

PROJECT = project_root()
LEDGER_CONFIG = config_dir() / "ledger.json"
TOKEN_PATH = secrets_dir() / "token_personal_drive.json"
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
NEW_YORK = ZoneInfo("America/New_York")
HTTP_TIMEOUT = 30

TRADES_TAB = "Trades"
DAILY_TAB = "Daily"
RULES_TAB = "Rules Log"

# The Trades tab, left to right, with the friendlier names a caller may use
# instead of the exact column heading.
TRADES_COLUMNS: list[tuple[str, tuple[str, ...]]] = [
    ("Timestamp (ET)", ("timestamp", "timestamp_et", "ts")),
    ("Date", ("date",)),
    ("Symbol", ("symbol",)),
    ("Side", ("side",)),
    ("Qty", ("qty", "quantity")),
    ("Fill Price", ("fill_price", "price")),
    ("Notional", ("notional",)),
    ("Commission", ("commission",)),
    ("Order Type", ("order_type",)),
    ("Order Id", ("order_id",)),
    ("Strategy Signal", ("strategy_signal", "signal")),
    ("Reason", ("reason", "rationale")),
    ("Realised P&L", ("realised_pnl", "realized_pnl", "pnl")),
    ("Notes", ("notes", "note")),
    ("Book", ("book", "book_id")),
    ("Model", ("model",)),
    ("Model Cost USD", ("model_cost_usd", "model_cost", "cost_usd")),
    ("Prompt Hash", ("prompt_hash", "hash")),
]

# The Daily tab is mostly formulas. These are the only columns the agent owns.
# D, E, F, H, I and J work out daily and cumulative profit, SPY's return and
# alpha from the columns below, and overwriting any of them would silently
# break every number on the Summary tab. So they are not in this list and must
# never be added to it.
#
# K starts life as a COUNTIF formula from ledger/create_ledger_sheet.py. We
# replace it with the count the loop actually saw, which is what
# ledger/README.md says the agent fills in.
DAILY_INPUT_COLUMNS = {
    "date": "A",
    "starting_equity": "B",
    "ending_equity": "C",
    "spy_close": "G",
    "trades_count": "K",
    "rules_triggered": "L",
    "notes": "M",
    "model_cost_usd": "N",
}
DAILY_FIRST_DATA_ROW = 2


def _warn(message: str) -> None:
    print(f"ledger_writer: {message}", file=sys.stderr)


def _safe_cell(value: Any) -> Any:
    """Stop a piece of free text from being read as a spreadsheet formula.

    A reason field that happens to begin with "=" or "-" would otherwise land
    in the sheet as a broken formula. A leading apostrophe tells Google Sheets
    "this is text", and the apostrophe itself is not displayed.
    """
    if isinstance(value, str) and value[:1] in ("=", "+", "@"):
        return "'" + value
    if value is None:
        return ""
    return value


def _cost_cell(value: Any) -> Any:
    """Turn a model cost into a cell, leaving it blank when the cost is unknown.

    None, an empty string, something that is not a number, and 0 all come back
    as an empty cell. 0 is included on purpose: OpenRouter reports 0 in the
    immediate reply and settles the real figure seconds later, so a 0 in the
    ledger would claim a call was free when nobody knows yet what it cost. A
    blank cell still counts as nothing inside the Books tab SUMIFS, so leaving
    it empty costs no total anywhere.
    """
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return "" if number == 0 else number


def _now_et_string() -> str:
    return datetime.now(NEW_YORK).strftime("%Y-%m-%d %H:%M:%S")


def _as_text(value: Any) -> str:
    """A timestamp may arrive as a datetime or as a string. Make it a string."""
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=NEW_YORK)
        return moment.astimezone(NEW_YORK).strftime("%Y-%m-%d %H:%M:%S")
    return "" if value is None else str(value)


def spreadsheet_id() -> str | None:
    """The ledger's id, read from config/ledger.json."""
    try:
        return json.loads(LEDGER_CONFIG.read_text())["spreadsheet_id"]
    except Exception as exc:  # noqa: BLE001
        _warn(f"cannot read the ledger id from {LEDGER_CONFIG}: {exc!r}")
        return None


def _session():
    """A signed in HTTP session, or None if signing in did not work.

    Imports live in here on purpose. In dry run nothing needs google-auth, so a
    missing package must not stop the loop from starting.
    """
    try:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2.credentials import Credentials
    except Exception as exc:  # noqa: BLE001
        _warn(f"google-auth is not installed in this venv: {exc!r}. "
              f"Fix with {PROJECT}/venv312/bin/pip install google-auth requests")
        return None
    try:
        credentials = Credentials.from_authorized_user_file(str(TOKEN_PATH))
        return AuthorizedSession(credentials)
    except Exception as exc:  # noqa: BLE001
        _warn(f"cannot sign in with the token at {TOKEN_PATH}: {exc!r}")
        return None


def _print_row(where: str, row: Sequence[Any]) -> None:
    printable = " | ".join("" if cell is None else str(cell) for cell in row)
    print(f"DRY RUN would add to the ledger tab {where}: {printable}")


def _append(tab: str, row: Sequence[Any], dry_run: bool) -> bool:
    """Add one row to the bottom of a tab."""
    if dry_run:
        _print_row(tab, row)
        return True
    sheet_id = spreadsheet_id()
    if not sheet_id:
        return False
    session = _session()
    if session is None:
        return False
    target = quote(f"{tab}!A:Z", safe="")
    url = (f"{SHEETS_API}/{sheet_id}/values/{target}:append"
           "?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS")
    try:
        response = session.post(
            url, json={"values": [[_safe_cell(cell) for cell in row]]}, timeout=HTTP_TIMEOUT)
        if response.status_code >= 400:
            _warn(f"Google refused the write to {tab}: "
                  f"HTTP {response.status_code} {response.text[:300]}")
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        _warn(f"could not write to {tab}, the row is lost but the loop carries on: {exc!r}")
        return False


# --------------------------------------------------------------------- Trades

def log_trade(row: dict, book_id: Any = None, model: Any = None,
              model_cost_usd: Any = None, prompt_hash: Any = None,
              dry_run: bool = False) -> bool:
    """Record one fill on the Trades tab.

    Accepts either the exact column headings or the shorter names listed in
    TRADES_COLUMNS above, so both of these work:

        log_trade({"Symbol": "AAPL", "Side": "BUY", "Qty": 50})
        log_trade({"symbol": "AAPL", "side": "BUY", "qty": 50, "price": 231.4})

    The book and the model can be passed either way too, whichever suits the
    caller. These two lines do the same thing:

        log_trade({"symbol": "AAPL", "book": "A", "model": "claude-fable-5.1"})
        log_trade({"symbol": "AAPL"}, book_id="A", model="claude-fable-5.1")

    An argument passed on its own wins over the same thing inside the dict.

    Anything left out is written as an empty cell. Notional is worked out from
    quantity times price when it was not supplied.
    """
    if not isinstance(row, dict):
        _warn(f"log_trade wants a dictionary, got {type(row).__name__}")
        return False

    filled: dict[str, Any] = {}
    for heading, aliases in TRADES_COLUMNS:
        value = row.get(heading)
        if value is None:
            for alias in aliases:
                if row.get(alias) is not None:
                    value = row[alias]
                    break
        filled[heading] = value

    if not filled["Timestamp (ET)"]:
        filled["Timestamp (ET)"] = _now_et_string()
    else:
        filled["Timestamp (ET)"] = _as_text(filled["Timestamp (ET)"])
    if not filled["Date"]:
        filled["Date"] = str(filled["Timestamp (ET)"])[:10]
    if filled["Notional"] in (None, "") and filled["Qty"] and filled["Fill Price"]:
        try:
            filled["Notional"] = round(abs(float(filled["Qty"])) * float(filled["Fill Price"]), 2)
        except (TypeError, ValueError):
            pass

    for heading, argument in (("Book", book_id), ("Model", model),
                              ("Model Cost USD", model_cost_usd),
                              ("Prompt Hash", prompt_hash)):
        if argument is not None:
            filled[heading] = argument
    filled["Model Cost USD"] = _cost_cell(filled["Model Cost USD"])

    unknown = set(row) - {h for h, _ in TRADES_COLUMNS} - {a for _, al in TRADES_COLUMNS for a in al}
    if unknown:
        _warn(f"log_trade ignored fields it has no column for: {sorted(unknown)}")

    return _append(TRADES_TAB, [filled[h] for h, _ in TRADES_COLUMNS], dry_run)


# ------------------------------------------------------------------ Rules Log

def log_decision(timestamp: Any, symbol: str, decision: str, rationale: str,
                 mode: str = "dry-run", book_id: Any = None, model: Any = None,
                 model_cost_usd: Any = None, prompt_hash: Any = None,
                 dry_run: bool = False) -> bool:
    """Record one judgement call on the Rules Log tab.

    The first four columns fold the judgement itself in like this:

      Timestamp     when
      Rule          the word "decision", so these are easy to filter out
      Detail        the symbol, then why
      Action Taken  the mode in brackets, then what was decided

    The last four say who made it and what it cost: Book, Model, Model Cost USD
    and Prompt Hash. Most of the month's model spend lands here rather than on
    the Trades tab, because a model is asked on every tick and only some ticks
    end in a fill.

    "Do nothing" is a decision and belongs here too. That is the strategy's
    rule, not a preference: every choice gets a written reason.
    """
    detail = f"{symbol}: {rationale}" if symbol else str(rationale)
    row = [_as_text(timestamp) or _now_et_string(), "decision", detail,
           f"[{mode}] {decision}", book_id, model,
           _cost_cell(model_cost_usd), prompt_hash]
    return _append(RULES_TAB, row, dry_run)


def log_rule(timestamp: Any, rule_id: str, detail: str, action: str,
             book_id: Any = None, model: Any = None,
             model_cost_usd: Any = None, prompt_hash: Any = None,
             dry_run: bool = False) -> bool:
    """Record one guardrail firing on the Rules Log tab.

    rule_id is the guardrail's own name, for example daily_loss_cap or
    max_open_positions, so the month end review can count how often each limit
    actually bit. book_id says which book it bit, which is the whole point of
    running five of them: a limit that only ever fires on one book is telling
    you something about that book.

    A guardrail is code, not a model, so model and model_cost_usd are usually
    left out here. They are accepted anyway for the case where a rule fires on
    the back of a model call, for instance a refusal being logged as a rule.
    """
    row = [_as_text(timestamp) or _now_et_string(), str(rule_id), str(detail),
           str(action), book_id, model, _cost_cell(model_cost_usd), prompt_hash]
    return _append(RULES_TAB, row, dry_run)


# ---------------------------------------------------------------------- Daily

def _daily_row_for_date(session, sheet_id: str, date_text: str) -> int | None:
    """Find which row on the Daily tab belongs to this date.

    Returns the row number of an existing row for that date, or of the first
    row whose Date cell is empty, or None if the lookup itself failed.

    Why not just append: the Daily tab arrives with forty rows of formulas
    already in place, so appending to the bottom would land far below them and
    every formula would sit there staring at an empty row.
    """
    target = quote(f"{DAILY_TAB}!A{DAILY_FIRST_DATA_ROW}:A200", safe="")
    try:
        response = session.get(f"{SHEETS_API}/{sheet_id}/values/{target}"
                               "?valueRenderOption=UNFORMATTED_VALUE", timeout=HTTP_TIMEOUT)
        if response.status_code >= 400:
            _warn(f"could not read the Daily dates: "
                  f"HTTP {response.status_code} {response.text[:300]}")
            return None
        column = response.json().get("values", [])
    except Exception as exc:  # noqa: BLE001
        _warn(f"could not read the Daily dates: {exc!r}")
        return None

    wanted = str(date_text).strip()[:10]
    first_empty: int | None = None
    for offset, cell in enumerate(column):
        row_number = DAILY_FIRST_DATA_ROW + offset
        value = str(cell[0]).strip() if cell and cell[0] not in (None, "") else ""
        if not value:
            if first_empty is None:
                first_empty = row_number
            continue
        # A date cell read unformatted may come back as a serial number, so
        # only a text match counts as "this day is already here".
        if value[:10] == wanted:
            return row_number
    if first_empty is not None:
        return first_empty
    return DAILY_FIRST_DATA_ROW + len(column)


def upsert_daily(date: Any, starting_equity: Any = None, ending_equity: Any = None,
                 spy_close: Any = None, trades_count: Any = None,
                 rules_triggered: Any = None, notes: Any = None,
                 model_cost_usd: Any = None, dry_run: bool = False) -> bool:
    """Fill in one day on the Daily tab, adding the row or updating it in place.

    Only the eight columns the agent owns are touched: A Date, B Starting
    Equity, C Ending Equity, G SPY Close, K Trades Count, L Rules Triggered,
    M Notes and N Model Cost USD. The profit, return and alpha columns are
    formulas and are left exactly as they are.

    There is no book column here on purpose. The Daily tab tracks the one paper
    account all five books share, so a day is a day, not a day per book. Per
    book figures live on the Books tab, which slices Trades and Rules Log by
    their Book column. model_cost_usd is the day's total spend across every
    book, and is left blank rather than written as 0 when it is not known.

    Leaving an argument out leaves that cell alone, so calling this at 9:30 with
    just the date and starting equity and again at 4:00 with the closing figures
    works and does not blank anything in between.
    """
    date_text = _as_text(date)[:10]
    if not date_text:
        _warn("upsert_daily needs a date")
        return False

    values = {
        "date": date_text,
        "starting_equity": starting_equity,
        "ending_equity": ending_equity,
        "spy_close": spy_close,
        "trades_count": trades_count,
        "rules_triggered": rules_triggered,
        "notes": notes,
        "model_cost_usd": _cost_cell(model_cost_usd) if model_cost_usd is not None else None,
    }
    supplied = {name: value for name, value in values.items() if value is not None}

    if dry_run:
        shown = ", ".join(f"{DAILY_INPUT_COLUMNS[name]} {name}={value}"
                          for name, value in supplied.items())
        print(f"DRY RUN would set on the ledger tab {DAILY_TAB} for {date_text}: {shown}")
        return True

    sheet_id = spreadsheet_id()
    if not sheet_id:
        return False
    session = _session()
    if session is None:
        return False

    row_number = _daily_row_for_date(session, sheet_id, date_text)
    if row_number is None:
        return False

    data = [{"range": f"{DAILY_TAB}!{DAILY_INPUT_COLUMNS[name]}{row_number}",
             "values": [[_safe_cell(value)]]}
            for name, value in supplied.items()]
    try:
        response = session.post(
            f"{SHEETS_API}/{sheet_id}/values:batchUpdate",
            json={"valueInputOption": "USER_ENTERED", "data": data}, timeout=HTTP_TIMEOUT)
        if response.status_code >= 400:
            _warn(f"Google refused the Daily update: "
                  f"HTTP {response.status_code} {response.text[:300]}")
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        _warn(f"could not update the Daily tab, the loop carries on: {exc!r}")
        return False


def _cli() -> int:
    parser = argparse.ArgumentParser(
        description="Ledger writer self test. With --dry-run it prints rows and writes nothing.")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the rows instead of writing them to the sheet")
    parser.add_argument("--write", action="store_true",
                        help="actually write the sample rows to the real ledger")
    args = parser.parse_args()

    if not args.dry_run and not args.write:
        print("Nothing to do. Pass --dry-run to see the rows this would write, "
              "or --write to really write sample rows to the live ledger.")
        return 1
    dry = not args.write

    print(f"ledger id: {spreadsheet_id()}")
    print(f"token:     {TOKEN_PATH}")
    print(f"mode:      {'dry run, nothing is written' if dry else 'WRITING to the live ledger'}")
    now = _now_et_string()
    # A stand in for the sha256 of a rendered system prompt.
    sample_hash = hashlib.sha256(b"sample system prompt").hexdigest()
    ok = [
        log_trade({"symbol": "SPY", "side": "BUY", "qty": 10, "price": 765.25,
                   "order_type": "LMT", "signal": "opening range break",
                   "reason": "sample row from the self test"},
                  book_id="A", model="openrouter/anthropic/claude-fable-5.1",
                  model_cost_usd=0.0184, prompt_hash=sample_hash, dry_run=dry),
        log_decision(now, "SPY", "no entry", "sample row from the self test",
                     mode="dry-run", book_id="A",
                     model="openrouter/anthropic/claude-fable-5.1",
                     model_cost_usd=None, prompt_hash=sample_hash, dry_run=dry),
        log_rule(now, "max_open_positions", "5 already open", "entry refused",
                 book_id="B", model="none", dry_run=dry),
        upsert_daily(now[:10], starting_equity=100000, ending_equity=100120,
                     spy_close=765.25, trades_count=2, rules_triggered="none",
                     notes="sample row from the self test", model_cost_usd=0.4211,
                     dry_run=dry),
    ]
    print("the decision row above has an empty model cost on purpose: "
          "None means the cost is not settled yet, and 0 would be a lie.")
    print(f"all four writers returned True: {all(ok)}")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    raise SystemExit(_cli())

"""Tests for the nightly rewrite of the Google Sheet from the database.

Google is never called. A stand in session records every request and answers
with the shape the real API answers with, so these tests check the two things
that actually matter and cannot be checked by looking at the sheet afterwards:

1. The rows built from the database are exactly the shape each tab expects,
   column for column, in the right order.
2. Nothing is ever written to a cell holding a formula. That is the failure
   that would not show up as an error anywhere: a blank sent to Trades column U
   deletes that row's slippage formula for good, and the loss looks like an
   empty cell rather than a broken one, so it could run for a fortnight before
   anybody noticed.

Run them with:

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python -m pytest -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
AGENT = REPO / "agent"
LEDGER = REPO / "ledger"
for folder in (AGENT, LEDGER):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import db  # noqa: E402
import sync_sheet  # noqa: E402

#: The header rows the real spreadsheet has today, read off it on 2026-09-06.
#: These are what ledger/create_ledger_sheet.py builds, so a change to that file
#: that forgets this one is caught here rather than by a wrong-looking sheet.
LIVE_HEADERS = {
    "Trades": ["Timestamp (ET)", "Date", "Symbol", "Side", "Qty", "Fill Price",
               "Notional", "Commission", "Order Type", "Order Id",
               "Strategy Signal", "Reason", "Realised P&L", "Notes", "Book",
               "Model", "Model Cost USD", "Prompt Hash", "Decision Price",
               "Decision Time (ET)", "Slippage $", "Slippage bps"],
    "Daily": ["Date", "Starting Equity", "Ending Equity", "Daily P&L $",
              "Daily P&L %", "Cumulative P&L %", "SPY Close", "SPY Daily %",
              "SPY Cumulative %", "Alpha vs SPY (cum)", "Trades Count",
              "Rules Triggered", "Notes", "Model Cost USD"],
    "Summary": ["Metric", "Value", "What it means"],
    "Rules Log": ["Timestamp", "Rule", "Detail", "Action Taken", "Book", "Model",
                  "Model Cost USD", "Prompt Hash"],
    "Config": ["Setting", "Value", "Notes"],
    "Books": ["Book", "Strategy", "Model", "Capital", "Equity", "Return %",
              "SPY %", "Alpha", "Max DD", "Trades", "Commissions",
              "Model Cost USD", "Rule Triggers", "Missed Ticks", "Slippage $",
              "Avg Slippage bps"],
}
LIVE_ROWS = {"Trades": 1000, "Daily": 200, "Summary": 30, "Rules Log": 300,
             "Config": 30, "Books": 20}

#: The Trades tab columns that hold the pre-filled slippage formulas.
TRADES_FORMULA_COLUMNS = {"U", "V"}

#: The Daily tab columns that work out profit, SPY's return and alpha.
DAILY_FORMULA_COLUMNS = {"D", "E", "F", "H", "I", "J"}

#: The Books tab columns that are live formulas or typed in once by hand.
BOOKS_UNTOUCHABLE_COLUMNS = {"F", "G", "H", "J", "K", "L", "M", "O", "P"}


def _column_number(letters: str) -> int:
    """A spreadsheet column name as a number. A is 1, Z is 26, AA is 27."""
    number = 0
    for letter in letters:
        number = number * 26 + (ord(letter) - ord("A") + 1)
    return number


def _column_letter(number: int) -> str:
    """The other way round, so a span can be listed out column by column."""
    letters = ""
    while number > 0:
        number, remainder = divmod(number - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeSession:
    """Answers like the Sheets API and writes down everything it was asked."""

    def __init__(self, headers=None, rows=None, books=("A", "B", "C", "D", "E")):
        self.headers = headers or LIVE_HEADERS
        self.rows = rows or LIVE_ROWS
        self.books = books
        self.gets: list[str] = []
        self.cleared: list[str] = []
        self.written: list[dict] = []
        self.other_posts: list[tuple[str, dict]] = []

    def get(self, url, timeout=None):
        self.gets.append(url)
        if "fields=sheets.properties" in url:
            return FakeResponse({"sheets": [
                {"properties": {"sheetId": index, "title": title,
                                "gridProperties": {"rowCount": self.rows[title],
                                                   "columnCount": len(header)}}}
                for index, (title, header) in enumerate(self.headers.items())]})
        if "values:batchGet" in url:
            return FakeResponse({"valueRanges": [{"values": [header]}
                                                 for header in self.headers.values()]})
        if "Books" in url and "A2" in url:
            return FakeResponse({"values": [[book] for book in self.books]})
        return FakeResponse({"values": []})

    def post(self, url, json=None, timeout=None):
        body = json or {}
        if "values:batchClear" in url:
            self.cleared.extend(body.get("ranges", []))
            return FakeResponse({"clearedRanges": body.get("ranges", [])})
        if "values:batchUpdate" in url:
            self.written.extend(body.get("data", []))
            cells = sum(len(entry["values"]) * len(entry["values"][0] or [1])
                        for entry in body.get("data", []) if entry.get("values"))
            return FakeResponse({"totalUpdatedCells": cells})
        self.other_posts.append((url, body))
        return FakeResponse({})

    # ---- little helpers the tests read the recording with ----

    def ranges_touched(self) -> list[str]:
        return [entry["range"] for entry in self.written]

    def columns_touched(self, tab: str) -> set[str]:
        """Every column this run wrote into, on one tab.

        A range like A2:C9 is expanded to A, B and C rather than just its two
        ends. That matters: the whole point of these tests is to prove no
        formula cell is written to, and a range that steps over a formula
        column in the middle would otherwise pass unnoticed.
        """
        found = set()
        for entry in self.written:
            name, _, cells = entry["range"].partition("!")
            if name.strip("'") != tab:
                continue
            letters = [match.group(1) for part in cells.split(":")
                       if (match := re.match(r"([A-Z]+)", part))]
            if not letters:
                continue
            if len(letters) == 1:
                found.add(letters[0])
                continue
            first, last = sorted((_column_number(letters[0]),
                                  _column_number(letters[-1])))
            found.update(_column_letter(number) for number in range(first, last + 1))
        return found


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    """A database holding one full trading day across two books."""
    target = tmp_path / "trading.sqlite"
    monkeypatch.setattr(db, "db_path", lambda: target)
    db.migrate(target)

    decision = db.record_decision(
        ts="2026-09-08 09:35:02", book_id="A", shape="pick",
        model="openrouter/anthropic/claude-fable-5.1", prompt_hash="9f2c1a",
        rules_commit="41d734d", symbol="AAPL", action="pick", side="long",
        entry=231.10, stop=228.0, target=238.0, qty=40, confidence=0.71,
        rationale="broke the opening range on 3.1x volume", cost_usd=0.0184)
    db.record_decision(ts="2026-09-08 09:35:02", book_id="A", shape="pick",
                       symbol="NVDA", action="skip", model="claude-fable-5.1",
                       prompt_hash="9f2c1a", rationale="already extended")
    db.record_decision(ts="2026-09-08 09:41:00", book_id="B", shape="rules",
                       symbol="MSFT", action="pick", rejected=True,
                       reject_reason="max_open_positions", model="none",
                       rationale="five already open")
    order = db.record_order(ts="2026-09-08 09:35:09", book_id="A",
                            order_ref="BOOK_A", broker_order_id=99001,
                            symbol="AAPL", side="BUY", qty=40, order_type="LMT",
                            limit_price=231.20, tif="DAY", purpose="entry",
                            status="filled", decision_id=decision)
    db.record_fill(ts="2026-09-08 09:35:11", order_id=order, exec_id="0001.abc",
                   symbol="AAPL", side="BUY", qty=40, price=231.25,
                   commission=1.0, decision_price=231.10)
    db.record_alert("warn", "market data", "delayed quotes only, IBKR code 10168",
                    channels=["slack", "log"], ts="2026-09-08 09:02:11")
    for book, start, end in (("A", 100000, 100310), ("B", 100000, 99940)):
        db.upsert_daily_summary("2026-09-08", book, start_equity=start,
                                end_equity=end, spy_close=765.25, trades=1,
                                commissions=1.0,
                                model_cost_usd=0.0184 if book == "A" else None,
                                rule_triggers=0 if book == "A" else 1,
                                missed_ticks=0, max_drawdown_pct=-0.0041)
    return target


# ------------------------------------------------------------------ row shapes

def test_a_trade_row_is_the_twenty_columns_the_sheet_expects(seeded):
    rows = sync_sheet.trades_rows()
    assert len(rows) == 1
    row = rows[0]
    assert len(row) == 20, "A to T, stopping before the two slippage formulas"
    assert len(row) == len(sync_sheet.TRADES_HEADERS)
    assert row == [
        "2026-09-08 09:35:11",                      # A Timestamp (ET)
        "2026-09-08",                               # B Date
        "AAPL",                                     # C Symbol
        "BUY",                                      # D Side
        40,                                         # E Qty
        231.25,                                     # F Fill Price
        9250.0,                                     # G Notional
        1.0,                                        # H Commission
        "LMT",                                      # I Order Type
        "99001",                                    # J Order Id
        "entry",                                    # K Strategy Signal
        "broke the opening range on 3.1x volume",   # L Reason
        "",                                         # M Realised P&L, not known
        "",                                         # N Notes
        "A",                                        # O Book
        "openrouter/anthropic/claude-fable-5.1",    # P Model
        0.0184,                                     # Q Model Cost USD
        "9f2c1a",                                   # R Prompt Hash
        231.1,                                      # S Decision Price
        "2026-09-08 09:35:02",                      # T Decision Time (ET)
    ]


def test_a_trade_row_takes_its_reason_model_cost_and_hash_from_the_decision(seeded):
    """Item 14. Four of the twenty columns reach the sheet through one join.

    db.trades_for_date walks fills to orders to decisions, and the middle link is
    orders.decision_id. Nothing in agent/loop.py ever set it until 2026-09-06, so
    the join matched nothing and all four of these columns were blank on every
    trade row the nightly sync wrote. A month of results that cannot be read
    against the model that produced it or the price it cost is the whole cost of
    a NULL in one column.
    """
    linked = sync_sheet.trades_rows()[0]
    assert linked[11] == "broke the opening range on 3.1x volume"    # L Reason
    assert linked[15] == "openrouter/anthropic/claude-fable-5.1"     # P Model
    assert linked[16] == pytest.approx(0.0184)                       # Q Model Cost USD
    assert linked[17] == "9f2c1a"                                    # R Prompt Hash

    # And an order with no decision on it, which is what every order row in the
    # database looked like before the fix. The row is still written, honestly
    # blank, rather than carrying a made up model or a made up cost.
    orphan = db.record_order(ts="2026-09-08 10:05:00", book_id="A",
                             order_ref="BOOK_A", broker_order_id=99002,
                             symbol="MSFT", side="BUY", qty=10, order_type="MKT",
                             tif="DAY", purpose="entry", status="filled")
    db.record_fill(ts="2026-09-08 10:05:02", order_id=orphan, exec_id="0002.abc",
                   symbol="MSFT", side="BUY", qty=10, price=500.0)

    blank = [row for row in sync_sheet.trades_rows() if row[2] == "MSFT"][0]
    assert [blank[11], blank[15], blank[16], blank[17]] == ["", "", "", ""]
    assert blank[2] == "MSFT" and blank[4] == 10, (
        "the trade itself still lands, so a missing decision loses the reason "
        "rather than the fill")


def test_the_book_column_lands_in_column_o_where_every_formula_looks_for_it():
    """The Books tab slices Trades by column O. One column out and every
    per book figure in the sheet silently becomes zero."""
    assert sync_sheet.TRADES_HEADERS.index("Book") == 14      # O is the 15th
    assert sync_sheet.TRADES_HEADERS.index("Model Cost USD") == 16   # Q
    assert sync_sheet.TRADES_HEADERS.index("Decision Price") == 18   # S


def test_a_daily_row_skips_the_formula_columns(seeded):
    rows = sync_sheet.daily_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["abc"] == ["2026-09-08", 200000.0, 200250.0], "A, B and C only"
    assert row["g"] == [765.25], "G on its own, because D to F are formulas"
    assert row["klmn"][0] == 2, "K, trades added up across the books"
    assert row["klmn"][1] == 1, "L, rules triggered"
    assert "2 books" in row["klmn"][2], "M, the note says how many books reported"
    assert row["klmn"][3] == pytest.approx(0.0184), "N, the day's model spend"


def test_the_daily_tab_warns_when_a_book_did_not_report(seeded):
    """A missing book makes the account look as if it lost a hundred thousand
    overnight, and the Summary tab would read that as a real drawdown."""
    db.upsert_daily_summary("2026-09-09", "A", start_equity=100310,
                            end_equity=100400, spy_close=762.10)
    plan = sync_sheet.build_plan()
    assert "CAREFUL" in plan["Daily"]["note"]
    assert "2026-09-09" in plan["Daily"]["note"]


def test_the_rules_log_holds_decisions_alerts_and_refusals_in_time_order(seeded):
    rows = sync_sheet.rules_rows()
    assert len(rows) == 4
    assert [row[0] for row in rows] == sorted(row[0] for row in rows)

    kinds = [row[1] for row in rows]
    assert kinds == ["alert:WARN", "decision", "decision", "max_open_positions"]

    alert = rows[0]
    assert alert[2] == "market data: delayed quotes only, IBKR code 10168"
    assert alert[3] == "sent to slack, log"
    assert alert[4] == "", "an alert belongs to no single book"

    pick = rows[1]
    assert pick[2] == "AAPL: broke the opening range on 3.1x volume"
    assert pick[3] == "[pick] pick"
    assert pick[4] == "A"
    assert pick[6] == 0.0184

    refused = rows[3]
    assert refused[1] == "max_open_positions", "named by the guardrail that bit"
    assert refused[3] == "refused: pick"
    assert refused[4] == "B"


def test_an_alert_never_counts_against_a_books_rule_triggers(seeded):
    """The Books tab counts Rules Log rows that are not the word decision, by
    book. An alert has no book, so it cannot inflate anybody's count."""
    for row in sync_sheet.rules_rows():
        if row[1].startswith("alert:"):
            assert row[4] == ""


def test_the_books_rows_are_the_three_the_sheet_cannot_work_out(seeded):
    rows = sync_sheet.books_rows()
    assert [row["book_id"] for row in rows] == ["A", "B"]
    assert rows[0]["equity"] == 100310.0
    assert rows[0]["max_drawdown_pct"] == pytest.approx(-0.0041)
    assert rows[0]["missed_ticks"] == 0
    assert set(rows[0]) == {"book_id", "equity", "max_drawdown_pct", "missed_ticks"}


def test_a_cost_of_zero_is_written_as_a_blank_and_not_a_zero():
    """A cost of 0 from OpenRouter means not settled yet, not free."""
    assert sync_sheet._cost(0) == ""
    assert sync_sheet._cost(0.0) == ""
    assert sync_sheet._cost(None) == ""
    assert sync_sheet._cost("") == ""
    assert sync_sheet._cost("nonsense") == ""
    assert sync_sheet._cost(0.0184) == 0.0184


def test_free_text_that_looks_like_a_formula_is_written_as_text():
    assert sync_sheet._cell("=SUM(A1:A2)") == "'=SUM(A1:A2)"
    assert sync_sheet._cell("+10 percent") == "'+10 percent"
    assert sync_sheet._cell("@here") == "'@here"
    assert sync_sheet._cell("a plain reason") == "a plain reason"
    assert sync_sheet._cell(None) == ""


def test_the_config_tab_comes_from_the_config_files(seeded):
    """Those are settings, not results, so they cannot come from the database."""
    rows = sync_sheet.config_rows()
    assert [row[0] for row in rows] == ["Starting equity", "Max position %",
                                        "Daily loss cap %", "Universe", "Cadence"]
    assert "books" in str(rows[0][1]), "read from config/books.yaml"
    assert rows[4][1], "the cadence should have been read from guardrails.yaml"


def test_the_summary_tab_is_left_entirely_alone(seeded):
    plan = sync_sheet.build_plan()
    assert plan["Summary"]["rows"] == []
    assert "formula" in plan["Summary"]["note"]


# ------------------------------------------------------------------ the writing

def run_sync(session, argv):
    """Run the command line with our stand in session instead of Google's."""
    return sync_sheet.main(argv), session


@pytest.fixture()
def http(monkeypatch):
    fake = FakeSession()
    monkeypatch.setattr(sync_sheet, "session", lambda: fake)
    return fake


def test_a_dry_run_reads_the_live_sheet_and_writes_nothing(seeded, http, capsys):
    assert sync_sheet.main(["--dry-run"]) == 0
    assert http.gets, "it should have read the sheet to check the headings"
    assert http.written == [], "and written nothing at all"
    assert http.cleared == [], "and cleared nothing"
    printed = capsys.readouterr().out
    assert "headers all match" in printed
    assert "Nothing was written" in printed


def test_a_write_never_touches_the_trades_slippage_formulas(seeded, http):
    assert sync_sheet.main(["--write"]) == 0
    touched = http.columns_touched("Trades")
    assert touched, "it should have written something to Trades"
    assert not (touched & TRADES_FORMULA_COLUMNS), (
        f"wrote into the slippage formula columns: {touched & TRADES_FORMULA_COLUMNS}")
    for cleared in http.cleared:
        if cleared.split("!")[0].strip("'") == "Trades":
            assert cleared.endswith(f"T{sync_sheet.TRADES_FORMULA_LAST_ROW}"), cleared
            assert ":T" in cleared, f"the clear must stop at column T: {cleared}"


def test_a_write_never_touches_the_daily_formula_columns(seeded, http):
    assert sync_sheet.main(["--write"]) == 0
    touched = http.columns_touched("Daily")
    assert touched == {"A", "B", "C", "G", "K", "L", "M", "N"}, (
        f"only A to C, G and K to N should be written, got {touched}")
    assert not (touched & DAILY_FORMULA_COLUMNS)
    for cleared in http.cleared:
        if cleared.split("!")[0].strip("'") != "Daily":
            continue
        columns = set(re.findall(r"([A-Z]+)\d+", cleared.split("!")[1]))
        assert not (columns & DAILY_FORMULA_COLUMNS), cleared


def test_a_write_only_fills_in_the_three_blank_books_columns(seeded, http):
    assert sync_sheet.main(["--write"]) == 0
    touched = http.columns_touched("Books")
    assert touched == {"E", "I", "N"}, f"expected Equity, Max DD, Missed Ticks: {touched}"
    assert not (touched & BOOKS_UNTOUCHABLE_COLUMNS)


def test_a_write_puts_each_books_figures_on_that_books_own_row(seeded, http):
    assert sync_sheet.main(["--write"]) == 0
    by_range = {entry["range"]: entry["values"][0][0] for entry in http.written
                if entry["range"].startswith("Books!")}
    # The fake sheet lists books A to E down rows 2 to 6.
    assert by_range["Books!E2"] == 100310.0, "book A on row 2"
    assert by_range["Books!E3"] == 99940.0, "book B on row 3"
    assert "Books!E4" not in by_range, "books with no rows in the database are skipped"


def test_a_write_leaves_the_summary_tab_untouched(seeded, http):
    assert sync_sheet.main(["--write"]) == 0
    assert not [entry for entry in http.written
                if entry["range"].startswith("Summary")]
    assert not [name for name in http.cleared if name.startswith("Summary")]


def test_the_config_tab_write_only_touches_the_value_column(seeded, http):
    assert sync_sheet.main(["--write"]) == 0
    assert sync_sheet.config_rows(), "there should be config rows to write"
    assert http.columns_touched("Config") == {"B"}, (
        "the setting names in A and the notes in C are typed in, not generated")


def test_every_tab_is_cleared_before_it_is_rewritten(seeded, http):
    """This is what makes it idempotent. Without the clear, a day removed from
    the database would live on in the sheet for ever."""
    assert sync_sheet.main(["--write"]) == 0
    cleared = {name.split("!")[0].strip("'") for name in http.cleared}
    assert {"Trades", "Daily", "Rules Log"} <= cleared


def test_running_it_twice_sends_exactly_the_same_thing(seeded, monkeypatch):
    first, second = FakeSession(), FakeSession()
    monkeypatch.setattr(sync_sheet, "session", lambda: first)
    assert sync_sheet.main(["--write"]) == 0
    monkeypatch.setattr(sync_sheet, "session", lambda: second)
    assert sync_sheet.main(["--write"]) == 0
    assert first.written == second.written
    assert first.cleared == second.cleared


def test_one_day_can_be_rewritten_on_its_own(seeded, http, monkeypatch):
    assert sync_sheet.main(["--write", "--date", "2026-09-08"]) == 0
    trades = [entry for entry in http.written if entry["range"].startswith("Trades!")]
    assert len(trades) == 1
    assert len(trades[0]["values"]) == 1

    other = FakeSession()
    monkeypatch.setattr(sync_sheet, "session", lambda: other)
    assert sync_sheet.main(["--write", "--date", "2026-09-09"]) == 0
    written = [entry for entry in other.written if entry["range"].startswith("Trades!")]
    assert written == [], "a day with no fills writes no trade rows"


def test_only_the_tab_you_asked_for_is_touched(seeded, http):
    assert sync_sheet.main(["--write", "--tab", "Trades"]) == 0
    tabs = {entry["range"].split("!")[0].strip("'") for entry in http.written}
    assert tabs == {"Trades"}


def test_an_empty_database_clears_the_sheet_rather_than_leaving_stale_rows(tmp_path,
                                                                          monkeypatch):
    target = tmp_path / "empty.sqlite"
    monkeypatch.setattr(db, "db_path", lambda: target)
    db.migrate(target)
    fake = FakeSession()
    monkeypatch.setattr(sync_sheet, "session", lambda: fake)

    assert sync_sheet.main(["--write"]) == 0
    cleared = {name.split("!")[0].strip("'") for name in fake.cleared}
    assert {"Trades", "Daily", "Rules Log"} <= cleared
    for tab in ("Trades", "Daily", "Rules Log"):
        assert not [entry for entry in fake.written
                    if entry["range"].split("!")[0].strip("'") == tab]


# ------------------------------------------------------------------ safety checks

def test_the_run_stops_when_a_column_has_moved(seeded, monkeypatch, capsys):
    """The column letters are hard coded, so a column inserted by hand has to
    stop the run rather than quietly shift every value one to the left."""
    moved = {name: list(header) for name, header in LIVE_HEADERS.items()}
    moved["Trades"].insert(3, "Somebody Added This")
    fake = FakeSession(headers=moved)
    monkeypatch.setattr(sync_sheet, "session", lambda: fake)

    assert sync_sheet.main(["--write"]) == 2
    assert fake.written == [], "nothing may be written once the shape is wrong"
    assert fake.cleared == [], "and nothing may be cleared either"
    assert "not the shape this writes into" in capsys.readouterr().err


def test_the_run_stops_when_the_slippage_columns_are_missing(seeded, monkeypatch):
    """If U and V are gone, the sheet is not the one this was built for and
    writing to it would put trades where the formulas used to be."""
    without = {name: list(header) for name, header in LIVE_HEADERS.items()}
    without["Trades"] = without["Trades"][:20]
    fake = FakeSession(headers=without)
    monkeypatch.setattr(sync_sheet, "session", lambda: fake)
    assert sync_sheet.main(["--write"]) == 2
    assert fake.written == []


def test_the_run_stops_when_a_tab_is_missing(seeded, monkeypatch):
    fewer = {name: header for name, header in LIVE_HEADERS.items()
             if name != "Books"}
    rows = {name: count for name, count in LIVE_ROWS.items() if name != "Books"}
    fake = FakeSession(headers=fewer, rows=rows)
    monkeypatch.setattr(sync_sheet, "session", lambda: fake)
    assert sync_sheet.main(["--write"]) == 2
    assert fake.written == []


def test_the_headers_this_writes_are_the_ones_the_sheet_builder_creates():
    """Both files list the Trades columns. If they ever disagree, this fails
    rather than the sheet quietly getting the wrong values in the wrong cells."""
    source = (REPO / "ledger" / "create_ledger_sheet.py").read_text(encoding="utf-8")
    namespace: dict = {}
    block = source.split("TRADES_HEADERS = [", 1)[1].split("]", 1)[0]
    exec("TRADES_HEADERS = [" + block + "]", namespace)   # noqa: S102
    built = [name for name in namespace["TRADES_HEADERS"]]
    assert built[:20] == sync_sheet.TRADES_HEADERS
    assert built[20:] == ["Slippage $", "Slippage bps"]


def test_the_rules_log_grows_when_there_are_more_rows_than_the_tab_holds(seeded,
                                                                        monkeypatch):
    """A month of five books deciding every five minutes is thousands of rows,
    and the tab arrives three hundred deep."""
    for number in range(400):
        db.record_decision(ts=f"2026-09-08 10:{number // 60:02d}:{number % 60:02d}",
                           book_id="A", symbol="AAPL", action="skip",
                           rationale=f"row {number}")
    fake = FakeSession()
    monkeypatch.setattr(sync_sheet, "session", lambda: fake)
    assert sync_sheet.main(["--write", "--tab", "Rules Log"]) == 0
    assert any("appendDimension" in str(body) for _, body in fake.other_posts), (
        "the tab should have been made longer before the write")


def test_more_trades_than_the_formulas_reach_is_said_out_loud(seeded, monkeypatch):
    """Writing a trade below row 1000 would leave it with no slippage formula,
    silently. Better to say so than to write it."""
    monkeypatch.setattr(sync_sheet, "TRADES_FORMULA_LAST_ROW", 3)
    for number in range(5):
        order = db.record_order(book_id="A", symbol="AAPL", side="BUY", qty=1)
        db.record_fill(order_id=order, exec_id=f"e{number}", symbol="AAPL",
                       side="BUY", qty=1, price=100.0 + number)
    plan = sync_sheet.build_plan()
    assert len(plan["Trades"]["rows"]) == 2, "only what the formulas reach"
    assert "left out" in plan["Trades"]["note"]
    assert "database still has them all" in plan["Trades"]["note"]


def test_the_sync_holds_no_database_connection_while_it_talks_to_google(seeded, http):
    """Every row is read out first and the connection closed, because a SQLite
    lock held across a network call is how two processes deadlock."""
    plan = sync_sheet.build_plan()
    assert plan["Trades"]["rows"], "the plan is built entirely before any request"
    assert http.gets == [], "and building it made no request at all"

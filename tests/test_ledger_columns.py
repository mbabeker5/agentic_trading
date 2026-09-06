"""The Trades tab has two owners, and these tests keep them from arguing.

Python owns columns A to T. It writes the fill and, new in this change, the
Decision Price and Decision Time the trade was decided at. The spreadsheet owns
columns U and V, where two formulas work out the slippage: the gap between the
price we decided at and the price we actually got. Those formulas are put in
place once, by ledger/create_ledger_sheet.py, and sit waiting in every row.

That split is easy to break by accident and expensive to notice late, because a
broken ledger looks like an empty cell rather than an error. So these tests
check the seam from both sides, and none of them touch the network, the token or
the real sheet:

1. The builder's headers and the writer's column list say the same thing.
2. The four new columns are on the end and nothing above them moved.
3. Python does not claim the two formula columns.
4. A trade is appended over A:T without pushing a new row in, while the Rules
   Log, which has no formulas, still does push a row in.
5. The slippage formulas cover every row and point at the right ones.
6. A dry run trade carries the decision price and time in S and T.
7. The Summary metrics the formulas address by cell have not shifted.
8. Every tab has one column width for every column.

Run them with:

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest tests/test_ledger_columns.py -q
"""
from __future__ import annotations

import inspect
from datetime import datetime

from ledger import create_ledger_sheet as builder
from ledger import ledger_writer

#: The eighteen columns the ledger had before the slippage work, written out in
#: full. If a rename or a reorder ever happens above column S, this list is what
#: notices, because every formula in the sheet is written against these
#: positions.
ORIGINAL_TRADES_HEADERS = [
    "Timestamp (ET)", "Date", "Symbol", "Side", "Qty", "Fill Price", "Notional",
    "Commission", "Order Type", "Order Id", "Strategy Signal", "Reason",
    "Realised P&L", "Notes", "Book", "Model", "Model Cost USD", "Prompt Hash",
]

#: The four added on the end, in order: S, T, U, V.
NEW_TRADES_HEADERS = [
    "Decision Price", "Decision Time (ET)", "Slippage $", "Slippage bps",
]

#: What log_trade prints in front of the row when it is only pretending.
DRY_RUN_PREFIX = "DRY RUN would add to the ledger tab Trades: "


def column_letter(index: int) -> str:
    """A to V from a zero based column number. The tab never gets past Z."""
    return chr(ord("A") + index)


def capture_appends(monkeypatch) -> list[dict]:
    """Swap _append for a recorder, keeping the real function's own defaults.

    log_rule calls _append without naming the last two arguments, so the
    recorder binds the call against the real signature and fills the defaults
    in. That way the test reads what actually reaches Google, not what a
    stand in decided to assume.
    """
    signature = inspect.signature(ledger_writer._append)
    calls: list[dict] = []

    def fake(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        calls.append(dict(bound.arguments))
        return True

    monkeypatch.setattr(ledger_writer, "_append", fake)
    return calls


# ------------------------------------------- 1 and 2. the two lists must agree

def test_the_builder_and_the_writer_agree_on_every_column_python_writes():
    written = [heading for heading, _ in ledger_writer.TRADES_COLUMNS]
    assert written == builder.TRADES_HEADERS[:len(written)]
    assert len(written) == 20
    assert column_letter(len(written) - 1) == "T"


def test_the_first_eighteen_columns_have_not_moved():
    assert builder.TRADES_HEADERS[:18] == ORIGINAL_TRADES_HEADERS


def test_the_four_new_columns_are_on_the_end_in_order():
    assert builder.TRADES_HEADERS[18:] == NEW_TRADES_HEADERS
    assert len(builder.TRADES_HEADERS) == 22


def test_the_two_new_inputs_answer_to_the_names_a_caller_would_reach_for():
    aliases = dict(ledger_writer.TRADES_COLUMNS)
    assert aliases["Decision Price"] == ("decision_price", "decided_price")
    assert aliases["Decision Time (ET)"] == (
        "decision_time", "decision_time_et", "decided_at")


# --------------------------------------- 3. Python must not touch the formulas

def test_python_does_not_claim_the_two_slippage_columns():
    """They are formulas in the sheet. Writing a blank to one would delete it."""
    written = [heading for heading, _ in ledger_writer.TRADES_COLUMNS]
    assert "Slippage $" in builder.TRADES_HEADERS
    assert "Slippage bps" in builder.TRADES_HEADERS
    assert "Slippage $" not in written
    assert "Slippage bps" not in written


# ------------------------------------------------------ 4. how a row is added

def test_a_trade_is_appended_over_the_columns_python_owns_and_no_further():
    first, last = ledger_writer.TRADES_APPEND_COLUMNS.split(":")
    assert first == "A"
    assert last == column_letter(len(ledger_writer.TRADES_COLUMNS) - 1) == "T"
    # U and V are the formula columns, and T stops short of both.
    assert last < "U"


def test_adding_a_trade_never_pushes_a_new_row_in(monkeypatch):
    """A pushed in row would arrive with no formulas and shove the ready ones down."""
    calls = capture_appends(monkeypatch)
    ledger_writer.log_trade({"symbol": "AAPL", "side": "BUY", "qty": 10,
                             "price": 231.40})
    assert len(calls) == 1
    assert calls[0]["tab"] == ledger_writer.TRADES_TAB
    assert calls[0]["columns"] == "A:T"
    assert calls[0]["insert_rows"] is False


def test_the_rules_log_still_pushes_a_new_row_in(monkeypatch):
    """It holds no formulas, so the old behaviour is still the right one."""
    calls = capture_appends(monkeypatch)
    ledger_writer.log_rule("2026-09-06 10:00:00", "daily_loss_cap",
                           "down 2.1 percent", "trading stopped for the day")
    assert len(calls) == 1
    assert calls[0]["tab"] == ledger_writer.RULES_TAB
    assert calls[0]["columns"] == "A:Z"
    assert calls[0]["insert_rows"] is True


# ------------------------------------------------------ 5. the formulas built

def test_the_slippage_formulas_fill_every_row_below_the_header():
    rows = builder.trades_formula_rows()
    assert len(rows) == builder.TRADES_FORMULA_ROWS == 999
    assert all(len(row) == 2 for row in rows)
    # Row 2 is the first row under the header, row 1000 is the last row of the
    # tab, so the formulas reach both ends and no further.
    assert "$S2" in rows[0][0] and "$U2" in rows[0][1]
    assert "$S1000" in rows[-1][0] and "$U1000" in rows[-1][1]
    assert 1 + len(rows) == builder.TABS[0]["rows"] == 1000


def test_the_dollar_slippage_formula_reads_the_way_it_is_meant_to():
    dollars, _bps = builder.trades_formula_rows()[0]
    assert dollars == (
        '=IF(OR(NOT(ISNUMBER($S2)),NOT(ISNUMBER($F2)),NOT(ISNUMBER($E2))),"",'
        'IF(UPPER($D2)="BUY",($F2-$S2)*ABS($E2),'
        'IF(UPPER($D2)="SELL",($S2-$F2)*ABS($E2),"")))')


def test_the_basis_points_formula_reads_the_way_it_is_meant_to():
    _dollars, bps = builder.trades_formula_rows()[0]
    assert bps == (
        '=IF(OR(NOT(ISNUMBER($U2)),NOT(ISNUMBER($S2)),NOT(ISNUMBER($E2)),'
        '$S2=0,$E2=0),"",$U2/($S2*ABS($E2))*10000)')


# --------------------------------------------------------- 6. a dry run trade

def test_a_dry_run_buy_carries_the_decision_price_and_time_in_s_and_t(capsys):
    ledger_writer.log_trade(
        {"symbol": "AAPL", "side": "BUY", "qty": 100, "price": 10.05},
        decision_price=10.00,
        decision_time=datetime(2026, 9, 6, 10, 31, 0),
        dry_run=True)

    printed = capsys.readouterr().out.strip()
    cells = printed.split(DRY_RUN_PREFIX, 1)[1].split(" | ")

    assert len(cells) == 20
    assert cells[ord("S") - ord("A")] == "10.0"
    # A datetime goes through the same helper as the Timestamp column, so it
    # lands as a New York time string rather than a Python object.
    assert cells[ord("T") - ord("A")] == "2026-09-06 10:31:00"


# ------------------------------------------ 7. the Summary rows did not shift

def test_the_summary_metrics_the_formulas_address_by_cell_have_not_moved():
    """Summary formulas point at $B$4 to $B$7, and Books points at Summary!$B$7.

    Row number is the position in the list plus two, because row 1 is the
    header. If the two new slippage metrics had been inserted anywhere but the
    end, every one of these would now be reading the wrong number.
    """
    names = [row[0] for row in builder.summary_rows()]
    row_of = {name: index + 2 for index, name in enumerate(names)}

    assert row_of["Starting Equity"] == 4
    assert row_of["Current Equity"] == 5
    assert row_of["Total Return %"] == 6
    assert row_of["SPY Return %"] == 7
    assert row_of["Alpha"] == 8

    alpha_formula = builder.summary_rows()[row_of["Alpha"] - 2][1]
    assert "$B$6" in alpha_formula and "$B$7" in alpha_formula
    assert "Summary!$B$7" in builder.books_rows()[0][6]


def test_the_two_slippage_metrics_are_the_last_two_summary_rows():
    names = [row[0] for row in builder.summary_rows()]
    assert names[-2:] == ["Avg Slippage bps", "Slippage $ total"]


# ------------------------------------------------------- 8. widths and shapes

def test_every_tab_has_one_column_width_for_every_column():
    for tab in builder.TABS:
        assert len(tab["widths"]) == len(tab["headers"]), tab["title"]


def test_every_book_row_has_one_cell_for_every_books_column():
    for row in builder.books_rows():
        assert len(row) == len(builder.BOOKS_HEADERS)

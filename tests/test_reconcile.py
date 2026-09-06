"""Tests for the daily check that the five books and the broker still agree.

agent/reconcile.py is the referee for one question: does what books A, B, C, D
and E believe they hold add up to what the shared IBKR paper account DUT077572
actually holds, and is every order in that account claimed by exactly one book.
These tests hand it made up broker data and made up book data and check that it
says yes when it should and no when it should, in sentences a person can read.

Nothing here touches the network, IB Gateway or a broker account. Every input is
a plain dictionary written out in the test itself.

Run them with:
    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python -m pytest -q
"""

from __future__ import annotations

import pytest

from agent.reconcile import (
    KIND_MISSING_WORKING_ORDER,
    KIND_ORDER_NOT_IN_BOOK,
    KIND_ORPHAN_POSITION,
    KIND_POSITION_QTY,
    KIND_UNKNOWN_ORDER_REF,
    ORDER_REF_PREFIX,
    Mismatch,
    Orphan,
    ReconcileReport,
    reconcile,
)


# ---------------------------------------------------------------------------
# Helpers, so every test reads as a story rather than as a pile of dictionaries
# ---------------------------------------------------------------------------


def held(symbol: str, qty, avg_cost: float = 100.0) -> dict:
    """One holding as the broker reports it. A short is a negative quantity."""
    return {"symbol": symbol, "qty": qty, "avg_cost": avg_cost}


def working(
    order_id,
    symbol: str = "NVDA",
    side: str = "BUY",
    qty: int = 10,
    order_ref: str = "BOOK_A",
) -> dict:
    """One open order as the broker reports it, tagged for the book that sent it."""
    return {
        "orderId": order_id,
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "order_ref": order_ref,
    }


def book(positions: dict | None = None, working_orders: dict | None = None) -> dict:
    """What one book believes about itself."""
    return {
        "positions": positions or {},
        "working_orders": working_orders or {},
    }


# The single share of SPY the paper account has held since a manual test.
LEFTOVER_SPY = {"SPY": 1}


# ---------------------------------------------------------------------------
# An account where everything already agrees
# ---------------------------------------------------------------------------


def test_a_clean_account_where_every_book_matches_the_broker_has_nothing_to_say():
    report = reconcile(
        broker_positions=[held("AAPL", 150), held("MSFT", 40)],
        broker_open_orders=[working(7, symbol="NVDA", order_ref="BOOK_B")],
        books_state={
            "A": book({"AAPL": 100}),
            "B": book({"AAPL": 50}, {7: {"symbol": "NVDA", "side": "BUY", "qty": 10}}),
            "C": book({"MSFT": 40}),
            "D": book(),
            "E": book(),
        },
    )
    assert report.ok is True
    assert report.lines == ()
    assert report.mismatches == ()
    assert report.orphans == ()
    assert report.books_to_halt == ()
    assert report.summary == "everything matched"


def test_a_book_that_holds_nothing_of_a_symbol_is_not_claiming_it():
    """A zero in a book's positions means it holds none, not that it owns none."""
    report = reconcile(
        broker_positions=[held("AAPL", 100)],
        broker_open_orders=[],
        books_state={"A": book({"AAPL": 100}), "B": book({"AAPL": 0})},
    )
    assert report.ok is True
    assert report.books_to_halt == ()


def test_quantities_that_arrive_from_the_broker_as_floats_are_read_as_whole_shares():
    report = reconcile(
        broker_positions=[held("AAPL", 100.0)],
        broker_open_orders=[],
        books_state={"A": book({"AAPL": 100.0})},
    )
    assert report.ok is True, report.lines


# ---------------------------------------------------------------------------
# Rule one: the books have to add up to the broker
# ---------------------------------------------------------------------------


def test_a_quantity_mismatch_stops_every_book_that_claims_that_symbol():
    """A holds 100 and C holds 50, which is 150, but the broker only has 120."""
    report = reconcile(
        broker_positions=[held("AAPL", 120)],
        broker_open_orders=[],
        books_state={"A": book({"AAPL": 100}), "C": book({"AAPL": 50})},
    )
    assert report.ok is False
    assert report.books_to_halt == ("A", "C")
    assert len(report.lines) == 1

    line = report.lines[0]
    assert "100" in line and "50" in line and "150" in line and "120" in line
    assert "AAPL" in line
    assert "Book A and book C stop trading until someone looks." in line

    assert {m.kind for m in report.mismatches} == {KIND_POSITION_QTY}
    assert {m.symbol for m in report.mismatches} == {"AAPL"}
    assert len(report.mismatches_for("A")) == 1
    assert len(report.mismatches_for("C")) == 1
    assert report.mismatches_for("B") == ()


def test_one_book_on_its_own_can_disagree_with_the_broker():
    report = reconcile(
        broker_positions=[held("AAPL", 120)],
        broker_open_orders=[],
        books_state={"A": book({"AAPL": 100}), "B": book()},
    )
    assert report.ok is False
    assert report.books_to_halt == ("A",)
    assert report.lines[0].endswith("Book A stops trading until someone looks.")


def test_a_symbol_a_book_claims_that_the_broker_does_not_hold_at_all_is_caught():
    report = reconcile(
        broker_positions=[held("MSFT", 40)],
        broker_open_orders=[],
        books_state={"A": book({"KO": 75}), "B": book({"MSFT": 40})},
    )
    assert report.ok is False
    assert report.books_to_halt == ("A",)
    assert len(report.lines) == 1
    assert "KO" in report.lines[0]
    assert "none at all" in report.lines[0]


def test_a_short_position_the_broker_disagrees_about_is_caught_too():
    report = reconcile(
        broker_positions=[held("TSLA", -30)],
        broker_open_orders=[],
        books_state={"A": book({"TSLA": -20})},
    )
    assert report.ok is False
    assert report.books_to_halt == ("A",)
    assert "short" in report.lines[0]


# ---------------------------------------------------------------------------
# Rule four: positions nobody claims
# ---------------------------------------------------------------------------


def test_a_position_at_the_broker_that_no_book_claims_is_an_orphan():
    report = reconcile(
        broker_positions=[held("AAPL", 100), held("GME", 20, avg_cost=31.5)],
        broker_open_orders=[],
        books_state={"A": book({"AAPL": 100})},
    )
    assert report.ok is False
    assert report.books_to_halt == (), "nobody claims it, so nobody can be stopped"
    assert report.mismatches == ()

    assert len(report.orphans) == 1
    orphan = report.orphans[0]
    assert isinstance(orphan, Orphan)
    assert (orphan.symbol, orphan.qty, orphan.avg_cost, orphan.expected) == (
        "GME",
        20,
        31.5,
        False,
    )
    assert orphan.kind == KIND_ORPHAN_POSITION
    assert report.unexpected_orphans == (orphan,)
    assert orphan.line in report.lines
    assert "GME" in orphan.line and "$31.50" in orphan.line


def test_the_one_share_of_spy_from_the_manual_test_is_expected_and_is_fine():
    report = reconcile(
        broker_positions=[held("AAPL", 100), held("SPY", 1, avg_cost=612.4)],
        broker_open_orders=[],
        books_state={"A": book({"AAPL": 100})},
        expected_orphans=LEFTOVER_SPY,
    )
    assert report.ok is True
    assert report.books_to_halt == ()
    assert report.unexpected_orphans == ()
    assert report.summary == "everything matched"

    assert len(report.orphans) == 1
    assert report.orphans[0].expected is True
    spy_line = report.orphans[0].line
    assert spy_line in report.lines, "an expected orphan still gets written down"
    assert "SPY" in spy_line
    assert "expect" in spy_line
    assert "1 share" in spy_line


def test_an_expected_orphan_whose_quantity_has_changed_is_not_expected_any_more():
    """We forgive exactly 1 share of SPY. Five of them is somebody's mistake."""
    report = reconcile(
        broker_positions=[held("SPY", 5, avg_cost=612.4)],
        broker_open_orders=[],
        books_state={"A": book()},
        expected_orphans=LEFTOVER_SPY,
    )
    assert report.ok is False
    assert report.orphans[0].expected is False
    assert report.unexpected_orphans == report.orphans
    assert report.books_to_halt == ()
    assert "5 shares" in report.orphans[0].line
    assert "1 share" in report.orphans[0].line, "the line says what we expected"


def test_expected_orphans_can_be_given_as_a_plain_list_of_symbols_instead():
    """A bare list forgives any quantity of that symbol, however much it changes."""
    for quantity in (1, 5, 500):
        report = reconcile(
            broker_positions=[held("SPY", quantity)],
            broker_open_orders=[],
            books_state={"A": book()},
            expected_orphans=["SPY"],
        )
        assert report.ok is True, (quantity, report.lines)
        assert report.orphans[0].expected is True


def test_with_no_expected_orphans_at_all_the_leftover_spy_is_a_problem():
    report = reconcile([held("SPY", 1)], [], {"A": book()})
    assert report.ok is False
    assert report.orphans[0].expected is False
    assert report.summary == "1 problem, with no book to blame"


# ---------------------------------------------------------------------------
# Rules two and three: orders on both sides have to match
# ---------------------------------------------------------------------------


def test_an_order_reference_that_belongs_to_no_book_halts_nobody_but_is_a_problem():
    report = reconcile(
        broker_positions=[],
        broker_open_orders=[working(55, symbol="NVDA", order_ref="BOOK_Z")],
        books_state={"A": book(), "B": book()},
    )
    assert report.ok is False
    assert report.books_to_halt == (), "there is no book to blame for it"
    assert len(report.mismatches) == 1

    mismatch = report.mismatches[0]
    assert isinstance(mismatch, Mismatch)
    assert mismatch.kind == KIND_UNKNOWN_ORDER_REF
    assert mismatch.book_id is None
    assert mismatch.order_id == "55"
    assert mismatch.symbol == "NVDA"
    assert "BOOK_Z" in mismatch.line
    assert "by hand" in mismatch.line


def test_an_order_carrying_no_reference_at_all_is_the_same_kind_of_problem():
    report = reconcile(
        broker_positions=[],
        broker_open_orders=[{"orderId": 55, "symbol": "NVDA", "side": "BUY", "qty": 10}],
        books_state={"A": book()},
    )
    assert report.ok is False
    assert report.books_to_halt == ()
    assert report.mismatches[0].kind == KIND_UNKNOWN_ORDER_REF
    assert "no order reference at all" in report.mismatches[0].line


def test_a_broker_order_the_book_it_names_has_never_heard_of_is_caught():
    report = reconcile(
        broker_positions=[],
        broker_open_orders=[working(55, symbol="NVDA", order_ref="BOOK_A")],
        books_state={"A": book(working_orders={"12": {}}), "B": book()},
    )
    assert report.ok is False
    assert report.books_to_halt == ("A",)

    kinds = {m.kind for m in report.mismatches}
    assert KIND_ORDER_NOT_IN_BOOK in kinds

    not_in_book = [m for m in report.mismatches if m.kind == KIND_ORDER_NOT_IN_BOOK]
    assert len(not_in_book) == 1
    assert not_in_book[0].order_id == "55"
    assert not_in_book[0].book_id == "A"
    assert "no record of it" in not_in_book[0].line


def test_a_working_order_a_book_believes_in_that_the_broker_has_never_heard_of():
    report = reconcile(
        broker_positions=[],
        broker_open_orders=[],
        books_state={
            "A": book(
                working_orders={
                    "77": {"symbol": "MSFT", "side": "SELL", "qty": 25},
                }
            ),
        },
    )
    assert report.ok is False
    assert report.books_to_halt == ("A",)
    assert len(report.mismatches) == 1

    mismatch = report.mismatches[0]
    assert mismatch.kind == KIND_MISSING_WORKING_ORDER
    assert (mismatch.book_id, mismatch.order_id, mismatch.symbol) == ("A", "77", "MSFT")
    assert "order 77" in mismatch.line
    assert "sell 25 shares of MSFT" in mismatch.line


def test_an_order_reference_is_read_the_same_however_it_is_typed():
    """BOOK_A, book_a, a spaced out reference and a bare A all mean book A."""
    for reference in ("BOOK_A", " book_a ", "A", " a "):
        report = reconcile(
            broker_positions=[],
            broker_open_orders=[working(7, order_ref=reference)],
            books_state={"A": book(working_orders={7: {}})},
        )
        assert report.ok is True, (reference, report.lines)


def test_a_caller_who_keys_the_books_by_the_full_reference_still_works():
    report = reconcile(
        broker_positions=[],
        broker_open_orders=[working(7, order_ref="BOOK_A")],
        books_state={"BOOK_A": book(working_orders={7: {}})},
    )
    assert report.ok is True, report.lines


def test_the_order_reference_prefix_is_the_same_one_the_guardrails_use():
    """Two copies of BOOK_ that drift apart would break every attribution."""
    from agent.guardrails import ORDER_REF_PREFIX as GUARDRAIL_PREFIX

    assert ORDER_REF_PREFIX == GUARDRAIL_PREFIX == "BOOK_"


# ---------------------------------------------------------------------------
# Several problems at once
# ---------------------------------------------------------------------------


def test_several_problems_at_once_name_each_affected_book_once_and_in_order():
    report = reconcile(
        broker_positions=[
            held("AAPL", 120),
            held("MSFT", 40),
            held("GME", 3, avg_cost=31.5),
            held("SPY", 1, avg_cost=612.4),
        ],
        broker_open_orders=[
            working(55, symbol="NVDA", order_ref="BOOK_Z"),
            working(9, symbol="TSLA", side="SELL", qty=3, order_ref="BOOK_D"),
        ],
        books_state={
            "A": book({"AAPL": 100}),
            "B": book({"MSFT": 40}),
            "C": book({"AAPL": 50}),
            "D": book(working_orders={"77": {"symbol": "KO", "side": "BUY", "qty": 5}}),
            "E": book(),
        },
        expected_orphans=LEFTOVER_SPY,
    )
    assert report.ok is False
    assert report.books_to_halt == ("A", "C", "D")
    assert report.books_to_halt == tuple(sorted(set(report.books_to_halt)))
    assert "B" not in report.books_to_halt, "book B agrees with the broker"
    assert "E" not in report.books_to_halt, "book E is holding nothing at all"

    kinds = {m.kind for m in report.mismatches}
    assert kinds == {
        KIND_POSITION_QTY,
        KIND_UNKNOWN_ORDER_REF,
        KIND_ORDER_NOT_IN_BOOK,
        KIND_MISSING_WORKING_ORDER,
    }

    expected_spy = [o for o in report.orphans if o.symbol == "SPY"]
    unclaimed_gme = [o for o in report.orphans if o.symbol == "GME"]
    assert expected_spy[0].expected is True
    assert unclaimed_gme[0].expected is False
    assert report.unexpected_orphans == (unclaimed_gme[0],)

    assert report.summary == "5 problems across books A, C, D"


def test_the_report_is_sorted_by_symbol_then_book_then_order():
    report = reconcile(
        broker_positions=[held("ZM", 5)],
        broker_open_orders=[],
        books_state={
            "C": book({"AAPL": 1}, {"55": {"symbol": "ZZZ"}, "7": {"symbol": "ZZZ"}}),
            "A": book({"AAPL": 1}),
        },
    )
    symbols = [m.symbol for m in report.mismatches]
    assert symbols == sorted(symbols), "symbols come out in alphabetical order"

    aapl_books = [m.book_id for m in report.mismatches if m.symbol == "AAPL"]
    assert aapl_books == ["A", "C"]

    zzz_orders = [m.order_id for m in report.mismatches if m.symbol == "ZZZ"]
    assert zzz_orders == ["7", "55"], "order 7 comes before order 55, as a person counts"


# ---------------------------------------------------------------------------
# The report reads like English, and reads the same way every time
# ---------------------------------------------------------------------------


def test_every_line_is_a_real_sentence_a_person_can_read():
    report = reconcile(
        broker_positions=[held("AAPL", 120), held("GME", 3), held("SPY", 1)],
        broker_open_orders=[
            working(55, symbol="NVDA", order_ref="BOOK_Z"),
            working(9, symbol="TSLA", side="SELL", qty=3, order_ref="BOOK_B"),
            {"orderId": 61, "symbol": "F", "side": "BUY", "qty": 2},
        ],
        books_state={
            "A": book({"AAPL": 100}, {"77": {"symbol": "KO", "side": "BUY", "qty": 5}}),
            "B": book(),
        },
        expected_orphans=LEFTOVER_SPY,
    )
    assert report.lines, "there is plenty wrong here, so there should be lines"

    for line in report.lines:
        assert line.endswith("."), line
        assert len(line.split()) >= 6, line
        assert line[0].isupper(), line

    for mismatch in report.mismatches:
        assert mismatch.line.endswith(".") and len(mismatch.line.split()) >= 6
    for orphan in report.orphans:
        assert orphan.line.endswith(".") and len(orphan.line.split()) >= 6

    assert set(report.lines) == {m.line for m in report.mismatches} | {
        o.line for o in report.orphans
    }


def test_the_same_input_twice_gives_exactly_the_same_report():
    inputs = dict(
        broker_positions=[held("MSFT", 40), held("AAPL", 120), held("GME", 3)],
        broker_open_orders=[
            working(9, symbol="TSLA", side="SELL", qty=3, order_ref="BOOK_D"),
            working(55, symbol="NVDA", order_ref="BOOK_Z"),
        ],
        books_state={
            "C": book({"AAPL": 50}),
            "A": book({"AAPL": 100}, {"77": {"symbol": "KO"}}),
            "D": book({"MSFT": 40}),
        },
    )
    first = reconcile(**inputs)
    second = reconcile(**inputs)

    assert isinstance(first, ReconcileReport)
    assert first == second
    assert first.lines == second.lines
    assert first.mismatches == second.mismatches
    assert first.orphans == second.orphans
    assert first.books_to_halt == second.books_to_halt


def test_the_summary_says_in_one_line_what_happened():
    clean = reconcile([held("AAPL", 10)], [], {"A": book({"AAPL": 10})})
    assert clean.summary == "everything matched"

    one_book = reconcile([held("AAPL", 10)], [], {"A": book({"AAPL": 11})})
    assert one_book.summary == "1 problem across book A"

    nobody = reconcile([], [working(55, order_ref="BOOK_Z")], {"A": book()})
    assert nobody.summary == "1 problem, with no book to blame"


# ---------------------------------------------------------------------------
# Broken input is refused with a sentence, not with a stack trace
# ---------------------------------------------------------------------------


def test_a_books_state_that_is_not_a_dictionary_is_refused():
    with pytest.raises(ValueError, match="books_state has to be a dictionary"):
        reconcile([], [], ["A", "B"])


def test_a_book_whose_state_is_not_a_dictionary_is_refused():
    with pytest.raises(ValueError, match="has to be a dictionary"):
        reconcile([], [], {"A": "nothing at all"})


def test_a_broker_position_with_no_symbol_on_it_is_refused():
    with pytest.raises(ValueError, match="There is no symbol"):
        reconcile([{"qty": 100}], [], {"A": book()})


def test_a_book_position_with_an_empty_symbol_is_refused():
    with pytest.raises(ValueError, match="There is no symbol"):
        reconcile([], [], {"A": book({"   ": 100})})


def test_a_quantity_that_is_not_a_number_is_refused_with_a_readable_sentence():
    with pytest.raises(ValueError, match="not a number of shares"):
        reconcile([held("AAPL", "a hundred")], [], {"A": book()})

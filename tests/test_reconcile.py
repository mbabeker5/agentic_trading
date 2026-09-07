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

import ast
from pathlib import Path

import pytest

from agent.reconcile import (
    KIND_MISSING_WORKING_ORDER,
    KIND_ORDER_NOT_IN_BOOK,
    KIND_ORPHAN_POSITION,
    KIND_POSITION_QTY,
    KIND_SYMBOL_SHARED,
    KIND_UNKNOWN_ORDER_REF,
    ORDER_REF_PREFIX,
    Mismatch,
    Orphan,
    ReconcileReport,
    Shared,
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
            "A": book({"AAPL": 150}),
            "B": book({}, {7: {"symbol": "NVDA", "side": "BUY", "qty": 10}}),
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
    # One problem, not two. Two books sharing AAPL is allowed since 2026-09-06,
    # so the only thing wrong here is that their total is not what the broker
    # has, and that is written up once naming both of them.
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
#
# An orphan nobody wrote down in advance stops EVERY book. Hub ruling,
# 2026-09-07, recorded in journal/2026-09-07.md and docs/BACKLOG.md item 0b.
# Nobody can be blamed for an orphan, so nobody can be singled out either, and
# the alternative is five books sizing their next order against a picture of the
# account that is missing a holding. The one way out is the forgiveness file.
# ---------------------------------------------------------------------------


def test_a_position_at_the_broker_that_no_book_claims_is_an_orphan():
    report = reconcile(
        broker_positions=[held("AAPL", 100), held("GME", 20, avg_cost=31.5)],
        broker_open_orders=[],
        books_state={"A": book({"AAPL": 100})},
    )
    assert report.ok is False
    assert report.books_to_halt == ("A",), "an orphan stops every book there is"
    assert report.mismatches == (), "and it does it without blaming any of them"

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
    assert "Every book stops trading" in orphan.line
    assert '{"GME": 20}' in orphan.line, "the line says how to forgive it"


def test_an_orphan_nobody_expected_halts_every_one_of_the_five_books():
    """The ruling, on the five books that actually run.

    Book A is the only one holding anything and every one of its own numbers is
    right. It stops anyway, and so do B, C, D and E, because a holding nobody
    can account for means nobody knows what else is missing.
    """
    report = reconcile(
        broker_positions=[held("AAPL", 100), held("GHOST", 40, avg_cost=12.0)],
        broker_open_orders=[],
        books_state={
            "A": book({"AAPL": 100}),
            "B": book(),
            "C": book(),
            "D": book(),
            "E": book(),
        },
    )
    assert report.ok is False
    assert report.books_to_halt == ("A", "B", "C", "D", "E")
    assert report.mismatches == ()
    assert report.mismatches_for("A") == (), (
        "a book halted for an orphan has no mismatch against its name, because "
        "there is nothing wrong with its own numbers")
    assert report.summary == "1 problem across books A, B, C, D, E"


def test_an_orphan_the_forgiveness_file_names_exactly_halts_nobody():
    """{"SPY": 1} and the broker holds 1 share of SPY. Everybody carries on."""
    report = reconcile(
        broker_positions=[held("AAPL", 100), held("SPY", 1, avg_cost=612.4)],
        broker_open_orders=[],
        books_state={
            "A": book({"AAPL": 100}),
            "B": book(),
            "C": book(),
            "D": book(),
            "E": book(),
        },
        expected_orphans=LEFTOVER_SPY,
    )
    assert report.ok is True
    assert report.books_to_halt == ()
    assert report.unexpected_orphans == ()
    assert report.orphans[0].line in report.lines, "and it still gets its line"


def test_a_forgiven_symbol_at_the_wrong_quantity_halts_every_book():
    """We forgive exactly 1 share of SPY. A second one appearing stops everybody.

    This is the whole point of the dict shape over the list shape: the thing
    worth halting on is not the share that has sat there for a week, it is the
    one that turned up this morning.
    """
    report = reconcile(
        broker_positions=[held("SPY", 2, avg_cost=612.4)],
        broker_open_orders=[],
        books_state={"A": book(), "B": book(), "C": book(), "D": book(),
                     "E": book()},
        expected_orphans=LEFTOVER_SPY,
    )
    assert report.ok is False
    assert report.orphans[0].expected is False
    assert report.books_to_halt == ("A", "B", "C", "D", "E")


def test_with_no_forgiveness_file_at_all_nothing_is_forgiven():
    """A missing output/expected_orphans.json reaches reconcile() as None.

    None forgives nothing, so the leftover share of SPY halts all five books.
    That is the safe way round and it is why that file stopped being a
    convenience on 2026-09-07: it has to be right before the first tick.
    """
    report = reconcile(
        broker_positions=[held("SPY", 1, avg_cost=612.4)],
        broker_open_orders=[],
        books_state={"A": book(), "B": book(), "C": book(), "D": book(),
                     "E": book()},
        expected_orphans=None,
    )
    assert report.ok is False
    assert report.orphans[0].expected is False
    assert report.books_to_halt == ("A", "B", "C", "D", "E")


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
    assert report.books_to_halt == ("A",), "so every book there is stops"
    assert "5 shares" in report.orphans[0].line
    assert "1 share" in report.orphans[0].line, "the line says what we expected"
    assert "Every book stops trading" in report.orphans[0].line


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
    assert report.books_to_halt == ("A",)
    assert report.summary == "1 problem across book A"


def test_an_orphan_with_no_books_at_all_has_nobody_to_stop():
    """The degenerate case, and it must not blow up.

    Nothing calls reconcile() with no books in real life, but if something ever
    does then an orphan has nobody to halt and the report says so plainly rather
    than pretending five books stopped.
    """
    report = reconcile([held("SPY", 1)], [], {})
    assert report.ok is False
    assert report.books_to_halt == ()
    assert report.summary == "1 problem, with no book to blame"


def test_an_orphan_and_a_real_mismatch_are_both_reported_and_neither_hides_the_other():
    """Book A is 20 shares out on AAPL, and 100 GHOST belong to nobody at all.

    Two different problems, and both have to survive into the report. Book A is
    blamed for the AAPL, and book B is not. Both of them stop all the same,
    because the GHOST stops everybody, and that must not swallow the sentence
    saying what is wrong with book A's AAPL.
    """
    report = reconcile(
        broker_positions=[held("AAPL", 120), held("GHOST", 100, avg_cost=120.0)],
        broker_open_orders=[],
        books_state={"A": book({"AAPL": 100}), "B": book()},
    )
    assert report.ok is False
    assert report.books_to_halt == ("A", "B"), "the GHOST stops both of them"

    # The per book mismatch is there, and blames only book A. Book B stops for
    # the orphan and is blamed for nothing, which is the difference between
    # books_to_halt and who has a mismatch against their name.
    assert [m.kind for m in report.mismatches] == [KIND_POSITION_QTY]
    assert (report.mismatches[0].book_id, report.mismatches[0].symbol) == ("A", "AAPL")
    assert report.mismatches_for("B") == ()

    # And so is the orphan. Two sentences in the log, one for each problem.
    assert [o.symbol for o in report.unexpected_orphans] == ["GHOST"]
    assert len(report.lines) == 2
    assert report.mismatches[0].line in report.lines
    assert report.orphans[0].line in report.lines
    assert report.summary == "2 problems across books A, B"


def test_reconcile_imports_nothing_that_could_talk_to_the_outside_world():
    """Pure arithmetic, and that has to stay true.

    agent/reconcile.py can be tested in under a second with no account open, no
    Slack token and no network, and that is only true while it imports nothing
    that could reach any of them. Telling somebody about an orphan is the
    caller's job: report_orphans in agent/loop.py reads report.orphans and puts
    the alert through agent/alerts.py. Importing agent/alerts.py in here to send
    it directly would throw the whole property away.
    """
    import agent.reconcile as reconcile_module

    source = Path(reconcile_module.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported == {"__future__", "dataclasses", "decimal", "math"}, imported


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
    """Four problems at once, including an unexpected orphan, so all five stop.

    The orphan is the GME, which nothing forgives. It halts every book, so the
    interesting part of this test is no longer who stops but who is BLAMED:
    books A, C and D have a mismatch against their name, books B and E do not.
    """
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
    assert report.books_to_halt == ("A", "B", "C", "D", "E"), (
        "the unclaimed GME stops all of them")
    assert report.books_to_halt == tuple(sorted(set(report.books_to_halt)))
    blamed = sorted({m.book_id for m in report.mismatches if m.book_id})
    assert blamed == ["A", "C", "D"]
    assert report.mismatches_for("B") == (), "book B agrees with the broker"
    assert report.mismatches_for("E") == (), "book E is holding nothing at all"

    kinds = {m.kind for m in report.mismatches}
    assert kinds == {
        KIND_POSITION_QTY,
        KIND_UNKNOWN_ORDER_REF,
        KIND_ORDER_NOT_IN_BOOK,
        KIND_MISSING_WORKING_ORDER,
    }
    # A and C share AAPL, which is reported rather than counted as a problem.
    assert [s.symbol for s in report.shared] == ["AAPL"]
    assert KIND_SYMBOL_SHARED not in kinds

    expected_spy = [o for o in report.orphans if o.symbol == "SPY"]
    unclaimed_gme = [o for o in report.orphans if o.symbol == "GME"]
    assert expected_spy[0].expected is True
    assert unclaimed_gme[0].expected is False
    assert report.unexpected_orphans == (unclaimed_gme[0],)

    assert report.summary == "5 problems across books A, B, C, D, E"


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
    assert aapl_books == ["A", "C"], "one quantity mismatch each, in book order"

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


# ---------------------------------------------------------------------------
# Two books in one ticker: allowed, reported, and checked as one ticker
#
# This was rule five, added on 2026-09-06 at the review team's request and
# retired by the hub the same day. It said no two books may claim the same
# symbol, whatever the quantities came to, and both of them stopped.
#
# What changed. IBKR does net positions by symbol inside the one shared paper
# account, so a shared name is a single line at the broker. But telling the two
# books apart never rested on that line: every order carries an orderRef tag
# naming the book that sent it, and every book keeps its own position record.
# Forbidding it would also delete the measurement month one exists to take, since
# two independent strategies picking the same name on the same morning is
# agreement between them.
#
# So the check is now per TICKER. For each symbol, the broker's net position has
# to equal the sum of what every book believes it holds in that symbol. When they
# disagree, the books that halt are exactly the ones holding that symbol. A
# shared ticker that adds up is written down with kind symbol_shared, on
# report.shared, and halts nobody.
#
# Mo can overturn this. It would mean turning those Shared records back into
# Mismatch records.
# ---------------------------------------------------------------------------


def test_two_books_in_one_name_whose_total_matches_reconciles_clean():
    """100 and 50 is the 150 the broker reports, so nothing is wrong.

    Before the afternoon of 2026-09-06 this halted both books. Now it is the
    ordinary case, and the only thing that happens is that the report says out
    loud that two books are in the name and the numbers add up.
    """
    report = reconcile(
        broker_positions=[held("NVDA", 150)],
        broker_open_orders=[],
        books_state={"A": book({"NVDA": 100}), "B": book({"NVDA": 50})},
    )
    assert report.ok is True, report.lines
    assert report.books_to_halt == ()
    assert report.mismatches == ()
    assert report.summary == "everything matched"

    assert len(report.shared) == 1
    record = report.shared[0]
    assert isinstance(record, Shared)
    assert record.symbol == "NVDA"
    assert record.holders == (("A", 100), ("B", 50))
    assert record.book_ids == ("A", "B")
    assert (record.total, record.broker_qty, record.matches) == (150, 150, True)
    assert record.kind == KIND_SYMBOL_SHARED


def test_the_line_for_a_shared_name_that_adds_up_says_so_in_plain_words():
    """The daily report should not be silent about two books in one ticker."""
    report = reconcile(
        broker_positions=[held("NVDA", 150)],
        broker_open_orders=[],
        books_state={"A": book({"NVDA": 100}), "B": book({"NVDA": 50})},
    )
    assert len(report.lines) == 1
    line = report.lines[0]
    assert line == report.shared[0].line
    assert "NVDA" in line
    assert "100" in line and "50" in line and "150" in line
    assert "is allowed" in line
    assert "no book stops trading" in line
    assert line.endswith(".") and len(line.split()) >= 6


def test_two_books_in_one_name_whose_total_is_wrong_halts_exactly_those_two():
    """100 and 50 is 150, and the broker has 120, so both holders stop."""
    report = reconcile(
        broker_positions=[held("NVDA", 120)],
        broker_open_orders=[],
        books_state={"A": book({"NVDA": 100}), "B": book({"NVDA": 50})},
    )
    assert report.ok is False
    assert report.books_to_halt == ("A", "B")
    assert {m.kind for m in report.mismatches} == {KIND_POSITION_QTY}
    assert len(report.mismatches_for("A")) == 1
    assert len(report.mismatches_for("B")) == 1

    # One sentence, not two. The quantity line already names both books, the
    # total and who stops, so the shared record does not repeat it in the log.
    assert len(report.lines) == 1
    line = report.lines[0]
    assert "150" in line and "120" in line
    assert "Book A and book B stop trading until someone looks." in line

    record = report.shared[0]
    assert (record.total, record.broker_qty, record.matches) == (150, 120, False)
    assert record.line not in report.lines


def test_a_third_book_in_a_different_name_is_untouched_by_that_mismatch():
    """Books A and B disagree about NVDA. Book C holds KO and carries on.

    This is the point of checking one ticker at a time. The old rule halted
    whoever was named in the problem, which was right, but the problem itself
    used to include "two books are in one name at all", which dragged in books
    that had nothing wrong with their numbers.
    """
    report = reconcile(
        broker_positions=[held("NVDA", 120), held("KO", 40)],
        broker_open_orders=[],
        books_state={
            "A": book({"NVDA": 100}),
            "B": book({"NVDA": 50}),
            "C": book({"KO": 40}),
            "D": book(),
        },
    )
    assert report.ok is False
    assert report.books_to_halt == ("A", "B")
    assert "C" not in report.books_to_halt, "book C agrees with the broker about KO"
    assert "D" not in report.books_to_halt, "book D is holding nothing at all"
    assert report.mismatches_for("C") == ()
    assert report.mismatches_for("D") == ()
    assert {m.symbol for m in report.mismatches} == {"NVDA"}


def test_a_symbol_only_one_book_holds_behaves_exactly_as_it_always_did():
    """Nothing about the single book case changed, in either direction."""
    clean = reconcile(
        broker_positions=[held("AAPL", 150), held("MSFT", 40)],
        broker_open_orders=[],
        books_state={
            "A": book({"AAPL": 150}),
            "B": book({"MSFT": 40}),
            "C": book(),
        },
    )
    assert clean.ok is True
    assert clean.books_to_halt == ()
    assert clean.shared == (), "nothing here is shared, so nothing is reported"
    assert clean.lines == ()

    wrong = reconcile(
        broker_positions=[held("AAPL", 120)],
        broker_open_orders=[],
        books_state={"A": book({"AAPL": 100}), "B": book()},
    )
    assert wrong.ok is False
    assert wrong.books_to_halt == ("A",)
    assert {m.kind for m in wrong.mismatches} == {KIND_POSITION_QTY}
    assert wrong.shared == ()
    assert wrong.lines[0].endswith("Book A stops trading until someone looks.")


def test_three_books_in_one_name_are_all_reported_and_all_add_up():
    report = reconcile(
        broker_positions=[held("NVDA", 60)],
        broker_open_orders=[],
        books_state={
            "A": book({"NVDA": 10}),
            "C": book({"NVDA": 20}),
            "E": book({"NVDA": 30}),
        },
    )
    assert report.ok is True, report.lines
    assert report.books_to_halt == ()
    assert report.shared[0].book_ids == ("A", "C", "E")
    assert "3 books holding NVDA at once is allowed" in report.lines[0]


def test_three_books_in_one_name_whose_total_is_wrong_stop_all_three():
    report = reconcile(
        broker_positions=[held("NVDA", 55)],
        broker_open_orders=[],
        books_state={
            "A": book({"NVDA": 10}),
            "C": book({"NVDA": 20}),
            "E": book({"NVDA": 30}),
        },
    )
    assert report.ok is False
    assert report.books_to_halt == ("A", "C", "E")
    assert len(report.lines) == 1
    assert "Book A, book C and book E stop trading until someone looks." in (
        report.lines[0]
    )


def test_a_book_holding_none_of_a_shared_name_is_not_one_of_the_holders():
    """A zero is not a claim, so book B is not dragged into book A's name."""
    report = reconcile(
        broker_positions=[held("AAPL", 100)],
        broker_open_orders=[],
        books_state={"A": book({"AAPL": 100}), "B": book({"AAPL": 0})},
    )
    assert report.ok is True
    assert report.books_to_halt == ()
    assert report.shared == (), "one real holder is not a shared ticker"


def test_a_shared_short_is_added_up_the_same_way_as_a_shared_long():
    """Minus 50 and minus 30 is the 80 short the broker reports."""
    report = reconcile(
        broker_positions=[held("GME", -80)],
        broker_open_orders=[],
        books_state={"A": book({"GME": -50}), "B": book({"GME": -30})},
    )
    assert report.ok is True, report.lines
    assert report.books_to_halt == ()
    assert report.shared[0].total == -80
    assert "is short" in report.lines[0]
    assert "80 short" in report.lines[0]


def test_one_book_long_and_another_short_the_same_name_nets_out():
    """A is long 200 and B is short 50, so the broker's netted line is 150.

    This is the shape the whole decision turns on: the broker cannot say whose
    shares are whose, and it does not have to, because the sum is what gets
    checked and the orderRef tag on each order is what says who owns what.
    """
    report = reconcile(
        broker_positions=[held("PAIR", 150)],
        broker_open_orders=[],
        books_state={"A": book({"PAIR": 200}), "B": book({"PAIR": -50})},
    )
    assert report.ok is True, report.lines
    assert report.books_to_halt == ()
    assert report.shared[0].holders == (("A", 200), ("B", -50))
    assert report.shared[0].matches is True


def test_a_shared_name_and_an_unshared_one_are_judged_separately():
    """AAPL is shared and adds up. MSFT belongs to one book and does not."""
    report = reconcile(
        broker_positions=[held("AAPL", 150), held("MSFT", 40)],
        broker_open_orders=[],
        books_state={
            "A": book({"AAPL": 100, "MSFT": 25}),
            "B": book({"AAPL": 50}),
        },
    )
    assert report.ok is False
    assert report.books_to_halt == ("A",), "book B is only in AAPL, which is fine"
    assert {m.symbol for m in report.mismatches} == {"MSFT"}
    assert [s.symbol for s in report.shared] == ["AAPL"]
    assert report.shared[0].matches is True


def test_the_shared_lines_are_real_sentences_and_the_report_repeats_itself():
    inputs = dict(
        broker_positions=[held("AAPL", 150), held("KO", 10)],
        broker_open_orders=[],
        books_state={
            "A": book({"AAPL": 100}),
            "B": book({"AAPL": 50}),
            "C": book({"KO": 5}),
        },
    )
    report = reconcile(**inputs)
    for line in report.lines:
        assert line.endswith(".") and len(line.split()) >= 6, line
    for record in report.shared:
        assert record.line.endswith(".") and len(record.line.split()) >= 6
    assert reconcile(**inputs) == report, "the same input twice gives the same report"


def test_shared_tickers_come_back_in_alphabetical_order():
    report = reconcile(
        broker_positions=[held("ZM", 30), held("AAPL", 30)],
        broker_open_orders=[],
        books_state={
            "A": book({"ZM": 10, "AAPL": 10}),
            "B": book({"ZM": 20, "AAPL": 20}),
        },
    )
    assert [record.symbol for record in report.shared] == ["AAPL", "ZM"]

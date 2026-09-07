"""The loop tells Mo when something is wrong, and says it once rather than eighty times.

Until 2026-09-06 agent/loop.py did not import agent/alerts.py at all and had no
alert call on any path. A book could halt at 09:50 and the only trace was a line
in a log file and a row in a spreadsheet, so nobody found out until somebody went
looking. The replay gate found it by asking, in three separate scenarios, whether
anybody had been told, and the answer every time was no.

The other half of this file is the rate limit, and it is the half that decides
whether the alerting is useful. There is no long running process here: launchd
wakes the loop, it does one tick, it exits. So a rate limit that lives in memory
is not a rate limit at all, and one that does not exist means the same sentence
arrives every five minutes until the close.

Nothing here touches Slack, iMessage, the screen, a broker or a network.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest tests/test_loop_alerts.py -q
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from agent import book_state as bs               # noqa: E402
from agent import guardrails as gr               # noqa: E402
from agent import loop                           # noqa: E402

BOOKS_YAML = REPO / "config" / "books.yaml"
NEW_YORK = ZoneInfo("America/New_York")
TUESDAY = date(2026, 9, 8)


def at(hour: int, minute: int) -> datetime:
    return datetime(2026, 9, 8, hour, minute, tzinfo=NEW_YORK)


@pytest.fixture
def sent(monkeypatch, tmp_path):
    """Every alert this run would have sent, caught instead of delivered."""
    caught: list[tuple[str, str, str]] = []

    class Caught:
        @staticmethod
        def alert(level, title, body):
            caught.append((level, title, body))
            return ["captured"]

    monkeypatch.setenv(loop.ROOT_ENV_VAR, str(tmp_path))
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(loop, "alerts_mod", Caught)
    monkeypatch.setattr(loop, "db_mod", None)
    monkeypatch.setattr(loop, "DB_ERROR", "not wanted in this test")
    loop._DB_TROUBLE.clear()
    return caught


def tick_for(book_id: str = "A", now: datetime | None = None) -> loop.BookTick:
    book = gr.load_book(BOOKS_YAML, book_id)
    return loop.BookTick(book, now or at(9, 40), "testhash", write_ledger=False,
                         quiet=True)


def titles(caught) -> list[str]:
    return [title for _level, title, _body in caught]


# ---------------------------------------------------------------------------
# Saying it once
# ---------------------------------------------------------------------------


def test_the_same_alert_stays_quiet_for_half_an_hour(sent):
    assert loop.raise_alert("error", "Book A is halted", "because", "halt", at(9, 50))
    assert loop.raise_alert("error", "Book A is halted", "because", "halt",
                            at(9, 55)) is None
    assert loop.raise_alert("error", "Book A is halted", "because", "halt",
                            at(10, 19)) is None
    assert loop.raise_alert("error", "Book A is halted", "because", "halt",
                            at(10, 20)) == ["captured"]
    assert len(sent) == 2, "thirty minutes apart, so twice and not eighty times"


def test_two_different_things_do_not_silence_each_other(sent):
    loop.raise_alert("error", "Book A is halted", "x", "A:halt", at(9, 50))
    loop.raise_alert("error", "Book C is halted", "x", "C:halt", at(9, 50))
    loop.raise_alert("warn", "Gateway outage", "x", "broker_unavailable", at(9, 50))
    assert len(sent) == 3


def test_the_quiet_period_survives_the_process_ending(sent, tmp_path):
    """launchd wakes a new process every tick, so this has to live on disk."""
    loop.raise_alert("error", "Book A is halted", "because", "halt", at(9, 50))
    assert (tmp_path / "output" / loop.ALERT_STATE_FILE).exists()

    loop._DB_TROUBLE.clear()          # a brand new process would know nothing
    assert loop.raise_alert("error", "Book A is halted", "because", "halt",
                            at(9, 55)) is None
    assert len(sent) == 1


def test_an_alert_meant_once_a_day_is_quiet_all_day(sent):
    loop.raise_alert("warn", "Nobody claims SPY", "x", "orphan:SPY", at(9, 50),
                     quiet_minutes=loop.ALERT_ONCE_A_DAY_MINUTES)
    for hour in (10, 12, 15):
        assert loop.raise_alert("warn", "Nobody claims SPY", "x", "orphan:SPY",
                                at(hour, 50),
                                quiet_minutes=loop.ALERT_ONCE_A_DAY_MINUTES) is None
    assert len(sent) == 1


def test_an_unreadable_state_file_lets_the_alert_through(sent, tmp_path):
    """Failing quiet is the wrong way to fail for a thing that exists to shout."""
    loop.alert_state_path().write_text("this is not json")
    assert loop.raise_alert("error", "Book A is halted", "x", "halt", at(9, 50))


def test_an_alert_channel_that_explodes_does_not_stop_the_tick(monkeypatch,
                                                               tmp_path, capsys):
    class Broken:
        @staticmethod
        def alert(level, title, body):
            raise RuntimeError("Slack is down and so is everything else")

    monkeypatch.setenv(loop.ROOT_ENV_VAR, str(tmp_path))
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(loop, "alerts_mod", Broken)
    assert loop.raise_alert("error", "Book A is halted", "x", "halt", at(9, 50)) == []
    assert "would not go out" in capsys.readouterr().err


def test_a_missing_alerts_module_is_said_on_stderr(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(loop.ROOT_ENV_VAR, str(tmp_path))
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(loop, "alerts_mod", None)
    monkeypatch.setattr(loop, "ALERTS_ERROR", "ImportError: no alerts")
    assert loop.raise_alert("error", "Book A is halted", "x", "halt", at(9, 50)) == []
    assert "nobody was told" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# The seven things worth telling Mo about
# ---------------------------------------------------------------------------


def test_a_halted_book_is_alerted_with_the_reason_on_it(sent, tmp_path):
    book = gr.load_book(BOOKS_YAML, "A")
    guard = gr.load_book_guardrails(BOOKS_YAML, "A")
    guards = loop.read_guards(tmp_path)

    class Quiet:
        def account_summary(self, account=None):
            return {"items": []}

        def portfolio(self, account=None, include_pnl=True):
            return {"positions": []}

        def open_orders(self, account=None, include_all=True):
            return {"orders": []}

        def executions(self, account=None, **kwargs):
            return {"executions": []}

        def snapshot(self, contracts, market_data_type=3):
            return {"snapshots": []}

        def historical_bars(self, contract, duration, bar_size, **kwargs):
            return {"bars": []}

    loop.run_book(book, guard, at(9, 40), guards, Quiet(), "DUT077572", {},
                  "testhash", write_ledger=False, quiet=True,
                  halt_reason="the books and the broker disagree about AAPL")

    assert titles(sent) == ["Book A is halted"]
    body = sent[0][2]
    assert "disagree about AAPL" in body
    assert "may still close" in body, "a halted book still gets out of things"


def test_a_loss_cap_refusal_is_alerted_once_per_rule(sent):
    tick = tick_for("A")
    intent = gr.OrderIntent(symbol="AAPL", side="BUY", qty=10, limit_price=50.0,
                            purpose="entry", book_id="A")
    decision = gr.Decision(allowed=False)
    decision.add("daily_loss_cap", "The account is down 2,100 dollars today.")
    decision.add("weekly_loss_cap", "The book is down 4,200 dollars this week.")

    loop.alert_on_caps(tick, intent, decision)
    assert titles(sent) == ["Book A is down to its daily loss cap",
                            "Book A is down to its weekly loss cap"]

    loop.alert_on_caps(tick, intent, decision)
    assert len(sent) == 2, "the same cap five minutes later says nothing"


def test_an_ordinary_refusal_is_not_worth_waking_anybody_for(sent):
    tick = tick_for("A")
    intent = gr.OrderIntent(symbol="AAPL", side="BUY", qty=10, limit_price=50.0,
                            purpose="entry", book_id="A")
    decision = gr.Decision(allowed=False)
    decision.add("max_open_positions", "This book already holds ten names.")
    decision.add("sector_cap", "Too much of this book is in technology already.")

    loop.alert_on_caps(tick, intent, decision)
    assert sent == [], "a cap doing its job on one order is not an incident"


def test_the_books_and_the_broker_disagreeing_is_alerted(sent):
    outcome = loop.ReconcileOutcome(
        available=True, ok=False, books_to_halt=["A", "C"],
        lines=("Book A believes it holds 100 AAPL and the broker reports 50.",),
        note="1 problem across books A, C")
    loop.alert_on_reconciliation(outcome, at(9, 50), "testhash")

    assert len(sent) == 1
    level, title, body = sent[0]
    assert level == "error"
    assert "1 problem across books A, C" in title
    assert "believes it holds 100 AAPL" in body
    assert "Halted: A, C" in body


def test_reconciliation_being_unavailable_is_its_own_message(sent):
    outcome = loop.ReconcileOutcome(
        available=False, ok=False, books_to_halt=["A", "B", "C", "D", "E"],
        note="reconciliation unavailable, halting all books: it would not import")
    loop.alert_on_reconciliation(outcome, at(9, 50), "testhash")

    assert titles(sent) == ["Reconciliation could not run at all"]
    assert "a missing referee means no" in sent[0][2]


def test_a_clean_reconciliation_says_nothing(sent):
    loop.alert_on_reconciliation(
        loop.ReconcileOutcome(available=True, ok=True, note="everything matched"),
        at(9, 50), "testhash")
    assert sent == []


def test_an_untagged_order_on_its_own_does_not_make_reconciliation_shout(sent):
    """This account has carried the untagged working order id 4 since 2026-09-02.

    So the reconciliation's own verdict is "not ok" on every tick of every day
    and will stay that way. Shouting about it would be nine identical messages a
    day saying nothing has changed. An order that is only working has changed
    nothing about what any book holds, so it halts nobody and report_orphans()
    says it once a day instead.
    """
    outcome = loop.ReconcileOutcome(
        available=True, ok=False, books_to_halt=[],
        lines=("Order 4 at the broker carries no book tag.",),
        unclaimed=[_Unclaimed("4")], note="1 problem, with no book to blame")
    assert outcome.books_agree is True

    loop.alert_on_reconciliation(outcome, at(9, 50), "testhash")
    assert sent == []


def test_the_reconciliation_alert_leaves_an_orphan_to_report_orphans(sent):
    """One finding, one message.

    An orphan halts every book now, so it does reach alert_on_reconciliation
    through books_to_halt. It must not be alerted here as well: the message that
    matters names the symbol, the quantity and how to forgive it, and that one
    comes out of report_orphans().
    """
    outcome = loop.ReconcileOutcome(
        available=True, ok=False, books_to_halt=["A", "B", "C", "D", "E"],
        lines=("40 shares of GHOST at the broker belong to no book.",),
        orphans=[_Orphan("GHOST")], mismatched_books=[],
        note="1 problem across books A, B, C, D, E")
    assert outcome.books_agree is False, "every book is halted for it"

    loop.alert_on_reconciliation(outcome, at(9, 50), "testhash")
    assert sent == []


def test_a_book_mismatch_alongside_an_orphan_is_still_its_own_message(sent):
    """Two findings, two messages, and the mismatch is not swallowed.

    Book A is out of step about AAPL and there is also a GHOST nobody claims.
    All five books stop, but book A's own numbers being wrong is a separate
    thing from the orphan and Mo has to hear about both.
    """
    outcome = loop.ReconcileOutcome(
        available=True, ok=False, books_to_halt=["A", "B", "C", "D", "E"],
        lines=("Book A believes it holds 100 of AAPL, but the broker reports 120.",),
        orphans=[_Orphan("GHOST")], mismatched_books=["A"],
        note="2 problems across books A, B, C, D, E")

    loop.alert_on_reconciliation(outcome, at(9, 50), "testhash")
    assert len(sent) == 1
    assert sent[0][1].startswith("The books and the broker disagree")


def test_the_three_files_that_stop_the_loop_are_each_alerted(sent, tmp_path):
    output = tmp_path / "output"
    for name in ("LOOP_DISABLED", "STOP", "NO_TRADE_TODAY"):
        (output / name).write_text("pulled by hand\n")

    loop.alert_on_guard_files(loop.read_guards(tmp_path), at(9, 50))
    assert titles(sent) == ["The trading loop is switched off",
                            "The stop file is in place",
                            "No book is opening anything today"]
    assert "reenable.sh" in sent[0][2]


def test_nothing_is_said_when_none_of_the_three_files_is_there(sent, tmp_path):
    loop.alert_on_guard_files(loop.read_guards(tmp_path), at(9, 50))
    assert sent == []


# ---------------------------------------------------------------------------
# A position nobody claims: every book halted, and told about once a day
#
# Hub ruling, 2026-09-07, recorded in journal/2026-09-07.md and
# docs/BACKLOG.md item 0b. reconcile() is what halts the books; these tests are
# about the message the loop sends, which has to be ONE per finding rather than
# one per book, has to name the symbol and the quantity, and has to say how to
# forgive it.
# ---------------------------------------------------------------------------


class _Orphan:
    def __init__(self, symbol, expected=False, qty=40):
        self.symbol = symbol
        self.expected = expected
        self.qty = qty
        self.line = f"{symbol} at the broker belongs to no book."


class _Unclaimed:
    def __init__(self, order_id):
        self.book_id = None
        self.order_id = order_id
        self.line = f"Order {order_id} at the broker carries no book tag."


def test_an_orphan_is_told_about_once_a_day_however_many_books_it_halted(
        sent, monkeypatch):
    """Five books halted, one message. Nine ticks later, still one message."""
    monkeypatch.setattr(loop.ledger_writer, "log_rule", lambda *a, **k: True)
    outcome = loop.ReconcileOutcome(
        available=True, ok=False, books_to_halt=["A", "B", "C", "D", "E"],
        orphans=[_Orphan("GHOST")], note="1 problem across books A, B, C, D, E")

    assert loop.report_orphans(outcome, at(11, 40), "testhash", False) == 1
    assert titles(sent) == [
        "GHOST at the broker belongs to no book, so every book is halted"]
    assert len(sent) == 1, "one alert for the finding, not one per halted book"
    assert outcome.books_agree is False, "and every book really is halted"

    for hour in (12, 14, 15):
        loop.report_orphans(outcome, at(hour, 40), "testhash", False)
    assert len(sent) == 1, "it is the same fact at 11:40 and at 15:40"


def test_two_orphans_are_two_findings_and_two_messages(sent, monkeypatch):
    """The rate limit is per name, so a second unclaimed symbol is its own alert."""
    monkeypatch.setattr(loop.ledger_writer, "log_rule", lambda *a, **k: True)
    outcome = loop.ReconcileOutcome(
        available=True, ok=False, books_to_halt=["A", "B", "C", "D", "E"],
        orphans=[_Orphan("GHOST"), _Orphan("PHANTOM")],
        note="2 problems across books A, B, C, D, E")

    assert loop.report_orphans(outcome, at(11, 40), "testhash", False) == 2
    assert len(sent) == 2
    assert any("GHOST" in title for title in titles(sent))
    assert any("PHANTOM" in title for title in titles(sent))


def test_an_orphan_somebody_has_already_looked_at_is_not_alerted(sent, monkeypatch):
    monkeypatch.setattr(loop.ledger_writer, "log_rule", lambda *a, **k: True)
    outcome = loop.ReconcileOutcome(
        available=True, ok=False, books_to_halt=[],
        orphans=[_Orphan("SPY", expected=True, qty=1)],
        note="1 problem, with no book to blame")

    assert loop.report_orphans(outcome, at(9, 40), "testhash", False) == 1
    assert sent == [], (
        "output/expected_orphans.json is somebody saying they have looked at it")
    assert outcome.books_agree is True, "and it halts nobody either"


def test_the_alert_says_the_quantity_and_how_to_forgive_it(sent, monkeypatch):
    monkeypatch.setattr(loop.ledger_writer, "log_rule", lambda *a, **k: True)
    loop.report_orphans(
        loop.ReconcileOutcome(available=True, ok=False,
                              books_to_halt=["A", "B", "C", "D", "E"],
                              orphans=[_Orphan("SPY", qty=2)]),
        at(9, 40), "testhash", False)
    body = sent[0][2]
    assert sent[0][0] == "error", "every book stopping is not a warning"
    assert "The broker holds 2 of SPY" in body, "the quantity is in the message"
    assert "expected_orphans.json" in body
    assert '{"SPY": 2}' in body, "the exact line to write, ready to copy"
    assert '["SPY"]' in body
    assert "Every book is halted" in body
    assert "2026-09-07" in body, "the ruling is cited rather than argued"
    assert "item 0b" in body
    assert "Rules testhash" in body, "the rules hash goes on every alert"


def test_a_missing_forgiveness_file_forgives_nothing(tmp_path):
    """No output/expected_orphans.json means None, and None forgives nothing.

    This is the pairing that makes the ruling safe: the file is read fresh every
    tick, a missing one hands reconcile() None, and None halts rather than
    trades on a picture nobody checked.
    """
    assert loop.expected_orphans(tmp_path) is None

    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    (tmp_path / "output" / "expected_orphans.json").write_text('{"SPY": 1}\n')
    assert loop.expected_orphans(tmp_path) == {"SPY": 1}


def test_an_unreadable_forgiveness_file_forgives_nothing_either(tmp_path):
    """Half written JSON forgives nothing rather than everything."""
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    (tmp_path / "output" / "expected_orphans.json").write_text('{"SPY": ')
    assert loop.expected_orphans(tmp_path) is None


def test_an_order_nobody_tagged_still_halts_nobody(sent, monkeypatch):
    """An untagged ORDER is deliberately not treated like an orphan POSITION.

    An order that is only working has changed nothing about what any book holds,
    so nobody is sizing anything against a wrong picture because of it. The
    untagged order id 4 in this account is told about and halts nobody, exactly
    as it did before the 2026-09-07 ruling on positions.
    """
    monkeypatch.setattr(loop.ledger_writer, "log_rule", lambda *a, **k: True)
    outcome = loop.ReconcileOutcome(
        available=True, ok=False, books_to_halt=[], unclaimed=[_Unclaimed("4")],
        note="1 problem, with no book to blame")

    assert loop.report_orphans(outcome, at(9, 40), "testhash", False) == 1
    assert titles(sent) == ["Order 4 at the broker belongs to no book"]
    assert outcome.books_agree is True


def test_books_agree_says_no_to_a_mismatch_and_to_an_orphan_and_to_a_blind_tick():
    """books_agree is what the loop acts on, and these are the three ways it is no.

    Since the 2026-09-07 ruling an orphan is one of them. It is checked from the
    orphans list rather than only from books_to_halt, so the answer is the same
    however this record was built.
    """
    orphan_only = loop.ReconcileOutcome(available=True, ok=False, books_to_halt=[],
                                        orphans=[_Orphan("SPY")])
    forgiven = loop.ReconcileOutcome(available=True, ok=True, books_to_halt=[],
                                     orphans=[_Orphan("SPY", expected=True, qty=1)])
    real = loop.ReconcileOutcome(available=True, ok=False, books_to_halt=["A"])
    blind = loop.ReconcileOutcome(available=False, ok=False, books_to_halt=["A"])

    assert orphan_only.books_agree is False, "a holding nobody claims stops everybody"
    assert forgiven.books_agree is True, "somebody has looked at that one"
    assert real.books_agree is False
    assert blind.books_agree is False, "nobody could ask, so nobody may say yes"


def test_falling_back_to_the_rules_because_no_model_answered_is_alerted(sent):
    tick = tick_for("A")
    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000)

    class Result:
        ok = True
        model = "claude-fable-5.1"
        cost_usd = 0.0
        prompt_hash = "abc"
        rejections: list = []
        fallback = "model_unavailable"
        notes = ["model_unavailable: the provider took longer than 45 seconds"]
        error = ""

    loop.record_decision_problems(tick, state, Result())

    assert titles(sent) == ["Book A fell back to its own rules"]
    body = sent[0][2]
    assert "45 seconds" in body
    assert "must never be counted later as a model answer" in body


def test_a_model_that_answered_properly_says_nothing(sent):
    tick = tick_for("A")
    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000)

    class Result:
        ok = True
        model = "claude-fable-5.1"
        cost_usd = 0.001
        prompt_hash = "abc"
        rejections: list = []
        fallback = None
        notes: list = []
        error = ""

    loop.record_decision_problems(tick, state, Result())
    assert sent == []

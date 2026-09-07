"""What the quotes say about themselves, and what the loop does about it.

Two findings from the first replay gate run, and they are the same blind spot.

IBKR code 10197 means another session is logged in with the same credentials and
has taken the market data line. The loop caught it inside snapshot_by_symbol(),
turned it into a note, and handled it exactly like a quote that did not arrive.
Nothing read the code and nothing said what it meant, so half an hour of no
quotes at all passed without a word and the loop went on managing positions off
the last price it happened to have.

And nothing anywhere read marketDataType off a reply, so a fifteen minute old
price and a live one were the same thing to it. That matters more than it
sounds: this paper account is served delayed data every day, checked against the
live server on 2026-09-06, and errors 10168 and 10089 say live data was refused
outright. Worse, the loop was ASKING for delayed: mcp_client.snapshot defaults to
market data type 3, and being given what you asked for proves nothing.

Nothing here touches a broker or a network.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest tests/test_market_data.py -q
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


class Feeder:
    """A broker that serves a chosen market data type and records what was asked."""

    def __init__(self, served: int | None = 1, price: float = 100.0):
        self.served = served
        self.price = price
        self.asked_for: list[int] = []

    def snapshot(self, contracts, market_data_type=3):
        self.asked_for.append(market_data_type)
        row = {"symbol": "AAPL", "last": self.price, "close": self.price,
               "marketPrice": self.price}
        if self.served is not None:
            row["marketDataType"] = self.served
        return {"snapshots": [row],
                **({"market_data_type": self.served}
                   if self.served is not None else {})}


class Competing:
    """Another session has the data line. IBKR code 10197."""

    def snapshot(self, contracts, market_data_type=3):
        raise RuntimeError(
            "market data is not available because another session is using this "
            "account (IBKR code 10197)")


class CodedError(RuntimeError):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


class CompetingWithCode:
    """The replay broker puts the number on the exception rather than in the words."""

    def snapshot(self, contracts, market_data_type=3):
        raise CodedError("another session is using this account", 10197)


class OldFake:
    """A broker whose snapshot will not take a market data type at all."""

    def snapshot(self, contracts):
        return {"snapshots": [{"symbol": "AAPL", "last": 100.0,
                               "marketDataType": 1}]}


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    for name in ("config", "strategies"):
        (tmp_path / name).symlink_to(REPO / name)
    (tmp_path / "output").mkdir()
    monkeypatch.setenv(loop.ROOT_ENV_VAR, str(tmp_path))
    monkeypatch.setattr(loop, "db_mod", None)
    monkeypatch.setattr(loop, "DB_ERROR", "not wanted in this test")
    loop._DB_TROUBLE.clear()
    return tmp_path


@pytest.fixture
def sent(monkeypatch):
    caught: list[tuple[str, str, str]] = []

    class Caught:
        @staticmethod
        def alert(level, title, body):
            caught.append((level, title, body))
            return ["captured"]

    monkeypatch.setattr(loop, "alerts_mod", Caught)
    return caught


def tick_for(book_id: str = "A", now: datetime | None = None) -> loop.BookTick:
    book = gr.load_book(BOOKS_YAML, book_id)
    return loop.BookTick(book, now or at(10, 0), "testhash", write_ledger=False,
                         quiet=True)


def fresh_state() -> bs.BookState:
    return bs.BookState(book_id="A", order_ref="BOOK_A", date="2026-09-08",
                        capital=100000.0, cash=100000.0, day_start_equity=100000.0)


# ---------------------------------------------------------------------------
# Reading what came back
# ---------------------------------------------------------------------------


def test_the_loop_asks_for_live_quotes_rather_than_delayed_ones():
    """Asking for delayed and being given delayed proves nothing."""
    broker = Feeder(served=1)
    loop.read_quotes(broker, [{"symbol": "AAPL"}], [])
    assert broker.asked_for == [loop.MARKET_DATA_LIVE]
    assert loop.MARKET_DATA_LIVE == 1


def test_a_live_feed_is_good_enough_to_open_a_position_on():
    feed = loop.read_quotes(Feeder(served=1), [{"symbol": "AAPL"}], [])
    assert feed.market_data_type == 1
    assert feed.label == "live"
    assert feed.good_enough_to_enter is True
    assert feed.why_not == ""
    assert feed.quotes["AAPL"]["last"] == 100.0


def test_a_delayed_feed_is_not():
    feed = loop.read_quotes(Feeder(served=3), [{"symbol": "AAPL"}], [])
    assert feed.market_data_type == 3
    assert feed.label == "delayed"
    assert feed.good_enough_to_enter is False
    assert "fifteen minutes old" in feed.why_not
    assert feed.quotes["AAPL"]["last"] == 100.0, (
        "the price is still there, because an exit may still use it")


def test_a_frozen_feed_is_not_either():
    for served in (2, 4):
        feed = loop.read_quotes(Feeder(served=served), [{"symbol": "AAPL"}], [])
        assert feed.good_enough_to_enter is False, served


def test_a_quote_that_will_not_say_what_it_is_is_not_good_enough():
    """The same rule as the halted tick: unknown refuses rather than assuming."""
    feed = loop.read_quotes(Feeder(served=None), [{"symbol": "AAPL"}], [])
    assert feed.market_data_type is None
    assert feed.good_enough_to_enter is False
    assert "nobody can say whether the price is current" in feed.why_not


def test_the_competing_session_code_is_kept_from_the_words():
    notes: list[str] = []
    feed = loop.read_quotes(Competing(), [{"symbol": "AAPL"}], notes)
    assert feed.competing_session is True
    assert 10197 in feed.codes
    assert feed.good_enough_to_enter is False
    assert "10197" in feed.why_not
    assert "live quote screen or app open" in feed.why_not
    assert notes, "and it still gets written down as a note"


def test_the_competing_session_code_is_kept_from_the_exception_too():
    feed = loop.read_quotes(CompetingWithCode(), [{"symbol": "AAPL"}], [])
    assert feed.competing_session is True
    assert feed.codes == (10197,)


def test_an_ordinary_failure_is_not_a_competing_session():
    feed = loop.read_quotes(
        type("Broken", (), {"snapshot": lambda self, c, market_data_type=3:
                            (_ for _ in ()).throw(RuntimeError("it broke"))})(),
        [{"symbol": "AAPL"}], [])
    assert feed.competing_session is False
    assert feed.codes == ()
    assert feed.good_enough_to_enter is False


def test_a_broker_that_cannot_take_a_data_type_still_works():
    """Some older doubles have a two argument snapshot. The loop must survive one."""
    feed = loop.read_quotes(OldFake(), [{"symbol": "AAPL"}], [])
    assert feed.market_data_type == 1
    assert feed.good_enough_to_enter is True


def test_asking_about_nothing_asks_the_broker_nothing():
    broker = Feeder(served=1)
    feed = loop.read_quotes(broker, [], [])
    assert broker.asked_for == []
    assert feed.quotes == {}


def test_the_error_code_reader_finds_ibkr_five_digit_codes():
    assert 10197 in loop.error_codes_from(RuntimeError("IBKR code 10197 again"))
    assert 10168 in loop.error_codes_from(RuntimeError("error 10168: no live data"))
    assert loop.error_codes_from(RuntimeError("no numbers here")) == ()
    assert loop.error_codes_from(RuntimeError("order 4 was rejected")) == ()


# ---------------------------------------------------------------------------
# What the loop does about it
# ---------------------------------------------------------------------------


def test_a_delayed_feed_halts_the_book_and_tells_mo_once(sandbox, sent):
    tick = tick_for("A")
    state = fresh_state()
    feed = loop.read_quotes(Feeder(served=3), [{"symbol": "AAPL"}], [])

    loop.note_the_feed(tick, state, feed)

    assert tick.data_block
    assert state.halted is True
    assert state.halt_causes() == {bs.HALT_MARKET_DATA}
    assert [title for _l, title, _b in sent] == [
        "Quotes are delayed, so no book is opening anything"]
    assert "10168" in sent[0][2], "the account's own refusal is named in the message"


def test_a_competing_session_says_what_it_actually_means(sandbox, sent):
    tick = tick_for("A")
    state = fresh_state()
    feed = loop.read_quotes(Competing(), [{"symbol": "AAPL"}], [])

    loop.note_the_feed(tick, state, feed)

    assert state.halted is True
    level, title, body = sent[0]
    assert level == "error"
    assert title == "Another session has taken the market data line"
    assert "live quote screen or app open" in body, (
        "a number is not an explanation")
    assert "Close the TWS window" in body


def test_the_delayed_message_is_said_once_a_day_not_every_half_hour(sandbox, sent):
    """This account is delayed every day, so half hourly would be thirteen a day."""
    state = fresh_state()
    feed = loop.read_quotes(Feeder(served=3), [{"symbol": "AAPL"}], [])
    for hour in (10, 11, 13, 15):
        loop.note_the_feed(tick_for("A", at(hour, 0)), state, feed)
    assert len(sent) == 1


def test_the_halt_lifts_itself_when_a_live_quote_arrives(sandbox, sent):
    state = fresh_state()
    loop.note_the_feed(tick_for("A", at(10, 0)), state,
                       loop.read_quotes(Feeder(served=3), [{"symbol": "AAPL"}], []))
    assert state.halted is True

    tick = tick_for("A", at(10, 35))
    loop.note_the_feed(tick, state,
                       loop.read_quotes(Feeder(served=1), [{"symbol": "AAPL"}], []))
    assert state.halted is False, (
        "a quote screen closed at 10:35 costs the half hour it was open, not the day")
    assert tick.data_block == ""


def test_a_market_data_halt_leaves_another_kind_of_halt_alone(sandbox, sent):
    state = fresh_state()
    state.halt("the books and the broker disagree", cause=bs.HALT_RECONCILIATION,
               at=at(9, 50).isoformat())
    loop.note_the_feed(tick_for("A", at(10, 0)), state,
                       loop.read_quotes(Feeder(served=3), [{"symbol": "AAPL"}], []))
    loop.note_the_feed(tick_for("A", at(10, 35)), state,
                       loop.read_quotes(Feeder(served=1), [{"symbol": "AAPL"}], []))

    assert state.halted is True
    assert state.halt_causes() == {bs.HALT_RECONCILIATION}


def test_a_live_feed_says_nothing_and_halts_nobody(sandbox, sent):
    tick = tick_for("A")
    state = fresh_state()
    loop.note_the_feed(tick, state,
                       loop.read_quotes(Feeder(served=1), [{"symbol": "AAPL"}], []))
    assert state.halted is False
    assert tick.data_block == ""
    assert sent == []


def test_a_tick_that_asked_for_no_quotes_judges_nothing(sandbox, sent):
    """A book with nothing to look at has no feed to complain about."""
    tick = tick_for("A")
    state = fresh_state()
    loop.note_the_feed(tick, state, loop.read_quotes(Feeder(), [], []))
    assert state.halted is False
    assert tick.data_block == ""
    assert sent == []


def test_a_data_block_stops_an_entry_and_leaves_an_exit_alone(sandbox):
    tick = tick_for("A")
    state = fresh_state()
    guards = loop.read_guards(sandbox)

    assert loop.entries_blocked_reason(guards, state, tick) is None

    tick.data_block = "the quotes came back delayed"
    blocked = loop.entries_blocked_reason(guards, state, tick)
    assert blocked and "delayed" in blocked

    # Nothing in here touches the closing path. do_manage and do_flatten never
    # ask entries_blocked_reason anything, which is what makes an exit safe.
    source = (REPO / "agent" / "loop.py").read_text(encoding="utf-8")
    assert "entries_blocked_reason" in source
    assert source.count("entries_blocked_reason(guards, state, tick)") == 2

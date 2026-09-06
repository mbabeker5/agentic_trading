"""A Gateway that is not answering is not an account that holds nothing.

This is the one distinction the loop used to get wrong, and it cost the whole
trading day every time. read_broker_facts() caught the connection error, wrote
down that it could not read the positions, and handed reconciliation an EMPTY
account. A book holding something then looked exactly like a book that had lost
it, so reconciliation called a mismatch, every book holding anything was halted,
and nothing anywhere cleared a halt.

The replay gate found it with a twenty minute outage injected at 11:00. Book A
was halted and never came back.

Nothing here touches a broker, a network or the real output folder.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest tests/test_loop_outage.py -q
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
from agent import loop                           # noqa: E402

BOOKS_YAML = REPO / "config" / "books.yaml"
NEW_YORK = ZoneInfo("America/New_York")
TUESDAY = date(2026, 9, 8)


def at(hour: int, minute: int) -> datetime:
    return datetime(2026, 9, 8, hour, minute, tzinfo=NEW_YORK)


class Healthy:
    """A broker that answers everything, holding one hundred AAPL."""

    def account_summary(self, account=None):
        return {"items": [{"tag": "NetLiquidation", "value": "500000"}]}

    def portfolio(self, account=None, include_pnl=True):
        return {"positions": [{"symbol": "AAPL", "position": 100, "avgCost": 100.0,
                               "marketPrice": 101.0, "marketValue": 10100.0}]}

    def open_orders(self, account=None, include_all=True):
        return {"orders": [{"orderId": 7, "symbol": "AAPL", "orderRef": "BOOK_A"}]}

    def executions(self, account=None, **kwargs):
        return {"executions": []}

    def snapshot(self, contracts, market_data_type=3):
        return {"snapshots": []}

    def historical_bars(self, contract, duration, bar_size, **kwargs):
        return {"bars": []}


class Dead(Healthy):
    """IB Gateway is not there. Every read raises, exactly as the real one does."""

    def account_summary(self, account=None):
        raise ConnectionError("cannot reach IB Gateway on port 4002")

    def portfolio(self, account=None, include_pnl=True):
        raise ConnectionError("cannot reach IB Gateway on port 4002")

    def open_orders(self, account=None, include_all=True):
        raise ConnectionError("cannot reach IB Gateway on port 4002")


class Wrapped(Healthy):
    """The MCP client turns a dead socket into its own error and loses the type."""

    def portfolio(self, account=None, include_pnl=True):
        raise RuntimeError("McpError: connection refused talking to the server")


class Awkward(Healthy):
    """A broker that answers, badly. Not an outage, just a problem to note."""

    def portfolio(self, account=None, include_pnl=True):
        raise ValueError("the portfolio reply was not a dictionary")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    for name in ("config", "strategies"):
        (tmp_path / name).symlink_to(REPO / name)
    (tmp_path / "output").mkdir()
    monkeypatch.setenv(loop.ROOT_ENV_VAR, str(tmp_path))
    monkeypatch.delenv("AGENTIC_TRADING_LIVE_ORDERS", raising=False)
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


# ---------------------------------------------------------------------------
# Telling the two apart
# ---------------------------------------------------------------------------


def test_a_connection_error_is_an_outage():
    assert loop.looks_like_an_outage(ConnectionError("refused"))
    assert loop.looks_like_an_outage(ConnectionRefusedError("refused"))
    assert loop.looks_like_an_outage(ConnectionResetError("reset"))
    assert loop.looks_like_an_outage(BrokenPipeError("gone"))
    assert loop.looks_like_an_outage(TimeoutError("waited too long"))


def test_a_wrapped_connection_error_is_an_outage_too():
    """agent/mcp_client.py raises its own error and the type is lost on the way."""
    assert loop.looks_like_an_outage(RuntimeError("McpError: connection refused"))
    assert loop.looks_like_an_outage(RuntimeError("the gateway is down"))
    assert loop.looks_like_an_outage(RuntimeError("request timed out after 45s"))


def test_an_ordinary_problem_is_not_an_outage():
    assert not loop.looks_like_an_outage(ValueError("that is not a number"))
    assert not loop.looks_like_an_outage(KeyError("positions"))
    assert not loop.looks_like_an_outage(RuntimeError("no such account U1234567"))


def test_a_healthy_broker_is_available(sandbox):
    facts = loop.read_broker_facts(Healthy(), "DUT077572")
    assert facts.available is True
    assert facts.outage == ""
    assert facts.positions["AAPL"]["position"] == 100


def test_a_dead_gateway_hands_back_nothing_rather_than_an_empty_account(sandbox):
    facts = loop.read_broker_facts(Dead(), "DUT077572")
    assert facts.available is False
    assert "cannot reach IB Gateway" in facts.outage
    assert facts.positions == {}, "and the caller must read available, not this"
    assert facts.rows == {}


def test_a_wrapped_outage_is_read_as_an_outage(sandbox):
    facts = loop.read_broker_facts(Wrapped(), "DUT077572")
    assert facts.available is False
    assert "connection refused" in facts.outage


def test_a_broker_that_answers_badly_is_a_problem_not_an_outage(sandbox):
    facts = loop.read_broker_facts(Awkward(), "DUT077572")
    assert facts.available is True, "this one answered, it just answered wrongly"
    assert facts.problems == ["could not read the positions: the portfolio reply "
                              "was not a dictionary"]


# ---------------------------------------------------------------------------
# What a blind tick does, which is as close to nothing as possible
# ---------------------------------------------------------------------------


def _book_holding_aapl(sandbox) -> Path:
    state = bs.BookState(book_id="A", order_ref="BOOK_A", date="2026-09-08",
                         capital=100000.0, cash=90000.0, day_start_equity=100000.0,
                         tick_count=7, realized_pnl_today=250.0,
                         entries_opened_today=1)
    state.put_position(bs.Position(symbol="AAPL", qty=100, avg_cost=100.0,
                                   entry=100.0, side="long", stop=98.5,
                                   opened_on="2026-09-08", market_value=10100.0))
    state.working_orders["7"] = {"symbol": "AAPL", "purpose": "stop", "price": 98.5}
    return bs.save_state(state, root=sandbox)


def test_a_blind_tick_leaves_every_book_file_exactly_as_it_was(sandbox, sent):
    path = _book_holding_aapl(sandbox)
    before = path.read_text()

    assert loop.main(["--now", "2026-09-08 11:05"], broker=Dead()) == 0

    assert path.read_text() == before, (
        "not one byte. A book carries on believing what it believed before the "
        "Gateway went away, which is the only honest thing it can believe.")


def test_a_blind_tick_halts_nobody(sandbox, sent, capsys):
    _book_holding_aapl(sandbox)
    loop.main(["--now", "2026-09-08 11:05"], broker=Dead())

    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000, root=sandbox)
    assert state.halted is False
    assert state.halt_reason is None
    assert len(state.all_positions()) == 1, "it still holds what it held"

    printed = capsys.readouterr().out
    assert "BROKER UNAVAILABLE" in printed
    assert "Reconciliation:" not in printed, "there is nothing to reconcile against"


def test_a_blind_tick_is_still_a_tick(sandbox, sent):
    """It returns zero, it logs, and it touches the heartbeat.

    Withholding the heartbeat would have the dead man's handle flatten the
    account over a Gateway outage, which is the opposite of help: the loop is
    alive, it is the broker that is not.
    """
    _book_holding_aapl(sandbox)
    assert loop.main(["--now", "2026-09-08 11:05"], broker=Dead()) == 0

    assert (sandbox / "output" / "heartbeat").exists()
    log = (sandbox / "output" / "loop.log").read_text()
    assert "phase=broker_unavailable" in log
    assert "book=A" in log


def test_a_blind_tick_alerts_once_and_then_stays_quiet(sandbox, sent):
    _book_holding_aapl(sandbox)
    for minute in (5, 10, 15, 20):
        loop.main([f"--now", f"2026-09-08 11:{minute:02d}"], broker=Dead())

    assert [title for _l, title, _b in sent] == ["IB Gateway is not answering"], (
        "four dead ticks, one message")
    assert "nothing has been lost" in sent[0][2]


def test_the_loop_carries_straight_on_when_the_broker_comes_back(sandbox, sent,
                                                                 capsys):
    _book_holding_aapl(sandbox)
    loop.main(["--now", "2026-09-08 11:05"], broker=Dead())
    capsys.readouterr()

    assert loop.main(["--now", "2026-09-08 11:25"], broker=Healthy()) == 0
    printed = capsys.readouterr().out
    assert "BROKER UNAVAILABLE" not in printed
    assert "Reconciliation:" in printed

    state = bs.load_state("A", "BOOK_A", TUESDAY, capital=100000, root=sandbox)
    assert len(state.all_positions()) == 1
    assert state.halted is False, (
        "the outage must not have left a halt behind to be cleared")

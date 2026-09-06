"""Tests for the 9 AM pre-flight check.

Everything here works on temporary folders and a stand in for the MCP server.
Nothing in this file talks to IB Gateway, creates a real output/NO_TRADE_TODAY,
sends an alert, or runs the scanner.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest /Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_preflight.py -q
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import preflight  # noqa: E402

NINE_AM = datetime(2026, 9, 8, 9, 0, tzinfo=preflight.EASTERN)


class FakeMcp:
    """Stands in for the MCP server. Reads only, like the real read tools."""

    def __init__(self, positions, cash="999233.85"):
        self._positions = positions
        self._cash = cash

    def portfolio(self, *a, **k):
        return {"account": "DUT077572",
                "positions": [{"symbol": s, "position": q} for s, q in self._positions.items()]}

    def account_values(self, *a, **k):
        return {"TotalCashValue": self._cash, "NetLiquidation": "1000175.35"}


def use_temp_output(monkeypatch, tmp_path: Path) -> Path:
    """Point the pre-flight's output folder at a throwaway directory."""
    monkeypatch.setattr(preflight, "output_dir", lambda *a, **k: tmp_path)
    monkeypatch.setattr(preflight, "no_trade_today_file", lambda: tmp_path / "NO_TRADE_TODAY")
    return tmp_path


def write_book(folder: Path, book: str, positions) -> Path:
    path = folder / f"state_BOOK_{book}.json"
    path.write_text(json.dumps({"book_id": book, "positions": positions}), encoding="utf-8")
    return path


# ------------------------------------------------- reading a book state file

def test_positions_read_from_a_list_of_objects():
    loaded = {"positions": [{"symbol": "SPY", "position": 3},
                            {"symbol": "DELL", "qty": 10}]}
    assert preflight._positions_from_book(loaded) == {"SPY": 3.0, "DELL": 10.0}


def test_positions_read_from_a_plain_mapping():
    assert preflight._positions_from_book({"positions": {"SPY": 3}}) == {"SPY": 3.0}


def test_positions_read_from_a_mapping_of_objects():
    loaded = {"positions": {"SPY": {"quantity": 2, "avg_cost": 766.15}}}
    assert preflight._positions_from_book(loaded) == {"SPY": 2.0}


def test_the_same_symbol_in_two_entries_is_added_up():
    loaded = {"positions": [{"symbol": "SPY", "position": 2},
                            {"symbol": "SPY", "position": 3}]}
    assert preflight._positions_from_book(loaded) == {"SPY": 5.0}


def test_a_file_with_no_positions_holds_nothing():
    assert preflight._positions_from_book({"book_id": "A"}) == {}
    assert preflight._positions_from_book("not a dict at all") == {}


# ------------------------------------------------------------ reconciliation

def test_no_book_state_files_means_no_books_active_and_a_pass(monkeypatch, tmp_path):
    use_temp_output(monkeypatch, tmp_path)
    result = preflight.check_reconcile()
    assert result.passed is True
    assert "no books active" in result.detail.lower()


def test_books_that_agree_with_the_broker_pass(monkeypatch, tmp_path):
    folder = use_temp_output(monkeypatch, tmp_path)
    write_book(folder, "A", [{"symbol": "SPY", "position": 1}])
    write_book(folder, "C", [{"symbol": "DELL", "position": 10}])
    monkeypatch.setattr(preflight.mcp, "McpClient",
                        lambda *a, **k: FakeMcp({"SPY": 1.0, "DELL": 10.0}))

    result = preflight.check_reconcile()
    assert result.passed is True
    assert result.facts["books_believe"] == {"SPY": 1.0, "DELL": 10.0}


def test_two_books_holding_the_same_symbol_are_added_together(monkeypatch, tmp_path):
    folder = use_temp_output(monkeypatch, tmp_path)
    write_book(folder, "A", [{"symbol": "SPY", "position": 1}])
    write_book(folder, "B", [{"symbol": "SPY", "position": 2}])
    monkeypatch.setattr(preflight.mcp, "McpClient", lambda *a, **k: FakeMcp({"SPY": 3.0}))
    assert preflight.check_reconcile().passed is True


def test_a_share_count_that_does_not_match_fails_and_says_which_symbol(monkeypatch, tmp_path):
    folder = use_temp_output(monkeypatch, tmp_path)
    write_book(folder, "A", [{"symbol": "SPY", "position": 5}])
    monkeypatch.setattr(preflight.mcp, "McpClient", lambda *a, **k: FakeMcp({"SPY": 1.0}))

    result = preflight.check_reconcile()
    assert result.passed is False
    assert "SPY" in result.detail
    assert "the books say 5" in result.detail
    assert "the broker says 1" in result.detail


def test_a_position_the_books_have_never_heard_of_fails(monkeypatch, tmp_path):
    folder = use_temp_output(monkeypatch, tmp_path)
    write_book(folder, "A", [])
    monkeypatch.setattr(preflight.mcp, "McpClient", lambda *a, **k: FakeMcp({"SPY": 1.0}))

    result = preflight.check_reconcile()
    assert result.passed is False
    assert "SPY" in result.detail


def test_a_corrupt_book_state_file_fails_rather_than_passing_quietly(monkeypatch, tmp_path):
    folder = use_temp_output(monkeypatch, tmp_path)
    (folder / "state_BOOK_A.json").write_text("{ half a file", encoding="utf-8")
    result = preflight.check_reconcile()
    assert result.passed is False
    assert "state_BOOK_A.json" in result.detail


def test_an_mcp_server_that_will_not_answer_fails(monkeypatch, tmp_path):
    folder = use_temp_output(monkeypatch, tmp_path)
    write_book(folder, "A", [{"symbol": "SPY", "position": 1}])

    def refuse(*a, **k):
        raise RuntimeError("cannot reach the MCP server")
    monkeypatch.setattr(preflight.mcp, "McpClient", refuse)

    result = preflight.check_reconcile()
    assert result.passed is False
    assert "MCP server" in result.detail


# ------------------------------------------------------- day trade counters

def test_no_day_trade_files_is_a_pass(monkeypatch, tmp_path):
    use_temp_output(monkeypatch, tmp_path)
    assert preflight.check_day_trade_counters().passed is True


def test_readable_day_trade_files_pass(monkeypatch, tmp_path):
    folder = use_temp_output(monkeypatch, tmp_path)
    (folder / "daytrades_2026-09-08.json").write_text('{"used": 1}', encoding="utf-8")
    result = preflight.check_day_trade_counters()
    assert result.passed is True
    assert result.facts["files"] == ["daytrades_2026-09-08.json"]


def test_a_corrupt_day_trade_file_fails(monkeypatch, tmp_path):
    folder = use_temp_output(monkeypatch, tmp_path)
    (folder / "day_trades.json").write_text("nope", encoding="utf-8")
    result = preflight.check_day_trade_counters()
    assert result.passed is False
    assert "day_trades.json" in result.detail


# -------------------------------------------------------- the written record

def test_the_dry_run_writes_to_its_own_file(monkeypatch, tmp_path):
    use_temp_output(monkeypatch, tmp_path)
    assert preflight.report_path(NINE_AM, dry_run=True).name == "preflight_dryrun.json"
    assert preflight.report_path(NINE_AM, dry_run=False).name == "preflight_2026-09-08.json"


def test_the_no_trade_file_says_why_it_is_there_and_how_to_clear_it(monkeypatch, tmp_path):
    use_temp_output(monkeypatch, tmp_path)
    path = preflight.write_no_trade_today(["market_data", "scanner"], NINE_AM)
    text = path.read_text(encoding="utf-8")
    assert "market_data, scanner" in text
    assert "must not open a new position" in text
    assert "reenable.sh" in text


def test_the_scanner_check_fails_when_the_scanner_is_missing(monkeypatch, tmp_path):
    use_temp_output(monkeypatch, tmp_path)
    monkeypatch.setattr(preflight, "agent_dir", lambda: tmp_path)
    result = preflight.check_scanner(tmp_path / "scan.json")
    assert result.passed is False
    assert "does not exist" in result.detail

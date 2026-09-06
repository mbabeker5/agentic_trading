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


# ------------------------------- one file per book per day, from book_state.py

def test_only_the_newest_day_of_each_book_counts(monkeypatch, tmp_path):
    """agent/book_state.py writes one file per book per day, so yesterday's file
    is still sitting there. Adding both would count Monday again on Tuesday."""
    folder = use_temp_output(monkeypatch, tmp_path)
    (folder / "state_BOOK_A_2026-09-07.json").write_text(
        json.dumps({"positions": {"SPY": {"qty": 9}}}), encoding="utf-8")
    (folder / "state_BOOK_A_2026-09-08.json").write_text(
        json.dumps({"positions": {"SPY": {"qty": 1}}}), encoding="utf-8")
    monkeypatch.setattr(preflight.mcp, "McpClient", lambda *a, **k: FakeMcp({"SPY": 1.0}))

    assert [p.name for p in preflight.newest_book_files(folder)] == ["state_BOOK_A_2026-09-08.json"]
    assert preflight.check_reconcile().passed is True


def test_each_book_keeps_its_own_newest_day(monkeypatch, tmp_path):
    folder = use_temp_output(monkeypatch, tmp_path)
    for name in ("state_BOOK_A_2026-09-07.json", "state_BOOK_A_2026-09-08.json",
                 "state_BOOK_C_2026-09-08.json"):
        (folder / name).write_text(json.dumps({"positions": {}}), encoding="utf-8")
    assert [p.name for p in preflight.newest_book_files(folder)] == [
        "state_BOOK_A_2026-09-08.json", "state_BOOK_C_2026-09-08.json"]


def test_a_state_file_with_no_date_on_the_end_still_counts(tmp_path):
    (tmp_path / "state_BOOK_A.json").write_text("{}", encoding="utf-8")
    assert [p.name for p in preflight.newest_book_files(tmp_path)] == ["state_BOOK_A.json"]


def test_the_book_state_shape_is_read_correctly():
    """The real shape agent/book_state.py writes: symbol keys, qty, side."""
    loaded = {"positions": {"SPY": {"symbol": "SPY", "qty": 3.0, "side": "long",
                                    "entry": 766.15, "stop": 754.65}}}
    assert preflight._positions_from_book(loaded) == {"SPY": 3.0}


def test_a_short_held_as_a_positive_number_still_reconciles_as_a_short():
    """book_state.py marks a short with side, and the qty may be positive. The
    broker always reports a short as a negative number, so these must match."""
    loaded = {"positions": {"DELL": {"symbol": "DELL", "qty": 25.0, "side": "short"}}}
    assert preflight._positions_from_book(loaded) == {"DELL": -25.0}


def test_a_short_already_stored_as_a_negative_number_is_left_alone():
    loaded = {"positions": {"DELL": {"symbol": "DELL", "qty": -25.0, "side": "short"}}}
    assert preflight._positions_from_book(loaded) == {"DELL": -25.0}


def test_a_short_book_position_matches_a_short_broker_position(monkeypatch, tmp_path):
    folder = use_temp_output(monkeypatch, tmp_path)
    (folder / "state_BOOK_A_2026-09-08.json").write_text(
        json.dumps({"positions": {"DELL": {"qty": 25.0, "side": "short"}}}), encoding="utf-8")
    monkeypatch.setattr(preflight.mcp, "McpClient", lambda *a, **k: FakeMcp({"DELL": -25.0}))
    assert preflight.check_reconcile().passed is True


def test_the_day_trade_check_finds_the_files_agent_pdt_actually_writes(monkeypatch, tmp_path):
    """agent/pdt.py writes output/pdt_BOOK_A.json, one per book."""
    folder = use_temp_output(monkeypatch, tmp_path)
    (folder / "pdt_BOOK_A.json").write_text('{"round_trips": []}', encoding="utf-8")
    (folder / "pdt_BOOK_C.json").write_text('{"round_trips": []}', encoding="utf-8")
    result = preflight.check_day_trade_counters()
    assert result.passed is True
    assert result.facts["files"] == ["pdt_BOOK_A.json", "pdt_BOOK_C.json"]


def test_a_corrupt_pdt_file_stops_the_morning(monkeypatch, tmp_path):
    folder = use_temp_output(monkeypatch, tmp_path)
    (folder / "pdt_BOOK_A.json").write_text("{ truncated", encoding="utf-8")
    result = preflight.check_day_trade_counters()
    assert result.passed is False
    assert "pdt_BOOK_A.json" in result.detail


# ------------------------------- the scanner check, and what it refuses to pass
#
# Two ways the scanner can hand back something that must not be read as "a quiet
# morning, nothing gapped":
#
#   exit code 3   the scanner itself did not believe its own scan. It wrote
#                 nothing, so yesterday's shortlist is still sitting there.
#   a 162, 165 or 365 in the scan diagnostics of a file it did write.
#
# Both stop the day. An empty candidates list with clean diagnostics does not,
# because at 9 AM the market has not opened and nothing has gapped yet.

import subprocess  # noqa: E402
from types import SimpleNamespace  # noqa: E402


BENIGN_162 = ("Historical Market Data Service error message:"
              "API scanner subscription cancelled: 3")
FILTER_DISABLED_162 = ("Historical Market Data Service error message:"
                       "Scanner filter priceAbove is disabled.")


def stub_scanner_process(monkeypatch, tmp_path, returncode=0, stderr="",
                         writes=None):
    """Put a fake agent/scanner.py and a fake venv python in place, and fake the
    subprocess run that would have called them."""
    (tmp_path / "scanner.py").write_text("# stand in", encoding="utf-8")
    (tmp_path / "python").write_text("# stand in", encoding="utf-8")
    monkeypatch.setattr(preflight, "agent_dir", lambda: tmp_path)
    monkeypatch.setattr(preflight, "venv_python", lambda: tmp_path / "python")

    def fake_run(command, **kwargs):
        if writes is not None:
            out = Path(command[command.index("--out") + 1])
            out.write_text(json.dumps(writes), encoding="utf-8")
        return SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)


def scan_failure_stderr(codes=(162, 365)):
    payload = {
        "message": "scan TOP_PERC_GAIN errors: [(162, '...'), (365, '...')]",
        "codes": list(codes),
        "errors": [{"code": 162, "message": FILTER_DISABLED_162},
                   {"code": 365, "message": "No scanner subscription found for ticker id:4"}],
        "scan_diagnostics": {"TOP_PERC_GAIN": {"rows": 0, "completed": True}},
        "wrote_anything": False,
    }
    return ("2026-09-08 09:00:01 ERROR scanner the scan could not be trusted\n"
            + preflight.SCAN_FAILURE_MARKER + json.dumps(payload) + "\n")


def test_exit_code_three_fails_the_morning_and_names_the_codes(monkeypatch, tmp_path):
    stub_scanner_process(monkeypatch, tmp_path, returncode=3,
                         stderr=scan_failure_stderr())
    result = preflight.check_scanner(tmp_path / "scan.json")

    assert result.passed is False
    assert result.facts["exit_code"] == 3
    assert result.facts["error_codes"] == [162, 365]
    assert result.facts["wrote_shortlist"] is False
    assert "162" in result.detail and "365" in result.detail
    assert "disabled" in result.detail
    assert "wrote nothing" in result.detail


def test_exit_code_three_with_no_json_line_still_fails(monkeypatch, tmp_path):
    """Even if the marker line is lost, exit 3 alone stops the day."""
    stub_scanner_process(monkeypatch, tmp_path, returncode=3,
                         stderr="something went wrong and nobody wrote it down")
    result = preflight.check_scanner(tmp_path / "scan.json")
    assert result.passed is False
    assert result.facts["exit_code"] == 3


def test_a_162_in_the_diagnostics_fails_even_when_the_scanner_exited_cleanly(
        monkeypatch, tmp_path):
    stub_scanner_process(monkeypatch, tmp_path, returncode=0, writes={
        "candidates": [],
        "scan_diagnostics": {
            "TOP_PERC_GAIN": {"rows": 0, "completed": True,
                              "errors": [{"code": 162, "message": FILTER_DISABLED_162}]},
            "MOST_ACTIVE": {"rows": 50, "completed": True, "errors": []},
        }})
    result = preflight.check_scanner(tmp_path / "scan.json")

    assert result.passed is False
    assert result.facts["error_codes"] == [162]
    assert "TOP_PERC_GAIN" in result.detail
    assert "disabled" in result.detail


def test_a_165_or_a_365_in_the_diagnostics_fails_too(monkeypatch, tmp_path):
    for code, message in ((165, "Historical Market Data Service query message"),
                          (365, "No scanner subscription found for ticker id:4")):
        stub_scanner_process(monkeypatch, tmp_path, returncode=0, writes={
            "candidates": [{"symbol": "NVDA"}],
            "scan_diagnostics": {
                "HOT_BY_VOLUME": {"rows": 0, "errors": [{"code": code, "message": message}]}}})
        result = preflight.check_scanner(tmp_path / "scan.json")
        assert result.passed is False, code
        assert result.facts["error_codes"] == [code]


def test_an_empty_shortlist_with_clean_diagnostics_passes(monkeypatch, tmp_path):
    """Before the open this is the normal answer, not a problem."""
    stub_scanner_process(monkeypatch, tmp_path, returncode=0, writes={
        "candidates": [],
        "scan_diagnostics": {
            "TOP_PERC_GAIN": {"rows": 50, "completed": True,
                              "errors": [{"code": 162, "message": BENIGN_162}]},
            "MOST_ACTIVE": {"rows": 50, "completed": True,
                            "errors": [{"code": 162, "message": BENIGN_162}]},
        }})
    result = preflight.check_scanner(tmp_path / "scan.json")

    assert result.passed is True
    assert result.facts["candidates"] == 0
    assert "empty list before the open is normal" in result.detail
    assert "TOP_PERC_GAIN" in result.detail


def test_the_benign_cancelled_message_is_not_treated_as_a_failure():
    """IBKR sends 162 to confirm a finished one-shot scan closed. Every healthy
    run carries it, so failing on it would stop every morning."""
    assert preflight.hard_scan_errors(
        {"TOP_PERC_GAIN": {"errors": [{"code": 162, "message": BENIGN_162}]}}) == []


def test_hard_scan_errors_copes_with_a_file_shaped_differently():
    assert preflight.hard_scan_errors(None) == []
    assert preflight.hard_scan_errors({}) == []
    assert preflight.hard_scan_errors({"X": "not a block"}) == []
    assert preflight.hard_scan_errors({"X": {"errors": ["not a dict"]}}) == []
    assert preflight.hard_scan_errors({"X": {"errors": [{"code": "abc"}]}}) == []


def test_the_scan_failure_line_is_read_off_stderr():
    parsed = preflight.read_scan_failure(scan_failure_stderr())
    assert parsed["codes"] == [162, 365]
    assert parsed["errors"][0]["code"] == 162

    assert preflight.read_scan_failure("") == {}
    assert preflight.read_scan_failure("no marker here") == {}
    assert preflight.read_scan_failure(preflight.SCAN_FAILURE_MARKER + "{ broken") == {}


# ------------------------------ the filter probe, which never stops the morning

def test_the_filter_probe_is_in_the_check_list_and_is_informational():
    assert preflight.CHECK_SCANNER_FILTERS == "scanner_filters_enabled"
    assert preflight.CHECK_SCANNER_FILTERS in preflight.CHECK_ORDER
    assert preflight.CHECK_SCANNER_FILTERS in preflight.INFORMATIONAL_CHECKS


def test_the_filter_probe_passes_even_when_it_cannot_reach_gateway(monkeypatch):
    class RefusingIB:
        def connect(self, *a, **k):
            raise ConnectionRefusedError("nothing is listening on 4002")

        def disconnect(self):
            pass

    monkeypatch.setattr(preflight.wd, "GATEWAY_HOST", "127.0.0.1", raising=False)
    import ib_async
    monkeypatch.setattr(ib_async, "IB", lambda *a, **k: RefusingIB())

    result = preflight.check_scanner_filters()
    assert result.passed is True, "the probe must never stop the day on its own"
    assert result.facts["filters_enabled"] is None


def test_the_filter_probe_records_false_when_the_filtered_scan_is_refused(monkeypatch):
    """The state Mo's account was in on 2026-09-06. False here is expected and
    changes nothing, because the scanner sends no filters."""
    import ib_async

    import scan_truth

    class QuietIB:
        def connect(self, *a, **k):
            return None

        def disconnect(self):
            pass

    monkeypatch.setattr(ib_async, "IB", lambda *a, **k: QuietIB())

    def refuse(ib, make_subscription, filters, timeout_s=30.0):
        raise scan_truth.ScanFailure(
            "scan TOP_PERC_GAIN errors: [(162, 'Scanner filter priceAbove is disabled.')]",
            [(162, "Scanner filter priceAbove is disabled.")])

    monkeypatch.setattr(scan_truth, "checked_scan", refuse)

    result = preflight.check_scanner_filters()
    assert result.passed is True
    assert result.facts["filters_enabled"] is False
    assert result.facts["probes"]["priceAbove"]["errors"] == [
        {"code": 162, "message": "Scanner filter priceAbove is disabled."}]
    assert "still off" in result.detail


def test_the_filter_probe_records_true_when_a_filtered_scan_comes_back(monkeypatch):
    import ib_async

    import scan_truth
    from scan_truth import ScanResult

    class QuietIB:
        def connect(self, *a, **k):
            return None

        def disconnect(self):
            pass

    monkeypatch.setattr(ib_async, "IB", lambda *a, **k: QuietIB())
    monkeypatch.setattr(
        scan_truth, "checked_scan",
        lambda *a, **k: (ScanResult("TOP_PERC_GAIN", [("priceAbove", "5")],
                                    [object()] * 41, 7),
                         ScanResult("TOP_PERC_GAIN", [], [object()] * 50, 8)))

    result = preflight.check_scanner_filters()
    assert result.passed is True
    assert result.facts["filters_enabled"] is True
    assert result.facts["probes"]["priceAbove"]["rows"] == 41
    assert result.facts["probes"]["priceAbove"]["control_rows"] == 50
    assert "now work" in result.detail


def test_the_filter_probe_says_so_when_only_some_filters_work(monkeypatch):
    """What was actually measured on 2026-09-06, hours apart on the same account:
    priceAbove came back with 50 rows and stVolume5MinAbove came back with none.
    A probe that only tried one of them would have reported the wrong answer."""
    import ib_async

    import scan_truth
    from scan_truth import ScanResult

    class QuietIB:
        def connect(self, *a, **k):
            return None

        def disconnect(self):
            pass

    monkeypatch.setattr(ib_async, "IB", lambda *a, **k: QuietIB())

    def mixed(ib, make_subscription, filters, timeout_s=30.0):
        tag = filters[0].tag
        if tag == "priceAbove":
            return (ScanResult("TOP_PERC_GAIN", [(tag, "5")], [object()] * 50, 7),
                    ScanResult("TOP_PERC_GAIN", [], [object()] * 50, 8))
        raise scan_truth.ScanFailure(
            f"scan TOP_PERC_GAIN errors: [(162, 'Scanner filter {tag} is disabled.')]",
            [(162, f"Scanner filter {tag} is disabled.")])

    monkeypatch.setattr(scan_truth, "checked_scan", mixed)

    result = preflight.check_scanner_filters()
    assert result.passed is True, "a mixed answer is still never a reason to stop"
    assert result.facts["probes"]["priceAbove"]["enabled"] is True
    assert result.facts["probes"]["stVolume5MinAbove"]["enabled"] is False
    assert "half on" in result.detail
    assert "stVolume5MinAbove" in result.detail


def test_the_probe_tries_the_filter_a_gap_scan_would_actually_want():
    tags = [tag for tag, _ in preflight.FILTER_PROBES]
    assert tags[0] == "priceAbove", "the headline answer stays priceAbove"
    assert "stVolume5MinAbove" in tags, (
        "the five minute volume filter is the one a 9:35 gap scan needs, so it "
        "has to be measured too")


# --------------------------------------------- the day trading regime check
#
# FINRA retired the pattern day trader rule with effect from 2026-06-04
# (Regulatory Notice 26-10) and replaced it with the intraday margin deficit
# rules. IBKR says which of the two an account is under through five account
# summary tags. This check reads them, writes the answer down, and never stops
# the morning on its own.
#
# Nothing here connects to Gateway: ib_async.IB is replaced with a stand in that
# hands back whatever tags the test wants, the same way the scanner filter probe
# tests above do it.

from margin_regime import DAY_TRADE_TAGS, Regime  # noqa: E402

REAL_GUARDRAILS = (
    Path(__file__).resolve().parent.parent / "config" / "guardrails.yaml"
)


class SummaryRow:
    """One account summary tag, shaped the way ib_async hands it back."""

    def __init__(self, tag, value, account="DUT077572"):
        self.account = account
        self.tag = tag
        self.value = str(value)
        self.currency = "USD"


def fake_gateway(monkeypatch, rows, refuse_connection=False):
    """Replace ib_async.IB with something that answers with these tags."""
    import ib_async

    class FakeIB:
        def connect(self, *a, **k):
            if refuse_connection:
                raise ConnectionRefusedError("nothing is listening on 4002")

        def accountSummary(self, *a, **k):
            return rows

        def disconnect(self):
            pass

    monkeypatch.setattr(ib_async, "IB", lambda *a, **k: FakeIB())


def counting_rows(remaining=3):
    """The five tags holding counts, which is the old rule still running."""
    return [SummaryRow(tag, remaining, account="U28440091")
            for tag in DAY_TRADE_TAGS]


def rows_without_day_trade_tags():
    """What the paper account DUT077572 actually sent on 2026-09-06."""
    return [SummaryRow("NetLiquidation", "1000175.35"),
            SummaryRow("TotalCashValue", "999233.85"),
            SummaryRow("BuyingPower", "3999243.66")]


def temp_guardrails(monkeypatch, tmp_path: Path) -> Path:
    """A throwaway copy of the real settings file for the writing tests."""
    copy = tmp_path / "guardrails.yaml"
    copy.write_text(REAL_GUARDRAILS.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(preflight, "guardrails_config_path", lambda: copy)
    return copy


def test_the_regime_check_is_in_the_list_and_can_never_stop_the_day():
    assert preflight.CHECK_DAY_TRADE_REGIME in preflight.CHECK_ORDER
    assert preflight.CHECK_DAY_TRADE_REGIME in preflight.INFORMATIONAL_CHECKS


def test_counting_tags_are_read_as_the_old_pattern_day_trader_rule(monkeypatch):
    fake_gateway(monkeypatch, counting_rows(3))

    result = preflight.check_day_trade_regime()

    assert result.passed is True
    assert result.facts["regime"] == Regime.OLD_PDT.value
    assert result.facts["tags_as_numbers"]["DayTradesRemaining"] == 3.0
    assert result.facts.get("warning") is not True


def test_no_day_trade_tags_are_read_as_the_new_rules(monkeypatch):
    fake_gateway(monkeypatch, rows_without_day_trade_tags())

    result = preflight.check_day_trade_regime()

    assert result.passed is True
    assert result.facts["regime"] == Regime.NEW_IMD.value
    assert result.facts["tags_missing"] == list(DAY_TRADE_TAGS)


def test_minus_one_is_read_as_the_new_rules(monkeypatch):
    fake_gateway(monkeypatch, counting_rows(-1))

    result = preflight.check_day_trade_regime()

    assert result.facts["regime"] == Regime.NEW_IMD.value


def test_an_answer_that_makes_no_sense_is_unknown_and_warns(monkeypatch):
    fake_gateway(monkeypatch, [SummaryRow(tag, "sometimes")
                               for tag in DAY_TRADE_TAGS])

    result = preflight.check_day_trade_regime()

    assert result.passed is True, "an unknown regime is never a reason to stop"
    assert result.facts["regime"] == Regime.UNKNOWN.value
    assert result.facts["warning"] is True
    assert "treat_unknown_as" in result.detail
    assert "old_pdt" in result.detail


def test_a_gateway_that_will_not_answer_warns_and_still_passes(monkeypatch):
    fake_gateway(monkeypatch, [], refuse_connection=True)

    result = preflight.check_day_trade_regime()

    assert result.passed is True
    assert result.facts["warning"] is True
    assert result.facts["regime"] == Regime.UNKNOWN.value


def test_the_report_says_the_paper_account_may_not_mirror_the_live_one(monkeypatch):
    fake_gateway(monkeypatch, rows_without_day_trade_tags())

    result = preflight.check_day_trade_regime()
    note = result.facts["paper_may_not_mirror_live"]

    assert preflight.LIVE_ACCOUNT in note
    assert "simulated money" in note


def test_nothing_on_disk_moves_without_the_write_regime_flag(monkeypatch, tmp_path):
    config = temp_guardrails(monkeypatch, tmp_path)
    before = config.read_text(encoding="utf-8")
    fake_gateway(monkeypatch, counting_rows(3))

    result = preflight.check_day_trade_regime()

    assert result.facts["config_written"] is False
    assert config.read_text(encoding="utf-8") == before


def test_the_write_regime_flag_writes_one_line_and_keeps_the_comments(
    monkeypatch, tmp_path
):
    config = temp_guardrails(monkeypatch, tmp_path)
    before = config.read_text(encoding="utf-8")
    fake_gateway(monkeypatch, counting_rows(3))

    result = preflight.check_day_trade_regime(write_regime=True)

    after = config.read_text(encoding="utf-8")
    assert result.facts["config_written"] is True
    assert "regime: old_pdt" in after
    assert after.count("\n") == before.count("\n"), "no line was added or lost"
    assert "pattern day trader rule" in after, "the comments survived"
    assert str(config) in result.detail


def test_an_unknown_regime_is_never_written_over_a_real_answer(
    monkeypatch, tmp_path
):
    config = temp_guardrails(monkeypatch, tmp_path)
    before = config.read_text(encoding="utf-8")
    fake_gateway(monkeypatch, [SummaryRow(tag, "sometimes")
                               for tag in DAY_TRADE_TAGS])

    result = preflight.check_day_trade_regime(write_regime=True)

    assert result.facts["config_written"] is False
    assert config.read_text(encoding="utf-8") == before
    assert "shrug" in result.facts["config_note"]


def test_the_regime_check_runs_last_so_a_slow_answer_holds_nothing_up(monkeypatch):
    assert preflight.CHECK_ORDER[-1] == preflight.CHECK_DAY_TRADE_REGIME


def test_the_regime_probe_has_its_own_client_id():
    """Every program talking to Gateway needs one of its own, or they collide."""
    others = {preflight.CLIENT_ID, preflight.FILTER_PROBE_CLIENT_ID}
    assert preflight.REGIME_CLIENT_ID == 282
    assert preflight.REGIME_CLIENT_ID not in others

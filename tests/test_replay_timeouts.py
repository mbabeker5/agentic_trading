"""The day recorder must give up on a read, not wait out the morning.

WHY THIS FILE EXISTS. On 2026-09-07 IB Gateway was up and logged in but had lost
its own upstream connection to IBKR (warning 2110). Every read timed out after a
long wait, the log filling with lines like "account updates for DUT077572 request
timed out", and one `record_day.py --once` tick sat there for eighteen minutes.
ib_async waits forever by default: IB.RequestTimeout is 0.

So: the connection hands the library a bound, the contract lookup gets one of its
own, and the whole tick has a cap over the top of it. A tick that overruns is
written down as a missed slot, which is a thing the manifest already knows how to
describe.

Nothing here reaches IB Gateway or the network. The IB object is a stand in.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest /Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_replay_timeouts.py -q
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from agent.replay import common, record_day  # noqa: E402

WHEN = datetime(2026, 9, 8, 10, 15, tzinfo=common.EASTERN)


class StandInIB:
    """An IB object that answers isConnected and hangs on everything else."""

    def __init__(self, connected: bool = True) -> None:
        self.connected = connected
        self.RequestTimeout = 0            # what ib_async starts at: no timeout
        self.asked_for: list[str] = []

    def isConnected(self) -> bool:         # noqa: N802 - ib_async's own spelling
        return self.connected

    async def connectAsync(self, *args, **kwargs):   # noqa: N802
        self.connected = True

    async def qualifyContractsAsync(self, *contracts):   # noqa: N802
        self.asked_for.extend(getattr(c, "symbol", "?") for c in contracts)
        await asyncio.sleep(3600)          # the 2026-09-07 answer: silence

    def disconnect(self) -> None:
        self.connected = False


def make_recorder(tmp_path: Path, ib=None) -> record_day.DayRecorder:
    args = argparse.Namespace(history_budget=55, market_data_type=3,
                              host="127.0.0.1", port=4002, client_id=299,
                              symbols="SPY", max_symbols=25, run_scanner=False)
    recorder = record_day.DayRecorder(args, WHEN.date(), tmp_path)
    recorder.ib = ib or StandInIB()
    return recorder


# --------------------------------------------------------- the library's own bound

def test_connecting_hands_the_library_a_timeout():
    """Without this ib_async waits forever, which is what cost eighteen minutes."""
    ib = StandInIB(connected=True)
    assert asyncio.run(common.connect_ib(ib, "127.0.0.1", 4002, 299)) is True
    assert ib.RequestTimeout == 20.0


def test_the_bound_is_set_even_when_the_connection_never_comes_up():
    ib = StandInIB(connected=False)

    async def refuse(*args, **kwargs):
        raise ConnectionRefusedError("nothing listening")

    ib.connectAsync = refuse
    assert asyncio.run(common.connect_ib(ib, "127.0.0.1", 4002, 299,
                                         attempts=1, timeout=7.5)) is False
    assert ib.RequestTimeout == 7.5


def test_the_bound_follows_the_timeout_it_was_given():
    ib = StandInIB(connected=True)
    asyncio.run(common.connect_ib(ib, "127.0.0.1", 4002, 299, timeout=20.0))
    assert ib.RequestTimeout == 20.0


# ------------------------------------------------------------ the contract lookup

def test_a_contract_lookup_that_never_answers_is_given_up_on(tmp_path, monkeypatch):
    monkeypatch.setattr(record_day, "QUALIFY_TIMEOUT_SECONDS", 0.3)
    recorder = make_recorder(tmp_path)

    began = time.monotonic()
    contracts = asyncio.run(recorder.qualify(["SPY", "QQQ"]))
    spent = time.monotonic() - began

    assert spent < 3, f"the lookup ran for {spent:.1f} seconds"
    assert contracts == []
    assert any("took more than" in note for note in recorder.warnings)
    assert recorder.ib.asked_for == ["SPY", "QQQ"]


def test_the_lookup_bound_is_the_same_one_the_connection_gets():
    assert record_day.QUALIFY_TIMEOUT_SECONDS == 20.0


# ------------------------------------------------------------------ the whole tick

def test_a_tick_that_hangs_is_written_down_as_missed(tmp_path, monkeypatch):
    monkeypatch.setattr(record_day, "TICK_TIMEOUT_SECONDS", 0.3)
    recorder = make_recorder(tmp_path)

    async def never_comes_back(*args, **kwargs):
        await asyncio.sleep(3600)

    monkeypatch.setattr(recorder, "one_tick", never_comes_back)

    began = time.monotonic()
    record = asyncio.run(record_day.capped_tick(recorder, WHEN, run_scanner=False))
    spent = time.monotonic() - began

    assert spent < 3, f"the tick ran for {spent:.1f} seconds"
    assert record["status"] == "missed"
    assert record["slot"] == record_day.slot_label(WHEN)
    assert "still waiting on IB Gateway" in record["errors"][0]

    recorder.write_tick(record)
    assert recorder.slots_missed == [record_day.slot_label(WHEN)]
    assert recorder.slots_run == []


def test_a_tick_that_finishes_is_handed_back_untouched(tmp_path, monkeypatch):
    recorder = make_recorder(tmp_path)
    mine = {"tick": WHEN.isoformat(), "slot": "10:15", "status": "ok",
            "symbols": 1, "snapshots_written": 1, "bars_written": 1,
            "late_seconds": 0.0, "errors": []}

    async def finishes(*args, **kwargs):
        return mine

    monkeypatch.setattr(recorder, "one_tick", finishes)
    assert asyncio.run(record_day.capped_tick(recorder, WHEN, False)) is mine


def test_the_tick_cap_is_inside_the_launchd_gap():
    """Every tick of the real day is its own --once process, five minutes apart."""
    assert record_day.TICK_TIMEOUT_SECONDS <= 300
    assert record_day.TICK_TIMEOUT_SECONDS > record_day.HISTORY_TIMEOUT_SECONDS

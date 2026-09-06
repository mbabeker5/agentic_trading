"""The replay gate's own tests: the safety locks, and the fast scenarios.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest -q tests/test_replay_gate.py

Two halves.

The first half tests the harness itself, and it is the half that matters most.
The gate deliberately opens the live order path: it puts every book into `full`
mode in its sandbox copy of the register and sets
AGENTIC_TRADING_LIVE_ORDERS=yes for its own process. The only thing standing
between that and a real order is which object is on the other end, so the tests
below check that lock rather than assume it, check that the environment is put
back afterwards, and check that a real McpBroker cannot be built while a run is
going on.

The second half runs every scenario that is not marked slow, against the fetched
history under
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/recordings/history/,
into a temporary sandbox root. It takes about fifteen seconds. The three slow
ones, the two clean days and the guardrail sweep, are left to
`python -m agent.replay.harness --all`, which is what a promotion decision is
made on.

What the second half asserts is deliberately narrow: that every scenario ran and
produced a report, and that the ones passing today still pass. It does not
assert that the failing ones still fail. A scenario that starts passing because
somebody fixed the loop is the point of the whole exercise, and a test that went
red for it would be worse than useless.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, time as clock_time
from pathlib import Path

import pytest

REAL_ROOT = Path(__file__).resolve().parent.parent
if str(REAL_ROOT) not in sys.path:
    sys.path.insert(0, str(REAL_ROOT))
for _extra in (REAL_ROOT / "agent", REAL_ROOT / "ledger"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from agent.replay import harness                                    # noqa: E402
from agent.replay import scenarios as scenarios_mod                 # noqa: E402
from agent.replay.common import EASTERN                             # noqa: E402
from agent.replay.fake_broker import FakeBroker                     # noqa: E402
from agent.replay.stub_decider import ScriptedPick, StubDecider     # noqa: E402

HISTORY = REAL_ROOT / "output" / "recordings" / "history"
BOOKS_YAML = REAL_ROOT / "config" / "books.yaml"
DAY = harness.DEFAULT_DAY

needs_history = pytest.mark.skipif(
    not (HISTORY / "manifest.json").exists(),
    reason="the fetched history is missing. Run agent/replay/fetch_history.py first.")


# --------------------------------------------------------------- the locks


class NotAFakeBroker:
    """Anything at all that is not a FakeBroker."""

    def portfolio(self, account=None, include_pnl=True):
        raise AssertionError("this should never be called")


def test_the_gate_refuses_a_broker_that_is_not_a_fake_one():
    with pytest.raises(AssertionError) as raised:
        harness._refuse_unless_fake(NotAFakeBroker())
    message = str(raised.value)
    assert "FakeBroker" in message
    assert "NotAFakeBroker" in message


def test_the_gate_accepts_a_fake_broker_and_the_adapter_around_one():
    fake = FakeBroker(bars={"SPY": []})
    harness._refuse_unless_fake(fake)
    harness._refuse_unless_fake(harness.ReplayBroker(fake, lambda: None))


def test_the_adapter_will_not_wrap_anything_but_a_fake_broker():
    with pytest.raises(AssertionError):
        harness.ReplayBroker(NotAFakeBroker(), lambda: None)


def test_a_real_broker_cannot_be_built_while_the_gate_runs():
    with pytest.raises(AssertionError) as raised:
        harness.ForbiddenBroker(account="DUT077572")
    assert "IB Gateway" in str(raised.value)


@needs_history
def test_the_live_order_lock_is_open_only_during_a_run_and_put_back_after(tmp_path):
    """The one environment variable that lets an order out is borrowed, not kept."""
    before = os.environ.get(harness.LIVE_ENV_VAR)
    seen: list[str | None] = []

    scenario = _one_tick_scenario(seen)
    report = harness.run_day("history", BOOKS_YAML, scenario, tmp_path)

    assert report.error is None, report.error
    assert seen and seen[0] == "yes", (
        "the gate has to open the live order path during a run, otherwise it is "
        "testing the dry run path and proving nothing about the real one")
    assert os.environ.get(harness.LIVE_ENV_VAR) == before
    assert os.environ.get(harness.ROOT_ENV_VAR) != str(tmp_path / scenario.key)


@needs_history
def test_the_run_writes_nothing_into_the_real_output_folder(tmp_path):
    """Every file a replayed day produces lands inside the sandbox."""
    real_output = REAL_ROOT / "output"
    before = {p.name for p in real_output.glob("*")}

    scenario = _one_tick_scenario([])
    harness.run_day("history", BOOKS_YAML, scenario, tmp_path)

    after = {p.name for p in real_output.glob("*")}
    assert after == before, f"the gate wrote into the real output folder: {after - before}"

    sandbox = tmp_path / scenario.key
    assert (sandbox / "output").exists()
    assert list((sandbox / "output").glob("state_BOOK_*.json"))


def test_the_sandbox_register_is_full_mode_with_a_promotion_stamp(tmp_path):
    """A book in full mode refuses to load without both stamps, so both are set."""
    import guardrails as gr                       # noqa: PLC0415

    sandbox = harness.build_sandbox(tmp_path / "register")
    registry = gr.load_books(sandbox.books_yaml)
    assert registry.books, "the sandbox register loaded no books"
    for book in registry.books:
        assert book.mode == "full", f"book {book.book_id} is in {book.mode} mode"
        assert book.promoted_on is not None
        assert book.rules_commit == harness.SANDBOX_RULES_COMMIT

    # And the real register is untouched by any of that.
    real = gr.load_books(BOOKS_YAML)
    assert all(b.mode == "dry_run" for b in real.books), (
        "the real config/books.yaml is not on dry_run any more, which no gate run "
        "should ever have done")


def test_the_sandbox_has_no_agent_folder_so_no_scanner_can_run(tmp_path):
    """The scanner and the sweeps talk to the outside world, so they must not run.

    agent/loop.py looks for the script and for venv312 before it shells out, and
    the sandbox deliberately holds neither, so run_helper gives up politely and
    reads whatever shortlist file is already there.
    """
    sandbox = harness.build_sandbox(tmp_path / "noagent")
    assert not (sandbox.root / "agent").exists()
    assert not (sandbox.root / "venv312").exists()
    assert (sandbox.root / "config" / "books.yaml").exists()
    assert (sandbox.root / "strategies").exists()


# --------------------------------------------------------- the stub decider


def test_the_stub_decider_costs_nothing_and_calls_no_model():
    decider = StubDecider(max_picks=2)
    packet = {"generated_at": f"{DAY:%Y-%m-%d}T09:35:00-04:00",
              "candidates": [{"symbol": "AAPL", "last_close": 230.0, "score": 99.0},
                             {"symbol": "MSFT", "last_close": 410.0, "score": 98.0},
                             {"symbol": "NVDA", "last_close": 120.0, "score": 97.0}]}
    result = decider.decide({"id": "A", "model": "openrouter/anything"},
                            REAL_ROOT / "strategies" / "momentum_hybrid",
                            "pick", packet, dry_run=False)
    assert result.ok
    assert result.cost_usd == 0.0
    assert result.model == "stub"
    assert [p["symbol"] for p in result.picks] == ["AAPL", "MSFT"]
    assert decider.total_cost_usd == 0.0


def test_a_scripted_pick_is_exactly_what_comes_back():
    decider = StubDecider(script=[
        ScriptedPick(book="A", symbol="MSFT", at="09:35", entry=400.0, stop_pct=1.5)])
    packet = {"generated_at": f"{DAY:%Y-%m-%d}T09:35:00-04:00",
              "candidates": [{"symbol": "AAPL", "last_close": 230.0, "score": 99.0},
                             {"symbol": "MSFT", "last_close": 410.0, "score": 1.0}]}
    result = decider.decide({"id": "A", "model": "none"}, "x", "pick", packet)
    assert [p["symbol"] for p in result.picks] == ["MSFT"]
    assert result.picks[0]["entry"] == 400.0
    assert result.picks[0]["stop"] == 394.0
    assert result.picks[0]["side"] == "long"


def test_the_stub_answers_for_anything_else_the_loop_reads_off_the_module():
    """The loop reads more than decide() off its decision module."""
    import decide as real                          # noqa: PLC0415

    decider = StubDecider()
    assert decider.PACKET_SCHEMA_VERSION == real.PACKET_SCHEMA_VERSION
    with pytest.raises(AttributeError):
        decider.this_name_exists_nowhere


# ------------------------------------------------------------- the scenarios


def test_every_scenario_has_a_key_a_title_and_a_check():
    every = scenarios_mod.all_scenarios(DAY)
    assert len(every) >= 12
    keys = [s.key for s in every]
    assert len(keys) == len(set(keys)), f"two scenarios share a key: {keys}"
    for scenario in every:
        assert scenario.title and scenario.proves
        assert scenario.check is not None, f"{scenario.key} has no check"


def test_the_gate_covers_every_rule_id_the_guardrails_can_emit():
    """The list in scenarios.py has to match what agent/guardrails.py actually emits.

    A rule added to the guardrails and not to this list would quietly never be
    tested, and the gate would still report that it covered everything.
    """
    import re                                      # noqa: PLC0415

    source = (REAL_ROOT / "agent" / "guardrails.py").read_text(encoding="utf-8")
    emitted = set(re.findall(r'decision\.add\(\s*\n?\s*"([a-z_]+)"', source))
    listed = set(scenarios_mod.GUARDRAIL_RULE_IDS)
    assert emitted == listed, (
        "agent/guardrails.py emits "
        f"{sorted(emitted - listed)} that the gate does not know about, and the "
        f"gate lists {sorted(listed - emitted)} that it no longer emits")


@pytest.fixture(scope="module")
def fast_reports(tmp_path_factory) -> dict:
    """Run every scenario that is not marked slow, once, and share the reports."""
    if not (HISTORY / "manifest.json").exists():
        pytest.skip("the fetched history is missing. Run agent/replay/fetch_history.py")
    root = tmp_path_factory.mktemp("replay_gate")
    out = {}
    for scenario in scenarios_mod.all_scenarios(DAY):
        if scenario.slow:
            continue
        out[scenario.key] = harness.run_day("history", BOOKS_YAML, scenario, root)
    return out


@needs_history
def test_every_fast_scenario_ran_a_whole_day(fast_reports):
    assert fast_reports, "no fast scenarios ran"
    for key, report in fast_reports.items():
        assert report.error is None, f"{key} raised: {report.error}"
        assert report.ticks == 81, f"{key} ran {report.ticks} ticks, not 81"
        assert report.evidence or report.failures, f"{key} produced no evidence"
        assert report.model_cost_usd == 0.0, f"{key} spent money on a model"


@needs_history
@pytest.mark.parametrize("key", [
    "daily_loss_cap",
    "kill_switch",
    "day_trade_counter",
    "rejected_order",
    "two_books_one_symbol",
])
def test_the_scenarios_that_pass_today_still_pass(fast_reports, key):
    """A regression guard, not a specification.

    These five pass against the loop as it stands. The other fast scenarios fail
    on real gaps, and they are deliberately not asserted on here: the day one of
    them starts passing is the day somebody fixed the loop, and a test that went
    red for that would be telling the wrong story.
    """
    report = fast_reports[key]
    assert report.passed, f"{key} failed: " + "; ".join(report.failures)


@needs_history
def test_no_scenario_ever_reached_a_real_broker(fast_reports):
    """Nothing in a gate run may build an McpBroker, and nothing did."""
    import broker as broker_mod                    # noqa: PLC0415

    assert broker_mod.McpBroker is not harness.ForbiddenBroker, (
        "the gate left agent/broker.py's McpBroker replaced after the run")
    for key, report in fast_reports.items():
        assert report.day == f"{DAY:%Y-%m-%d}", key


@needs_history
def test_the_report_survives_a_round_trip_through_json(fast_reports):
    import json                                    # noqa: PLC0415

    payload = {"scenarios": [r.as_dict() for r in fast_reports.values()]}
    text = json.dumps(payload, indent=2, default=str)
    back = json.loads(text)
    assert len(back["scenarios"]) == len(fast_reports)
    for row in back["scenarios"]:
        assert set(row) >= {"key", "title", "proves", "passed", "evidence",
                            "failures", "rule_ids_fired", "end_of_day"}


# ------------------------------------------------------------------ helpers


def _one_tick_scenario(seen: list) -> harness.Scenario:
    """The smallest possible replayed day: one book, three ticks, one pick.

    Used by the tests about the locks, which care about what the environment
    looked like while a tick was running and not about what the tick decided.
    """

    def before_tick(context, moment):
        seen.append(os.environ.get(harness.LIVE_ENV_VAR))

    return harness.Scenario(
        key="lock_check",
        title="a three tick day, for the tests about the locks",
        proves="nothing on its own",
        day=DAY,
        start=clock_time(9, 25), end=clock_time(9, 35),
        symbols=("SPY",),
        book_patches=scenarios_mod.only("A"),
        decider=lambda s: StubDecider(max_picks=1),
        before_tick=before_tick,
        check=lambda context: (True, ["ran"], []),
    )

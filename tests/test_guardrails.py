"""Tests for the guardrails, the code that refuses orders that break a limit.

Every rule id gets at least one test that blocks and one that allows, because a
guardrail that always says no is just as broken as one that always says yes.

Nothing here touches the network, IB Gateway or a broker account. Dates are all
in the week of 2026-09-02, which is a Wednesday, so 2026-09-05 is a Saturday.

Run them with:
    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python -m pytest -q
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from agent.guardrails import (
    LIVE_MODE_ENV_VAR,
    AccountState,
    Decision,
    GuardrailConfigError,
    GuardrailUsageError,
    Guardrails,
    OrderIntent,
    PositionInfo,
    available_cash,
    check_order,
    daily_loss_hit,
    entries_allowed_now,
    is_regular_hours,
    load_guardrails,
    max_shares_for,
    must_flatten_now,
    stop_price_for,
)

try:  # Python 3.9 and later
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    raise

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHIPPED_CONFIG = PROJECT_ROOT / "config" / "guardrails.yaml"
EXAMPLE_CONFIG = PROJECT_ROOT / "config" / "guardrails.example.yaml"

EASTERN = ZoneInfo("America/New_York")

# Every rule id check_order is allowed to report. The last test in this file
# proves each one can actually fire.
ALL_RULE_IDS = {
    "paper_only",
    "wrong_account",
    "kill_switch",
    "sec_type",
    "currency",
    "blacklist",
    "whitelist",
    "no_shorts",
    "entry_window",
    "outside_market_hours",
    "flatten_time",
    "daily_loss_cap",
    "max_order_notional",
    "max_position_pct",
    "max_open_positions",
}

# The proposed settings, as a plain dictionary, so a test can change one value
# and write it back out to a temporary file.
BASE_CONFIG: dict = {
    "account": {
        "mode": "paper",
        "account_id": "DUT077572",
        "gateway_port_paper": 4002,
        "gateway_port_live": 4001,
    },
    "money": {
        "starting_equity": 100000,
        "max_position_pct": 10,
        "max_open_positions": 5,
        "max_daily_loss_pct": 2,
        "max_order_notional": 10000,
    },
    "risk": {
        "stop_loss_pct": 1.5,
        "use_opening_range_low_if_tighter": True,
    },
    "universe": {
        "price_floor": 5,
        "min_avg_volume": 1000000,
        "allow_options": False,
        "allow_shorts": False,
        "allowed_sec_types": ["STK"],
        "allowed_currencies": ["USD"],
        "whitelist": [],
        "blacklist": [],
    },
    "scanner": {
        "rel_volume_min": 2.0,
        "max_candidates": 20,
        "exclude_leveraged_etfs": True,
    },
    "schedule": {
        "timezone": "America/New_York",
        "scan_start": "09:30",
        "pick_time": "09:35",
        "entries_until": "11:00",
        "flatten_at": "15:55",
        "market_close": "16:00",
        "loop_minutes": 5,
        "trade_only_regular_hours": True,
    },
    "kill_switch": {"file": "output/STOP"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_config(tmp_path: Path, changes: dict | None = None, name: str = "g.yaml") -> Path:
    """Write a settings file built from BASE_CONFIG with a few values changed.

    changes is nested, for example {"money": {"max_position_pct": 150}}. A value
    of None deletes that setting, so a test can prove a missing value is caught.
    """
    data = copy.deepcopy(BASE_CONFIG)
    for section, settings in (changes or {}).items():
        if settings is None:
            data.pop(section, None)
            continue
        for key, value in settings.items():
            if value is None:
                data[section].pop(key, None)
            else:
                data[section][key] = value
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, default_flow_style=False, sort_keys=False))
    return path


def load_with(tmp_path: Path, changes: dict | None = None) -> Guardrails:
    """Load a settings file with a few values changed."""
    return load_guardrails(write_config(tmp_path, changes))


def et(day: int, hour: int, minute: int, month: int = 9, year: int = 2026) -> datetime:
    """A New York time. 2026-09-02 is a Wednesday."""
    return datetime(year, month, day, hour, minute, tzinfo=EASTERN)


def make_state(
    now: datetime,
    equity: float = 100000.0,
    day_start_equity: float | None = None,
    realized_pnl_today: float = 0.0,
    unrealized_pnl: float = 0.0,
    positions: dict[str, PositionInfo] | None = None,
    pending_order_notional: float = 0.0,
    kill_switch_present: bool = False,
    account_id: str = "DUT077572",
) -> AccountState:
    """An account snapshot with sensible defaults, so tests stay readable."""
    return AccountState(
        equity=equity,
        day_start_equity=equity if day_start_equity is None else day_start_equity,
        realized_pnl_today=realized_pnl_today,
        unrealized_pnl=unrealized_pnl,
        open_positions=positions or {},
        pending_order_notional=pending_order_notional,
        now=now,
        kill_switch_present=kill_switch_present,
        account_id=account_id,
    )


def position(symbol: str, qty: int, price: float) -> PositionInfo:
    return PositionInfo(
        symbol=symbol, qty=qty, avg_cost=price, market_value=qty * price
    )


def entry(
    symbol: str = "AAPL",
    qty: int = 100,
    limit_price: float | None = 50.0,
    **kwargs,
) -> OrderIntent:
    return OrderIntent(
        symbol=symbol, side="BUY", qty=qty, limit_price=limit_price, **kwargs
    )


@pytest.fixture()
def g(tmp_path: Path) -> Guardrails:
    """The proposed settings, loaded from a temporary copy."""
    return load_with(tmp_path)


# A quiet mid morning moment on a Wednesday, inside the entry window.
MID_MORNING = et(2, 9, 40)


# ---------------------------------------------------------------------------
# The settings file that actually ships
# ---------------------------------------------------------------------------


def test_shipped_config_loads_with_the_proposed_numbers():
    loaded = load_guardrails(SHIPPED_CONFIG)

    assert loaded.account.mode == "paper"
    assert loaded.account.account_id == "DUT077572"
    assert loaded.account.gateway_port_paper == 4002
    assert loaded.account.gateway_port_live == 4001
    assert loaded.account.gateway_port == 4002

    assert loaded.money.starting_equity == 100000
    assert loaded.money.max_position_pct == 10
    assert loaded.money.max_open_positions == 5
    assert loaded.money.max_daily_loss_pct == 2
    assert loaded.money.max_order_notional == 10000

    assert loaded.risk.stop_loss_pct == 1.5
    assert loaded.risk.use_opening_range_low_if_tighter is True

    assert loaded.universe.price_floor == 5
    assert loaded.universe.min_avg_volume == 1000000
    assert loaded.universe.allow_options is False
    assert loaded.universe.allow_shorts is False
    assert loaded.universe.allowed_sec_types == ("STK",)
    assert loaded.universe.allowed_currencies == ("USD",)
    assert loaded.universe.whitelist == ()
    assert loaded.universe.blacklist == ()

    assert loaded.scanner.rel_volume_min == 2.0
    assert loaded.scanner.max_candidates == 20
    assert loaded.scanner.exclude_leveraged_etfs is True

    assert loaded.schedule.timezone == "America/New_York"
    assert loaded.schedule.scan_start.strftime("%H:%M") == "09:30"
    assert loaded.schedule.pick_time.strftime("%H:%M") == "09:35"
    assert loaded.schedule.entries_until.strftime("%H:%M") == "11:00"
    assert loaded.schedule.flatten_at.strftime("%H:%M") == "15:55"
    assert loaded.schedule.market_close.strftime("%H:%M") == "16:00"
    assert loaded.schedule.loop_minutes == 5
    assert loaded.schedule.trade_only_regular_hours is True

    assert loaded.kill_switch.file == "output/STOP"
    assert loaded.source_path == SHIPPED_CONFIG


def test_shipped_and_example_configs_hold_the_same_values():
    """The example file is the shipped one with a different header comment."""
    shipped = load_guardrails(SHIPPED_CONFIG)
    example = load_guardrails(EXAMPLE_CONFIG)
    assert shipped.account == example.account
    assert shipped.money == example.money
    assert shipped.risk == example.risk
    assert shipped.universe == example.universe
    assert shipped.scanner == example.scanner
    assert shipped.schedule == example.schedule
    assert shipped.kill_switch == example.kill_switch


def test_base_config_in_this_test_file_matches_the_shipped_one(tmp_path: Path):
    """If someone edits the yaml, this test says the test fixtures went stale."""
    shipped = load_guardrails(SHIPPED_CONFIG)
    from_tests = load_with(tmp_path)
    assert from_tests.money == shipped.money
    assert from_tests.schedule == shipped.schedule
    assert from_tests.universe == shipped.universe


# ---------------------------------------------------------------------------
# Settings validation
# ---------------------------------------------------------------------------


def test_missing_file_says_where_to_copy_the_example(tmp_path: Path):
    with pytest.raises(GuardrailConfigError) as caught:
        load_guardrails(tmp_path / "nope.yaml")
    assert "no guardrail settings file" in str(caught.value)
    assert "guardrails.example.yaml" in str(caught.value)


def test_a_folder_is_not_a_settings_file(tmp_path: Path):
    with pytest.raises(GuardrailConfigError, match="is a folder"):
        load_guardrails(tmp_path)


def test_broken_yaml_is_reported_plainly(tmp_path: Path):
    path = tmp_path / "broken.yaml"
    path.write_text("account:\n  mode: paper\n   account_id: oops\n")
    with pytest.raises(GuardrailConfigError, match="not valid yaml"):
        load_guardrails(path)


def test_empty_file_is_rejected(tmp_path: Path):
    path = tmp_path / "empty.yaml"
    path.write_text("# nothing but a comment\n")
    with pytest.raises(GuardrailConfigError, match="is empty"):
        load_guardrails(path)


def test_a_list_at_the_top_is_rejected(tmp_path: Path):
    path = tmp_path / "list.yaml"
    path.write_text("- account\n- money\n")
    with pytest.raises(GuardrailConfigError, match="named sections"):
        load_guardrails(path)


def test_missing_section_is_named(tmp_path: Path):
    with pytest.raises(GuardrailConfigError, match="no money section"):
        load_with(tmp_path, {"money": None})


def test_section_that_is_not_settings_is_rejected(tmp_path: Path):
    path = write_config(tmp_path)
    data = yaml.safe_load(path.read_text())
    data["money"] = "ten percent"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(GuardrailConfigError, match="should hold a list of settings"):
        load_guardrails(path)


def test_missing_setting_is_named(tmp_path: Path):
    with pytest.raises(
        GuardrailConfigError, match="money.max_position_pct is missing"
    ):
        load_with(tmp_path, {"money": {"max_position_pct": None}})


@pytest.mark.parametrize("bad_percent", [0, -5, 100.5, 150, 1000])
def test_percentages_have_to_be_above_zero_and_at_most_one_hundred(
    tmp_path: Path, bad_percent
):
    with pytest.raises(GuardrailConfigError, match="percentage here has to be"):
        load_with(tmp_path, {"money": {"max_position_pct": bad_percent}})


def test_one_hundred_percent_is_allowed(tmp_path: Path):
    loaded = load_with(tmp_path, {"money": {"max_position_pct": 100}})
    assert loaded.money.max_position_pct == 100


def test_percentage_written_as_text_is_rejected(tmp_path: Path):
    with pytest.raises(GuardrailConfigError, match="should be a number"):
        load_with(tmp_path, {"risk": {"stop_loss_pct": "1.5%"}})


def test_daily_loss_percentage_is_checked_too(tmp_path: Path):
    with pytest.raises(GuardrailConfigError, match="money.max_daily_loss_pct"):
        load_with(tmp_path, {"money": {"max_daily_loss_pct": 0}})


@pytest.mark.parametrize("bad_count", [0, -1, 2.5, "five"])
def test_max_open_positions_has_to_be_a_whole_number_above_zero(
    tmp_path: Path, bad_count
):
    with pytest.raises(GuardrailConfigError, match="money.max_open_positions"):
        load_with(tmp_path, {"money": {"max_open_positions": bad_count}})


def test_negative_order_cap_is_rejected(tmp_path: Path):
    with pytest.raises(GuardrailConfigError, match="more than zero"):
        load_with(tmp_path, {"money": {"max_order_notional": -1}})


@pytest.mark.parametrize("bad_time", ["9:5", "25:00", "09:60", "half past nine", "0935", ""])
def test_times_have_to_be_hh_colon_mm(tmp_path: Path, bad_time):
    with pytest.raises(GuardrailConfigError, match="schedule.pick_time"):
        load_with(tmp_path, {"schedule": {"pick_time": bad_time}})


def test_a_time_without_quotation_marks_gets_a_helpful_message(tmp_path: Path):
    """Yaml turns 11:00 without quotes into the number 660, so say so."""
    with pytest.raises(GuardrailConfigError, match="quotation marks"):
        load_with(tmp_path, {"schedule": {"pick_time": 660}})


def test_times_have_to_run_forwards(tmp_path: Path):
    with pytest.raises(GuardrailConfigError, match="out of order"):
        load_with(tmp_path, {"schedule": {"entries_until": "09:00"}})


def test_flatten_has_to_be_before_the_close(tmp_path: Path):
    with pytest.raises(GuardrailConfigError, match="flatten_at"):
        load_with(tmp_path, {"schedule": {"flatten_at": "16:00"}})


def test_unknown_timezone_is_rejected(tmp_path: Path):
    with pytest.raises(GuardrailConfigError, match="not a timezone"):
        load_with(tmp_path, {"schedule": {"timezone": "America/New_Yark"}})


def test_true_or_false_settings_are_checked(tmp_path: Path):
    with pytest.raises(GuardrailConfigError, match="should be true or false"):
        load_with(tmp_path, {"universe": {"allow_shorts": "no"}})


def test_a_list_setting_written_as_text_is_rejected(tmp_path: Path):
    with pytest.raises(GuardrailConfigError, match="should be a list"):
        load_with(tmp_path, {"universe": {"whitelist": "AAPL"}})


def test_a_list_of_numbers_is_rejected(tmp_path: Path):
    with pytest.raises(GuardrailConfigError, match="not\na symbol|not a symbol"):
        load_with(tmp_path, {"universe": {"blacklist": [123]}})


def test_symbols_are_upper_cased_and_trimmed(tmp_path: Path):
    loaded = load_with(tmp_path, {"universe": {"whitelist": [" aapl ", "msft"]}})
    assert loaded.universe.whitelist == ("AAPL", "MSFT")


def test_empty_allowed_sec_types_is_rejected(tmp_path: Path):
    with pytest.raises(GuardrailConfigError, match="allowed_sec_types"):
        load_with(tmp_path, {"universe": {"allowed_sec_types": []}})


def test_empty_allowed_currencies_is_rejected(tmp_path: Path):
    with pytest.raises(GuardrailConfigError, match="allowed_currencies"):
        load_with(tmp_path, {"universe": {"allowed_currencies": []}})


def test_mode_has_to_be_paper_or_live(tmp_path: Path):
    with pytest.raises(GuardrailConfigError, match="either paper or live"):
        load_with(tmp_path, {"account": {"mode": "practice"}})


def test_paper_mode_needs_a_du_account_id(tmp_path: Path):
    with pytest.raises(GuardrailConfigError, match="start with DU"):
        load_with(tmp_path, {"account": {"account_id": "U1234567"}})


def test_missing_account_id_is_caught(tmp_path: Path):
    with pytest.raises(GuardrailConfigError, match="account.account_id is missing"):
        load_with(tmp_path, {"account": {"account_id": None}})


def test_loop_minutes_over_an_hour_is_rejected(tmp_path: Path):
    with pytest.raises(GuardrailConfigError, match="loop_minutes"):
        load_with(tmp_path, {"schedule": {"loop_minutes": 90}})


def test_kill_switch_file_is_required(tmp_path: Path):
    with pytest.raises(GuardrailConfigError, match="kill_switch.file is missing"):
        load_with(tmp_path, {"kill_switch": {"file": None}})


# ---------------------------------------------------------------------------
# Live mode refusal
# ---------------------------------------------------------------------------


def test_live_mode_will_not_load_without_the_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv(LIVE_MODE_ENV_VAR, raising=False)
    with pytest.raises(GuardrailConfigError) as caught:
        load_with(tmp_path, {"account": {"mode": "live", "account_id": "U1234567"}})
    message = str(caught.value)
    assert "live trading with real money" in message
    assert LIVE_MODE_ENV_VAR in message


@pytest.mark.parametrize("value", ["", "no", "true", "YES", "1", "yes please"])
def test_only_the_exact_word_yes_unlocks_live_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value
):
    monkeypatch.setenv(LIVE_MODE_ENV_VAR, value)
    with pytest.raises(GuardrailConfigError, match="live trading with real money"):
        load_with(tmp_path, {"account": {"mode": "live", "account_id": "U1234567"}})


def test_live_mode_loads_when_the_environment_variable_says_yes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(LIVE_MODE_ENV_VAR, "yes")
    loaded = load_with(
        tmp_path, {"account": {"mode": "live", "account_id": "U1234567"}}
    )
    assert loaded.account.mode == "live"
    assert loaded.account.is_paper is False
    assert loaded.account.gateway_port == 4001


def test_paper_mode_ignores_the_live_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(LIVE_MODE_ENV_VAR, "yes")
    assert load_with(tmp_path).account.mode == "paper"


# ---------------------------------------------------------------------------
# The clock
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "moment, expected",
    [
        (et(2, 9, 34), False),   # one minute before Claude picks
        (et(2, 9, 35), True),    # the moment entries open
        (et(2, 10, 59), True),   # one minute before the window shuts
        (et(2, 11, 0), False),   # the moment it shuts
        (et(2, 11, 1), False),
        (et(2, 9, 0), False),    # before the market opens
        (et(2, 15, 56), False),  # after flatten time
        (et(5, 10, 0), False),   # Saturday
        (et(6, 10, 0), False),   # Sunday
    ],
)
def test_entry_window_boundaries(g: Guardrails, moment, expected):
    assert entries_allowed_now(g, moment) is expected


@pytest.mark.parametrize(
    "moment, expected",
    [
        (et(2, 9, 29), False),
        (et(2, 9, 30), True),
        (et(2, 15, 59), True),
        (et(2, 16, 0), False),
        (et(2, 16, 1), False),
        (et(2, 4, 0), False),
        (et(5, 10, 0), False),  # Saturday
    ],
)
def test_regular_hours_boundaries(g: Guardrails, moment, expected):
    assert is_regular_hours(g, moment) is expected


@pytest.mark.parametrize(
    "moment, expected",
    [
        (et(2, 15, 54), False),
        (et(2, 15, 55), True),
        (et(2, 15, 59), True),
        (et(2, 16, 0), False),  # too late to sell anything
        (et(2, 9, 40), False),
        (et(5, 15, 56), False),  # Saturday
    ],
)
def test_flatten_time_boundaries(g: Guardrails, moment, expected):
    assert must_flatten_now(g, moment) is expected


def test_a_time_in_another_timezone_is_converted_not_rejected(g: Guardrails):
    """13:35 UTC is 09:35 in New York in September, so entries are open."""
    utc_moment = datetime(2026, 9, 2, 13, 35, tzinfo=timezone.utc)
    assert entries_allowed_now(g, utc_moment) is True
    assert is_regular_hours(g, utc_moment) is True


def test_a_time_with_no_timezone_is_refused_not_guessed(g: Guardrails):
    naive = datetime(2026, 9, 2, 9, 40)
    with pytest.raises(GuardrailUsageError, match="carries no timezone"):
        entries_allowed_now(g, naive)
    with pytest.raises(GuardrailUsageError, match="carries no timezone"):
        is_regular_hours(g, naive)
    with pytest.raises(GuardrailUsageError, match="carries no timezone"):
        must_flatten_now(g, naive)
    with pytest.raises(GuardrailUsageError, match="carries no timezone"):
        make_state(naive)


def test_a_date_instead_of_a_time_is_refused(g: Guardrails):
    with pytest.raises(GuardrailUsageError, match="has to be a date and time"):
        entries_allowed_now(g, "2026-09-02 09:40")


# ---------------------------------------------------------------------------
# The order intent itself
# ---------------------------------------------------------------------------


def test_order_intent_normalises_its_fields():
    intent = OrderIntent(
        symbol=" aapl ", side="buy", qty=10, limit_price=5, sec_type="stk",
        currency="usd", purpose="ENTRY",
    )
    assert intent.symbol == "AAPL"
    assert intent.side == "BUY"
    assert intent.sec_type == "STK"
    assert intent.currency == "USD"
    assert intent.purpose == "entry"
    assert intent.notional == 50.0
    assert intent.is_closing is False


def test_order_notional_is_unknown_without_a_limit_price():
    assert OrderIntent(symbol="AAPL", side="BUY", qty=10).notional is None


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"side": "sell short"}, "BUY or SELL"),
        ({"qty": 0}, "more than zero"),
        ({"qty": -5}, "more than zero"),
        ({"qty": 10.5}, "whole number of shares"),
        ({"purpose": "gamble"}, "purpose has to be"),
        ({"limit_price": 0}, "more than zero"),
        ({"symbol": "  "}, "has to be a symbol"),
    ],
)
def test_a_nonsense_order_is_refused_at_the_door(kwargs, message):
    fields = {"symbol": "AAPL", "side": "BUY", "qty": 10, "limit_price": 50.0}
    fields.update(kwargs)
    with pytest.raises(GuardrailUsageError, match=message):
        OrderIntent(**fields)


# ---------------------------------------------------------------------------
# check_order: the happy path
# ---------------------------------------------------------------------------


def test_a_normal_entry_mid_morning_is_allowed(g: Guardrails):
    decision = check_order(g, make_state(MID_MORNING), entry())
    assert decision.allowed is True
    assert decision.reasons == []
    assert decision.rule_ids == []
    assert decision.daily_halt is False
    assert decision.summary == "allowed"


def test_every_reason_has_a_matching_rule_id(g: Guardrails):
    state = make_state(et(5, 20, 0), account_id="U9999999", kill_switch_present=True)
    decision = check_order(
        g, state, entry(symbol="TSLA", qty=1000, limit_price=400.0, sec_type="OPT")
    )
    assert decision.allowed is False
    assert len(decision.reasons) == len(decision.rule_ids)
    assert decision.reasons, "a blocked order has to say why"
    assert decision.summary.startswith("blocked:")


def test_all_broken_rules_are_collected_not_just_the_first(g: Guardrails):
    """A Saturday order, wrong account, options, wrong currency, far too big."""
    state = make_state(et(5, 20, 0), account_id="U9999999")
    decision = check_order(
        g,
        state,
        entry(qty=1000, limit_price=400.0, sec_type="OPT", currency="EUR"),
    )
    assert decision.allowed is False
    assert {
        "paper_only",
        "wrong_account",
        "sec_type",
        "currency",
        "entry_window",
        "outside_market_hours",
        "max_order_notional",
        "max_position_pct",
    } <= set(decision.rule_ids)


# ---------------------------------------------------------------------------
# check_order: which account
# ---------------------------------------------------------------------------


def test_a_live_looking_account_id_is_blocked_in_paper_mode(g: Guardrails):
    state = make_state(MID_MORNING, account_id="U1234567")
    decision = check_order(g, state, entry())
    assert decision.allowed is False
    assert "paper_only" in decision.rule_ids
    assert "wrong_account" in decision.rule_ids
    assert "does not start with DU" in " ".join(decision.reasons)


def test_a_different_paper_account_is_still_blocked(g: Guardrails):
    state = make_state(MID_MORNING, account_id="DU9999999")
    decision = check_order(g, state, entry())
    assert decision.allowed is False
    assert decision.rule_ids == ["wrong_account"]


def test_the_right_account_passes(g: Guardrails):
    decision = check_order(g, make_state(MID_MORNING), entry())
    assert "wrong_account" not in decision.rule_ids
    assert "paper_only" not in decision.rule_ids


# ---------------------------------------------------------------------------
# check_order: the kill switch
# ---------------------------------------------------------------------------


def test_the_kill_switch_blocks_a_new_entry(g: Guardrails):
    state = make_state(MID_MORNING, kill_switch_present=True)
    decision = check_order(g, state, entry())
    assert decision.allowed is False
    assert "kill_switch" in decision.rule_ids
    assert "output/STOP" in " ".join(decision.reasons)


@pytest.mark.parametrize("purpose", ["exit", "flatten"])
def test_the_kill_switch_still_lets_us_get_out(g: Guardrails, purpose):
    state = make_state(
        MID_MORNING,
        positions={"AAPL": position("AAPL", 100, 50.0)},
        kill_switch_present=True,
    )
    intent = OrderIntent(
        symbol="AAPL", side="SELL", qty=100, limit_price=50.0, purpose=purpose
    )
    decision = check_order(g, state, intent)
    assert decision.allowed is True, decision.reasons


def test_the_kill_switch_also_stops_new_stop_orders(g: Guardrails):
    """Spelled out because it is a deliberate choice, not an oversight.

    With the stop file in place the agent closes positions itself rather than
    leaving fresh stop orders sitting at the broker.
    """
    state = make_state(
        MID_MORNING,
        positions={"AAPL": position("AAPL", 100, 50.0)},
        kill_switch_present=True,
    )
    intent = OrderIntent(
        symbol="AAPL", side="SELL", qty=100, limit_price=49.0, purpose="stop"
    )
    decision = check_order(g, state, intent)
    assert decision.allowed is False
    assert "kill_switch" in decision.rule_ids


# ---------------------------------------------------------------------------
# check_order: what may be traded
# ---------------------------------------------------------------------------


def test_options_are_blocked(g: Guardrails):
    decision = check_order(g, make_state(MID_MORNING), entry(sec_type="OPT"))
    assert decision.allowed is False
    assert "sec_type" in decision.rule_ids
    assert "stock option" in " ".join(decision.reasons)


def test_shares_are_the_allowed_kind(g: Guardrails):
    decision = check_order(g, make_state(MID_MORNING), entry(sec_type="STK"))
    assert "sec_type" not in decision.rule_ids


def test_options_stay_blocked_even_if_someone_adds_opt_to_the_list(tmp_path: Path):
    """Two locks on the same door: the list, and the allow_options switch."""
    guardrails = load_with(
        tmp_path, {"universe": {"allowed_sec_types": ["STK", "OPT"]}}
    )
    decision = check_order(guardrails, make_state(MID_MORNING), entry(sec_type="OPT"))
    assert decision.allowed is False
    assert "sec_type" in decision.rule_ids
    assert "allow_options" in " ".join(decision.reasons)


def test_a_foreign_currency_is_blocked(g: Guardrails):
    decision = check_order(g, make_state(MID_MORNING), entry(currency="EUR"))
    assert decision.allowed is False
    assert "currency" in decision.rule_ids


def test_dollars_are_allowed(g: Guardrails):
    decision = check_order(g, make_state(MID_MORNING), entry(currency="USD"))
    assert "currency" not in decision.rule_ids


def test_a_blacklisted_symbol_is_blocked(tmp_path: Path):
    guardrails = load_with(tmp_path, {"universe": {"blacklist": ["TSLA", "GME"]}})
    blocked = check_order(guardrails, make_state(MID_MORNING), entry(symbol="TSLA"))
    assert blocked.allowed is False
    assert "blacklist" in blocked.rule_ids

    allowed = check_order(guardrails, make_state(MID_MORNING), entry(symbol="AAPL"))
    assert allowed.allowed is True, allowed.reasons


def test_a_blacklist_beats_a_whitelist(tmp_path: Path):
    guardrails = load_with(
        tmp_path, {"universe": {"whitelist": ["TSLA"], "blacklist": ["TSLA"]}}
    )
    decision = check_order(guardrails, make_state(MID_MORNING), entry(symbol="TSLA"))
    assert decision.allowed is False
    assert "blacklist" in decision.rule_ids


def test_a_whitelist_shuts_out_everything_else(tmp_path: Path):
    guardrails = load_with(tmp_path, {"universe": {"whitelist": ["AAPL", "MSFT"]}})
    blocked = check_order(guardrails, make_state(MID_MORNING), entry(symbol="NVDA"))
    assert blocked.allowed is False
    assert "whitelist" in blocked.rule_ids

    allowed = check_order(guardrails, make_state(MID_MORNING), entry(symbol="MSFT"))
    assert allowed.allowed is True, allowed.reasons


def test_an_empty_whitelist_means_no_restriction(g: Guardrails):
    assert g.universe.whitelist == ()
    decision = check_order(g, make_state(MID_MORNING), entry(symbol="ANYTHING"))
    assert "whitelist" not in decision.rule_ids


# ---------------------------------------------------------------------------
# check_order: no short selling
# ---------------------------------------------------------------------------


def test_selling_what_we_do_not_own_is_blocked(g: Guardrails):
    intent = OrderIntent(
        symbol="AAPL", side="SELL", qty=100, limit_price=50.0, purpose="exit"
    )
    decision = check_order(g, make_state(MID_MORNING), intent)
    assert decision.allowed is False
    assert "no_shorts" in decision.rule_ids
    assert "short sale" in " ".join(decision.reasons)


def test_selling_exactly_what_we_hold_is_allowed(g: Guardrails):
    state = make_state(MID_MORNING, positions={"AAPL": position("AAPL", 100, 50.0)})
    intent = OrderIntent(
        symbol="AAPL", side="SELL", qty=100, limit_price=50.0, purpose="exit"
    )
    decision = check_order(g, state, intent)
    assert decision.allowed is True, decision.reasons


def test_selling_part_of_what_we_hold_is_allowed(g: Guardrails):
    state = make_state(MID_MORNING, positions={"AAPL": position("AAPL", 100, 50.0)})
    intent = OrderIntent(
        symbol="AAPL", side="SELL", qty=40, limit_price=50.0, purpose="exit"
    )
    assert check_order(g, state, intent).allowed is True


def test_selling_more_than_we_hold_is_blocked(g: Guardrails):
    state = make_state(MID_MORNING, positions={"AAPL": position("AAPL", 100, 50.0)})
    intent = OrderIntent(
        symbol="AAPL", side="SELL", qty=150, limit_price=50.0, purpose="exit"
    )
    decision = check_order(g, state, intent)
    assert decision.allowed is False
    assert "no_shorts" in decision.rule_ids
    assert "50 of them would be a short sale" in " ".join(decision.reasons)


def test_shorting_is_allowed_when_the_setting_says_so(tmp_path: Path):
    guardrails = load_with(tmp_path, {"universe": {"allow_shorts": True}})
    intent = OrderIntent(
        symbol="AAPL", side="SELL", qty=100, limit_price=50.0, purpose="entry"
    )
    decision = check_order(guardrails, make_state(MID_MORNING), intent)
    assert decision.allowed is True, decision.reasons


# ---------------------------------------------------------------------------
# check_order: the clock
# ---------------------------------------------------------------------------


def test_an_entry_one_minute_early_is_blocked(g: Guardrails):
    decision = check_order(g, make_state(et(2, 9, 34)), entry())
    assert decision.allowed is False
    assert "entry_window" in decision.rule_ids


def test_an_entry_the_moment_the_window_opens_is_allowed(g: Guardrails):
    decision = check_order(g, make_state(et(2, 9, 35)), entry())
    assert decision.allowed is True, decision.reasons


def test_an_entry_at_one_minute_to_eleven_is_allowed(g: Guardrails):
    assert check_order(g, make_state(et(2, 10, 59)), entry()).allowed is True


def test_an_entry_at_eleven_is_blocked(g: Guardrails):
    decision = check_order(g, make_state(et(2, 11, 0)), entry())
    assert decision.allowed is False
    assert "entry_window" in decision.rule_ids


def test_an_entry_on_a_saturday_is_blocked(g: Guardrails):
    decision = check_order(g, make_state(et(5, 10, 0)), entry())
    assert decision.allowed is False
    assert "entry_window" in decision.rule_ids
    assert "outside_market_hours" in decision.rule_ids


def test_nothing_but_an_exit_runs_before_the_open(g: Guardrails):
    before_open = et(2, 8, 0)
    blocked = check_order(g, make_state(before_open), entry())
    assert blocked.allowed is False
    assert "outside_market_hours" in blocked.rule_ids

    state = make_state(before_open, positions={"AAPL": position("AAPL", 100, 50.0)})
    exit_intent = OrderIntent(
        symbol="AAPL", side="SELL", qty=100, limit_price=50.0, purpose="exit"
    )
    assert check_order(g, state, exit_intent).allowed is True


def test_out_of_hours_is_allowed_when_the_setting_is_switched_off(tmp_path: Path):
    guardrails = load_with(
        tmp_path, {"schedule": {"trade_only_regular_hours": False}}
    )
    # Still blocked by the entry window, but not by the market hours rule.
    decision = check_order(guardrails, make_state(et(2, 8, 0)), entry())
    assert "outside_market_hours" not in decision.rule_ids
    assert "entry_window" in decision.rule_ids


def test_one_minute_before_flatten_time_an_exit_is_still_normal(g: Guardrails):
    state = make_state(et(2, 15, 54), positions={"AAPL": position("AAPL", 100, 50.0)})
    intent = OrderIntent(
        symbol="AAPL", side="SELL", qty=100, limit_price=50.0, purpose="exit"
    )
    decision = check_order(g, state, intent)
    assert decision.allowed is True
    assert must_flatten_now(g, state.now) is False


def test_at_flatten_time_only_closing_orders_go_through(g: Guardrails):
    at_flatten = et(2, 15, 55)
    state = make_state(at_flatten, positions={"AAPL": position("AAPL", 100, 50.0)})

    blocked = check_order(g, state, entry())
    assert blocked.allowed is False
    assert "flatten_time" in blocked.rule_ids
    assert "entry_window" in blocked.rule_ids

    for purpose in ("exit", "stop", "flatten"):
        intent = OrderIntent(
            symbol="AAPL", side="SELL", qty=100, limit_price=50.0, purpose=purpose
        )
        decision = check_order(g, state, intent)
        assert decision.allowed is True, (purpose, decision.reasons)


def test_a_flatten_order_after_the_close_is_still_permitted_by_the_rules(g: Guardrails):
    """The market hours rule never blocks a closing order, whatever the time."""
    state = make_state(et(2, 16, 30), positions={"AAPL": position("AAPL", 100, 50.0)})
    intent = OrderIntent(
        symbol="AAPL", side="SELL", qty=100, limit_price=50.0, purpose="flatten"
    )
    assert check_order(g, state, intent).allowed is True


# ---------------------------------------------------------------------------
# check_order: the daily loss cap
# ---------------------------------------------------------------------------


def test_daily_loss_exactly_at_the_cap_halts_new_entries(g: Guardrails):
    """Two percent of 100,000 is 2,000. Landing exactly on it counts as hit."""
    state = make_state(
        MID_MORNING,
        equity=98000.0,
        day_start_equity=100000.0,
        realized_pnl_today=-1500.0,
        unrealized_pnl=-500.0,
    )
    assert daily_loss_hit(g, state) is True

    decision = check_order(g, state, entry())
    assert decision.allowed is False
    assert "daily_loss_cap" in decision.rule_ids
    assert decision.daily_halt is True


def test_a_penny_short_of_the_cap_still_trades(g: Guardrails):
    state = make_state(
        MID_MORNING,
        equity=98000.01,
        day_start_equity=100000.0,
        realized_pnl_today=-1500.0,
        unrealized_pnl=-499.99,
    )
    assert daily_loss_hit(g, state) is False
    decision = check_order(g, state, entry())
    assert decision.allowed is True, decision.reasons
    assert decision.daily_halt is False


def test_past_the_cap_exits_are_still_allowed_and_the_halt_flag_is_set(g: Guardrails):
    state = make_state(
        MID_MORNING,
        equity=95000.0,
        day_start_equity=100000.0,
        realized_pnl_today=-3000.0,
        unrealized_pnl=-2000.0,
        positions={"AAPL": position("AAPL", 100, 50.0)},
    )
    intent = OrderIntent(
        symbol="AAPL", side="SELL", qty=100, limit_price=50.0, purpose="exit"
    )
    decision = check_order(g, state, intent)
    assert decision.allowed is True, decision.reasons
    assert decision.daily_halt is True


def test_a_winning_day_never_trips_the_cap(g: Guardrails):
    state = make_state(
        MID_MORNING, realized_pnl_today=1200.0, unrealized_pnl=300.0
    )
    assert daily_loss_hit(g, state) is False
    assert check_order(g, state, entry()).daily_halt is False


def test_open_losses_count_towards_the_cap_on_their_own(g: Guardrails):
    state = make_state(
        MID_MORNING, day_start_equity=100000.0, unrealized_pnl=-2500.0
    )
    assert daily_loss_hit(g, state) is True


def test_a_zero_opening_balance_halts_rather_than_dividing_by_nothing(g: Guardrails):
    state = make_state(MID_MORNING, equity=0.0, day_start_equity=0.0)
    assert daily_loss_hit(g, state) is True


# ---------------------------------------------------------------------------
# check_order: position size
# ---------------------------------------------------------------------------


def test_an_entry_at_exactly_ten_percent_of_the_account_is_allowed(g: Guardrails):
    """200 shares at 50 dollars is 10,000, which is exactly both caps."""
    decision = check_order(g, make_state(MID_MORNING), entry(qty=200, limit_price=50.0))
    assert decision.allowed is True, decision.reasons


def test_a_position_over_ten_percent_of_the_account_is_blocked(g: Guardrails):
    decision = check_order(g, make_state(MID_MORNING), entry(qty=201, limit_price=50.0))
    assert decision.allowed is False
    assert "max_position_pct" in decision.rule_ids


def test_a_part_filled_position_plus_pending_orders_counts_towards_the_cap(
    g: Guardrails,
):
    """4,000 dollars held, 3,000 on order, so only 3,000 of room is left."""
    state = make_state(
        MID_MORNING,
        positions={"AAPL": position("AAPL", 80, 50.0)},
        pending_order_notional=3000.0,
    )

    over = check_order(g, state, entry(symbol="AAPL", qty=80, limit_price=50.0))
    assert over.allowed is False
    assert "max_position_pct" in over.rule_ids
    assert "$11,000.00" in " ".join(over.reasons)

    just_right = check_order(g, state, entry(symbol="AAPL", qty=60, limit_price=50.0))
    assert just_right.allowed is True, just_right.reasons


def test_a_short_position_uses_up_room_rather_than_creating_it(tmp_path: Path):
    """A short shows up at the broker as a negative value, and money is still at risk.

    Subtracting a negative number would quietly hand out extra room, which is
    the opposite of what a limit is for.
    """
    guardrails = load_with(tmp_path, {"universe": {"allow_shorts": True}})
    short = PositionInfo(symbol="AAPL", qty=-160, avg_cost=50.0, market_value=-8000.0)
    state = make_state(MID_MORNING, positions={"AAPL": short})

    assert state.held_market_value("AAPL") == -8000.0
    assert state.held_exposure("AAPL") == 8000.0
    # 8,000 dollars of the 10,000 limit is used up, so 2,000 is left.
    assert max_shares_for(guardrails, state, "AAPL", 50.0) == 40

    intent = OrderIntent(
        symbol="AAPL", side="SELL", qty=100, limit_price=50.0, purpose="entry"
    )
    decision = check_order(guardrails, state, intent)
    assert decision.allowed is False
    assert "max_position_pct" in decision.rule_ids


def test_a_single_order_cannot_be_worth_more_than_the_order_cap(tmp_path: Path):
    """A big account, so only the order cap can be the thing that blocks it."""
    guardrails = load_with(tmp_path, {"money": {"max_open_positions": 20}})
    state = make_state(MID_MORNING, equity=1000000.0)

    blocked = check_order(guardrails, state, entry(qty=300, limit_price=40.0))
    assert blocked.allowed is False
    assert blocked.rule_ids == ["max_order_notional"]

    allowed = check_order(guardrails, state, entry(qty=250, limit_price=40.0))
    assert allowed.allowed is True, allowed.reasons


def test_an_entry_with_no_limit_price_cannot_be_checked_so_it_is_blocked(g: Guardrails):
    decision = check_order(g, make_state(MID_MORNING), entry(limit_price=None))
    assert decision.allowed is False
    assert "max_order_notional" in decision.rule_ids
    assert "no limit price" in " ".join(decision.reasons)


def test_an_exit_needs_no_limit_price_and_is_never_blocked_for_being_big(g: Guardrails):
    """Blocking a way out is the worst failure available, so size never does it."""
    state = make_state(
        MID_MORNING, positions={"AAPL": position("AAPL", 5000, 200.0)}
    )
    intent = OrderIntent(symbol="AAPL", side="SELL", qty=5000, purpose="flatten")
    decision = check_order(g, state, intent)
    assert decision.allowed is True, decision.reasons


def test_a_sixth_position_is_blocked(g: Guardrails):
    held = {
        symbol: position(symbol, 10, 50.0)
        for symbol in ("AAPL", "MSFT", "NVDA", "AMD", "TSLA")
    }
    state = make_state(MID_MORNING, positions=held)
    decision = check_order(g, state, entry(symbol="META", qty=10, limit_price=50.0))
    assert decision.allowed is False
    assert "max_open_positions" in decision.rule_ids
    assert "would make 6" in " ".join(decision.reasons)


def test_adding_to_a_position_we_already_hold_does_not_count_twice(g: Guardrails):
    held = {
        symbol: position(symbol, 10, 50.0)
        for symbol in ("AAPL", "MSFT", "NVDA", "AMD", "TSLA")
    }
    state = make_state(MID_MORNING, positions=held)
    decision = check_order(g, state, entry(symbol="TSLA", qty=10, limit_price=50.0))
    assert decision.allowed is True, decision.reasons


def test_a_closed_out_position_leaves_room_for_a_new_name(g: Guardrails):
    """A holding of zero shares is a leftover row, not an open position."""
    held = {
        symbol: position(symbol, 10, 50.0)
        for symbol in ("AAPL", "MSFT", "NVDA", "AMD")
    }
    held["TSLA"] = position("TSLA", 0, 0.0)
    state = make_state(MID_MORNING, positions=held)
    assert state.open_position_count() == 4
    decision = check_order(g, state, entry(symbol="META", qty=10, limit_price=50.0))
    assert decision.allowed is True, decision.reasons


def test_size_limits_do_not_apply_to_stops(g: Guardrails):
    state = make_state(
        MID_MORNING, positions={"AAPL": position("AAPL", 400, 50.0)}
    )
    intent = OrderIntent(
        symbol="AAPL", side="SELL", qty=400, limit_price=49.0, purpose="stop"
    )
    assert check_order(g, state, intent).allowed is True


# ---------------------------------------------------------------------------
# Where the stop loss goes
# ---------------------------------------------------------------------------


def test_stop_is_one_and_a_half_percent_below_entry_by_default(g: Guardrails):
    assert stop_price_for(g, 100.0, None) == 98.50


def test_a_tighter_opening_range_low_wins(g: Guardrails):
    assert stop_price_for(g, 100.0, 99.0) == 99.00


def test_a_wider_opening_range_low_loses(g: Guardrails):
    assert stop_price_for(g, 100.0, 95.0) == 98.50


def test_a_tie_between_the_two_gives_the_same_answer_either_way(g: Guardrails):
    assert stop_price_for(g, 100.0, 98.50) == 98.50


def test_an_opening_range_low_at_the_entry_price_is_ignored(g: Guardrails):
    """A stop at the entry price would be hit instantly, so use the percentage."""
    assert stop_price_for(g, 100.0, 100.0) == 98.50


def test_an_opening_range_low_above_the_entry_price_is_ignored(g: Guardrails):
    assert stop_price_for(g, 100.0, 101.0) == 98.50


def test_the_stop_is_never_above_the_entry_price(g: Guardrails):
    for entry_price in (0.05, 1.0, 7.5, 33.33, 250.0, 1234.56):
        assert stop_price_for(g, entry_price, entry_price * 1.2) < entry_price
        assert stop_price_for(g, entry_price, None) < entry_price


def test_the_stop_is_rounded_to_whole_cents(g: Guardrails):
    assert stop_price_for(g, 33.33, None) == 32.83
    assert stop_price_for(g, 7.77, None) == 7.65


def test_the_opening_range_low_can_be_switched_off(tmp_path: Path):
    guardrails = load_with(
        tmp_path, {"risk": {"use_opening_range_low_if_tighter": False}}
    )
    assert stop_price_for(guardrails, 100.0, 99.0) == 98.50


def test_a_wider_percentage_setting_moves_the_stop(tmp_path: Path):
    guardrails = load_with(tmp_path, {"risk": {"stop_loss_pct": 3}})
    assert stop_price_for(guardrails, 100.0, None) == 97.00
    assert stop_price_for(guardrails, 100.0, 99.0) == 99.00


@pytest.mark.parametrize("bad_price", [0, -10, "cheap"])
def test_a_nonsense_entry_price_is_refused(g: Guardrails, bad_price):
    with pytest.raises(GuardrailUsageError):
        stop_price_for(g, bad_price, None)


# ---------------------------------------------------------------------------
# How many shares we may buy
# ---------------------------------------------------------------------------


def test_share_count_is_whole_shares_only(g: Guardrails):
    """10,000 dollars of room at 33.33 buys 300 shares, not 300.03."""
    state = make_state(MID_MORNING)
    assert max_shares_for(g, state, "AAPL", 33.33) == 300


def test_share_count_lands_exactly_on_the_cap_when_it_divides_evenly(g: Guardrails):
    state = make_state(MID_MORNING)
    assert max_shares_for(g, state, "AAPL", 50.0) == 200


def test_share_count_always_rounds_down_never_to_the_nearest(g: Guardrails):
    """10,000 dollars of room at 6 dollars is 1,666.67 shares.

    Rounding to the nearest whole share would give 1,667, and 1,667 shares at 6
    dollars is 10,002, which is over the limit. So it has to round down.
    """
    state = make_state(MID_MORNING)
    assert max_shares_for(g, state, "AAPL", 6.0) == 1666
    assert 1666 * 6.0 <= g.money.max_order_notional
    assert 1667 * 6.0 > g.money.max_order_notional


def test_share_count_leaves_room_for_what_we_already_hold_and_have_on_order(
    g: Guardrails,
):
    state = make_state(
        MID_MORNING,
        positions={"AAPL": position("AAPL", 80, 50.0)},
        pending_order_notional=3000.0,
    )
    # 10,000 cap, less 4,000 held, less 3,000 on order, is 3,000 of room.
    assert max_shares_for(g, state, "AAPL", 50.0) == 60


def test_share_count_is_zero_when_the_position_is_already_full(g: Guardrails):
    state = make_state(MID_MORNING, positions={"AAPL": position("AAPL", 200, 50.0)})
    assert max_shares_for(g, state, "AAPL", 50.0) == 0


def test_share_count_is_capped_by_the_cash_we_have_left(g: Guardrails):
    state = make_state(
        MID_MORNING,
        positions={
            "MSFT": position("MSFT", 500, 100.0),
            "NVDA": position("NVDA", 450, 100.0),
        },
    )
    # 100,000 equity with 95,000 in positions leaves 5,000 of cash.
    assert available_cash(state) == 5000.0
    assert max_shares_for(g, state, "AAPL", 50.0) == 100


def test_share_count_is_capped_by_the_single_order_limit_on_a_big_account(g: Guardrails):
    state = make_state(MID_MORNING, equity=1000000.0)
    # Ten percent of a million is 100,000, but no order may top 10,000.
    assert max_shares_for(g, state, "AAPL", 50.0) == 200


def test_a_share_count_the_guardrails_gave_us_always_passes_the_check(g: Guardrails):
    """The sizing helper and the order check have to agree, or the loop stalls."""
    state = make_state(
        MID_MORNING,
        positions={"AAPL": position("AAPL", 30, 50.0)},
        pending_order_notional=1000.0,
    )
    for price in (7.5, 16.0, 33.33, 50.0, 187.42):
        qty = max_shares_for(g, state, "AAPL", price)
        assert qty > 0
        decision = check_order(
            g, state, entry(symbol="AAPL", qty=qty, limit_price=price)
        )
        assert decision.allowed is True, (price, qty, decision.reasons)

        one_too_many = check_order(
            g, state, entry(symbol="AAPL", qty=qty + 1, limit_price=price)
        )
        assert one_too_many.allowed is False, (price, qty)


@pytest.mark.parametrize("bad_price", [0, -1, "free"])
def test_a_nonsense_price_is_refused_when_sizing(g: Guardrails, bad_price):
    with pytest.raises(GuardrailUsageError):
        max_shares_for(g, make_state(MID_MORNING), "AAPL", bad_price)


# ---------------------------------------------------------------------------
# Every rule id has to be able to fire
# ---------------------------------------------------------------------------


def test_every_documented_rule_id_can_block_an_order(tmp_path: Path):
    """One scenario per rule id, so no rule can quietly stop working."""
    default = load_with(tmp_path)
    held_aapl = {"AAPL": position("AAPL", 100, 50.0)}
    five_held = {
        symbol: position(symbol, 10, 50.0)
        for symbol in ("AAPL", "MSFT", "NVDA", "AMD", "TSLA")
    }

    scenarios: dict[str, tuple[Guardrails, AccountState, OrderIntent]] = {
        "paper_only": (
            default,
            make_state(MID_MORNING, account_id="U1234567"),
            entry(),
        ),
        "wrong_account": (
            default,
            make_state(MID_MORNING, account_id="DU0000000"),
            entry(),
        ),
        "kill_switch": (
            default,
            make_state(MID_MORNING, kill_switch_present=True),
            entry(),
        ),
        "sec_type": (default, make_state(MID_MORNING), entry(sec_type="OPT")),
        "currency": (default, make_state(MID_MORNING), entry(currency="GBP")),
        "blacklist": (
            load_with(tmp_path, {"universe": {"blacklist": ["AAPL"]}}),
            make_state(MID_MORNING),
            entry(symbol="AAPL"),
        ),
        "whitelist": (
            load_with(tmp_path, {"universe": {"whitelist": ["MSFT"]}}),
            make_state(MID_MORNING),
            entry(symbol="AAPL"),
        ),
        "no_shorts": (
            default,
            make_state(MID_MORNING),
            OrderIntent(symbol="AAPL", side="SELL", qty=10, limit_price=50.0,
                        purpose="exit"),
        ),
        "entry_window": (default, make_state(et(2, 14, 0)), entry()),
        "outside_market_hours": (default, make_state(et(2, 7, 0)), entry()),
        "flatten_time": (default, make_state(et(2, 15, 56)), entry()),
        "daily_loss_cap": (
            default,
            make_state(
                MID_MORNING, day_start_equity=100000.0, realized_pnl_today=-2500.0
            ),
            entry(),
        ),
        "max_order_notional": (
            default,
            make_state(MID_MORNING, equity=1000000.0),
            entry(qty=1000, limit_price=50.0),
        ),
        "max_position_pct": (
            default,
            make_state(MID_MORNING, positions=held_aapl),
            entry(symbol="AAPL", qty=150, limit_price=50.0),
        ),
        "max_open_positions": (
            default,
            make_state(MID_MORNING, positions=five_held),
            entry(symbol="META", qty=10, limit_price=50.0),
        ),
    }

    assert set(scenarios) == ALL_RULE_IDS, "a rule id has no scenario"

    for rule_id, (guardrails, state, intent) in scenarios.items():
        decision = check_order(guardrails, state, intent)
        assert decision.allowed is False, rule_id
        assert rule_id in decision.rule_ids, (rule_id, decision.rule_ids)
        # Plain language check: every reason is a real sentence, not a code.
        for reason in decision.reasons:
            assert reason.endswith(".") and len(reason.split()) >= 6, reason


def test_a_decision_can_be_built_by_hand_for_other_parts_of_the_agent():
    decision = Decision(allowed=True)
    decision.add("kill_switch", "The stop file exists, so nothing new was opened.")
    assert decision.allowed is False
    assert decision.rule_ids == ["kill_switch"]
    assert decision.summary.startswith("blocked:")

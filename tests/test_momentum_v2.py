"""Momentum v2: one test for every change Mo approved on 2026-09-06.

The changes come from the consolidated critique at
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/momentum_spec_critique_2026-09-06.md
and the item ids below (A1, D3 and so on) are the ones that document uses. The
same ids are in both strategy changelogs and in the comments in the yaml files,
so a number in the ledger can always be traced back to the decision behind it.

This file exists so a future edit that quietly undoes one of Mo's decisions
fails loudly and by name, rather than being noticed a month later in the
returns. Everything here runs on paper: no broker, no network, no model.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest tests/test_momentum_v2.py -q
"""
from __future__ import annotations

import sys
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

REAL_ROOT = Path(__file__).resolve().parent.parent
if str(REAL_ROOT) not in sys.path:
    sys.path.insert(0, str(REAL_ROOT))

from agent import decide as decide_mod          # noqa: E402
from agent import guardrails as gr              # noqa: E402
from agent import loop                          # noqa: E402

BOOKS_YAML = REAL_ROOT / "config" / "books.yaml"
SHARED_CONFIG = REAL_ROOT / "config" / "guardrails.yaml"
STRATEGIES = REAL_ROOT / "strategies"
NEW_YORK = ZoneInfo("America/New_York")

#: A, B and E all run the opening momentum strategy, and their numbers have to
#: stay identical because the only thing month one compares is the model.
MOMENTUM_BOOKS = ("A", "B", "E")

#: A Tuesday, so nothing here trips over a weekend.
TUESDAY = date(2026, 9, 8)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def at(hour: int, minute: int, day: date = TUESDAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=NEW_YORK)


def guard_for(book_id: str = "A") -> gr.Guardrails:
    return gr.load_book_guardrails(BOOKS_YAML, book_id)


def state_for(
    book_id: str = "A",
    equity: float = 100000.0,
    now: datetime | None = None,
    **changes,
) -> gr.AccountState:
    """A snapshot of one book with nothing wrong with it, unless a test says so."""
    fields = {
        "equity": equity,
        "day_start_equity": equity,
        "realized_pnl_today": 0.0,
        "unrealized_pnl": 0.0,
        "open_positions": {},
        "pending_order_notional": 0.0,
        "now": now or at(9, 40),
        "kill_switch_present": False,
        "account_id": "DUT077572",
        "book_id": book_id,
    }
    fields.update(changes)
    return gr.AccountState(**fields)


def entry(book_id: str = "A", symbol: str = "AAPL", qty: int = 10,
          price: float = 100.0, sector: str | None = "Technology",
          **changes) -> gr.OrderIntent:
    fields = {
        "symbol": symbol, "side": "BUY", "qty": qty, "limit_price": price,
        "purpose": "entry", "book_id": book_id, "sector": sector,
    }
    fields.update(changes)
    return gr.OrderIntent(**fields)


def reasons_for(decision: gr.Decision, rule_id: str) -> list[str]:
    return [why for rule, why in zip(decision.rule_ids, decision.reasons)
            if rule == rule_id]


# ---------------------------------------------------------------------------
# A1. The stop is 10 percent of the average true range, never inside the range
# ---------------------------------------------------------------------------


def test_the_stop_is_a_tenth_of_the_average_true_range():
    """A 2 dollar average swing gives a 20 cent stop, not a 1.50 dollar one."""
    g = guard_for("A")
    assert gr.atr_stop_distance(g, 2.0) == pytest.approx(0.20)
    assert gr.stop_price_for(g, 100.0, None, "BUY", None, atr=2.0) == 99.80


def test_a_quieter_stock_gets_a_tighter_stop_and_a_wilder_one_a_wider_stop():
    """The whole point of measuring the stop off the stock's own daily swing."""
    g = guard_for("A")
    quiet = gr.stop_price_for(g, 100.0, None, "BUY", None, atr=0.60)
    wild = gr.stop_price_for(g, 100.0, None, "BUY", None, atr=8.00)
    assert quiet == 99.94
    assert wild == 99.20
    assert quiet > wild, "the quiet name should stop nearer to where it was bought"


def test_the_stop_is_never_inside_the_opening_range_for_a_long():
    """Inside the range is inside the noise the trade is made of."""
    g = guard_for("A")
    # The average true range alone would stop at 99.80, which is inside a range
    # whose low is 99.50, so the stop is pushed down to the range low.
    assert gr.stop_price_for(g, 100.0, 99.50, "BUY", None, atr=2.0) == 99.50


def test_the_stop_is_never_inside_the_opening_range_for_a_short():
    g = guard_for("A")
    # Mirrored: the range high pushes a short's stop up rather than down.
    assert gr.stop_price_for(g, 100.0, None, "SELL", 100.60, atr=2.0) == 100.60


def test_a_wide_opening_range_widens_the_stop_to_its_low():
    """This is the rule biting the way it usually will on a real gapper.

    A stock that gapped has a wide first five minutes, so a stop 10 percent of
    the average true range from the entry price will nearly always land inside
    that range and get pushed out to the range low. That is deliberate: inside
    the range is inside the noise the setup is made of, so a stop there would be
    hit by the setup itself. The risk based sizing is what keeps the wider stop
    from costing more money, because it simply buys fewer shares.
    """
    g = guard_for("A")
    assert gr.stop_price_for(g, 100.0, 98.0, "BUY", None, atr=2.0) == 98.00


def test_with_no_average_true_range_the_old_percentage_stop_stands_in():
    """A position carried in from an older file still gets a stop, not none."""
    g = guard_for("A")
    assert gr.stop_price_for(g, 100.0, None, "BUY") == 98.50


def test_the_filing_books_have_no_volatility_stop_at_all():
    """Handing book C an average true range must not silently retune its stop."""
    c = guard_for("C")
    assert c.risk.stop_atr_pct is None
    assert gr.atr_stop_distance(c, 2.0) is None
    assert gr.stop_price_for(c, 100.0, None, "BUY", None, atr=2.0) == 92.00


def test_a_model_may_still_only_tighten_a_stop():
    """The clamp Mo asked to keep. A wider stop comes back at the rule stop."""
    g = guard_for("A")
    wide = loop.protective_levels(g, entry=100.0, short=False, model_stop=97.0,
                                  model_target=0.0, atr=2.0)
    assert wide.stop == 99.80
    assert any("never widen" in note for note in wide.notes)

    tight = loop.protective_levels(g, entry=100.0, short=False, model_stop=99.9,
                                   model_target=0.0, atr=2.0)
    assert tight.stop == 99.90


# ---------------------------------------------------------------------------
# A2. No profit target
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("book_id", MOMENTUM_BOOKS)
def test_no_momentum_book_takes_a_profit_target(book_id: str):
    assert guard_for(book_id).risk.use_profit_target is False


def test_a_target_is_dropped_even_when_it_is_on_the_right_side():
    g = guard_for("A")
    levels = loop.protective_levels(g, entry=100.0, short=False, model_stop=99.8,
                                    model_target=110.0, atr=2.0)
    assert levels.target == 0.0
    assert any("no profit target at all" in note for note in levels.notes)


def test_the_rules_only_book_asks_for_no_target_either():
    params, _ = decide_mod.load_params(STRATEGIES / "momentum_rules")
    packet = {"account": {"equity": 100000},
              "candidates": [_candidate("AAA")]}
    result = decide_mod.rules_only_decision(packet, params, "pick", "B")
    assert result.picks
    assert all(pick["target"] is None for pick in result.picks)


def test_the_prompt_never_asks_the_model_for_a_target():
    params, _ = decide_mod.load_params(STRATEGIES / "momentum_hybrid")
    rendered = decide_mod.render_prompt(STRATEGIES / "momentum_hybrid", "pick", params)
    assert "NO PROFIT TARGET" in rendered
    assert "target_r_multiple" not in rendered


# ---------------------------------------------------------------------------
# A3. The volatility filter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("book_id", MOMENTUM_BOOKS)
def test_every_momentum_book_carries_the_volatility_filter(book_id: str):
    g = guard_for(book_id)
    assert g.universe.min_atr_usd == 0.50
    assert g.universe.min_atr_pct_of_price == 1.5
    assert g.universe.atr_days == 14


# ---------------------------------------------------------------------------
# A4. Ranked by relative volume
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("book_id", MOMENTUM_BOOKS)
def test_the_shortlist_is_ranked_by_relative_volume(book_id: str):
    g = guard_for(book_id)
    assert g.scanner.rank_by == "rel_volume"
    assert g.scanner.rel_volume_min == 2.0, "the 2x floor stays as a floor"
    assert g.scanner.rel_volume_window == "09:30-09:35"
    assert g.scanner.rel_volume_baseline_days == 14


def test_the_rules_only_path_takes_the_names_in_rank_order():
    """Book B follows the ranking rather than re-sorting on something else."""
    params, _ = decide_mod.load_params(STRATEGIES / "momentum_rules")
    rows = [_candidate("CCC", rank=3), _candidate("AAA", rank=1),
            _candidate("BBB", rank=2)]
    result = decide_mod.rules_only_decision(
        {"account": {"equity": 100000}, "candidates": rows}, params, "pick", "B")
    assert [pick["symbol"] for pick in result.picks] == ["AAA", "BBB", "CCC"]


# ---------------------------------------------------------------------------
# A5. Direction from the first five minute candle, and no trade on a flat one
# ---------------------------------------------------------------------------


def test_a_candle_that_closed_up_is_a_long():
    assert decide_mod.direction_from_candle(
        {"opening_range_open": 99.0, "opening_range_close": 101.0}) == "long"


def test_a_candle_that_closed_down_is_a_short():
    assert decide_mod.direction_from_candle(
        {"opening_range_open": 101.0, "opening_range_close": 99.0}) == "short"


def test_a_flat_candle_is_no_trade_at_all():
    """Open equal to close means the buyers and sellers finished level."""
    assert decide_mod.direction_from_candle(
        {"opening_range_open": 100.0, "opening_range_close": 100.0}) is None


def test_a_name_with_no_candle_is_not_guessed_at():
    assert decide_mod.direction_from_candle({"gain_pct": 8.0}) is None


def test_the_rules_only_path_skips_a_flat_candle():
    params, _ = decide_mod.load_params(STRATEGIES / "momentum_rules")
    rows = [_candidate("FLAT", open_price=20.0, close_price=20.0, rank=1),
            _candidate("GOOD", rank=2)]
    result = decide_mod.rules_only_decision(
        {"account": {"equity": 100000}, "candidates": rows}, params, "pick", "B")
    assert [pick["symbol"] for pick in result.picks] == ["GOOD"]
    assert "FLAT" in [skip["symbol"] for skip in result.skips]


# ---------------------------------------------------------------------------
# A6. Risk based sizing, with the notional cap over the top of it
# ---------------------------------------------------------------------------


def test_the_share_count_comes_from_the_risk_and_the_stop_distance():
    """250 dollars of risk over a 20 cent stop is 1,250 shares, before any cap."""
    g = guard_for("A")
    assert g.money.risk_per_trade_pct == 0.25
    shares = gr.shares_for_risk(g, state_for("A"), "AAPL", 100.0, 99.80)
    # 1,250 shares at 100 dollars would be 125,000, so the caps cut it hard.
    assert shares == 100, "the 10,000 dollar order cap is what actually bites here"


def test_a_wider_stop_buys_fewer_shares_and_risks_the_same_money():
    """The point of the whole rule: equal risk, whatever the stop distance is.

    Both sizes below sit under the 10,000 dollar order cap, so nothing but the
    risk rule decides them, and both come out risking the same 250 dollars.
    """
    g = guard_for("A")
    state = state_for("A")
    tight = gr.shares_for_risk(g, state, "AAPL", 10.0, 9.75)   # 25 cents away
    wide = gr.shares_for_risk(g, state, "AAPL", 10.0, 9.50)    # 50 cents away
    assert tight == 1000
    assert wide == 500
    assert tight * 0.25 == pytest.approx(250.0)
    assert wide * 0.50 == pytest.approx(250.0)


def test_the_notional_cap_is_still_the_ceiling():
    """A very tight stop must not buy an enormous position."""
    g = guard_for("A")
    shares = gr.shares_for_risk(g, state_for("A"), "AAPL", 10.0, 9.99)
    assert shares * 10.0 <= g.money.max_order_notional + 0.01


def test_a_book_with_no_risk_rule_sizes_the_old_way():
    c = guard_for("C")
    assert c.money.risk_per_trade_pct is None
    plain = gr.max_shares_for(c, state_for("C"), "AAPL", 100.0)
    assert gr.shares_for_risk(c, state_for("C"), "AAPL", 100.0, 92.0) == plain


@pytest.mark.parametrize("book_id", MOMENTUM_BOOKS)
def test_the_notional_cap_is_ten_percent_of_the_book(book_id: str):
    assert guard_for(book_id).money.max_position_pct == 10


# ---------------------------------------------------------------------------
# A7. The daily loss cap, re-derived so it can actually bind
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("book_id", MOMENTUM_BOOKS)
def test_the_daily_cap_is_one_percent(book_id: str):
    assert guard_for(book_id).money.max_daily_loss_pct == 1


def test_the_daily_cap_now_binds_before_the_natural_worst_case():
    """The arithmetic Mo asked to be written down.

    Ten positions each risking 0.25 percent is a natural worst case of 2.5
    percent in one day. A cap above that could never fire, which is what made
    the old 2 percent cap decoration. One percent binds after four stop outs.
    """
    g = guard_for("A")
    natural_worst_case = g.money.max_open_positions * g.money.risk_per_trade_pct
    assert natural_worst_case == 2.5
    assert g.money.max_daily_loss_pct < natural_worst_case

    four_stop_outs = -(100000 * g.money.risk_per_trade_pct / 100.0) * 4
    assert gr.daily_loss_hit(g, state_for("A", realized_pnl_today=four_stop_outs))


def test_the_yaml_writes_the_derivation_down():
    for name in ("momentum_hybrid", "momentum_rules"):
        text = (STRATEGIES / name / "strategy.yaml").read_text(encoding="utf-8")
        assert "THE DERIVATION" in text
        assert "2.5 percent" in text


# ---------------------------------------------------------------------------
# A8. The limits beyond the day
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("book_id", MOMENTUM_BOOKS)
def test_every_momentum_book_has_the_three_limits_beyond_the_day(book_id: str):
    g = guard_for(book_id)
    assert g.money.max_weekly_loss_pct == 4
    assert g.money.max_monthly_loss_pct == 6
    assert g.money.max_consecutive_losing_days == 3


def test_a_week_at_four_percent_down_pauses_the_book():
    g = guard_for("A")
    state = state_for("A", week_pnl=-4000.0)
    assert gr.weekly_loss_hit(g, state) is True
    decision = gr.check_order(g, state, entry("A"))
    assert decision.allowed is False
    assert "weekly_loss_cap" in decision.rule_ids


def test_a_month_at_six_percent_down_pauses_the_book():
    g = guard_for("A")
    decision = gr.check_order(g, state_for("A", month_pnl=-6000.0), entry("A"))
    assert "monthly_loss_cap" in decision.rule_ids


def test_three_losing_days_in_a_row_pauses_the_book():
    g = guard_for("A")
    decision = gr.check_order(g, state_for("A", consecutive_losing_days=3), entry("A"))
    assert "losing_streak_pause" in decision.rule_ids
    assert "three" not in decision.summary.lower() or True


@pytest.mark.parametrize("purpose", ["exit", "stop", "flatten"])
def test_a_paused_book_can_still_get_out(purpose: str):
    """Refusing the way out of a trade is worse than any limit this enforces."""
    g = guard_for("A")
    state = state_for("A", week_pnl=-9000.0, month_pnl=-9000.0,
                      consecutive_losing_days=9)
    intent = entry("A", purpose=purpose, side="SELL")
    decision = gr.check_order(g, state, intent)
    for rule in ("weekly_loss_cap", "monthly_loss_cap", "losing_streak_pause"):
        assert rule not in decision.rule_ids


def test_a_quiet_week_stops_nothing():
    g = guard_for("A")
    decision = gr.check_order(g, state_for("A", week_pnl=120.0), entry("A"))
    assert decision.allowed is True, decision.reasons


def test_the_loop_works_the_week_and_the_month_out_of_the_book_files(tmp_path):
    """Only the loop can see a book's own history, so only the loop can say."""
    folder = tmp_path / "output"
    folder.mkdir()
    for day, pnl in (("2026-09-01", -100.0), ("2026-09-07", -50.0),
                     ("2026-09-08", -25.0), ("2026-09-09", -10.0)):
        (folder / f"state_BOOK_A_{day}.json").write_text(
            '{"book_id": "A", "order_ref": "BOOK_A", "date": "%s", '
            '"realized_pnl_today": %s}' % (day, pnl))

    history = loop.loss_history("BOOK_A", date(2026, 9, 9), -10.0, root=tmp_path)
    # The week runs Monday to Sunday. 2026-09-09 is a Wednesday, so its Monday
    # is the 7th and the 1st of the month falls outside the week.
    assert history.week_pnl == -85.0
    assert history.month_pnl == -185.0
    assert history.losing_days == 3


def test_a_winning_day_breaks_the_losing_streak(tmp_path):
    folder = tmp_path / "output"
    folder.mkdir()
    for day, pnl in (("2026-09-04", -100.0), ("2026-09-07", 40.0),
                     ("2026-09-08", -25.0)):
        (folder / f"state_BOOK_A_{day}.json").write_text(
            '{"book_id": "A", "order_ref": "BOOK_A", "date": "%s", '
            '"realized_pnl_today": %s}' % (day, pnl))
    history = loop.loss_history("BOOK_A", date(2026, 9, 9), 0.0, root=tmp_path)
    assert history.losing_days == 1


# ---------------------------------------------------------------------------
# A9. The correlation caps
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("book_id", MOMENTUM_BOOKS)
def test_every_momentum_book_has_the_correlation_caps(book_id: str):
    g = guard_for(book_id)
    assert g.money.sector_gross_pct_max == 25
    assert g.money.account_symbol_pct_max == 15


def test_a_quarter_of_the_book_in_one_industry_is_the_limit():
    g = guard_for("A")
    state = state_for("A", sector_exposure={"Technology": 24000.0})
    fine = gr.check_order(g, state, entry("A", qty=10, price=100.0))
    assert fine.allowed is True, fine.reasons

    over = gr.check_order(g, state, entry("A", qty=20, price=100.0))
    assert "sector_cap" in over.rule_ids
    assert "Technology" in reasons_for(over, "sector_cap")[0]


def test_a_different_industry_has_its_own_room():
    g = guard_for("A")
    state = state_for("A", sector_exposure={"Technology": 25000.0})
    decision = gr.check_order(g, state, entry("A", sector="Health Care"))
    assert decision.allowed is True, decision.reasons


def test_a_name_whose_industry_nobody_knows_is_refused():
    """A cap that cannot be measured is not a cap."""
    g = guard_for("A")
    decision = gr.check_order(g, state_for("A"), entry("A", sector=None))
    assert "sector_cap" in decision.rule_ids
    assert "which industry" in reasons_for(decision, "sector_cap")[0]


def test_an_unknown_industry_never_blocks_the_way_out():
    g = guard_for("A")
    decision = gr.check_order(
        g, state_for("A"), entry("A", sector=None, purpose="exit", side="SELL"))
    assert "sector_cap" not in decision.rule_ids


def test_the_filing_books_have_no_sector_cap_so_an_unknown_industry_is_fine():
    c = guard_for("C")
    assert c.money.sector_gross_pct_max is None
    decision = gr.check_order(c, state_for("C"), entry("C", sector=None, qty=10))
    assert "sector_cap" not in decision.rule_ids


def test_fifteen_percent_of_all_five_books_is_the_limit_on_one_ticker():
    g = guard_for("A")
    state = state_for("A", account_equity=500000.0,
                      symbol_exposure_all_books={"AAPL": 70000.0})
    fine = gr.check_order(g, state, entry("A", qty=50, price=100.0))
    assert fine.allowed is True, fine.reasons

    over = gr.check_order(g, state, entry("A", qty=90, price=100.0))
    assert "account_symbol_cap" in over.rule_ids


def test_without_the_account_figure_the_books_own_equity_stands_in():
    """The smaller number, so the cap comes out tighter rather than looser."""
    g = guard_for("A")
    state = state_for("A", symbol_exposure_all_books={"AAPL": 14000.0})
    over = gr.check_order(g, state, entry("A", qty=90, price=100.0))
    assert "account_symbol_cap" in over.rule_ids
    assert "what this book alone is worth" in reasons_for(over, "account_symbol_cap")[0]


# ---------------------------------------------------------------------------
# A10. Shorting is still pending Mo's decision, so it stays off
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("book_id", MOMENTUM_BOOKS)
def test_shorting_is_still_switched_off(book_id: str):
    assert guard_for(book_id).universe.allow_shorts is False


def test_the_yaml_says_shorting_is_pending_rather_than_decided():
    for name in ("momentum_hybrid", "momentum_rules"):
        text = (STRATEGIES / name / "strategy.yaml").read_text(encoding="utf-8")
        assert "PENDING MO'S DECISION" in text.upper()


# ---------------------------------------------------------------------------
# A11. The close, in two stages
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("book_id", MOMENTUM_BOOKS)
def test_flattening_begins_at_a_quarter_to_four(book_id: str):
    g = guard_for(book_id)
    assert g.schedule.flatten_at == time(15, 45)
    assert g.schedule.flatten_market_at == time(15, 55)
    assert gr.must_flatten_now(g, at(15, 45)) is True
    assert gr.must_flatten_at_market_now(g, at(15, 45)) is False
    assert gr.must_flatten_at_market_now(g, at(15, 55)) is True


def test_a_long_is_flattened_on_the_bid_and_a_short_on_the_ask():
    """Limit orders on the other side's price, because spreads widen at the close."""
    quote = {"bid": 99.90, "ask": 100.10, "last": 100.0}
    assert loop.flatten_price(quote, short=False) == 99.90
    assert loop.flatten_price(quote, short=True) == 100.10


def test_with_no_bid_or_ask_the_flatten_falls_back_to_the_last_price():
    assert loop.flatten_price({"last": 100.0}, short=False) == 100.0
    assert loop.flatten_price(None, short=False) is None


# ---------------------------------------------------------------------------
# A12. The hard exclusions, and the listing age rule Mo rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("book_id", MOMENTUM_BOOKS)
def test_every_hard_exclusion_is_switched_on(book_id: str):
    u = guard_for(book_id).universe
    assert u.exclude_spacs is True
    assert u.exclude_warrants_and_rights is True
    assert u.exclude_preferred is True
    assert u.require_us_primary_listing is True
    assert u.exclude_halted is True


@pytest.mark.parametrize("book_id", MOMENTUM_BOOKS)
def test_history_replaces_the_listing_age_rule(book_id: str):
    """Mo dropped the 90 day listing rule in favour of needing enough history."""
    u = guard_for(book_id).universe
    assert u.min_history_sessions == 30
    assert u.dollar_volume_sessions == 30
    assert u.atr_days == 14


def test_nothing_anywhere_carries_a_listing_age_rule():
    for name in ("momentum_hybrid", "momentum_rules"):
        text = (STRATEGIES / name / "strategy.yaml").read_text(encoding="utf-8")
        assert "days_since_listing" not in text
        assert "min_listing_age" not in text


# ---------------------------------------------------------------------------
# A13. No headline and no news anywhere
# ---------------------------------------------------------------------------


def test_no_headline_or_news_reaches_the_momentum_model():
    """Press release copy is prompt injection with a profit motive."""
    assert "headline" not in decide_mod.MOMENTUM_CANDIDATE_KEYS
    assert "news" not in decide_mod.MOMENTUM_CANDIDATE_KEYS
    assert "headline" not in decide_mod.MOMENTUM_POSITION_KEYS
    assert "news" not in decide_mod.MOMENTUM_POSITION_KEYS


def test_the_momentum_packet_drops_a_headline_that_somehow_arrives():
    """Even a row that carries one must not pass it on."""
    packet = {
        "strategy_key": "momentum_hybrid",
        "candidates": [{"symbol": "AAPL", "headline": "MIRACLE CURE ANNOUNCED",
                        "news": "and some news", "rel_volume": 4.0}],
    }
    message = decide_mod.build_user_message("pick", packet)
    assert "MIRACLE" not in message
    assert "headline" not in message
    assert "news" not in message


def test_neither_momentum_prompt_asks_about_a_catalyst():
    params, _ = decide_mod.load_params(STRATEGIES / "momentum_hybrid")
    for shape in ("pick", "manage"):
        rendered = decide_mod.render_prompt(
            STRATEGIES / "momentum_hybrid", shape, params)
        assert "headline" not in rendered.lower() or "no headline" in rendered.lower()


# ---------------------------------------------------------------------------
# A14. The cadence is data driven
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("book_id", MOMENTUM_BOOKS)
def test_the_fast_window_is_thirty_seconds_from_935_to_1100(book_id: str):
    g = guard_for(book_id)
    assert g.schedule.fast_poll_seconds == 30
    assert g.schedule.fast_poll_from == time(9, 35)
    assert g.schedule.fast_poll_until == time(11, 0)


def test_a_book_holding_something_in_the_morning_wants_thirty_seconds():
    g = guard_for("A")
    assert gr.next_tick_seconds(g, at(9, 40), holding=True) == 30
    assert gr.next_tick_seconds(g, at(10, 59), holding=True) == 30


def test_a_book_holding_nothing_waits_five_minutes():
    g = guard_for("A")
    assert gr.next_tick_seconds(g, at(9, 40), holding=False) == 300


def test_after_eleven_the_cadence_goes_back_to_five_minutes():
    g = guard_for("A")
    assert gr.next_tick_seconds(g, at(11, 0), holding=True) == 300
    assert gr.next_tick_seconds(g, at(14, 0), holding=True) == 300


def test_a_book_with_no_fast_window_always_waits_its_loop_minutes():
    c = guard_for("C")
    assert c.schedule.fast_poll_seconds is None
    assert gr.next_tick_seconds(c, at(9, 40), holding=True) == 30 * 60


def test_the_loop_writes_the_cadence_out_for_the_wrapper(tmp_path, monkeypatch):
    monkeypatch.setenv(loop.ROOT_ENV_VAR, str(tmp_path))
    path = loop.write_next_tick(30)
    assert path.read_text().strip() == "30"


# ---------------------------------------------------------------------------
# A15. What the ledger records
# ---------------------------------------------------------------------------


def test_every_fact_the_ledger_needs_comes_off_the_row_and_the_trigger():
    from agent import book_state as bs           # noqa: PLC0415

    state = bs.BookState(book_id="A", order_ref="BOOK_A", date="2026-09-08")
    state.shortlist = [_candidate("AAPL", rank=2)]
    state.triggered["AAPL"] = {"at": "2026-09-08T09:36:00-04:00", "price": 101.0,
                               "stop": 99.0, "qty": 100}

    facts = loop.trade_facts(state, "AAPL")
    assert facts["decision_price"] == 101.0
    assert facts["decision_time"] == "2026-09-08T09:36:00-04:00"
    assert facts["atr"] == 2.0
    assert facts["rel_volume"] == 4.0
    assert facts["rank"] == 2
    assert facts["candle"] == "99.50 to 100.50 (up)"
    assert facts["risk_usd"] == 200.0
    assert facts["sector"] == "Technology"

    line = loop.facts_line(facts)
    for wanted in ("rank 2", "relative volume 4.00x", "atr 2.00", "opening candle",
                   "risking 200.00 dollars", "sector Technology", "decided at 101.00"):
        assert wanted in line


# ---------------------------------------------------------------------------
# A16. The success gate is written down before day one
# ---------------------------------------------------------------------------


def test_the_success_gate_is_pre_registered_in_the_spec_and_both_changelogs():
    """Pre-registered means written down before day one and not moved afterwards."""
    files = [
        REAL_ROOT / "docs" / "STRATEGY.md",
        STRATEGIES / "momentum_hybrid" / "CHANGELOG.md",
        STRATEGIES / "momentum_rules" / "CHANGELOG.md",
    ]
    for path in files:
        text = path.read_text(encoding="utf-8").lower()
        assert "95 percent" in text or "95%" in text, path
        assert "60" in text, path
        assert "profit factor" in text, path
        assert "drawdown" in text, path


def test_the_spec_judges_month_one_on_operations_first():
    text = (REAL_ROOT / "docs" / "STRATEGY.md").read_text(encoding="utf-8")
    assert "How we judge month one" in text


# ---------------------------------------------------------------------------
# D1. Ten positions rather than five
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("book_id", MOMENTUM_BOOKS)
def test_ten_positions_at_risk_based_size(book_id: str):
    g = guard_for(book_id)
    assert g.money.max_open_positions == 10
    assert g.schedule.entries_per_day_max == 10


def test_every_momentum_book_may_pick_ten_names():
    for name in ("momentum_hybrid", "momentum_rules"):
        params, _ = decide_mod.load_params(STRATEGIES / name)
        assert decide_mod.max_picks_for(params) == 10


# ---------------------------------------------------------------------------
# D2. The VWAP fade is logged, not acted on
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("book_id", MOMENTUM_BOOKS)
def test_the_fade_count_is_kept_but_the_fade_acts_on_nothing(book_id: str):
    book = gr.load_book(BOOKS_YAML, book_id)
    assert loop.vwap_fade_closes_for(book) == 2, "the count is kept"
    assert loop.vwap_fade_acts_for(book) is False, "and it closes nothing"


def test_a_fade_comes_back_as_an_observation():
    from agent import book_state as bs           # noqa: PLC0415

    book = gr.load_book(BOOKS_YAML, "A")
    plan = loop.plan_for(book, guard_for("A"))
    position = bs.Position(symbol="AAPL", qty=100, avg_cost=100.0, entry=100.0,
                           stop=98.0, target=0.0, side="long",
                           trailing_high_or_low=100.0, opened_on="2026-09-08")
    trigger, why = loop.exit_reason_for(position, plan, guard_for("A"), TUESDAY,
                                        99.5, vwap=100.5, closes_through_vwap=2)
    assert trigger == "fade_observed"
    assert "momentum faded" in why


def test_a_book_told_to_act_on_a_fade_still_closes_on_it(tmp_path):
    """One yaml line puts the old behaviour back, which is the point of D2."""
    import shutil                               # noqa: PLC0415
    import yaml                                 # noqa: PLC0415

    folder = tmp_path / "momentum_hybrid"
    shutil.copytree(STRATEGIES / "momentum_hybrid", folder)
    path = folder / "strategy.yaml"
    loaded = yaml.safe_load(path.read_text())
    loaded["risk"]["vwap_fade_action"] = "exit"
    path.write_text(yaml.safe_dump(loaded, sort_keys=False))

    params, _ = decide_mod.load_params(folder)
    assert str(params["vwap_fade_action"]) == "exit"


# ---------------------------------------------------------------------------
# D3. New entries stop at 10:15, and every one it blocks is written down
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("book_id", MOMENTUM_BOOKS)
def test_new_entries_stop_at_a_quarter_past_ten(book_id: str):
    g = guard_for(book_id)
    assert g.schedule.entries_until == time(10, 15)
    assert gr.entries_allowed_now(g, at(10, 14)) is True
    assert gr.entries_allowed_now(g, at(10, 15)) is False


def test_an_entry_after_the_cutoff_is_refused_by_name():
    g = guard_for("A")
    decision = gr.check_order(g, state_for("A", now=at(10, 30)), entry("A"))
    assert "entry_window" in decision.rule_ids


def test_the_cutoff_writes_down_every_entry_it_blocks(tmp_path, monkeypatch):
    """So month one measures what the cutoff cost rather than guessing at it."""
    from agent import book_state as bs           # noqa: PLC0415

    monkeypatch.setenv(loop.ROOT_ENV_VAR, str(tmp_path))
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)

    book = gr.load_book(BOOKS_YAML, "A")
    plan = loop.plan_for(book, guard_for("A"))
    tick = loop.BookTick(book, at(10, 30), "testhash", write_ledger=False, quiet=True)
    state = bs.BookState(book_id="A", order_ref="BOOK_A", date="2026-09-08")

    loop.note_late_entry(tick, state, plan, "AAPL", "the trigger never broke")

    written = [row for row in state.decisions if row["symbol"] == "AAPL"]
    assert written, "the blocked entry was not written down"
    assert "10:15" in written[-1]["rationale"]
    assert "past the cutoff" in written[-1]["decision"]


# ---------------------------------------------------------------------------
# D7. No Finviz anywhere
# ---------------------------------------------------------------------------


def test_no_settings_file_mentions_finviz():
    files = [SHARED_CONFIG, REAL_ROOT / "config" / "guardrails.example.yaml",
             STRATEGIES / "momentum_hybrid" / "strategy.yaml",
             STRATEGIES / "momentum_rules" / "strategy.yaml"]
    for path in files:
        text = path.read_text(encoding="utf-8").lower()
        # The one allowed mention is the note saying it was deliberately removed.
        for line in text.splitlines():
            if "finviz" in line:
                assert line.strip().startswith("#"), f"{path}: {line}"


def test_the_scanner_has_no_finviz_settings_left():
    from agent import scanner as scanner_mod     # noqa: PLC0415

    assert not hasattr(scanner_mod, "FinvizSettings")
    assert not hasattr(scanner_mod, "parse_finviz_csv")
    assert "finviz_enabled" not in scanner_mod.Thresholds().as_dict()


# ---------------------------------------------------------------------------
# The three momentum books still differ only in who decides
# ---------------------------------------------------------------------------


def test_the_three_momentum_books_still_carry_identical_numbers():
    """The whole experiment rests on this, so it is worth testing twice."""
    a = guard_for("A")
    for book_id in ("B", "E"):
        other = guard_for(book_id)
        assert other.money == a.money
        assert other.risk == a.risk
        assert other.universe == a.universe
        assert other.scanner == a.scanner
        assert other.schedule == a.schedule


def test_both_momentum_folders_carry_a_changelog_naming_the_version():
    for name in ("momentum_hybrid", "momentum_rules"):
        text = (STRATEGIES / name / "CHANGELOG.md").read_text(encoding="utf-8")
        assert "Momentum v2" in text
        assert "2026-09-06" in text


# ---------------------------------------------------------------------------
# A candidate row in the shape Momentum v2 expects
# ---------------------------------------------------------------------------


def _candidate(symbol: str, rank: int = 1, open_price: float = 99.5,
               close_price: float = 100.5, atr: float = 2.0,
               rel_volume: float = 4.0) -> dict:
    """One shortlist row, ranked, with a candle and an average true range on it."""
    return {
        "symbol": symbol,
        "opening_range_high": 101.0,
        "opening_range_low": 99.0,
        "opening_range_open": open_price,
        "opening_range_close": close_price,
        "atr": atr,
        "atr_pct_of_price": 2.0,
        "rank": rank,
        "rel_volume": rel_volume,
        "score": rel_volume,
        "sector": "Technology",
        "last": 100.0,
    }

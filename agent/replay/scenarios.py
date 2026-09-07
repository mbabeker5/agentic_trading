#!/usr/bin/env python3
"""The twelve things the replay gate proves, and the evidence for each.

Run them with the harness, never on their own:

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m agent.replay.harness --all

Every scenario in here is one `Scenario` from
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/replay/harness.py.
It says which day to replay, which faults to inject and when, what to set up
before the first tick, and a `check` that reads the finished day back and says
pass or fail with its evidence written out in words. Nothing here talks to a
broker: the harness hands every scenario a FakeBroker and refuses to run against
anything else.

WHERE THE BARS COME FROM
------------------------
Most scenarios replay real recorded bars, the ten liquid names under
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/recordings/history/,
on a real session. Five of them cannot: a stock that falls through its stop on
cue, a position that is still open at 15:50, one book long and another short the
same name. A recorded Friday will not do those on demand, so those scenarios
write their own bars with `crafted_bars` below and every one of them says so in
its own evidence. A crafted scenario proves the loop's arithmetic and its
decisions. It does not prove anything about the market.

WHAT A FAILURE HERE MEANS
-------------------------
A failing scenario is not a broken harness. It is the loop doing something the
strategy documents say it must not, on a day where that could be seen. The
failure lines are written to be read on their own, months later, by somebody
deciding whether a book may be promoted.
"""

from __future__ import annotations

import sys
from datetime import date as date_type, datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.replay.common import EASTERN                             # noqa: E402
from agent.replay.harness import (                                  # noqa: E402
    DEFAULT_DAY,
    DEFAULT_SYMBOLS,
    Fault,
    RunContext,
    Scenario,
    bar,
    crafted_broker,
    eastern,
    seed_book_position,
    seed_day_trades,
)
from agent.replay.stub_decider import (                             # noqa: E402
    ScriptedExit,
    ScriptedPick,
    StubDecider,
)

#: Every rule id agent/guardrails.py's check_order can put on a refusal, read off
#: the decision.add() calls in that file on 2026-09-06. docs/REPLAY.md lists the
#: first twenty; halted arrived later, in commit e653508.
#: A rule missing from a gate run has not been tested, it has merely not been
#: reached.
#:
#: symbol_exclusive left this list on 2026-09-06 and is back in it. It is now a
#: SWITCH rather than a decision: universe.symbol_exclusive in
#: config/guardrails.yaml is true by default, which is one ticker one book and a
#: refusal, and false makes it report instead, which is what the hub's commit
#: 03e5318 did. This list is refusals only, and the rule can refuse again, so it
#: belongs here. Both branches are tested in tests/test_books.py, and Mo has not
#: chosen: see journal/2026-09-06.md.
GUARDRAIL_RULE_IDS = (
    "paper_only", "wrong_account", "wrong_book", "kill_switch",
    "symbol_exclusive",
    "halted", "sec_type", "currency", "blacklist", "whitelist", "no_shorts",
    "short_price_floor", "shortable_required", "entry_window",
    "outside_market_hours", "flatten_time", "daily_loss_cap", "weekly_loss_cap",
    "monthly_loss_cap", "losing_streak_pause", "max_order_notional",
    "max_position_pct", "max_open_positions", "gross_exposure_cap",
    "account_symbol_cap", "sector_cap", "entries_per_day",
)

#: Rules whose facts agent/loop.py does not yet gather, so the loop cannot reach
#: them however the day goes. They are proven here by probe and the report says
#: so, because a rule that only a probe can reach is a rule with nothing behind
#: it in production.
#:
#: Every one of these reads a field on AccountState or OrderIntent that
#: agent/book_state.py's account_state_for() and agent/loop.py's _entry_intent()
#: do not set, and every one of those fields defaults to a value meaning all
#: clear. They are checked against the loop rather than written out by hand, in
#: _not_wired_up() below, so this list cannot go stale on its own.
#:
#: This dictionary shrank on 2026-09-06. agent/loop.py now fills every one of
#: these fields on the way to the guardrails: the halt facts off IBKR's tick 49,
#: the week and month figures and the losing day count out of the book's own
#: earlier state files, the industry off the shortlist row, and the account wide
#: symbol figures from reading all five book files once a tick. What is left
#: here is checked against the loop rather than trusted, so an entry that is no
#: longer true fails rather than lying.
NOT_WIRED_UP_FIELDS = {
    "halted": "halted and limit_state",
    "weekly_loss_cap": "week_pnl",
    "monthly_loss_cap": "month_pnl",
    "losing_streak_pause": "consecutive_losing_days",
    "sector_cap": "sector",
    "account_symbol_cap": "symbol_exposure_all_books and account_equity",
}
NOT_WIRED_UP = tuple(NOT_WIRED_UP_FIELDS)

#: The five minute grid a crafted day is written on, 09:25 to 16:05.
CRAFTED_START = clock_time(9, 25)
CRAFTED_END = clock_time(16, 0)


# --------------------------------------------------------------- crafted bars


def five_minute_grid(day: date_type, start: clock_time = CRAFTED_START,
                     end: clock_time = CRAFTED_END) -> list[datetime]:
    """Every five minute bar stamp of a crafted day."""
    out = []
    moment = eastern(day, start)
    last = eastern(day, end)
    while moment <= last:
        out.append(moment)
        moment += timedelta(minutes=5)
    return out


def crafted_bars(day: date_type, price_at, volume: float = 800_000.0) -> list[dict]:
    """One symbol's whole day, from a function saying what it is worth when.

    price_at takes the bar's own time and hands back either one number, which
    becomes a flat bar, or (open, high, low, close). Writing a day this way
    keeps the shape of the test in one readable line instead of forty bar
    dictionaries.
    """
    rows = []
    for moment in five_minute_grid(day):
        value = price_at(moment)
        if isinstance(value, (int, float)):
            open_ = high = low = close = float(value)
        else:
            open_, high, low, close = (float(v) for v in value)
        rows.append(bar(day, moment.time(), open_, high, low, close, volume))
    return rows


def flat(price: float):
    """A stock that does nothing all day, for a name that is only scenery."""
    return lambda moment: price


def steps(day: date_type, schedule: dict[str, Any], start: float):
    """A stock that changes price at named times and holds between them.

    schedule maps "HH:MM" to the new value, which is a price or a full
    (open, high, low, close). The first bar of the day starts at `start`.
    """
    ordered = sorted(schedule.items())

    def price_at(moment: datetime):
        current: Any = start
        for at, value in ordered:
            if f"{moment:%H:%M}" >= at:
                current = value
        return current

    return price_at


def ramp(day: date_type, first: float, last: float):
    """A stock that climbs evenly from the open to the close.

    Used where a position has to survive the whole day: a rising close is always
    above the day's volume weighted average price, so the momentum books' fade
    rule never fires and the position is still there at 15:55 to be flattened.
    """
    grid = five_minute_grid(day)
    span = max(1, len(grid) - 1)

    def price_at(moment: datetime):
        try:
            place = grid.index(moment)
        except ValueError:
            place = span
        return first + (last - first) * (place / span)

    return price_at


def widen_opening(rows: list[dict], low: float, bars: int = 2) -> list[dict]:
    """Put a wick on the first bars, so the opening range is a real range.

    The stop a book opens with is the nearer of its percentage stop and the
    opening range low (risk.use_opening_range_low_if_tighter). A crafted day
    that only climbs has an opening range low equal to its own open, so the rule
    stop lands a cent under the entry and the position stops out on the first
    tick that dips. Real days do not look like that, so the crafted ones get a
    wick rather than a degenerate range.
    """
    for row in rows[:bars]:
        row["low"] = min(float(row["low"]), float(low))
    return rows


def daily_history(day: date_type, closes: dict[str, float],
                  sessions: int = 40) -> dict[str, list[dict]]:
    """Forty flat daily bars behind a crafted day, so a prior close exists.

    Without these the synthetic shortlist has no yesterday to measure today's
    move against, and every candidate scores zero, which makes the ranking
    arbitrary. Each name gets its own prior close, because a fifty dollar stock
    behind a hundred dollar yesterday reads as down fifty percent, and the stub
    decider would then pick it short.
    """
    out: dict[str, list[dict]] = {}
    for symbol, close in closes.items():
        close = float(close)
        rows = []
        cursor = day - timedelta(days=1)
        while len(rows) < sessions:
            if cursor.weekday() < 5:
                rows.append({"time": f"{cursor:%Y-%m-%d}", "open": close,
                             "high": close, "low": close, "close": close,
                             "volume": 20_000_000.0, "average": close,
                             "barCount": 1000})
            cursor -= timedelta(days=1)
        out[str(symbol).upper()] = list(reversed(rows))
    return out


def prior_closes(series: dict[str, list[dict]]) -> dict[str, float]:
    """Yesterday's close for each crafted name, taken as today's first open.

    A crafted day that opens flat is a day with no gap in it, which is what
    every scenario here wants unless it says otherwise.
    """
    return {symbol: float(rows[0]["open"]) for symbol, rows in series.items() if rows}


def only(*book_ids: str) -> dict:
    """Turn every book off except the ones named, for a scenario that needs few.

    A scenario that only proves something about book A does not need the other
    four replayed eighty one times, and a smaller run is a faster gate and a
    shorter report to read.
    """
    wanted = {str(b).upper() for b in book_ids}
    return {book: {"enabled": book in wanted} for book in ("A", "B", "C", "D", "E")}


# ------------------------------------------------------------- small readers


def _positions(context: RunContext, order_ref: str) -> dict:
    return {s: int(round(p.qty)) for s, p in context.positions_for(order_ref).items()}


def _orders(context: RunContext, order_ref: str, side: str | None = None,
            order_type: str | None = None, symbol: str | None = None) -> list:
    rows = context.orders_for(order_ref)
    if side:
        rows = [o for o in rows if o.side == side]
    if order_type:
        rows = [o for o in rows if o.order_type == order_type]
    if symbol:
        rows = [o for o in rows if o.symbol == str(symbol).upper()]
    return rows


def _entries_placed(context: RunContext, book_id: str | None = None) -> list:
    """Every order the loop actually sent in order to OPEN a position.

    The side is not enough to tell an entry from an exit. Covering a short is a
    BUY exactly like opening a long, and the plain IBKR order dictionary the
    loop hands the broker carries no purpose at all. What does carry it is the
    loop's own decision line, which reads "placed BUY 100 AAPL limit 230.00
    (purpose: entry)", so that is what is counted here.
    """
    rows = []
    for row in context.ledger.rows:
        if row.payload.get("kind") != "decision":
            continue
        text = str(row.payload.get("decision") or "")
        if not text.startswith("placed") or "purpose: entry" not in text:
            continue
        if book_id and row.book_id != str(book_id).upper():
            continue
        rows.append(row)
    return rows


def _closings_placed(context: RunContext, book_id: str | None = None,
                     symbol: str | None = None) -> list:
    """Every order the loop actually sent in order to CLOSE a position.

    Read the same way as _entries_placed above, off the loop's own decision
    line, because a bracket's stop and target children are sells too and they
    went out with the entry rather than as a decision to get out.
    """
    rows = []
    for row in context.ledger.rows:
        if row.payload.get("kind") != "decision":
            continue
        text = str(row.payload.get("decision") or "")
        if not text.startswith("placed"):
            continue
        if "purpose: exit" not in text and "purpose: flatten" not in text:
            continue
        if book_id and row.book_id != str(book_id).upper():
            continue
        if symbol and str(symbol).upper() not in text:
            continue
        rows.append(row)
    return rows


def _halt_reason(text: str, width: int = 150) -> str:
    """One book's halt reason, deduped and cut short.

    agent/book_state.py's halt() appends to halt_reason every time it is called,
    and reconciliation calls it on every tick, so after a whole day the reason
    is the same sentence eighty times over. That is a defect of its own and it
    is reported, but a report that quoted it whole would be unreadable.
    """
    seen: list[str] = []
    for part in str(text or "").split("; "):
        part = part.strip()
        if part and part not in seen:
            seen.append(part)
    joined = "; ".join(seen)
    return joined[:width] + ("..." if len(joined) > width else "")


def _stacked_orders(context: RunContext) -> list[str]:
    """Orders the loop sent again while an identical one was still working.

    agent/loop.py never asks whether it already has an order out for a name
    before sending another. Every phase works from the book's positions, not
    from the account's working orders, so a closing order that does not fill is
    sent again on the next tick, and again, for as long as the position is open
    and the rule keeps firing.

    Grouped by book, symbol, side and order type, because a bracket leaves a
    stop and a target resting on purpose and those two differ by type.
    """
    groups: dict[tuple, int] = {}
    for order in context.fake.open_orders().get("orders") or []:
        key = (str(order.get("orderRef")), str(order.get("symbol")),
               str(order.get("action")), str(order.get("orderType")))
        groups[key] = groups.get(key, 0) + 1
    return [f"{count} identical {key[2]} {key[3]} orders for {key[1]} from {key[0]}"
            for key, count in sorted(groups.items(), key=lambda kv: -kv[1])
            if count > 1]


def _why_no_entry(context: RunContext, book_id: str | None = None) -> str:
    """Which rule refused this book's entries, when none of them got out.

    Several scenarios need a position to exist before they can test anything.
    When the entry never happens they should say which rule stopped it rather
    than report the thing they were actually testing as broken.
    """
    counts: dict[str, int] = {}
    for row in context.ledger.rule_hits:
        if book_id and row.book_id != str(book_id).upper():
            continue
        rule_id = str(row.payload.get("rule_id"))
        if rule_id in GUARDRAIL_RULE_IDS:
            counts[rule_id] = counts.get(rule_id, 0) + 1
    if not counts:
        return "no guardrail refused anything, so the entry was never worked out"
    worst = sorted(counts.items(), key=lambda kv: -kv[1])
    return "the guardrails refused " + ", ".join(f"{r} ({n} times)" for r, n in worst[:3])


def _every_tick_ran(context: RunContext) -> tuple[bool, str]:
    bad = [t.at for t in context.ticks if t.exit_code != 0]
    if bad:
        return False, f"these ticks did not return zero: {', '.join(bad)}"
    return True, f"all {len(context.ticks)} ticks ran and returned zero"


def _reconciled_every_tick(context: RunContext) -> tuple[bool, list[str]]:
    bad = [t.at for t in context.ticks if t.reconcile_note != "everything matched"]
    return (not bad), bad


# ==========================================================================
# (a) The day runs at all
# ==========================================================================


def clean_day(day: date_type) -> Scenario:
    """A whole recorded day with nothing broken, run against the real loop.

    There used to be a second copy of this scenario, clean_day_no_fill_bridge,
    which ran the same day with the harness fill bridge switched off so that the
    size of a gap in the loop was measured rather than argued about. The gap was
    that agent/loop.py never read executions(), so a resting order that filled
    later existed at the broker and not in any book file. It was closed on
    2026-09-06 by ingest_fills(), the bridge is gone, and there is nothing left
    for a second copy of this day to measure. What replaced it is
    fills_from_the_broker below, which tests the ingestion itself on a crafted
    day where a limit order fills two ticks after it was sent.
    """
    key = "clean_day"
    title = "A whole recorded day, five books, nothing broken"
    proves = ("that the loop runs 09:25 to 16:05 without a person touching it, "
              "that the books and the broker agree at every tick, and that the "
              "momentum books are flat at the close")

    def check(context: RunContext) -> tuple[bool, list[str], list[str]]:
        evidence: list[str] = []
        failures: list[str] = []

        ok, line = _every_tick_ran(context)
        evidence.append(line)
        if not ok:
            failures.append(line)

        orders = len(context.broker.orders)
        fills = len(context.fake.fills)
        evidence.append(f"{orders} orders went to the broker and {fills} of them "
                        "produced a fill")
        if orders == 0:
            failures.append("not one order was placed all day, so this day proves "
                            "nothing about the order path")

        matched, bad = _reconciled_every_tick(context)
        if matched:
            evidence.append("reconciliation said everything matched on every one of "
                            f"the {len(context.ticks)} ticks")
        else:
            first_bad = next(t for t in context.ticks if t.at == bad[0])
            first_line = ""
            for line in context.text(bad[0]).splitlines():
                if line.startswith("  Book "):
                    first_line = line.strip()
                    break
            failures.append(f"reconciliation disagreed on {len(bad)} of "
                            f"{len(context.ticks)} ticks, first at {bad[0]}: "
                            f"{first_bad.reconcile_note}. {first_line[:220]}")

        halted = context.halted_books()
        if halted:
            failures.append("these books halted on a clean day: "
                            + "; ".join(f"{b}: {_halt_reason(why)}"
                                        for b, why in sorted(halted.items())))
            shared = [t for t in context.ticks
                      if "same name" in context.text(t.at)]
            if shared:
                line = next((ln.strip() for ln in context.text(shared[0].at).splitlines()
                             if "same name" in ln), "")
                # Two books in one ticker stopped being a failure on 2026-09-06,
                # when the hub retired symbol exclusivity. It is expected on any
                # ordinary day, because the books that share a strategy share a
                # shortlist and rank it the same way, and that agreement is what
                # month one is measuring. What matters now is only whether the
                # numbers add up, which reconciliation checks per symbol, so this
                # is a failure ONLY when the total disagrees with the broker.
                if any(not getattr(row, "matches", True) for row in shared):
                    failures.append(
                        "THE HEADLINE: two books are in the same ticker and their "
                        "positions do not add up to what the broker holds. It "
                        f"happened at {shared[0].at}. Sharing a name is allowed "
                        "since 2026-09-06 and is expected between books that share "
                        "a strategy; the totals disagreeing is not, and every book "
                        "holding that ticker is halted for the rest of the day "
                        f"until somebody works out why. The line was: {line[:180]}")
            long_reason = max((len(str(why)) for why in halted.values()), default=0)
            if long_reason > 400:
                failures.append(
                    f"one halt reason is {long_reason} characters long. "
                    "agent/book_state.py's halt() appends to halt_reason every time "
                    "it is called and reconciliation calls it on every tick, so the "
                    "same sentence is stored eighty times over in the book file and "
                    "in every log line that quotes it.")
        else:
            evidence.append("no book halted")

        stacked = _stacked_orders(context)
        if stacked:
            failures.append("the loop sent the same order again while an identical "
                            "one was still working: " + "; ".join(stacked[:3]))
        else:
            evidence.append("no order was left stacked on top of an identical one")

        # A rule that refuses every entry every book ever works out is not a
        # guardrail doing its job, it is a stopped machine, and the clean day is
        # where that shows up first.
        blanket = {}
        for row in context.ledger.rule_hits:
            rule_id = str(row.payload.get("rule_id"))
            if rule_id in GUARDRAIL_RULE_IDS:
                blanket[rule_id] = blanket.get(rule_id, 0) + 1
        for rule_id, count in sorted(blanket.items(), key=lambda kv: -kv[1]):
            if count >= 10:
                failures.append(
                    f"{rule_id} refused {count} orders on a day that was supposed to "
                    "be ordinary. A guardrail that stops everything has stopped the "
                    "machine rather than protected it. Check whether the loop "
                    "actually gives that rule the fact it reads before deciding "
                    "which of the two is broken.")
                break

        for order_ref in ("BOOK_A", "BOOK_B", "BOOK_E"):
            held = _positions(context, order_ref)
            if held:
                failures.append(f"{order_ref} is a momentum book and it still holds "
                                f"{held} after the close")
        if not failures:
            evidence.append("every momentum book is flat after 15:55")

        spend = round(sum(float(getattr(c, "cost", 0.0) or 0.0)
                          for c in context.decider.calls), 6)
        evidence.append(f"the decision step was called {len(context.decider.calls)} "
                        f"times and cost {spend:.6f} dollars, because no model was "
                        "called")

        rows = len(context.ledger.rows)
        evidence.append(f"{rows} ledger rows were written, every one with a book and "
                        "a reason on it")
        if rows == 0:
            failures.append("nothing reached the ledger, so no decision was recorded")

        if "daily_summary" not in context.rule_ids():
            failures.append("no book wrote its end of day summary line")
        else:
            evidence.append("every book wrote its end of day summary after the close")

        # Every fill the broker made has to be in exactly one book file. This is
        # the loop's own ingestion, with nothing standing in for it: the harness
        # counts what filled and applies none of it.
        watched = len(context.watcher.applied)
        if watched:
            evidence.append(f"the broker filled {watched} order(s) and the loop read "
                            "every one of them back out of executions() itself, with "
                            "nothing in the harness applying a fill")

        return not failures, evidence, failures

    return Scenario(
        key=key, title=title, proves=proves, day=day,
        slow=True,
        decider=lambda s: StubDecider(max_picks=3),
        check=check,
    )


# ==========================================================================
# (a2) A fill that arrives after the order call reaches the book file
# ==========================================================================


def fills_from_the_broker(day: date_type) -> Scenario:
    """A limit entry that fills two ticks later still reaches the book file.

    THE SCENARIO THIS REPLACED. clean_day_no_fill_bridge ran the whole recorded
    day with the harness fill bridge switched off, to measure a gap in the loop:
    agent/loop.py recorded a fill only from what place_order() handed straight
    back, so a resting order that filled later existed at the broker and did not
    exist in any book file. On a clean day the fake broker filled nineteen
    orders and not one book file knew.

    The gap closed on 2026-09-06 with ingest_fills(), so there was nothing left
    for that scenario to measure. This tests the ingestion itself instead, and
    on a crafted day rather than a recorded one, because a recorded day cannot
    be asked to leave an order resting for exactly two ticks.

    How the day is built. WAIT opens at 100 and does nothing until 10:30, when
    it drops to 96. Book A is told to buy it at 09:35 with a limit of 97, which
    is below the market, so the order rests. Nothing fills at 09:35, nothing
    fills at 10:00, and the bar at 10:30 goes through the limit.

    What it proves, one check each:

      the book file does NOT hold it while the order is only resting
      the book file DOES hold it on the tick after the bar that filled it
      the share count, the average cost and entries_opened_today are right
      the working order is gone from the book file once it is filled
      the fill reached the ledger's Trades tab with the decision price on it
      the same execution was not applied twice, which is what the exec id is for
    """
    wait, other = "WAIT", "OTHER"
    watch: dict[str, dict] = {}

    def build(scenario: Scenario):
        series = {
            wait: crafted_bars(day, steps(day, {"10:30": 96.0}, 100.0)),
            other: crafted_bars(day, flat(50.0)),
        }
        return crafted_broker(series,
                              daily=daily_history(day, prior_closes(series)))

    def after_tick(context: RunContext, moment: datetime) -> None:
        at = f"{moment:%H:%M}"
        if at in ("09:35", "10:00", "10:25", "10:35", "10:40"):
            state = context.state_for("BOOK_A")
            watch[at] = {
                "positions": _positions(context, "BOOK_A"),
                "working": {str(k): dict(v) for k, v in
                            (state.working_orders or {}).items()
                            if isinstance(v, dict)},
                "entries": int(state.entries_opened_today),
                "fills_seen": list(getattr(state, "fills_seen", []) or []),
                # The broker's own per book view, read at the SAME moment. Read
                # at the close it would be empty, because a momentum book is
                # flat by then, and the comparison would say nothing.
                "broker": {s: int(held.qty) for s, held
                           in context.fake.book_positions("BOOK_A").items()},
            }

    def check(context: RunContext) -> tuple[bool, list[str], list[str]]:
        evidence: list[str] = []
        failures: list[str] = []

        ok, line = _every_tick_ran(context)
        evidence.append(line)
        if not ok:
            failures.append(line)

        resting = watch.get("10:00", {})
        if resting.get("positions"):
            failures.append(
                f"book A held {resting['positions']} at 10:00, before the bar that "
                "filled its order. Something invented a position out of an order "
                "that was only resting.")
        elif resting.get("working"):
            evidence.append(
                f"at 10:00 book A had {len(resting['working'])} order(s) resting "
                "and held nothing, which is the state the old loop could never "
                "get out of")
        else:
            failures.append(
                "book A had nothing resting at 10:00, so its limit entry was "
                f"never placed and nothing here was tested: {_why_no_entry(context)}")

        after = watch.get("10:35") or watch.get("10:40") or {}
        held = after.get("positions") or {}
        if held.get(wait):
            evidence.append(
                f"the bar at 10:30 filled the order and book A held {held[wait]} "
                f"{wait} on the next tick, read out of executions() by the loop "
                "itself with nothing in the harness applying it")
        else:
            failures.append(
                f"the bar at 10:30 went through book A's limit and the book file "
                f"still holds {held}. This is the bug the harness fill bridge used "
                "to cover: a fill that arrives after place_order returned never "
                "reaches the book.")

        if held.get(wait) and after.get("entries") != 1:
            failures.append(
                f"book A opened one position and entries_opened_today says "
                f"{after.get('entries')}. Every per day entry limit is counted off "
                "that number.")
        elif held.get(wait):
            evidence.append("entries_opened_today was put up to 1 by the fill, "
                            "which is what every per day entry limit counts")

        if held.get(wait) and after.get("working"):
            still = {k: v.get("purpose") for k, v in after["working"].items()}
            if any(purpose == "entry" for purpose in still.values()):
                failures.append(
                    f"the entry filled and book A still lists it as working: "
                    f"{still}. A book waiting on an order that has already filled "
                    "counts its money twice.")
        elif held.get(wait):
            evidence.append("the working order was marked filled and taken out of "
                            "the book file")

        if after.get("fills_seen"):
            evidence.append(
                f"the execution id was written into the book file "
                f"({len(after['fills_seen'])} of them), which is what stops the "
                "same fill being applied a second time after a restart")
        elif held.get(wait):
            failures.append(
                "a fill was applied and no execution id was remembered, so the "
                "next tick would apply it again")

        # The arithmetic, against the broker's own per book view at the same
        # moment. A fill counted twice shows up here and nowhere else.
        book_view = after.get("broker") or {}
        if book_view != held:
            failures.append(
                f"the book file says {held} and the broker's per book view says "
                f"{book_view}. A fill counted twice looks exactly like this.")
        else:
            evidence.append(f"the book file and the broker's own per book view "
                            f"agree: {held}")

        trades = [row for row in context.ledger.rows
                  if row.tab == "Trades"
                  and str(row.payload.get("symbol") or "").upper() == wait]
        if trades:
            with_price = [row for row in trades
                          if row.payload.get("decision_price") not in (None, "")]
            if with_price:
                evidence.append(
                    f"{len(trades)} fill(s) reached the Trades tab, "
                    f"{len(with_price)} of them carrying the decision price the "
                    "slippage columns are worked out from")
            else:
                failures.append(
                    "the fill reached the Trades tab with no decision price on it, "
                    "so the slippage columns stay blank and the live ramp's "
                    "slippage trigger cannot be measured")
        else:
            failures.append(f"no fill for {wait} reached the ledger's Trades tab. "
                            f"Rows written: {len(context.ledger.rows)}")

        return not failures, evidence, failures

    return Scenario(
        key="fills_from_the_broker",
        title="A limit order that fills two ticks later reaches the book file",
        proves="that the loop reads the broker's own executions rather than "
               "believing what the order call handed back, that a fill updates the "
               "position, the average cost, the entry count and the working order, "
               "and that an execution id cannot be applied twice",
        day=day, symbols=(wait, other), build_broker=build,
        book_patches=only("A"),
        strategy_overlays={"momentum_hybrid": {"schedule": {"entries_until": "11:00"}}},
        decider=lambda s: StubDecider(
            max_picks=1,
            script=[ScriptedPick(book="A", symbol=wait, at="09:35", entry=97.0,
                                 stop=94.0, target=0.0, qty_hint=100)]),
        after_tick=after_tick,
        check=check,
    )


# ==========================================================================
# (b) Every guardrail refuses something
# ==========================================================================


def every_guardrail(day: date_type) -> Scenario:
    """Each of the twenty rule ids blocks an order and lands in the ledger.

    Seven of them are reached by the loop's own order flow, which is the strong
    kind of evidence. The other thirteen are backstops behind a door the loop
    keeps shut: it will not build an entry outside the entry window, it will not
    build one while the stop file is there, it sizes every entry through
    max_shares_for so it cannot ask for more than the caps allow, and it always
    builds an ordinary dollar denominated share order for the right book. Those
    are pushed a crafted order through agent/loop.py's own consider(), with the
    real guardrails and the real ledger, and the report says which is which.
    """

    def setup(context: RunContext) -> None:
        # Book E starts the day already past its daily loss cap, so the pick it
        # makes at 09:35 is refused by daily_loss_cap rather than by anything
        # the harness had to arrange at the broker.
        state = context.state_for("BOOK_E")
        state.realized_pnl_today = -3_000.0
        state.day_start_equity = 100_000.0
        context.bs.save_state(state)

        # Book D has already opened its two names for the day, which is its
        # whole allowance, so its first pick is refused by entries_per_day.
        state = context.state_for("BOOK_D")
        state.entries_opened_today = 3
        context.bs.save_state(state)

    def finish(context: RunContext) -> None:
        gr = context.gr
        day_at = lambda h, m: datetime.combine(context.day, clock_time(h, m),
                                               tzinfo=EASTERN)

        # SPY on purpose: a probe must not use the name book A blacklists, or
        # blacklist would look like a rule only a probe can reach when the loop
        # reaches it perfectly well on its own.
        def entry(symbol="SPY", qty=10, price=100.0, **extra):
            return gr.OrderIntent(symbol=symbol, side="BUY", qty=qty,
                                  limit_price=price, purpose="entry",
                                  book_id="A", **extra)

        # paper_only and wrong_account, from one order aimed at a live account.
        context.probe_rule("A", entry(),
                           context.account_state("A", account_id="U1234567"),
                           note="a live account id, which is not a DU paper one")

        # wrong_book: book A's limits, an order tagged for book B.
        context.probe_rule(
            "A", gr.OrderIntent(symbol="SPY", side="BUY", qty=10, limit_price=100.0,
                                purpose="entry", book_id="B"),
            context.account_state("A"), note="an order tagged for the wrong book")

        # kill_switch: the stop file is there and this is not a closing order.
        context.probe_rule("A", entry(),
                           context.account_state("A", kill_switch_present=True),
                           note="the stop file exists")

        # sec_type and currency.
        context.probe_rule("A", entry(sec_type="OPT"), context.account_state("A"),
                           note="an options order")
        context.probe_rule("A", entry(currency="EUR"), context.account_state("A"),
                           note="an order priced in euros")

        # entry_window and outside_market_hours, from one order at breakfast.
        context.probe_rule("A", entry(), context.account_state("A", now=day_at(8, 0)),
                           note="an entry at 08:00, before the market opens")

        # flatten_time: after 15:55 the loop only closes.
        context.probe_rule("A", entry(),
                           context.account_state("A", now=day_at(15, 58)),
                           note="an entry at 15:58, after the flatten time")

        # max_order_notional: more than 15,000 dollars in one order.
        context.probe_rule("A", entry(qty=200, price=100.0), context.account_state("A"),
                           note="a 20,000 dollar order")

        # max_position_pct: inside the order cap, over 15 percent of a smaller book.
        context.probe_rule("A", entry(qty=100, price=100.0),
                           context.account_state("A", equity=50_000.0,
                                                 day_start_equity=50_000.0),
                           note="10,000 dollars into a 50,000 dollar book")

        # max_open_positions: the book's own limit already held, and this would
        # be one more. The number is read off the settings rather than written
        # here, because it has already changed once (five to ten on 2026-09-06)
        # and a hard coded five would have quietly stopped testing the rule.
        limit = int(context.guard_for("A").money.max_open_positions)
        full = {f"FULL{n}": gr.PositionInfo(symbol=f"FULL{n}", qty=10,
                                            avg_cost=100.0, market_value=1_000.0)
                for n in range(limit)}
        context.probe_rule("A", entry(qty=10, price=100.0),
                           context.account_state("A", open_positions=full),
                           note=f"one position more than the limit of {limit}")

        # gross_exposure_cap: the book is already fully invested.
        context.probe_rule("A", entry(qty=10, price=100.0),
                           context.account_state("A", gross_exposure=100_000.0),
                           note="a book already 100 percent invested")

        # symbol_exclusive: another book is already in the name. This scenario
        # forces universe.symbol_exclusive on in its own settings copy, because
        # the point here is that the rule CAN refuse and that line is Mo's to
        # set. With it off the same order comes back allowed with a note on it,
        # which is what commit 03e5318 did and what tests/test_books.py covers
        # on both sides. Either way agent/reconcile.py checks each ticker as a
        # whole by adding up what every book holding it believes.
        context.probe_rule(
            "A", entry(symbol="TAKEN"),
            context.account_state("A", symbols_held_elsewhere={"TAKEN": "B"}),
            note="a name book B is already in")

        # The three caps that look beyond one day, and the losing streak pause.
        # The loop fills all four fields now, so a probe is a belt and braces
        # check rather than the only way to reach them.
        context.probe_rule("A", entry(),
                           context.account_state("A", week_pnl=-20_000.0),
                           note="a book well into its weekly loss cap")
        context.probe_rule("A", entry(),
                           context.account_state("A", month_pnl=-40_000.0),
                           note="a book well into its monthly loss cap")
        context.probe_rule("A", entry(),
                           context.account_state("A", consecutive_losing_days=10),
                           note="a book that has finished down ten days running")

        # sector_cap: the book is already full of one sector, and this order is
        # in the same one.
        context.probe_rule(
            "A", entry(sector="Technology"),
            context.account_state("A", sector_exposure={"Technology": 100_000.0}),
            note="another technology name in a book already full of them")

        # account_symbol_cap: the other books have already put the whole account
        # into this name.
        context.probe_rule(
            "A", entry(symbol="NVDA"),
            context.account_state(
                "A", account_equity=500_000.0,
                symbol_exposure_all_books={"NVDA": 500_000.0}),
            note="a name the five books between them have already filled up on")

        # halted, in all three of its shapes: the name is halted, the name is
        # in a limit band, and the halt status could not be read at all.
        context.probe_rule("A", entry(halted=True), context.account_state("A"),
                           note="a name that is halted")
        context.probe_rule("A", entry(limit_state=True), context.account_state("A"),
                           note="a name in a limit up limit down band")
        context.probe_rule("A", entry(halted=None), context.account_state("A"),
                           note="a name whose halt status could not be read")

    def check(context: RunContext) -> tuple[bool, list[str], list[str]]:
        evidence: list[str] = []
        failures: list[str] = []

        seen = context.rule_ids()
        in_play = context.in_play_rule_ids()
        missing = [r for r in GUARDRAIL_RULE_IDS if r not in seen]

        reached = sorted(r for r in GUARDRAIL_RULE_IDS if r in in_play)
        probed = sorted(r for r in GUARDRAIL_RULE_IDS if r in seen and r not in in_play)

        evidence.append(f"{len(GUARDRAIL_RULE_IDS) - len(missing)} of "
                        f"{len(GUARDRAIL_RULE_IDS)} guardrail rule ids blocked an "
                        "order and reached the ledger")
        evidence.append("reached by the loop's own order flow: "
                        + (", ".join(reached) or "none"))
        evidence.append("reached only by a crafted probe through the loop's own "
                        "consider(), so the rule works but the loop may never get "
                        "itself there: " + (", ".join(probed) or "none"))

        if missing:
            failures.append("these rule ids never fired, so they are untested rather "
                            "than proven: " + ", ".join(missing))

        stranded = sorted(r for r in NOT_WIRED_UP if r in probed)
        if stranded:
            evidence.append(
                "NOT WIRED UP, and this is the important line in this scenario: "
                + ", ".join(f"{r} reads {NOT_WIRED_UP_FIELDS[r]}" for r in stranded)
                + ". Every one of those fields is left at the value that means all "
                "clear, because nothing on the way from agent/book_state.py's "
                "account_state_for() through agent/loop.py sets them. The rules "
                "work when a probe hands them the facts. In production they cannot "
                "fire however the day goes, so what looks like "
                f"{len(GUARDRAIL_RULE_IDS)} guardrails is "
                f"{len(GUARDRAIL_RULE_IDS) - len(stranded)}.")

        for rule_id in ("blacklist", "whitelist", "no_shorts", "daily_loss_cap",
                        "entries_per_day"):
            rows = context.ledger.rows_for_rule(rule_id)
            if rows and rule_id in in_play:
                evidence.append(f"{rule_id} was logged against book "
                                f"{rows[0].book_id or 'unknown'}: "
                                f"{str(rows[0].payload.get('detail'))[:110]}")

        for row in context.ledger.rule_hits:
            if row.payload.get("rule_id") in GUARDRAIL_RULE_IDS and not row.book_id:
                failures.append("a guardrail row reached the ledger with no book on "
                                f"it: {row.payload}")
                break

        return not failures, evidence, failures

    top = "AAPL"
    return Scenario(
        key="every_guardrail",
        title="Every guardrail rule id refuses an order and is written down",
        proves="that every rule id agent/guardrails.py can emit blocks an order and "
               "reaches the ledger with the rule id and the book on it",
        day=day, slow=True,
        # ONE TICKER, ONE BOOK IS FORCED ON FOR THIS SCENARIO, whichever way
        # config/guardrails.yaml has it. That line is Mo's to set and it has
        # been moved twice in a day. This scenario's job is to prove that every
        # rule id CAN refuse an order, and a rule switched off by a setting is
        # untested rather than proven, so the setting is overridden here rather
        # than the scenario going red every time the default moves.
        guardrail_overlay={"universe": {"symbol_exclusive": True}},
        strategy_overlays={
            # Books A and E. A is scripted onto the blacklisted name.
            "momentum_hybrid": {"universe": {"blacklist": [top]}},
            # Book B. Any short trips the price floor as well as the two borrow
            # rules, which is how a short is refused three times over today.
            "momentum_rules": {"universe": {"short_price_floor": 100_000}},
            # Book C. Nothing on its sweep is on the list, so every pick is refused.
            "insider": {"universe": {"whitelist": ["ZZZZ"]}},
        },
        decider=lambda s: StubDecider(
            max_picks=2,
            script=[
                ScriptedPick(book="A", symbol=top, at="09:35"),
                ScriptedPick(book="B", symbol="MSFT", side="short", at="09:35"),
                ScriptedPick(book="E", symbol="NVDA", at="09:35"),
            ]),
        setup=setup, finish=finish, check=check,
    )


# ==========================================================================
# (c) The daily loss cap trips
# ==========================================================================


def daily_loss_cap(day: date_type) -> Scenario:
    """Book A is 3 percent down by the time it picks, so the cap has to bite.

    Crafted bars, because a recorded Friday will not hand a book a 3 percent
    loss on a schedule. The book's pick time is moved to 10:15 in the sandbox
    copy of its strategy file, so the loss is already on the books when the
    first entry of the day is worked out. That is the only moment the cap can be
    seen doing its job: agent/guardrails.py sets the halt flag on any order once
    the cap is hit, but only an entry gets the daily_loss_cap rule id written
    against it, because a closing order is meant to go through.
    """
    loser, target = "AAA", "BBB"

    def build(scenario: Scenario):
        series = {
            loser: crafted_bars(day, steps(day, {"09:55": 94.0}, 100.0)),
            target: crafted_bars(day, flat(50.0)),
        }
        return crafted_broker(series, daily=daily_history(day, prior_closes(series)))

    def setup(context: RunContext) -> None:
        # Half the book, so there is still cash to size an entry with. A book
        # with nothing left to spend would refuse the entry for want of money
        # and the loss cap would never be reached.
        seed_book_position(context, "A", loser, 500, 100.0, stop=98.50,
                           target=110.0, opened_on=f"{day:%Y-%m-%d}")

    def check(context: RunContext) -> tuple[bool, list[str], list[str]]:
        evidence: list[str] = []
        failures: list[str] = []

        ok, line = _every_tick_ran(context)
        evidence.append(line)
        if not ok:
            failures.append(line)

        rows = context.ledger.rows_for_rule("daily_loss_cap")
        if rows:
            evidence.append(f"daily_loss_cap was logged against book "
                            f"{rows[0].book_id}: "
                            f"{str(rows[0].payload.get('detail'))[:130]}")
        else:
            failures.append("the book was more than 2 percent down and "
                            "daily_loss_cap never reached the ledger")

        halted = context.halted_books()
        if "A" in halted:
            evidence.append(f"book A halted: {halted['A'][:110]}")
        else:
            failures.append("book A hit its daily loss cap and was not halted")

        entries = _entries_placed(context, "A")
        if entries:
            failures.append("the halted book still opened "
                            f"{len(entries)} new positions: "
                            + "; ".join(str(r.payload.get("decision"))[:60]
                                        for r in entries[:3]))
        else:
            evidence.append("no new position was opened after the cap tripped")

        exits = _orders(context, "BOOK_A", side="SELL", symbol=loser)
        if exits:
            evidence.append(
                f"the halt did not block the way out: {len(exits)} sell orders for "
                f"{loser} went through, the first at {exits[0].at[11:16]}")
        else:
            failures.append(f"the halted book never sent a closing order for {loser}, "
                            "so the halt blocked the exit as well as the entry, which "
                            "is the failure mode this scenario exists to catch")

        held = _positions(context, "BOOK_A")
        if held.get(loser):
            failures.append(f"book A still holds {held[loser]} {loser} at the close")
        else:
            evidence.append(f"book A is out of {loser} by the end of the day")

        return not failures, evidence, failures

    return Scenario(
        key="daily_loss_cap",
        title="The daily loss cap halts one book and still lets it out",
        proves="that a book 3 percent down opens nothing else that day, that "
               "daily_loss_cap is written against it, and that the halt does not "
               "block the closing orders",
        day=day, symbols=(target,), build_broker=build,
        book_patches=only("A"),
        # The pick is moved late so the loss is already on the books when the
        # first entry of the day is worked out. entries_until has to move with
        # it: agent/loop.py's phase_for() only calls a tick a pick while the
        # entry window is still open, and the momentum books close theirs at
        # 10:15 as of 2026-09-06.
        strategy_overlays={"momentum_hybrid": {
            "schedule": {"pick_time": "10:15", "entries_until": "11:00"}}},
        decider=lambda s: StubDecider(
            max_picks=1,
            script=[ScriptedPick(book="A", symbol=target, at="10:15", side="long")]),
        setup=setup, check=check,
    )


# ==========================================================================
# (d) The 15:55 flatten
# ==========================================================================


def flatten_at_close(day: date_type) -> Scenario:
    """One book with something to sell at 15:55, one with nothing.

    Crafted bars again: a position has to still be open at 15:50, and a recorded
    name will have hit a stop, a target or the fade rule long before then. RIDE
    climbs gently all day, so its close is always above the day's volume
    weighted average price and the momentum fade never fires.

    REST is the other half. Its entry limit sits below the market all day, so
    the order is still working at 15:55, which is the case docs/REPLAY.md asks
    about and the one the loop has no code for.
    """
    holder, resting = "RIDE", "REST"

    def build(scenario: Scenario):
        series = {
            holder: crafted_bars(day, ramp(day, 100.0, 101.0)),
            resting: crafted_bars(day, ramp(day, 100.0, 101.0)),
        }
        return crafted_broker(series, daily=daily_history(day, prior_closes(series)))

    def setup(context: RunContext) -> None:
        seed_book_position(context, "A", holder, 200, 100.0, stop=95.0, target=500.0,
                           opened_on=f"{day:%Y-%m-%d}")

    def check(context: RunContext) -> tuple[bool, list[str], list[str]]:
        evidence: list[str] = []
        failures: list[str] = []

        ok, line = _every_tick_ran(context)
        evidence.append(line)
        if not ok:
            failures.append(line)

        # The flatten went two stage on 2026-09-06 (item A11): limit orders at
        # the bid from flatten_at, market orders from flatten_market_at. So what
        # is checked is that the whole position was sent out to be closed, not
        # which kind of order carried it.
        closings = _closings_placed(context, "A", holder)
        flatten = [o for o in _orders(context, "BOOK_A", side="SELL", symbol=holder)
                   if o.purpose != "stop"]
        if closings and flatten:
            kinds = sorted({o.order_type for o in flatten})
            evidence.append(
                f"at the flatten, book A sent {len(flatten)} closing orders for "
                f"{flatten[0].qty} {holder} as {', '.join(kinds)}, which is the whole "
                "position")
            if "MKT" not in kinds:
                evidence.append(
                    "none of them was a market order, so the limit stage of the "
                    "flatten got it done before the market backstop was reached")
        else:
            failures.append(f"book A held {holder} at 15:50 and sent nothing to "
                            f"close it: {len(closings)} closing decisions, "
                            f"{len(flatten)} orders")

        held = _positions(context, "BOOK_A")
        if held.get(holder):
            failures.append(f"book A still holds {held[holder]} {holder} after the "
                            "close")
        else:
            evidence.append("book A is flat after the close")

        zero = [o for o in context.broker.orders if o.qty <= 0]
        if zero:
            failures.append(f"{len(zero)} orders were sent for zero shares or fewer")
        else:
            evidence.append("no order was ever sent for zero shares, so the book with "
                            "nothing open sent nothing")

        b_orders = context.orders_for("BOOK_B")
        if b_orders:
            evidence.append(f"book B sent {len(b_orders)} orders all day, none of them "
                            "at the flatten")
        b_flatten = [o for o in b_orders if o.at[11:16] >= "15:55"]
        if b_flatten:
            failures.append("book B had nothing open and still sent "
                            f"{len(b_flatten)} orders at the flatten")
        else:
            evidence.append("book B had nothing open at 15:55 and sent nothing")

        # The working order. agent/loop.py never calls cancel_order anywhere, so
        # an entry that has not filled by the flatten is still live at the
        # broker while the book believes it is flat.
        working = [o for o in context.fake.open_orders()["orders"]
                   if o.get("symbol") == resting]
        if working:
            kinds = ", ".join(f"{o.get('action')} {o.get('remaining')} at "
                              f"{o.get('orderType')}" for o in working)
            failures.append(
                f"{len(working)} orders for {resting} were still working at the close "
                f"({kinds}) and nothing cancelled them. agent/loop.py calls "
                "cancel_order in exactly one place, move_resting_stop(), when the "
                "trailing rule tightens a stop. Nothing cancels an entry that never "
                "filled, and nothing cancels the stop and target children that went "
                "out with it. So a momentum book that is meant to be flat by 15:55 "
                "can be filled into a position between the flatten and the close, and "
                "its two children can fill on their own and sell stock it does not "
                "own. They are DAY orders and IBKR would expire them at the close, "
                "which covers the overnight case and not the five minutes that "
                "matter.")
        elif _orders(context, "BOOK_A", symbol=resting):
            evidence.append("no order was left working at the close")
        else:
            evidence.append(
                "the second half of this scenario, an entry still resting at the "
                "flatten, could not run: book A never placed the entry at all "
                f"because {_why_no_entry(context, 'A')}. Nothing here says the loop "
                "cancels a working order, only that there was not one to cancel.")

        if context.broker.cancels:
            evidence.append(f"{len(context.broker.cancels)} cancels were sent")

        return not failures, evidence, failures

    return Scenario(
        key="flatten_at_close",
        title="Everything open is sold at 15:55, and nothing is sold twice",
        proves="that a momentum book holding a position at 15:50 is flat by the "
               "close with market orders, that a book holding nothing sends no "
               "order at all, and what happens to an order still working",
        day=day, symbols=(resting,), build_broker=build,
        book_patches=only("A", "B"),
        decider=lambda s: StubDecider(
            max_picks=1, pick_nothing_for=("B",),
            # Every level is given rather than derived, so this scenario does
            # not move when the stop percentage in the strategy file does. The
            # entry sits below a price that only climbs, the stop below that,
            # and the target far above anything the day reaches, so all three
            # legs are still resting at the close whatever the rules say today.
            script=[ScriptedPick(book="A", symbol=resting, at="09:35",
                                 entry=99.50, stop=99.00, target=150.00)]),
        setup=setup, check=check,
    )


# ==========================================================================
# (e) A phantom position
# ==========================================================================


def phantom_position(day: date_type) -> Scenario:
    """A holding appears at the broker that the books cannot account for.

    Two shapes, one after the other, because they are genuinely different
    situations and only one of them halts anybody.

    10:30  the account holds more OWNED than book A claims. That is a quantity
           mismatch with book A's name on it, so book A halts, book B does not,
           and Mo is told.
    11:35  the account holds GHOST, which no book has ever claimed. That is an
           orphan. Nobody halts, and Mo is told once for that name for the day.

    THE SECOND ONE IS A DECISION, not the loop being lax, and this scenario used
    to assert the opposite. The paper account holds one share of SPY bought by
    hand on 2026-09-02 and a working order with no tag on it from the same
    session, and neither will ever belong to a book. Halting on an orphan means
    halting all five books on every tick of every day for the rest of the month
    over a share nobody is managing and nobody is at risk from. A safety rule
    that fires every five minutes forever is not a safety rule.

    Crafted bars and no picks, so the only thing that changes across the day is
    the fault. Neither book trades: a scenario about reconciliation should not
    also be a scenario about the shortlist.
    """
    owned, ghost = "OWNED", "GHOST"
    watch: dict[str, dict] = {}

    def build(scenario: Scenario):
        series = {owned: crafted_bars(day, ramp(day, 100.0, 101.0)),
                  ghost: crafted_bars(day, flat(120.0))}
        return crafted_broker(series, daily=daily_history(day, prior_closes(series)))

    def setup(context: RunContext) -> None:
        seed_book_position(context, "A", owned, 100, 100.0, stop=90.0, target=500.0,
                           opened_on=f"{day:%Y-%m-%d}")

    def after_tick(context: RunContext, moment: datetime) -> None:
        at = f"{moment:%H:%M}"
        if at in ("10:25", "10:35", "11:40"):
            watch[at] = dict(context.halted_books())

    def check(context: RunContext) -> tuple[bool, list[str], list[str]]:
        evidence: list[str] = []
        failures: list[str] = []

        ok, line = _every_tick_ran(context)
        evidence.append(line)
        if not ok:
            failures.append(line)

        clean = watch.get("10:25", {})
        if clean:
            failures.append(f"books were already halted before the fault: {clean}")
        else:
            evidence.append("nothing was halted before the phantom appeared")

        mismatch_note = next((t.reconcile_note for t in context.ticks
                              if t.at == "10:35"), "")
        halted_after = watch.get("10:35", {})
        if "A" in halted_after:
            evidence.append(f"book A halted on the first tick after the phantom "
                            f"appeared in a name it claims: {mismatch_note}")
        else:
            failures.append("the account and book A disagreed about how much "
                            f"{owned} they held and book A was not halted: "
                            f"reconciliation said {mismatch_note!r}")

        if "B" in halted_after:
            failures.append("book B was halted for a mismatch that belonged to book "
                            "A, so the halt is not confined to the affected book")
        else:
            evidence.append("book B was not halted, so the halt landed on the "
                            "affected book only")

        orphan_note = next((t.reconcile_note for t in context.ticks
                            if t.at == "11:40"), "")
        if orphan_note and orphan_note != "everything matched":
            evidence.append(f"the unclaimed {ghost} position was noticed: "
                            f"{orphan_note}")
        else:
            failures.append(f"the account held 100 {ghost} that no book claims and "
                            "reconciliation said everything matched")

        # AN ORPHAN MUST NOT HALT ANYBODY, and that is a decision rather than a
        # gap. This scenario used to fail unless a book halted for GHOST. The
        # paper account holds one share of SPY bought by hand on 2026-09-02 and
        # an untagged order from the same session, and neither will ever belong
        # to a book, so halting on an orphan means halting all five books on
        # every tick of every day for the rest of the month over a share nobody
        # is managing and nobody is at risk from. What the loop does instead is
        # say so, once per name per day, and write a line every tick.
        halted_late = watch.get("11:40", {})
        if halted_late:
            failures.append(
                f"the account held 100 {ghost} that no book claims and "
                f"{', '.join(sorted(halted_late))} halted for it. An orphan is not "
                "a book being wrong about what it holds, and halting on one would "
                "halt every book every day forever over the SPY share left behind "
                "by the manual test on 2026-09-02.")
        else:
            evidence.append(f"no book was halted for the unclaimed {ghost}, which "
                            "is the decision: an orphan is told about, not halted "
                            "on")

        titles = [a.title for a in context.alerts.alerts]
        if any(ghost in title for title in titles):
            evidence.append(f"somebody was told about the unclaimed {ghost}: "
                            + next(t for t in titles if ghost in t))
        else:
            failures.append(
                f"the account held 100 {ghost} that no book claims and nobody was "
                f"told. Alerts raised: {titles or 'none'}")

        if any("halted" in title for title in titles):
            evidence.append("somebody was told about the halt: "
                            + next(t for t in titles if "halted" in t))
        else:
            failures.append(
                "book A was halted and nobody was told. Alerts raised: "
                f"{titles or 'none'}")

        said_once = [t for t in titles if ghost in t]
        if len(said_once) > 1:
            failures.append(
                f"the unclaimed {ghost} was alerted {len(said_once)} times in one "
                "day. Once per name per day is the rule, because it is the same "
                "fact at 11:40 and at 15:40.")

        evidence.append(
            f"the fake broker reports the phantom as a SECOND ROW for {owned} "
            "rather than a larger one, and agent/loop.py now keys the account's "
            "positions by (symbol, account) and adds two rows that land on the "
            "same key, so the share count in the message is the total rather than "
            "whichever row happened to be read last.")

        return not failures, evidence, failures

    return Scenario(
        key="phantom_position",
        title="A mismatch halts one book, an orphan halts nobody, and Mo hears both",
        proves="that a quantity mismatch halts only the book it belongs to, that a "
               "holding no book claims halts nobody at all, and that somebody is "
               "told about each of them",
        day=day, symbols=(ghost,), build_broker=build,
        book_patches=only("A", "B"),
        faults=(
            Fault(at="10:30", action="inject", kind="phantom_position",
                  options={"symbol": owned, "quantity": 50, "avg_cost": 100.0}),
            Fault(at="11:30", action="clear", kind="phantom_position"),
            Fault(at="11:35", action="inject", kind="phantom_position",
                  options={"symbol": ghost, "quantity": 100, "avg_cost": 120.0}),
        ),
        decider=lambda s: StubDecider(max_picks=1, pick_nothing_for=("A", "B")),
        setup=setup, after_tick=after_tick, check=check,
    )


# ==========================================================================
# (f) The kill switch
# ==========================================================================


def kill_switch(day: date_type) -> Scenario:
    """The panic button at 11:00, and a loop that does nothing afterwards.

    agent/kill_switch.py's pull() is the real thing, run against the fake
    broker: it writes output/STOP and output/LOOP_DISABLED into the sandbox,
    cancels every working order, sends a market order to close every position,
    and alerts. Then the rest of the day is ticks that have to do nothing at
    all, because output/LOOP_DISABLED is the first thing agent/loop.py reads.
    """
    holder = "RIDE"
    result: dict[str, Any] = {}

    def build(scenario: Scenario):
        series = {holder: crafted_bars(day, ramp(day, 100.0, 101.0)),
                  "REST": crafted_bars(day, ramp(day, 100.0, 101.0))}
        return crafted_broker(series, daily=daily_history(day, prior_closes(series)))

    def setup(context: RunContext) -> None:
        seed_book_position(context, "A", holder, 200, 100.0, stop=95.0, target=500.0,
                           opened_on=f"{day:%Y-%m-%d}")

    def before_tick(context: RunContext, moment: datetime) -> None:
        if f"{moment:%H:%M}" != "11:00":
            return
        import kill_switch as ks                  # noqa: PLC0415
        code, outcome = ks.pull(context.broker, really=True, now=moment,
                                sleep=lambda seconds: None)
        result["code"] = code
        result["outcome"] = outcome
        context.notes.append(f"the kill switch ran at 11:00 and returned {code}")

    def check(context: RunContext) -> tuple[bool, list[str], list[str]]:
        evidence: list[str] = []
        failures: list[str] = []

        ok, line = _every_tick_ran(context)
        evidence.append(line)
        if not ok:
            failures.append(line)

        if context.sandbox.stop_file.exists() and \
                context.sandbox.loop_disabled_file.exists():
            evidence.append("the kill switch wrote both brake files, "
                            f"{context.sandbox.stop_file.name} and "
                            f"{context.sandbox.loop_disabled_file.name}")
        else:
            failures.append("the kill switch did not write both brake files")

        if context.broker.global_cancels:
            evidence.append(f"it sent {context.broker.global_cancels} global cancel, "
                            "so nothing was left resting")
        else:
            failures.append("no global cancel was sent")

        closing = [o for o in context.broker.orders
                   if o.order_type == "MKT" and o.symbol == holder and o.side == "SELL"]
        if closing:
            evidence.append(f"it sent a market sell for {closing[0].qty} {holder} to "
                            "close the position")
        else:
            failures.append(f"the position in {holder} was never closed out")

        after = [t for t in context.ticks if t.at >= "11:00"]
        busy = [t.at for t in after if t.orders_placed]
        if busy:
            failures.append("the loop kept sending orders after the kill switch, at "
                            + ", ".join(busy))
        else:
            evidence.append(f"every one of the {len(after)} ticks from 11:00 onwards "
                            "did nothing at all, because output/LOOP_DISABLED exists")

        left = {s: q for s, q in context.fake.positions.items() if q}
        if left:
            failures.append(f"the account still holds {left} at the end of the day")
        else:
            evidence.append("the account is flat by the end of the day")

        if context.alerts.alerts:
            evidence.append("the kill switch alerted: "
                            + ", ".join(a.title for a in context.alerts.alerts))
        else:
            failures.append("the kill switch sent no alert")

        if result.get("code") == 1:
            evidence.append(
                "pull() returned 1, meaning it was not flat when it looked. That is "
                "the replay, not a fault: nothing fills at this broker until the "
                "clock moves, and the clock only moves on the next tick. Against a "
                "live market the closing orders come back filled.")

        return not failures, evidence, failures

    return Scenario(
        key="kill_switch",
        title="The kill switch cancels, flattens, and the next tick does nothing",
        proves="that pulling the switch mid day empties the account and stops the "
               "loop dead for the rest of the day",
        day=day, symbols=("REST",), build_broker=build,
        book_patches=only("A"),
        decider=lambda s: StubDecider(
            max_picks=1,
            script=[ScriptedPick(book="A", symbol="REST", at="09:35",
                                 entry=99.50, stop=99.00, target=150.00)]),
        setup=setup, before_tick=before_tick, check=check,
    )


# ==========================================================================
# (g) The day trade counter
# ==========================================================================


def day_trade_counter(day: date_type) -> Scenario:
    """The fourth round trip: refused on book C, allowed and written down on book A.

    Both books start the day with three day trades already behind them, put
    straight into their counter files, because making the loop actually trade
    three round trips would take three replayed days this scenario does not
    have. Then one crafted name opens and falls through both books' stops on the
    same day, which is the fourth round trip for each of them.

    Book C holds for weeks and sets pdt.hard_limit, so its closing order is
    refused. The momentum books day trade on purpose and set hard_limit false,
    so book A's order goes out and the refusal that a live account under 25,000
    dollars would have suffered is written down instead, which is how the cost
    of the rule gets measured rather than guessed.

    ONE NAME EACH, ON PURPOSE. This used to put both books into the same
    ticker, which made it a scenario about symbol exclusivity as well as one
    about the day trade counter: with universe.symbol_exclusive on, book C is
    locked out of a name book A got to first, and the scenario failed for a
    reason that had nothing to do with day trades. A scenario should test one
    thing, so the two books now fall through their own stops in their own names
    and it reads the same whichever way that setting points.
    """
    for_a, for_c = "DROPA", "DROPC"

    def build(scenario: Scenario):
        # The same shape twice, one name per book, because the two books have
        # different stops: A's is 1.5 percent and C's is 8 percent.
        shape = {
            "09:40": (100.0, 100.0, 100.0, 100.0),      # the entry fills here
            "09:45": (100.0, 100.0, 97.0, 97.0),        # through A's 1.5% stop
            "09:50": (97.0, 97.0, 97.0, 97.0),          # C's entry fills here
            "11:00": (97.0, 97.0, 88.0, 88.0),          # through C's 8% stop
            "11:30": (88.0, 88.0, 88.0, 88.0),
        }
        series = {for_a: crafted_bars(day, steps(day, shape, 100.0)),
                  for_c: crafted_bars(day, steps(day, shape, 100.0))}
        return crafted_broker(series, daily=daily_history(day, prior_closes(series)))

    def setup(context: RunContext) -> None:
        for book_id in ("A", "C"):
            seed_day_trades(context, book_id, 3, symbol="SEEDED")

    def check(context: RunContext) -> tuple[bool, list[str], list[str]]:
        evidence: list[str] = []
        failures: list[str] = []

        ok, line = _every_tick_ran(context)
        evidence.append(line)
        if not ok:
            failures.append(line)

        rows = context.ledger.rows_for_rule("pdt_limit")
        by_book: dict[str, list] = {}
        for row in rows:
            by_book.setdefault(row.book_id, []).append(row)

        refused = [r for r in by_book.get("C", [])
                   if "not placed" in str(r.payload.get("action"))]
        if refused:
            evidence.append("book C: the fourth day trade was refused and logged as "
                            f"pdt_limit. {str(refused[0].payload.get('detail'))[:120]}")
        else:
            failures.append("book C is held to three day trades in five business days "
                            "and its fourth closing order was not refused. pdt_limit "
                            f"rows for C: {len(by_book.get('C', []))}")

        c_exits = _closings_placed(context, "C", for_c)
        if c_exits:
            failures.append(f"book C sent {len(c_exits)} closing orders for "
                            f"{for_c} even though the day trade rule refused them")
        else:
            evidence.append(f"book C sent no closing order for {for_c}, so the "
                            "refusal held all the way to the broker")

        if context.fake.day_trade_count("BOOK_C"):
            evidence.append(
                "WORTH ESCALATING: book C made a round trip in "
                f"{for_c} anyway. Its stop was already resting at the broker as the "
                "child of the entry bracket, and a resting stop fires whatever the "
                "day trade counter says. So the pdt hard limit on books C and D can "
                "refuse the loop's own closing order and still not stop the round "
                "trip happening. Since the bracket work landed, that rule protects "
                "less than it reads as protecting.")

        flagged = [r for r in by_book.get("A", [])
                   if "allowed here" in str(r.payload.get("action"))]
        if flagged:
            evidence.append("book A: the same fourth day trade was allowed and "
                            "written down as the live money cost of the rule. "
                            f"{str(flagged[0].payload.get('detail'))[:120]}")
        else:
            failures.append("book A day trades on purpose, so its fourth round trip "
                            "should have been allowed and flagged, and no flagged "
                            f"pdt_limit row was written. Rows for A: "
                            f"{len(by_book.get('A', []))}")

        a_exits = _closings_placed(context, "A", for_a)
        if a_exits:
            evidence.append(f"book A sent {len(a_exits)} closing orders for {for_a}, "
                            "so the flag did not stop it trading")
        else:
            failures.append(f"book A never closed {for_a}, so the flag blocked it "
                            "when it should only have been written down")

        counts = {ref: context.fake.day_trade_count(ref)
                  for ref in ("BOOK_A", "BOOK_C")}
        evidence.append(f"the broker's own round trip count for the day: {counts}")
        for book_id, ref in (("A", "BOOK_A"), ("C", "BOOK_C")):
            if _entries_placed(context, book_id):
                continue
            failures.append(
                f"book {book_id} never opened a position at all, so nothing about "
                f"its day trade allowance was tested: {_why_no_entry(context, book_id)}"
                ". The reason is upstream of this scenario.")

        return not failures, evidence, failures

    return Scenario(
        key="day_trade_counter",
        title="The fourth day trade is refused on book C and only flagged on book A",
        proves="that the pattern day trader allowance blocks the books that hold for "
               "weeks and is measured, not enforced, on the books that day trade",
        day=day, symbols=(for_a, for_c), build_broker=build,
        book_patches=only("A", "C"),
        decider=lambda s: StubDecider(
            max_picks=1,
            script=[ScriptedPick(book="A", symbol=for_a, at="09:35"),
                    ScriptedPick(book="C", symbol=for_c, at="09:45")]),
        setup=setup, check=check,
    )


# ==========================================================================
# (h) Gateway down, then back
# ==========================================================================


def gateway_down(day: date_type) -> Scenario:
    """Four dead ticks in the middle of the day, then the connection returns.

    docs/REPLAY.md asks four things of this: survive it, do not conclude the
    account is empty just because it cannot be read, do not double up when the
    connection comes back, and reconcile before trading again.

    Crafted bars and one book, so that the only thing changing across the outage
    is the outage. Both names climb gently, so no stop, target or fade fires and
    anything the book loses across the twenty minutes was lost by the outage.
    """
    held, opened = "HOLD", "NEWBUY"

    def build(scenario: Scenario):
        series = {held: crafted_bars(day, ramp(day, 100.0, 101.0)),
                  opened: crafted_bars(day, ramp(day, 50.0, 50.5))}
        return crafted_broker(series, daily=daily_history(day, prior_closes(series)))

    watch: dict[str, dict] = {}

    def setup(context: RunContext) -> None:
        # Opened today, because a momentum book's time stop is one trading day
        # and anything dated earlier is closed on the first manage tick.
        seed_book_position(context, "A", held, 100, 100.0, stop=90.0, target=500.0,
                           opened_on=f"{day:%Y-%m-%d}")

    def after_tick(context: RunContext, moment: datetime) -> None:
        # What the book believed at each edge of the outage. Reading it at the
        # end of the day would only show the 15:55 flatten.
        at = f"{moment:%H:%M}"
        if at in ("10:55", "11:15", "11:20", "11:30"):
            watch[at] = _positions(context, "BOOK_A")

    def check(context: RunContext) -> tuple[bool, list[str], list[str]]:
        evidence: list[str] = []
        failures: list[str] = []

        dead = [t for t in context.ticks if "11:00" <= t.at <= "11:15"]
        ok, line = _every_tick_ran(context)
        evidence.append(line)
        if not ok:
            failures.append(line)
        evidence.append(f"the {len(dead)} ticks with the Gateway down all ran and "
                        "returned zero rather than crashing")

        orders_while_down = sum(t.orders_placed for t in dead)
        if orders_while_down:
            failures.append(f"{orders_while_down} orders were sent while the Gateway "
                            "was refusing every call")
        else:
            evidence.append("no order was sent while the connection was down")

        after = [t for t in context.ticks if t.at > "11:15"]
        recovered = [t for t in after if t.reconcile_note == "everything matched"]
        if recovered:
            evidence.append("reconciliation matched again from "
                            f"{recovered[0].at}, once the connection was back")
        else:
            failures.append("reconciliation never matched again after the Gateway "
                            "came back: "
                            + "; ".join(sorted({t.reconcile_note for t in after}))[:220])

        before = watch.get("10:55", {}).get(held)
        during = watch.get("11:15", {}).get(held)
        after_it = watch.get("11:30", {}).get(held)
        if before and during == before and after_it == before:
            evidence.append(f"book A held {before} {held} before the outage, still "
                            "said so on the last blind tick, and still said so "
                            "afterwards, so it never concluded it held nothing just "
                            "because it could not ask")
        else:
            failures.append(f"book A's own record of {held} went {before} before the "
                            f"outage, {during} during it and {after_it} after it")

        after_orders = [o for o in context.broker.orders if o.at[11:16] > "11:15"]
        repeated = [o for o in after_orders
                    if o.side == "BUY" and o.symbol in (held, opened)
                    and o.purpose != "stop"]
        entries_after = _entries_placed(context, "A")
        late_entries = [r for r in entries_after if str(r.at)[11:16] > "11:15"]
        if late_entries:
            failures.append(
                f"{len(late_entries)} new positions were opened after the connection "
                "came back, in names the book already held, which is the double up "
                "this scenario exists to catch")
        else:
            evidence.append(f"the {len(repeated)} buy orders after the recovery opened "
                            "nothing new, so the loop did not buy what it already had")

        halted = context.halted_books()
        if halted:
            failures.append(
                "the outage halted " + ", ".join(sorted(halted))
                + " and nothing ever un-halted them. agent/loop.py's "
                "read_broker_facts() catches the ConnectionError and hands "
                "reconciliation an empty account, so a book that holds something "
                "looks exactly like a book that has lost it. The halt is written "
                "into the book file and no code path anywhere clears it, so a "
                "twenty minute Gateway outage costs the whole trading day.")
        else:
            evidence.append("no book was halted by the outage")

        return not failures, evidence, failures

    return Scenario(
        key="gateway_down",
        title="Twenty minutes with no Gateway, then the connection returns",
        proves="that the loop survives four dead ticks, keeps its own record of what "
               "it holds, sends nothing while blind, and reconciles before trading "
               "again",
        day=day, symbols=(opened,), build_broker=build,
        book_patches=only("A"),
        faults=(Fault(at="11:00", action="inject", kind="gateway_down"),
                Fault(at="11:20", action="clear", kind="gateway_down")),
        decider=lambda s: StubDecider(
            max_picks=1,
            script=[ScriptedPick(book="A", symbol=opened, at="09:35", side="long")]),
        setup=setup, after_tick=after_tick, check=check,
    )


# ==========================================================================
# (i) A competing session, and delayed data
# ==========================================================================


def competing_session_and_delayed_data(day: date_type) -> Scenario:
    """Someone logs in elsewhere, and later the data goes delayed.

    10:00 to 10:30, every snapshot raises with IBKR's code 10197, which is what
    happens when the same login is used on another machine. docs/REPLAY.md says
    the loop must halt and alert rather than trade on stale numbers.

    From 10:35, every snapshot reports market data type 3. The loop must either
    refuse to open a position on delayed prices or record loudly that it opened
    them on delayed prices. Quietly trading on delayed quotes is the failure,
    and it is worth saying that the paper account is served delayed data all the
    time today, so this is the normal state of the world rather than an exotic
    fault.

    One book, and a name that climbs all day, so the position is still there for
    every manage tick to ask a quote about. With two momentum books the day ends
    before 10:00 for a different reason: they pick from the same shortlist, land
    in the same ticker and halt each other. See the clean day for that.
    """
    name = "RISER"
    watch: dict[str, dict] = {}

    def build(scenario: Scenario):
        series = {name: widen_opening(crafted_bars(day, ramp(day, 100.0, 102.0)), 97.0),
                  "OTHER": crafted_bars(day, flat(60.0))}
        return crafted_broker(series, daily=daily_history(day, prior_closes(series)))

    def after_tick(context: RunContext, moment: datetime) -> None:
        at = f"{moment:%H:%M}"
        if at in ("09:55", "10:30", "11:00"):
            watch[at] = dict(context.halted_books())
            watch.setdefault("held", {})[at] = _positions(context, "BOOK_A")

    def _book_lines(context: RunContext, since: str) -> str:
        """Only the lines the loop wrote about a book, not its own header.

        The header names the sandbox folder, and the sandbox folder is named
        after this scenario, so a plain search for the word delayed finds the
        path rather than anything the loop noticed.
        """
        out = []
        for tick in context.ticks:
            if tick.at < since:
                continue
            for line in context.text(tick.at).splitlines():
                if line.strip().startswith("[BOOK_"):
                    out.append(line.strip())
        return "\n".join(out).lower()

    def check(context: RunContext) -> tuple[bool, list[str], list[str]]:
        evidence: list[str] = []
        failures: list[str] = []

        ok, line = _every_tick_ran(context)
        evidence.append(line)
        if not ok:
            failures.append(line)

        holdings = watch.get("held", {})
        if holdings.get("09:55"):
            evidence.append(f"book A held {holdings['09:55']} going into the outage, "
                            "so every tick of it asked the broker for a quote")
        else:
            failures.append(
                "book A held nothing when the competing session began, so no "
                "snapshot was asked for and nothing here was tested: "
                + _why_no_entry(context, "A")
                + ". The reason is upstream of this scenario.")

        during = _book_lines(context, "10:00")
        if "10197" in during:
            evidence.append("the competing session error reached the loop's own log "
                            "for the ticks between 10:00 and 10:30, as a note beside "
                            "the book that could not get a quote")
        else:
            failures.append("the snapshots raised IBKR code 10197 for six ticks and "
                            "nothing about it reached the loop's log")

        before = watch.get("09:55", {})
        mid = watch.get("10:30", {})
        if before:
            failures.append(f"books were already halted before the fault: {before}")
        if not before and mid:
            evidence.append("books halted while another session held the account: "
                            + ", ".join(sorted(mid)))
        elif not mid:
            failures.append(
                "a competing session took the account for half an hour and no book "
                "halted. agent/loop.py catches every snapshot failure inside "
                "snapshot_by_symbol() and turns it into a note, so IBKR code 10197 "
                "is handled exactly like a quote that did not arrive. Nothing reads "
                "the code and nothing halts, so the loop went on managing positions "
                "off the last price it happened to have.")

        if context.alerts.alerts:
            evidence.append("alerts raised: "
                            + ", ".join(a.title for a in context.alerts.alerts))
        else:
            failures.append("nobody was told about the competing session, because "
                            "agent/loop.py has no alert call on any path")

        after = _book_lines(context, "10:35")
        noticed = "market data type" in after or "delayed" in after
        entries_after = [r for r in _entries_placed(context)
                         if str(r.at)[11:16] >= "10:35"]
        if noticed:
            evidence.append("the loop wrote down that the quotes it was working from "
                            "were delayed")
        else:
            failures.append(
                "from 10:35 every quote came back as market data type 3 and the loop "
                "never said so once. Nothing in agent/loop.py reads marketDataType "
                "off a snapshot: snapshot_price() looks at last, marketPrice and "
                "close and no other field, so a delayed quote and a live one are the "
                "same thing to it. That matters more than it sounds, because this "
                "paper account is served delayed data every day.")
        if entries_after:
            evidence.append(f"{len(entries_after)} positions were opened after the "
                            "feed went delayed")
        else:
            evidence.append("no position was opened after the feed went delayed, "
                            "though that is because the day's entry was already made "
                            "at 09:35 and not because the loop noticed")

        return not failures, evidence, failures

    return Scenario(
        key="competing_session_delayed_data",
        title="A competing session, then delayed data",
        proves="that IBKR code 10197 halts a book while it lasts, and that a "
               "position is never quietly opened on a delayed quote",
        day=day, symbols=(name,), build_broker=build,
        book_patches=only("A"),
        faults=(Fault(at="10:00", action="inject", kind="competing_session"),
                Fault(at="10:35", action="clear", kind="competing_session"),
                Fault(at="10:35", action="inject", kind="delayed_data")),
        decider=lambda s: StubDecider(
            max_picks=1,
            script=[ScriptedPick(book="A", symbol=name, at="09:35", side="long",
                                 entry=100.50, stop_pct=1.5)]),
        after_tick=after_tick, check=check,
    )


# ==========================================================================
# (j) A rejected order
# ==========================================================================


def rejected_order(day: date_type) -> Scenario:
    """The broker says no. The loop must not call that a fill, and must not retry.

    The fault clears itself after one order, so exactly one order comes back
    with IBKR's code 201 on it. What matters afterwards is what the book file
    says: no position, no working order, and no second attempt at the same
    thing. And no phantom position, because a rejected order moves nothing, so
    reconciliation has to stay clean through it.
    """

    def check(context: RunContext) -> tuple[bool, list[str], list[str]]:
        evidence: list[str] = []
        failures: list[str] = []

        ok, line = _every_tick_ran(context)
        evidence.append(line)
        if not ok:
            failures.append(line)

        rejected = [o for o in context.broker.orders if o.rejected]
        if rejected:
            first = rejected[0]
            evidence.append(f"one order was rejected: {first.side} {first.qty} "
                            f"{first.symbol} at {first.at[11:16]}, "
                            f"{str(first.error)[:80]}")
        else:
            failures.append(
                "the reject_next_order fault was injected and no order came back "
                "rejected, because the loop never sent one: "
                + _why_no_entry(context, "A")
                + ". Nothing about a rejection was tested, and the reason is "
                  "upstream of this scenario.")
            return False, evidence, failures

        symbol = rejected[0].symbol
        order_ref = rejected[0].order_ref
        state = context.state_for(order_ref)
        held = _positions(context, order_ref)
        if held.get(symbol):
            failures.append(f"{order_ref} believes it holds {held[symbol]} {symbol} "
                            "from an order the broker refused")
        else:
            evidence.append(f"{order_ref} did not treat the rejection as a fill: it "
                            f"holds no {symbol}")

        working = [o for o in (state.working_orders or {}).values()
                   if isinstance(o, dict)
                   and str(o.get("symbol", "")).upper() == symbol
                   and not o.get("is_child")]
        if working:
            failures.append(f"the rejected order was recorded as working: {working}")
        else:
            evidence.append("the rejected order was not recorded as a working order")

        same = [o for o in context.broker.orders
                if o.order_ref == order_ref and o.symbol == symbol
                and o.side == rejected[0].side and o.purpose != "stop"]
        if len(same) > 2:
            failures.append(f"the loop sent {len(same)} orders for {symbol} after the "
                            "rejection, which is a retry loop")
        else:
            evidence.append(f"the loop sent {len(same)} order(s) for {symbol} in "
                            "total, so a rejection is not retried")

        matched, bad = _reconciled_every_tick(context)
        if matched:
            evidence.append("reconciliation matched on every tick, so a rejected "
                            "order left no phantom position behind")
        else:
            failures.append("reconciliation disagreed after a rejection, on ticks "
                            + ", ".join(bad[:4]))

        placed = [r for r in context.ledger.rows
                  if r.payload.get("kind") == "decision"
                  and str(r.payload.get("decision", "")).startswith("placed")
                  and symbol in str(r.payload.get("decision", ""))]
        confirmed_neither = [r for r in placed
                             if "confirmed by neither" in str(r.payload.get("rationale"))]
        if confirmed_neither:
            evidence.append(
                "the ledger row for the rejected order reads 'placed ... The broker "
                "confirmed by neither', which is honest about the outcome but reads "
                "as though the order went out. Worth a plainer word than 'placed' "
                "for a refusal.")

        return not failures, evidence, failures

    return Scenario(
        key="rejected_order",
        title="A rejected order is not a fill, and is not retried",
        proves="that IBKR refusing an order leaves no position, no working order, no "
               "retry loop and no reconciliation mismatch",
        day=day, symbols=("SPY", "QQQ", "AAPL"),
        book_patches=only("A"),
        faults=(Fault(at="09:35", action="inject", kind="reject_next_order"),),
        decider=lambda s: StubDecider(max_picks=1),
        check=check,
    )


# ==========================================================================
# (k) Two books, one symbol, opposite sides
# ==========================================================================


def two_books_one_symbol(day: date_type) -> Scenario:
    """Book A long and book B short the same name, told apart by order_ref.

    This is the whole reason agent/replay/fake_broker.py keeps five sets of
    books. IBKR nets the account and would show one line of PAIR, so the only
    thing that says which book owns what is the tag on the order that opened it.
    Both positions are seeded, because every book's settings say allow_shorts
    false and the loop itself cannot open the short half.

    From 2026-09-06 this is a state the project ALLOWS. The hub retired one
    ticker one book that day: a netted line can be split back apart, because the
    tag on the order says who sent it and each book keeps its own record, and
    forbidding it would have deleted the one signal month one exists to measure,
    which is two independent strategies agreeing on a name.

    What replaced the block is arithmetic. agent/reconcile.py compares, for
    every ticker, the broker's netted line against the SUM of what all the books
    believe they hold in it. Here that is 500 long and 300 short, so the sum is
    200 and the broker's line is 200, and the day carries on. Had they not
    added up, every book holding the ticker would be halted and no other book
    touched.

    So this scenario proves three things: the per book view at the broker tells
    the two apart by order_ref, the book files agree with it, and reconciliation
    adds a shared name up correctly instead of panicking about it.
    """
    name = "PAIR"

    def build(scenario: Scenario):
        series = {name: crafted_bars(day, ramp(day, 100.0, 100.4)),
                  "OTHER": crafted_bars(day, flat(50.0))}
        return crafted_broker(series, daily=daily_history(day, prior_closes(series)))

    def setup(context: RunContext) -> None:
        seed_book_position(context, "A", name, 500, 100.0, stop=90.0, target=500.0,
                           opened_on=f"{day:%Y-%m-%d}")
        seed_book_position(context, "B", name, -300, 100.0, stop=120.0, target=1.0,
                           opened_on=f"{day:%Y-%m-%d}")

    def check(context: RunContext) -> tuple[bool, list[str], list[str]]:
        evidence: list[str] = []
        failures: list[str] = []

        ok, line = _every_tick_ran(context)
        evidence.append(line)
        if not ok:
            failures.append(line)

        # The order_ref half: the broker can still say whose shares are whose,
        # which is what a real IBKR account cannot do and what makes the whole
        # five book arrangement possible in the first place.
        a_view = context.fake.book_positions("BOOK_A")
        b_view = context.fake.book_positions("BOOK_B")
        a_qty = int(a_view[name].qty) if name in a_view else 0
        b_qty = int(b_view[name].qty) if name in b_view else 0
        netted = int(context.fake.positions.get(name, 0))
        evidence.append(f"asked by order_ref, the broker says BOOK_A holds {a_qty} "
                        f"{name} and BOOK_B holds {b_qty}, while the netted account "
                        f"IBKR would show reports a single line of {netted}")

        a_file = _positions(context, "BOOK_A").get(name, 0)
        b_file = _positions(context, "BOOK_B").get(name, 0)
        if a_file == a_qty and b_file == b_qty:
            evidence.append("each book file matches its own view at the broker, so "
                            "every fill was traced back to the book that sent it")
        else:
            failures.append(f"the book files say A holds {a_file} and B holds "
                            f"{b_file}, and the broker's per book view says {a_qty} "
                            f"and {b_qty}")

        every_order_tagged = all(o.order_ref for o in context.broker.orders)
        if every_order_tagged:
            evidence.append(f"all {len(context.broker.orders)} orders carried an "
                            "order_ref")
        else:
            failures.append("an order went out with no order_ref on it")

        # The shared name half. Since 2026-09-06 the question is not whether
        # two books are in one ticker, it is whether their positions add up to
        # what the broker actually holds.
        total = a_file + b_file
        if total == netted:
            evidence.append(f"the two books hold {a_file} and {b_file} of {name}, "
                            f"which adds up to {total}, and the broker's netted "
                            f"line is {netted}, so the shared name reconciles")
        else:
            failures.append(f"the two books hold {a_file} and {b_file} of {name}, "
                            f"which adds up to {total}, and the broker says "
                            f"{netted}")

        halted = context.halted_books()
        if not ({"A", "B"} & set(halted)):
            evidence.append("neither book was halted, which is right: sharing a "
                            "ticker is allowed and the totals agree")
        else:
            failures.append("the shared name adds up and yet these books were "
                            "halted anyway: " + ", ".join(sorted(halted)))

        stacked = _stacked_orders(context)
        if stacked:
            failures.append(
                "the loop stacked the same order over and over: "
                + "; ".join(stacked[:3])
                + ". Book B is short a name whose price rises all day, so the fade "
                "rule fires on every manage tick, and every tick sends a fresh "
                "limit order to cover without ever asking whether the last one is "
                "still working. Nothing in agent/loop.py reads open_orders() before "
                "sending, and nothing cancels. In a live account that is the whole "
                "position resting at the broker once for every five minutes of the "
                "day, and they would all fill together on the first dip.")
        else:
            evidence.append("no order was ever sent twice while an identical one was "
                            "still working")

        entries = _entries_placed(context)
        if entries:
            failures.append(f"{len(entries)} entry orders went out, and the stub "
                            "decider was told to pick nothing for either book")
        else:
            covers = [o for o in context.broker.orders if o.side == "BUY"]
            evidence.append(
                "neither book opened anything, and the "
                f"{len(covers)} buy orders that did go out were book B covering "
                "its short at the flatten")

        return not failures, evidence, failures

    return Scenario(
        key="two_books_one_symbol",
        title="One book long and another short the same name, told apart by order_ref",
        proves="that the per book view at the broker tells two books apart inside one "
               "netted account, and that a shared ticker whose positions add up to "
               "the broker's line reconciles cleanly and halts nobody",
        day=day, symbols=("OTHER",), build_broker=build,
        book_patches=only("A", "B"),
        decider=lambda s: StubDecider(max_picks=1, pick_nothing_for=("A", "B")),
        setup=setup, check=check,
    )


# ==========================================================================
# The register
# ==========================================================================


def all_scenarios(day: date_type = DEFAULT_DAY) -> list[Scenario]:
    """Every scenario the gate runs, in the order docs/REPLAY.md lists them."""
    return [
        clean_day(day),
        fills_from_the_broker(day),
        every_guardrail(day),
        daily_loss_cap(day),
        flatten_at_close(day),
        phantom_position(day),
        kill_switch(day),
        day_trade_counter(day),
        gateway_down(day),
        competing_session_and_delayed_data(day),
        rejected_order(day),
        two_books_one_symbol(day),
    ]


def scenario_keys(day: date_type = DEFAULT_DAY) -> list[str]:
    return [s.key for s in all_scenarios(day)]

#!/usr/bin/env python3
"""The replay gate: the real five book loop, a fake broker, and a whole day.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m agent.replay.harness --all

No book in
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/books.yaml
moves off `dry_run` until this passes. That is the whole job of this file.

What it does, once per scenario:

  1. Builds a sandbox: its own project root with its own config/, strategies/
     and an empty output/. AGENTIC_TRADING_ROOT points at it, so every state
     file, every pdt counter, every packet and every guard file the loop writes
     lands inside the sandbox and never touches
     /Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/.
  2. Puts the books into `full` mode INSIDE THAT SANDBOX COPY, with promoted_on
     and rules_commit stamped so the register loads, and sets
     AGENTIC_TRADING_LIVE_ORDERS=yes for this process only. Both of those exist
     so the live order path in agent/loop.py is actually executed rather than
     skipped, and both are undone when the run ends.
  3. Refuses to start unless the broker really is a FakeBroker. That check is
     the last line of defence and it is not optional: see _refuse_unless_fake.
  4. Steps a FakeBroker through the day at five minute ticks from 09:25 to
     16:05, calling agent/loop.py's own main() at each one with --now set to the
     replayed time, --books-file set to the sandbox register, and the fake
     broker handed in.
  5. Collects everything: orders, fills, guardrail rule ids, reconciliation,
     halts, alerts, day trade counts, ledger rows and the end of day state per
     book, and hands back a GateReport.

Nothing here can reach a real broker.

  * agent/decide.py is swapped for agent/replay/stub_decider.py, so no model is
    called and the gate costs nothing to run.
  * agent/broker.py's McpBroker is replaced, for the duration of the run, with a
    class that raises if anything tries to build one.
  * agent/alerts.py's alert() is captured, so nothing is sent to Slack, iMessage
    or the macOS notification centre.
  * ledger_writer's four writers are captured, so nothing reaches the Google
    Sheet.
  * The MCP order tools are never imported, let alone called.

THE CLOCK, AND WHY IT IS ONE SECOND BEHIND
------------------------------------------
At a tick at 09:35 the last five minute bar that has actually finished is the
one stamped 09:30, which covers 09:30 to 09:35. The bar stamped 09:35 has not
happened yet. So before running the tick at 09:35 the broker is advanced to
09:34:59, not to 09:35. Orders placed at 09:35 then fill against the bar stamped
09:35, on the next advance, which is the first bar after the decision. Advancing
to 09:35 before the tick would let the loop see and fill against a bar from its
own future, and every number the gate produced after that would be worthless.

THE FILL BRIDGE, AND THE HOLE IT COVERS
---------------------------------------
agent/loop.py records a fill in one place only: submit(), from what
place_order() hands straight back. There is no code anywhere in that file that
reads executions() or turns a working order into a position later. Grep it: the
word `executions` does not appear.

Against the real MCP broker a marketable order comes back already filled, so
that mostly works. Against anything that fills a resting order later, including
this harness and including a real limit order that fills at 10:20, the loop
never learns. The position exists at the broker and does not exist in the book
file, reconciliation calls it an orphan, and the day falls apart.

That is a real gap in the loop, not in the harness, and it is reported rather
than quietly patched. But every other scenario needs fills to exist, so the
harness carries a FillBridge that reads the broker's own executions after each
tick and applies them with agent/loop.py's own record_fill(), which is the same
arithmetic the loop would use. It is on by default because otherwise nothing
downstream can be tested, `fill_bridge_used` is written into every report, and
the clean day scenario runs it once with the bridge OFF to prove the gap is
real.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date as date_type, datetime, time as clock_time, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
for _extra in (PROJECT_ROOT / "agent", PROJECT_ROOT / "ledger"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from agent.replay.common import EASTERN                              # noqa: E402
from agent.replay.fake_broker import FakeBroker, FakeBrokerError     # noqa: E402
from agent.replay.stub_decider import StubDecider                    # noqa: E402

REAL_ROOT = PROJECT_ROOT
REAL_BOOKS_YAML = REAL_ROOT / "config" / "books.yaml"
REAL_OUTPUT = REAL_ROOT / "output"

#: The trading day the gate replays, and the window it steps through.
DEFAULT_DAY = date_type(2026, 9, 4)
DAY_START = clock_time(9, 25)
DAY_END = clock_time(16, 5)
TICK_MINUTES = 5

#: The two benchmarks plus the eight liquid names fetch_history.py pulled.
DEFAULT_SYMBOLS = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA",
                   "AMD", "META", "AMZN", "DELL")

#: Stamped onto every book in the sandbox register, because a book set to full
#: without both of these refuses to load. They are fiction and they never leave
#: the sandbox.
SANDBOX_PROMOTED_ON = "2026-09-04"
SANDBOX_RULES_COMMIT = "replaygate"

LIVE_ENV_VAR = "AGENTIC_TRADING_LIVE_ORDERS"
ROOT_ENV_VAR = "AGENTIC_TRADING_ROOT"


# ---------------------------------------------------------------- small things


def eastern(day: date_type, moment: clock_time) -> datetime:
    return datetime.combine(day, moment, tzinfo=EASTERN)


def tick_times(day: date_type, start: clock_time = DAY_START,
               end: clock_time = DAY_END,
               minutes: int = TICK_MINUTES) -> list[datetime]:
    """Every tick of the replayed day, 09:25 to 16:05 inclusive by default."""
    out: list[datetime] = []
    moment = eastern(day, start)
    last = eastern(day, end)
    step = timedelta(minutes=minutes)
    while moment <= last:
        out.append(moment)
        moment += step
    return out


def _number(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if out == out else default


def real_rules_commit() -> str:
    """The short git hash of the real repository, for the report.

    agent/loop.py works this out per tick by shelling out to git in whatever
    project_root() says. In a sandbox that is not a checkout, so it would answer
    "unknown" eighty one times and spawn eighty one processes to do it. The gate
    asks the real repository once and pins the answer.
    """
    try:
        finished = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                  cwd=str(REAL_ROOT), capture_output=True,
                                  text=True, timeout=10)
    except Exception:                            # noqa: BLE001
        return "unknown"
    if finished.returncode != 0:
        return "unknown"
    return finished.stdout.strip() or "unknown"


# --------------------------------------------------------------- the sandbox


@dataclass
class Sandbox:
    """One scenario's own project root. Nothing it writes leaves this folder."""

    root: Path
    books_yaml: Path
    output: Path

    @property
    def stop_file(self) -> Path:
        return self.output / "STOP"

    @property
    def loop_disabled_file(self) -> Path:
        return self.output / "LOOP_DISABLED"

    @property
    def no_trade_file(self) -> Path:
        return self.output / "NO_TRADE_TODAY"


def _patch_yaml_scalar(text: str, key: str, value: str) -> str:
    """Set `key:` to `value` on every line that starts one, keeping the indent.

    A deliberately dumb rewrite rather than a yaml round trip, because
    config/books.yaml is mostly comments explaining why every book is on
    dry_run, and a round trip would throw all of them away. The sandbox copy is
    meant to stay readable when a run goes wrong and somebody opens it.
    """
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{key}:") or stripped.startswith(f"- {key}:"):
            indent = line[:len(line) - len(line.lstrip())]
            dash = "- " if stripped.startswith("- ") else ""
            out.append(f"{indent}{dash}{key}: {value}")
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def build_sandbox(root: Path, *, mode: str = "full",
                  books_yaml: Path | None = None,
                  strategy_overlays: dict[str, dict] | None = None,
                  guardrail_overlay: dict | None = None,
                  book_patches: dict[str, dict] | None = None) -> Sandbox:
    """Make a project root of this scenario's own, and return where things are.

    config/ and strategies/ are copied rather than symlinked, because the whole
    point is that a scenario may edit them (a blacklist, a whitelist, a smaller
    cap) without touching the real files. output/ starts empty.

    agent/ and venv312/ are deliberately NOT copied or linked. agent/loop.py's
    run_helper() looks for both before shelling out to the scanner or a sweep,
    and finding neither it gives up politely and reads whatever shortlist file
    is already there. That is exactly what the gate wants: real shortlist
    reading, no IBKR scanner call, no SEC call, no subprocess at all.
    """
    import yaml                                  # noqa: PLC0415

    root = Path(root)
    if root.exists():
        shutil.rmtree(root)
    (root / "output").mkdir(parents=True)
    shutil.copytree(REAL_ROOT / "config", root / "config",
                    ignore=shutil.ignore_patterns("launchd", "*.ini"))
    shutil.copytree(REAL_ROOT / "strategies", root / "strategies")

    source = Path(books_yaml or REAL_BOOKS_YAML)
    text = source.read_text()
    text = _patch_yaml_scalar(text, "mode", mode)
    text = _patch_yaml_scalar(text, "promoted_on", SANDBOX_PROMOTED_ON)
    text = _patch_yaml_scalar(text, "rules_commit", SANDBOX_RULES_COMMIT)
    target = root / "config" / "books.yaml"
    target.write_text(text)

    if book_patches:
        loaded = yaml.safe_load(target.read_text()) or {}
        for book in loaded.get("books") or []:
            patch = book_patches.get(str(book.get("book_id")))
            if patch:
                book.update(patch)
        target.write_text(yaml.safe_dump(loaded, sort_keys=False))

    for folder, overlay in (strategy_overlays or {}).items():
        path = root / "strategies" / folder / "strategy.yaml"
        loaded = yaml.safe_load(path.read_text()) or {}
        for section, values in overlay.items():
            if isinstance(values, dict) and isinstance(loaded.get(section), dict):
                loaded[section].update(values)
            else:
                loaded[section] = values
        path.write_text(yaml.safe_dump(loaded, sort_keys=False))

    if guardrail_overlay:
        path = root / "config" / "guardrails.yaml"
        loaded = yaml.safe_load(path.read_text()) or {}
        for section, values in guardrail_overlay.items():
            if isinstance(values, dict) and isinstance(loaded.get(section), dict):
                loaded[section].update(values)
            else:
                loaded[section] = values
        path.write_text(yaml.safe_dump(loaded, sort_keys=False))

    return Sandbox(root=root, books_yaml=target, output=root / "output")


# -------------------------------------------------------- capturing the writers


@dataclass
class LedgerRow:
    """One row the loop tried to write to the Google Sheet, kept in memory."""

    tab: str
    at: str
    book_id: str
    payload: dict


class LedgerCapture:
    """Stands in for ledger/ledger_writer.py. Writes nothing anywhere.

    The real module already refuses to write when dry_run is True, and the loop
    passes dry_run=not --write-ledger, so the sheet was never at risk. This
    exists so the gate can read back what would have been written, which is
    where every guardrail rule id and every decision ends up.
    """

    def __init__(self) -> None:
        self.rows: list[LedgerRow] = []

    # The four functions agent/loop.py calls on the module.

    def log_trade(self, row: dict, book_id: Any = None, model: Any = None,
                  **kwargs) -> bool:
        self.rows.append(LedgerRow("Trades", str(row.get("at") or ""),
                                   str(book_id or ""), dict(row)))
        return True

    def log_decision(self, timestamp: Any, symbol: str, decision: str,
                     rationale: str, book_id: Any = None, **kwargs) -> bool:
        self.rows.append(LedgerRow(
            "Rules", str(timestamp), str(book_id or ""),
            {"kind": "decision", "symbol": symbol, "decision": decision,
             "rationale": rationale, **{k: v for k, v in kwargs.items()
                                        if k in ("mode", "model", "prompt_hash")}}))
        return True

    def log_rule(self, timestamp: Any, rule_id: str, detail: str, action: str,
                 book_id: Any = None, **kwargs) -> bool:
        self.rows.append(LedgerRow(
            "Rules", str(timestamp), str(book_id or ""),
            {"kind": "rule", "rule_id": str(rule_id), "detail": detail,
             "action": action}))
        return True

    def upsert_daily(self, date: Any, **kwargs) -> bool:
        self.rows.append(LedgerRow("Daily", str(date), "",
                                   {"kind": "daily", **kwargs}))
        return True

    # -- reading it back --------------------------------------------------

    @property
    def rule_hits(self) -> list[LedgerRow]:
        return [r for r in self.rows if r.payload.get("kind") == "rule"]

    def rule_ids(self, book_id: str | None = None) -> set[str]:
        return {str(r.payload.get("rule_id")) for r in self.rule_hits
                if book_id is None or r.book_id == book_id}

    def rows_for_rule(self, rule_id: str) -> list[LedgerRow]:
        return [r for r in self.rule_hits if r.payload.get("rule_id") == rule_id]


@dataclass
class CapturedAlert:
    level: str
    title: str
    body: str


class AlertCapture:
    """Stands in for agent/alerts.py's alert(). Sends nothing, remembers everything."""

    def __init__(self) -> None:
        self.alerts: list[CapturedAlert] = []

    def alert(self, level: str, title: str, body: str) -> list[str]:
        self.alerts.append(CapturedAlert(str(level), str(title), str(body)))
        return ["captured"]

    def titles(self) -> list[str]:
        return [a.title for a in self.alerts]


# ----------------------------------------------------------- the broker adapter


class ForbiddenBroker:
    """What agent/broker.py's McpBroker is replaced with during a gate run.

    If anything in the loop, or anything the loop imports, tries to build a real
    broker while the gate is running, it gets this and the run stops with a loud
    message rather than quietly opening a connection to IB Gateway.
    """

    def __init__(self, *args, **kwargs):
        raise AssertionError(
            "the replay gate tried to build a real McpBroker. Nothing in a gate "
            "run may talk to IB Gateway or the MCP server. This is a bug in the "
            "harness, not something to work around.")


@dataclass
class PlacedOrder:
    """One order the loop actually sent, in the gate's own words.

    `at` is the fake broker's clock, which sits one second before the tick that
    sent the order, for the reason in this file's opening notes.

    There is no purpose field, because agent/loop.py's submit() does not put one
    on the order it hands the broker: the dictionary it builds carries action,
    totalQuantity, orderType, tif and a limit price and nothing else. Why an
    order was sent lives in the ledger rows instead, where every decision reads
    "... (purpose: entry)" or exit or flatten. An order type of MKT is a
    give away on its own, since do_flatten() is the only place in the loop that
    sends one.
    """

    at: str
    book_id: str
    order_ref: str
    symbol: str
    side: str
    qty: int
    order_type: str
    limit_price: float | None
    order_id: Any
    status: str
    rejected: bool
    error: str | None
    #: "stop" or "target" for a bracket's children, empty for anything else.
    #: The loop's own order dictionary carries no purpose, so this is the one
    #: thing the gate knows that the order itself does not say.
    purpose: str = ""


@dataclass
class SeenFill:
    at: str
    order_ref: str
    symbol: str
    side: str
    shares: int
    price: float
    commission: float
    exec_id: str
    reason: str


class ReplayBroker:
    """A Broker for agent/loop.py, sitting on top of a FakeBroker.

    Two jobs, and only two.

    ONE. Translate the order answer. agent/broker.py's protocol says
    place_order returns sent, order_id, filled_qty, avg_fill_price, working,
    error, raw and confirmed_by. agent/replay/fake_broker.py returns IBKR's own
    words instead: status, filled, avgFillPrice, rejected. Handed the raw fake
    answer, agent/loop.py's submit() reads filled_qty as nothing and working as
    nothing, falls into its last branch and writes down that the broker neither
    filled nor is working, which is wrong in both directions. So the shapes are
    translated here. That mismatch is worth knowing about on its own:
    docs/REPLAY.md claims the fake broker is a drop in for the protocol, and for
    the six read methods it is, but not for place_order.

    TWO. Write down every order, cancel and fill that went past, so the gate
    report can show its working.

    Every read is passed straight through untouched, faults and all, because the
    whole point is that the loop meets the fake broker's real behaviour.
    """

    #: The order statuses agent/replay/fake_broker.py counts as still live.
    LIVE_STATUSES = frozenset({"Submitted", "Triggered", "PartiallyFilled"})

    def __init__(self, fake: FakeBroker, clock: Callable[[], datetime | None]):
        _refuse_unless_fake(fake)
        self.fake = fake
        self._clock = clock
        self.orders: list[PlacedOrder] = []
        self.cancels: list[dict] = []
        self.global_cancels = 0
        self.read_failures: list[str] = []

    # -- reads, straight through -----------------------------------------

    def account_summary(self, account: str | None = None) -> dict:
        return self.fake.account_summary(account)

    def portfolio(self, account: str | None = None, include_pnl: bool = True) -> dict:
        return self.fake.portfolio(account, include_pnl)

    def open_orders(self, account: str | None = None, include_all: bool = True) -> dict:
        return self.fake.open_orders(account, include_all)

    def executions(self, account: str | None = None, symbol: str | None = None,
                   sec_type: str | None = None, exchange: str | None = None,
                   side: str | None = None, time: str | None = None) -> dict:
        return self.fake.executions(account, symbol, sec_type, exchange, side, time)

    def snapshot(self, contracts: list[dict], market_data_type: int = 3) -> dict:
        return self.fake.snapshot(contracts, market_data_type)

    def historical_bars(self, contract: dict, duration: str, bar_size: str,
                        what: str = "TRADES", use_rth: bool = True,
                        end_date_time: str = "") -> dict:
        return self.fake.historical_bars(contract, duration, bar_size, what,
                                         use_rth, end_date_time)

    def is_up(self) -> bool:
        return self.fake.is_up()

    # -- acting -----------------------------------------------------------

    def place_order(self, contract: dict, order: dict, order_ref: str) -> dict:
        raw = self.fake.place_order(contract, order, order_ref)
        self._remember(raw, order_ref)
        return self._translate(raw, order_ref)

    def _translate(self, raw: dict, order_ref: str) -> dict:
        """The fake broker's IBKR words, in the eight keys agent/broker.py promises."""
        status = str(raw.get("status") or "")
        filled = _number(raw.get("filled"))
        rejected = bool(raw.get("rejected"))
        working = status in self.LIVE_STATUSES and filled < _number(
            raw.get("totalQuantity"))
        return {
            "sent": not rejected,
            "order_id": raw.get("orderId"),
            "filled_qty": filled,
            "avg_fill_price": raw.get("avgFillPrice"),
            "working": working,
            "error": raw.get("error"),
            "raw": raw,
            "order_ref": str(order_ref or ""),
            "symbol": str(raw.get("symbol") or ""),
            "confirmed_by": ("executions" if filled > 0
                             else "open_orders" if working else "neither"),
        }

    #: How agent/replay/fake_broker.py spells a refused order.
    REJECTED_STATUS = "Rejected"

    def _remember(self, raw: dict, order_ref: str, purpose: str = "") -> None:
        """Write one order into the gate's own record of what went past.

        The rejected flag has to be worked out twice over. place_order puts it
        on the answer, but Order.as_dict() does not carry it, and a bracket's
        legs are read back out of the broker's own order book rather than off
        the answer. So the status is the fallback, and it is the same fact.
        """
        status = str(raw.get("status") or "")
        rejected = bool(raw.get("rejected")) or status == self.REJECTED_STATUS
        error = raw.get("error")
        if error is None and rejected:
            notes = [str(n) for n in (raw.get("notes") or [])]
            error = notes[-1] if notes else "the broker rejected this order"
        self.orders.append(PlacedOrder(
            at=self._now_text(), book_id=str(order_ref or "").replace("BOOK_", ""),
            order_ref=str(order_ref or ""), symbol=str(raw.get("symbol") or ""),
            side=str(raw.get("side") or ""), qty=int(_number(raw.get("totalQuantity"))),
            order_type=str(raw.get("orderType") or ""),
            limit_price=raw.get("lmtPrice"),
            order_id=raw.get("orderId"), status=status,
            rejected=rejected, error=error, purpose=purpose))

    def bracket_order(self, contract: dict, entry: dict, stop: dict,
                      target: dict | None = None, order_ref: str = "") -> dict:
        """An entry with its stop, and its target when it has one.

        agent/loop.py sends every entry this way since 2026-09-06, so the gate
        has to offer it or the live path it opens would fall over on the first
        pick. The fake broker grew its own bracket_order at the same time, so
        this is the same translation place_order does, with the two extra keys
        the loop reads off a bracket kept on the answer:

            legs        one dict per leg, each with its order id and price
            bracketed   True when the protective children really went out

        Every leg is written into self.orders, so a scenario can count the stop
        and the target as orders in their own right, which at this broker they
        are: the fake broker's children are live from the moment they are
        placed and they are not one cancels the other.
        """
        raw = self.fake.bracket_order(contract, entry, stop, target, order_ref)
        answer = self._translate(raw, order_ref)
        answer["legs"] = list(raw.get("legs") or [])
        answer["bracketed"] = bool(raw.get("bracketed"))

        placed_ids = {o.order_id for o in self.orders}
        for leg in answer["legs"]:
            order_id = leg.get("order_id")
            if order_id in placed_ids:
                continue
            order = self.fake.orders.get(order_id)
            if order is None:
                continue
            self._remember(order.as_dict(), order_ref, purpose=str(leg.get("purpose")))
        return answer

    def cancel_order(self, order_id: Any) -> dict:
        answer = self.fake.cancel_order(int(order_id))
        self.cancels.append({"at": self._now_text(), "order_id": order_id,
                             "answer": answer})
        return answer

    def global_cancel(self) -> dict:
        self.global_cancels += 1
        answer = self.fake.global_cancel()
        self.cancels.append({"at": self._now_text(), "order_id": "all",
                             "answer": answer})
        return answer

    # -- helpers ----------------------------------------------------------

    def _now_text(self) -> str:
        moment = self._clock()
        return moment.isoformat() if moment else ""


def _refuse_unless_fake(broker: Any) -> None:
    """Stop the run dead unless this really is a FakeBroker.

    Called before a single tick runs and again inside the adapter. The gate sets
    AGENTIC_TRADING_LIVE_ORDERS=yes and puts every book into full mode, so the
    live order path in agent/loop.py is genuinely open during a run. The only
    thing standing between that and a real order is which object is on the other
    end, so that is checked rather than assumed.
    """
    if isinstance(broker, ReplayBroker):
        broker = broker.fake
    if not isinstance(broker, FakeBroker):
        raise AssertionError(
            "the replay gate will only run against agent/replay/fake_broker.py's "
            f"FakeBroker, and it was handed a {type(broker).__name__}. Refusing to "
            "run: this harness turns on the live order path, and the only reason "
            "that is safe is that the broker cannot reach IBKR.")


# ------------------------------------------------------------- the fill bridge


class FillBridge:
    """Puts the broker's fills into the book files, because the loop does not.

    agent/loop.py only ever records a fill that place_order() handed straight
    back. A resting order that fills later is never noticed: the position exists
    at the broker and does not exist in the book file, and the next
    reconciliation calls it an orphan.

    This reads the fake broker's own executions after each tick and applies the
    new ones with agent/loop.py's own record_fill(), so the arithmetic is the
    loop's rather than the harness's, and clears the matching working order.

    It is a stand in for a loop feature that does not exist. Every GateReport
    says whether it was used, and the clean day scenario runs once with it
    switched off so the gap is on the record rather than papered over.
    """

    def __init__(self, loop_module, book_state_module, guardrails_module,
                 books_yaml: Path | str | None = None, pdt_module=None):
        self.loop = loop_module
        self.bs = book_state_module
        self.gr = guardrails_module
        self.books_yaml = Path(books_yaml) if books_yaml else None
        self.pdt = pdt_module
        self.seen: set[str] = set()
        self.applied: list[SeenFill] = []
        self._guards: dict[str, Any] = {}
        self._counters: dict[str, Any] = {}

    def guard_for(self, book_id: str):
        """This book's real settings, loaded once and kept.

        record_fill() in agent/loop.py takes the guardrails so it can put a stop
        and a target on a brand new position. Handing it None would leave every
        replayed position with a zero stop, which is the exact hole the loop
        closed on 2026-09-06, so the gate would be testing a world that no
        longer exists.
        """
        if self.books_yaml is None:
            return None
        if book_id not in self._guards:
            try:
                self._guards[book_id] = self.gr.load_book_guardrails(
                    str(self.books_yaml), book_id)
            except Exception:                    # noqa: BLE001
                self._guards[book_id] = None
        return self._guards[book_id]

    def counter_for(self, book_id: str):
        """This book's day trade counter, or None when agent/pdt.py is missing.

        The loop only tells the counter about a fill that place_order handed
        straight back, the same gap this whole class covers. Without this the
        day trade scenario could never see a round trip, because nothing would
        ever have told the counter about the opening half of one.
        """
        if self.pdt is None:
            return None
        if book_id not in self._counters:
            guard = self.guard_for(book_id)
            try:
                self._counters[book_id] = (self.pdt.counter_for(guard)
                                           if guard is not None
                                           else self.pdt.DayTradeCounter(book_id))
            except Exception:                    # noqa: BLE001
                self._counters[book_id] = None
        return self._counters[book_id]

    def apply(self, broker: ReplayBroker, books: Iterable, day: date_type,
              now: datetime) -> list[SeenFill]:
        """Every fill the broker has that no book file knows about yet."""
        fresh: list[SeenFill] = []
        for book in books:
            order_ref = str(book.order_ref)
            try:
                answer = broker.fake.executions(order_ref=order_ref) or {}
            except Exception:                    # noqa: BLE001
                continue
            rows = [r for r in (answer.get("fills") or [])
                    if str(r.get("order_ref") or r.get("orderRef") or "") == order_ref]
            new = [r for r in rows if str(r.get("execId")) not in self.seen]
            if not new:
                continue
            state = self.bs.load_state(book.book_id, order_ref, day,
                                       capital=book.capital_usd)
            for row in new:
                self.seen.add(str(row.get("execId")))
                shares = int(_number(row.get("shares")))
                price = _number(row.get("price"))
                if shares <= 0 or price <= 0:
                    continue
                side = "BUY" if str(row.get("side")).upper() in ("BUY", "BOT") else "SELL"
                intent = self.gr.OrderIntent(
                    symbol=str(row.get("symbol")), side=side, qty=shares,
                    limit_price=round(price, 2), purpose="entry",
                    book_id=book.book_id)
                try:
                    self.loop.record_fill(state, intent, float(shares), price, now,
                                          self.guard_for(book.book_id))
                except TypeError:
                    # The older five argument record_fill, before brackets.
                    self.loop.record_fill(state, intent, float(shares), price, now)
                counter = self.counter_for(book.book_id)
                if counter is not None:
                    try:
                        counter.record_fill(
                            str(row.get("symbol")), side, shares,
                            datetime.fromisoformat(str(row.get("time"))),
                            fill_id=str(row.get("execId") or "") or None)
                    except Exception:            # noqa: BLE001
                        pass
                seen = SeenFill(
                    at=str(row.get("time") or ""), order_ref=order_ref,
                    symbol=str(row.get("symbol")), side=side, shares=shares,
                    price=price, commission=_number(row.get("commission")),
                    exec_id=str(row.get("execId")),
                    reason=str(row.get("reason") or ""))
                fresh.append(seen)
                self.applied.append(seen)
                self._clear_working(state, row)
            self.bs.save_state(state)
        return fresh

    @staticmethod
    def _clear_working(state, row: dict) -> None:
        """Drop the working order this fill belongs to, whole or in part."""
        order_id = str(row.get("orderId") or "")
        held = state.working_orders.get(order_id)
        if not isinstance(held, dict):
            return
        left = int(_number(held.get("remaining"), _number(held.get("qty")))) \
            - int(_number(row.get("shares")))
        if left <= 0:
            state.working_orders.pop(order_id, None)
        else:
            held["remaining"] = left


# ---------------------------------------------------------------- the scenario


@dataclass
class Fault:
    """One fault injected or cleared at one moment of the replayed day."""

    at: str                     # "11:00"
    action: str                 # "inject" or "clear"
    kind: str
    options: dict = field(default_factory=dict)


@dataclass
class Scenario:
    """One thing the gate proves, and everything needed to prove it."""

    key: str
    title: str
    proves: str
    day: date_type = DEFAULT_DAY
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS
    start: clock_time = DAY_START
    end: clock_time = DAY_END
    slow: bool = False
    fill_bridge: bool = True

    #: Builds the FakeBroker. Defaults to the fetched history for `symbols`.
    build_broker: Callable[["Scenario"], FakeBroker] | None = None
    #: The stub decider, or a factory for one.
    decider: Callable[["Scenario"], StubDecider] | None = None

    faults: tuple[Fault, ...] = ()
    strategy_overlays: dict = field(default_factory=dict)
    guardrail_overlay: dict = field(default_factory=dict)
    book_patches: dict = field(default_factory=dict)
    books_mode: str = "full"

    #: Called once with the RunContext after the sandbox exists, before tick one.
    setup: Callable[["RunContext"], None] | None = None
    before_tick: Callable[["RunContext", datetime], None] | None = None
    after_tick: Callable[["RunContext", datetime], None] | None = None
    #: Called once when the day is over, before the report is built. This is
    #: where guardrail probes go, because they need the sandbox still in place.
    finish: Callable[["RunContext"], None] | None = None
    #: Reads the finished RunContext and says pass or fail with its evidence.
    check: Callable[["RunContext"], tuple[bool, list[str], list[str]]] | None = None


# ------------------------------------------------------------------ the report


@dataclass
class TickRecord:
    at: str
    exit_code: int
    orders_placed: int
    fills_applied: int
    rule_ids: list[str]
    reconcile_note: str
    halted_books: list[str]
    problems: list[str]


@dataclass
class GateReport:
    """What one scenario proved, in a shape a person and a JSON file both read."""

    key: str
    title: str
    proves: str
    passed: bool
    day: str
    evidence: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    fill_bridge_used: bool = True
    ticks: int = 0
    orders_placed: int = 0
    fills: int = 0
    rule_ids_fired: list[str] = field(default_factory=list)
    alerts: list[dict] = field(default_factory=list)
    halts: dict = field(default_factory=dict)
    day_trades: dict = field(default_factory=dict)
    ledger_rows: int = 0
    model_cost_usd: float = 0.0
    end_of_day: dict = field(default_factory=dict)
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "key": self.key, "title": self.title, "proves": self.proves,
            "passed": self.passed, "day": self.day,
            "evidence": self.evidence, "failures": self.failures,
            "fill_bridge_used": self.fill_bridge_used, "ticks": self.ticks,
            "orders_placed": self.orders_placed, "fills": self.fills,
            "rule_ids_fired": sorted(self.rule_ids_fired),
            "alerts": self.alerts, "halts": self.halts,
            "day_trades": self.day_trades, "ledger_rows": self.ledger_rows,
            "model_cost_usd": self.model_cost_usd,
            "end_of_day": self.end_of_day, "error": self.error,
        }


# --------------------------------------------------------------- the run itself


class RunContext:
    """Everything one replayed day produced, handed to the scenario's check()."""

    def __init__(self, scenario: Scenario, sandbox: Sandbox, broker: ReplayBroker,
                 ledger: LedgerCapture, alerts: AlertCapture,
                 decider: StubDecider, modules: dict):
        self.scenario = scenario
        self.sandbox = sandbox
        self.broker = broker
        self.fake = broker.fake
        self.ledger = ledger
        self.alerts = alerts
        self.decider = decider
        self.loop = modules["loop"]
        self.bs = modules["book_state"]
        self.gr = modules["guardrails"]
        self.pdt = modules.get("pdt")
        self.day = scenario.day
        self.ticks: list[TickRecord] = []
        self.fills: list[SeenFill] = []
        self.reconcile_notes: list[str] = []
        self.tick_output: dict[str, str] = {}
        self.notes: list[str] = []
        self.bridge: FillBridge | None = None
        self.books: list = []
        #: Rule ids that only fired because a probe pushed a crafted order at
        #: them. Kept apart from the rest so a report can never claim the loop
        #: reached a rule it cannot actually reach.
        self.probed: set[str] = set()

    # -- reading the day back ---------------------------------------------

    def state_for(self, order_ref: str):
        """One book's state file as it stands right now."""
        book = next((b for b in self.books if b.order_ref == order_ref), None)
        if book is None:
            return None
        return self.bs.load_state(book.book_id, order_ref, self.day,
                                  capital=book.capital_usd)

    def positions_for(self, order_ref: str) -> dict:
        state = self.state_for(order_ref)
        return {} if state is None else state.all_positions()

    def rule_ids(self, book_id: str | None = None) -> set[str]:
        return self.ledger.rule_ids(book_id)

    def orders_for(self, order_ref: str) -> list[PlacedOrder]:
        return [o for o in self.broker.orders if o.order_ref == order_ref]

    def text(self, at: str) -> str:
        return self.tick_output.get(at, "")

    def all_text(self) -> str:
        return "\n".join(self.tick_output.values())

    def halted_books(self) -> dict[str, str]:
        out = {}
        for book in self.books:
            state = self.state_for(book.order_ref)
            if state is not None and state.halted:
                out[book.book_id] = str(state.halt_reason or "")
        return out

    def probe_rule(self, book_id: str, intent, account_state=None,
                   note: str = "") -> Any:
        """Push one crafted order through the loop's own consider(), and log it.

        Some guardrail rule ids cannot be reached by the loop's own order flow,
        and that is by design rather than by accident: the loop refuses to build
        an entry outside the entry window, refuses to build one while the stop
        file is there, and sizes every entry through max_shares_for() so it can
        never ask for more than the notional caps allow. Those rules are
        backstops behind a door the loop keeps shut.

        A backstop that is never tested is not a backstop, so the gate pushes a
        crafted order at them through agent/loop.py's real consider(), with the
        real guardrails, the real book state and the real ledger writing. What
        that proves is that the rule and its ledger row work. What it does not
        prove, and the report says so, is that the loop could ever get itself
        into that state.
        """
        book = next((b for b in self.books if b.book_id == book_id), None)
        if book is None:
            raise AssertionError(f"there is no book {book_id} in this run")
        guard = self.gr.load_book_guardrails(self.sandbox.books_yaml, book_id)
        state = self.state_for(book.order_ref)
        now = (account_state.now if account_state is not None
               else datetime.combine(self.day, clock_time(9, 40), tzinfo=EASTERN))
        tick = self.loop.BookTick(book, now, SANDBOX_RULES_COMMIT, False, quiet=True)
        tick.phase = "probe"
        if account_state is None:
            account_state = self.bs.account_state_for(
                state, self.gr, now, guard.account.account_id, False, None)
        guards = self.loop.read_guards(self.sandbox.root)
        with contextlib.redirect_stdout(io.StringIO()):
            decision = self.loop.consider(tick, state, guard, account_state, intent,
                                          self.broker, guards,
                                          extra=note or "guardrail probe")
        self.probed.update(decision.rule_ids)
        self.notes.append(
            f"probe {book_id} {intent.side} {intent.qty} {intent.symbol}: "
            + ("allowed" if decision.allowed
               else "refused by " + ", ".join(decision.rule_ids)))
        return decision

    def account_state(self, book_id: str, **overrides):
        """An AccountState built by hand, for a probe. Every field is a keyword.

        The defaults are a healthy hundred thousand dollar book at 09:40 on the
        replayed day with nothing open, so a probe only has to name the one
        thing it is bending.
        """
        book = next((b for b in self.books if b.book_id == book_id), None)
        guard = self.gr.load_book_guardrails(self.sandbox.books_yaml, book_id)
        fields = {
            "equity": 100_000.0,
            "day_start_equity": 100_000.0,
            "realized_pnl_today": 0.0,
            "unrealized_pnl": 0.0,
            "open_positions": {},
            "pending_order_notional": 0.0,
            "now": datetime.combine(self.day, clock_time(9, 40), tzinfo=EASTERN),
            "kill_switch_present": False,
            "account_id": guard.account.account_id,
            "book_id": book.book_id if book is not None else book_id,
            "gross_exposure": None,
            "entries_opened_today": 0,
        }
        fields.update(overrides)
        return self.gr.AccountState(**fields)

    def guard_for(self, book_id: str):
        """This book's real settings, out of the sandbox register."""
        return self.gr.load_book_guardrails(self.sandbox.books_yaml, book_id)

    def pdt_counter(self, book_id: str):
        """This book's day trade counter, writing into the sandbox output folder."""
        if self.pdt is None:
            return None
        return self.pdt.counter_for(self.guard_for(book_id))

    def orders_at(self, at: str) -> list[PlacedOrder]:
        """Every order sent on one tick, named by its "HH:MM"."""
        return [o for o in self.broker.orders if o.at[11:16] == at]

    def in_play_rule_ids(self) -> set[str]:
        """Rule ids the loop's own order flow reached, with no probe behind them."""
        return self.rule_ids() - self.probed


def _import_project_modules() -> dict:
    """Import the real loop and its neighbours, once, against the real root.

    agent/loop.py works out PROJECT at import time and uses it only to build
    sys.path, so it must be imported while AGENTIC_TRADING_ROOT still points at
    the real checkout. Everything it does at run time asks again, which is what
    lets the sandbox take over afterwards.
    """
    import book_state                            # noqa: PLC0415
    import broker as broker_mod                  # noqa: PLC0415
    import guardrails                            # noqa: PLC0415
    import loop                                  # noqa: PLC0415
    modules = {"loop": loop, "book_state": book_state, "guardrails": guardrails,
               "broker_mod": broker_mod}
    try:
        import pdt                                # noqa: PLC0415
        modules["pdt"] = pdt
    except Exception:                             # noqa: BLE001
        modules["pdt"] = None
    try:
        import alerts                             # noqa: PLC0415
        modules["alerts"] = alerts
    except Exception:                             # noqa: BLE001
        modules["alerts"] = None
    return modules


def default_broker_for(scenario: Scenario) -> FakeBroker:
    """A FakeBroker holding the fetched past for this scenario's symbols."""
    return FakeBroker.from_history(
        scenario.symbols, account_id="DUT077572",
        starting_cash=500_000.0, default_book_capital=100_000.0)


def seed_position(fake: FakeBroker, order_ref: str, symbol: str, qty: int,
                  avg_cost: float) -> None:
    """Give a book a holding it did not buy during this replay.

    Some scenarios need a position that already exists when the day opens: a
    stock carried overnight that gaps down, a resting long at 15:50, one book
    long and another short the same name. Making the loop buy it first would
    take half a morning of replay and would mix the setting up with the thing
    being tested.

    Both sets of books are moved, the account's netted view and the book's own,
    plus the cash on each side, so agent/replay/fake_broker.py's own reconcile()
    still balances afterwards. Anything less and every scenario using this would
    fail on a reconciliation mismatch it invented itself.
    """
    symbol = str(symbol).upper()
    ref = str(order_ref).strip().upper()
    qty = int(qty)
    cost = float(avg_cost)
    if qty == 0:
        return

    # The book's own set of books. FakeBroker._move_position is the arithmetic
    # the broker itself uses on a fill, and it takes a positions map and a costs
    # map rather than a BookPosition, so the one field is unpacked around it.
    book = fake.book(ref)
    held = fake.book_position(ref, symbol)
    book_qty = {symbol: held.qty}
    book_cost = {symbol: held.avg_cost}
    realized = FakeBroker._move_position(book_qty, book_cost, symbol, qty, cost)
    held.qty = book_qty[symbol]
    held.avg_cost = book_cost[symbol]
    held.realized_pnl += realized
    book.realized_pnl += realized
    book.cash -= qty * cost

    # The netted account, which is all IBKR would ever show.
    fake.realized_pnl += FakeBroker._move_position(
        fake.positions, fake.avg_cost, symbol, qty, cost)
    if not fake.positions.get(symbol):
        fake.positions.pop(symbol, None)
        fake.avg_cost.pop(symbol, None)
    fake.cash -= qty * cost
    fake.last_price.setdefault(symbol, cost)


def seed_book_position(context: "RunContext", book_id: str, symbol: str, qty: int,
                       avg_cost: float, *, stop: float = 0.0, target: float = 0.0,
                       opened_on: str = "", last_close: float | None = None) -> None:
    """Give one book a holding before the replay starts, on both sets of books.

    Three things have to move together or the day falls apart on a
    reconciliation mismatch the scenario invented itself:

      1. the fake broker's netted account, which is all IBKR would ever show,
      2. that book's own position at the fake broker, keyed by order_ref,
      3. the book file agent/loop.py reads, in the sandbox output folder.

    The stop and the target go on the book file's position, because that is
    where agent/loop.py's exit_reason_for() looks for them. Nothing is placed at
    the broker: a seeded position is one that was opened before this replay
    began, so its bracket is not part of what the day is testing.
    """
    book = next((b for b in context.books if b.book_id == str(book_id).upper()), None)
    if book is None:
        raise AssertionError(f"there is no enabled book {book_id} in this run")
    symbol = str(symbol).upper()
    qty = int(qty)
    cost = float(avg_cost)

    seed_position(context.fake, book.order_ref, symbol, qty, cost)

    state = context.bs.load_state(book.book_id, book.order_ref, context.day,
                                  capital=book.capital_usd)
    held = state.position(symbol)
    signed = float(qty)
    if held is None:
        held = context.bs.Position(
            symbol=symbol, qty=signed, avg_cost=cost,
            opened_on=opened_on or "", entry=cost,
            side="short" if signed < 0 else "long",
            trailing_high_or_low=cost, stop=float(stop), target=float(target))
    else:
        held.qty += signed
    held.last_close = float(last_close if last_close is not None else cost)
    held.market_value = round(held.last_close * held.qty, 2)
    state.put_position(held)
    state.cash = round(float(state.cash) - signed * cost, 2)
    if not state.day_start_equity:
        state.day_start_equity = float(book.capital_usd)
    context.bs.save_state(state)
    context.notes.append(
        f"seeded book {book.book_id} with {qty} {symbol} at {cost:.2f}"
        + (f", stop {float(stop):.2f}" if stop else ""))


def seed_day_trades(context: "RunContext", book_id: str, count: int,
                    symbol: str = "SEEDED") -> int:
    """Put finished round trips into one book's day trade file, dated earlier this week.

    The pattern day trader rule counts four in five business days, so a scenario
    that wants to see the fourth one refused has to start from three. Making the
    loop actually trade three round trips would take three replayed days it does
    not have. Each pair is a buy and a sell on the same earlier business day,
    which is exactly what the counter counts.
    """
    if context.pdt is None:
        return 0
    counter = context.pdt_counter(book_id)
    if counter is None:
        return 0
    days = context.pdt.business_days_back(context.day, int(count) + 1)
    made = 0
    for index, day in enumerate(days[:-1]):      # every day but today
        if made >= int(count):
            break
        when = datetime.combine(day, clock_time(11, 0), tzinfo=EASTERN)
        counter.record_fill(symbol, "BUY", 10, when, fill_id=f"seed-{index}-buy")
        counter.record_fill(symbol, "SELL", 10, when + timedelta(minutes=5),
                            fill_id=f"seed-{index}-sell")
        made += 1
    context.notes.append(
        f"seeded book {book_id} with {made} day trades before today, so the counter "
        f"reads {counter.count_last_5_business_days(context.day)}")
    return made


def bar(day: date_type, moment: clock_time, open_: float, high: float, low: float,
        close: float, volume: float = 500_000.0) -> dict:
    """One five minute bar, in the shape agent/replay/common.py writes them."""
    when = datetime.combine(day, moment, tzinfo=EASTERN)
    return {"time": when.isoformat(), "open": open_, "high": high, "low": low,
            "close": close, "volume": volume,
            "average": round((high + low) / 2.0, 4), "barCount": 100}


def crafted_broker(series: dict[str, list[dict]], *, daily: dict | None = None,
                   **options) -> FakeBroker:
    """A FakeBroker over bars written by hand rather than recorded.

    Three of the scenarios need a shape the recorded days do not contain: a
    stock that gaps twenty percent through its stop, a name held long by one
    book and short by another, a position that is still open at 15:50. Real bars
    cannot be asked to do that on demand, so those scenarios craft their own and
    say so in the report. Everything else in the gate runs on real recorded
    bars.
    """
    settings = {"account_id": "DUT077572", "starting_cash": 500_000.0,
                "default_book_capital": 100_000.0}
    settings.update(options)
    return FakeBroker(bars=series,
                      bar_series={"5 mins": series, "1 day": daily or {}},
                      **settings)


def synthetic_shortlist(broker: FakeBroker, day: date_type,
                        symbols: Iterable[str]) -> list[dict]:
    """The scanner's answer, worked out from the recorded bars instead.

    The real scanner talks to IBKR's scanner service, which a replay cannot and
    should not do. So the gate builds the same shape of answer out of the bars
    it already has: rank the recorded names by how far they moved from the prior
    close to 09:35, and by how much traded in the first five minutes.

    That is deliberately the scanner's own idea in miniature, not a copy of it.
    It gives the momentum books real candidates on a real day, and it is honest
    about being an approximation: nothing here proves the scanner works, only
    that the loop does something sensible with a shortlist.
    """
    rows: list[dict] = []
    for symbol in symbols:
        symbol = str(symbol).upper()
        opening = [b for b in broker.bar_series.get("5 mins", {}).get(symbol, [])
                   if str(b.get("time", ""))[:10] == f"{day:%Y-%m-%d}"]
        if not opening:
            continue
        first = opening[0]
        daily = broker.bar_series.get("1 day", {}).get(symbol, [])
        prior = [b for b in daily if str(b.get("time", ""))[:10] < f"{day:%Y-%m-%d}"]
        prior_close = _number(prior[-1].get("close")) if prior else 0.0
        minute = [b for b in broker.bar_series.get("1 min", {}).get(symbol, [])
                  if str(b.get("time", ""))[:10] == f"{day:%Y-%m-%d}"]
        window = minute or [first]
        high = max(_number(b.get("high")) for b in window)
        low = min(_number(b.get("low")) for b in window if _number(b.get("low")) > 0)
        close = _number(first.get("close"))
        volume = _number(first.get("volume"))
        gain = ((close / prior_close - 1.0) * 100.0) if prior_close > 0 else 0.0
        rows.append({
            "symbol": symbol,
            "last": round(close, 2),
            "last_close": round(close, 2),
            "prior_close": round(prior_close, 2),
            "gain_pct": round(gain, 3),
            "volume": int(volume),
            "opening_range_high": round(high, 2),
            "opening_range_low": round(low, 2),
            "avg_daily_dollar_volume": int(
                sum(_number(b.get("volume")) * _number(b.get("close"))
                    for b in daily[-20:]) / max(1, len(daily[-20:]))),
            "source": "replay gate, built from the recorded bars",
        })
    # Rank by the size of the move first, then by what traded, then by name so
    # two runs of the same day produce the same order.
    rows.sort(key=lambda r: (-abs(r["gain_pct"]), -r["volume"], r["symbol"]))
    for place, row in enumerate(rows, start=1):
        row["score"] = round(100.0 - place, 3)
        row["rank"] = place
    return rows


def synthetic_sweep(rows: list[dict], kind: str) -> list[dict]:
    """A filing sweep's answer, in the shape the real sweeps write it.

    Both sweeps key their rows on "ticker" rather than "symbol", because that is
    the word the SEC and the House Clerk use, and agent/loop.py's
    normalise_candidate() translates. Using the sweep's own spelling here means
    that translation is exercised rather than bypassed.
    """
    out = []
    for place, row in enumerate(rows[:6], start=1):
        entry = {"ticker": row["symbol"], "score": round(90.0 - place, 3),
                 "source": f"replay gate synthetic {kind} sweep"}
        if kind == "insider":
            entry.update({"issuer_name": f"{row['symbol']} Inc",
                          "cluster_count": 3, "insider_title": "CEO",
                          "buy_usd": 250000})
        else:
            entry.update({"asset_description": f"{row['symbol']} common stock",
                          "crowd_count": 2, "representative": "A Member",
                          "amount": "$50,001 - $100,000"})
        out.append(entry)
    return out


def run_day(recording_or_history: Any, books_yaml: Path | str,
            scenario: Scenario, output_root: Path | str) -> GateReport:
    """Replay one whole day for one scenario and say whether it passed.

    recording_or_history says where the bars come from: a FakeBroker built by
    the caller, the string "history" for the fetched past under
    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/recordings/history/,
    or a date for one recorded day under output/recordings/<day>/.

    books_yaml is the real register the sandbox copy is made from.
    output_root is the folder the sandbox is built inside. Nothing is written
    outside it.
    """
    modules = _import_project_modules()
    loop = modules["loop"]
    bs = modules["book_state"]
    gr = modules["guardrails"]
    broker_mod = modules["broker_mod"]

    sandbox = build_sandbox(
        Path(output_root) / scenario.key, mode=scenario.books_mode,
        books_yaml=books_yaml, strategy_overlays=scenario.strategy_overlays,
        guardrail_overlay=scenario.guardrail_overlay,
        book_patches=scenario.book_patches)

    fake = _broker_from(recording_or_history, scenario)
    _refuse_unless_fake(fake)
    replay = ReplayBroker(fake, lambda: fake.now)

    ledger = LedgerCapture()
    alerts = AlertCapture()
    decider = (scenario.decider(scenario) if scenario.decider is not None
               else StubDecider())

    report = GateReport(key=scenario.key, title=scenario.title,
                        proves=scenario.proves, passed=False,
                        day=f"{scenario.day:%Y-%m-%d}",
                        fill_bridge_used=scenario.fill_bridge)

    saved_env = {ROOT_ENV_VAR: os.environ.get(ROOT_ENV_VAR),
                 LIVE_ENV_VAR: os.environ.get(LIVE_ENV_VAR)}
    saved_decide = loop.decide_mod
    saved_ledger = loop.ledger_writer
    saved_mcp = broker_mod.McpBroker
    alerts_module = modules.get("alerts")
    saved_alert = getattr(alerts_module, "alert", None) if alerts_module else None
    saved_commit = loop.rules_commit

    context = RunContext(scenario, sandbox, replay, ledger, alerts, decider, modules)

    try:
        os.environ[ROOT_ENV_VAR] = str(sandbox.root)
        # Opened here and nowhere else, and only while the broker above is a
        # FakeBroker. The finally block below always puts it back.
        os.environ[LIVE_ENV_VAR] = "yes"
        loop.decide_mod = decider
        loop.ledger_writer = ledger
        loop.rules_commit = lambda: SANDBOX_RULES_COMMIT
        broker_mod.McpBroker = ForbiddenBroker
        if alerts_module is not None:
            alerts_module.alert = alerts.alert

        registry = gr.load_books(sandbox.books_yaml)
        context.books = list(registry.enabled_books())
        context.bridge = (FillBridge(loop, bs, gr, sandbox.books_yaml,
                                     modules.get("pdt"))
                          if scenario.fill_bridge else None)

        _write_shortlists(context, fake)
        if scenario.setup is not None:
            scenario.setup(context)

        # One long step from wherever the recording starts to just before the
        # first tick, so the earlier sessions are consumed with nothing resting.
        first = eastern(scenario.day, scenario.start)
        if fake.now is None or fake.now < first - timedelta(seconds=1):
            fake.advance_to(first - timedelta(seconds=1))

        for moment in tick_times(scenario.day, scenario.start, scenario.end):
            _apply_faults(fake, scenario, moment)
            if fake.now is None or fake.now <= moment - timedelta(seconds=1):
                fake.advance_to(moment - timedelta(seconds=1))

            # The bridge runs BEFORE the tick, not after, because that is where
            # the loop's own fill ingestion would sit: the bars ran, the resting
            # orders filled, and the book files have to say so before the loop
            # reconciles them against the broker. Running it after the tick
            # leaves every filled order looking, for one whole tick, like a
            # working order the broker has lost, and reconciliation halts the
            # book for it.
            fresh: list[SeenFill] = []
            if context.bridge is not None:
                fresh = context.bridge.apply(replay, context.books, scenario.day,
                                             moment)
                context.fills.extend(fresh)

            if scenario.before_tick is not None:
                scenario.before_tick(context, moment)

            before_orders = len(replay.orders)
            buffer = io.StringIO()
            try:
                with contextlib.redirect_stdout(buffer):
                    code = loop.main(["--now", f"{moment:%Y-%m-%d %H:%M}",
                                      "--books-file", str(sandbox.books_yaml)],
                                     broker=replay)
            except Exception as exc:              # noqa: BLE001
                code = -1
                buffer.write(f"\nTHE TICK RAISED {type(exc).__name__}: {exc}\n")

            text = buffer.getvalue()
            at = f"{moment:%H:%M}"
            context.tick_output[at] = text
            context.ticks.append(TickRecord(
                at=at, exit_code=int(code),
                orders_placed=len(replay.orders) - before_orders,
                fills_applied=len(fresh),
                rule_ids=sorted(ledger.rule_ids()),
                reconcile_note=_reconcile_note(text),
                halted_books=sorted(context.halted_books()),
                problems=[line.strip() for line in text.splitlines()
                          if "note:" in line and "could not" in line]))

            if scenario.after_tick is not None:
                scenario.after_tick(context, moment)

        if scenario.finish is not None:
            scenario.finish(context)

        # One last step past the end, so an order placed on the final tick still
        # gets its chance to fill and show up in the end of day figures.
        last = eastern(scenario.day, scenario.end) + timedelta(minutes=TICK_MINUTES)
        with contextlib.suppress(FakeBrokerError):
            fake.advance_to(last)
        if context.bridge is not None:
            context.fills.extend(context.bridge.apply(
                replay, context.books, scenario.day,
                eastern(scenario.day, scenario.end)))

        report.ticks = len(context.ticks)
        report.orders_placed = len(replay.orders)
        report.fills = len(fake.fills)
        report.rule_ids_fired = sorted(ledger.rule_ids())
        report.alerts = [{"level": a.level, "title": a.title} for a in alerts.alerts]
        report.halts = context.halted_books()
        report.ledger_rows = len(ledger.rows)
        report.model_cost_usd = round(
            sum(_number(getattr(c, "cost", 0.0)) for c in decider.calls), 6)
        report.day_trades = {b.order_ref: fake.day_trade_count(b.order_ref)
                             for b in context.books}
        report.end_of_day = _end_of_day(context)

        if scenario.check is None:
            report.passed = True
            report.evidence.append("no check was written for this scenario")
        else:
            passed, evidence, failures = scenario.check(context)
            report.passed = bool(passed) and not failures
            report.evidence = list(evidence)
            report.failures = list(failures)
    except Exception as exc:                      # noqa: BLE001
        import traceback
        report.passed = False
        report.error = f"{type(exc).__name__}: {exc}"
        report.failures.append(f"the scenario raised: {report.error}")
        report.failures.append(traceback.format_exc().splitlines()[-3:][0])
    finally:
        loop.decide_mod = saved_decide
        loop.ledger_writer = saved_ledger
        loop.rules_commit = saved_commit
        broker_mod.McpBroker = saved_mcp
        if alerts_module is not None and saved_alert is not None:
            alerts_module.alert = saved_alert
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    return report


def _broker_from(source: Any, scenario: Scenario) -> FakeBroker:
    if isinstance(source, FakeBroker):
        return source
    if callable(source):
        return source(scenario)
    if scenario.build_broker is not None:
        return scenario.build_broker(scenario)
    if isinstance(source, (date_type, str)) and str(source) != "history":
        return FakeBroker.from_recording(source, account_id="DUT077572",
                                         starting_cash=500_000.0)
    return default_broker_for(scenario)


def _apply_faults(fake: FakeBroker, scenario: Scenario, moment: datetime) -> None:
    for fault in scenario.faults:
        if fault.at != f"{moment:%H:%M}":
            continue
        if fault.action == "inject":
            fake.inject_fault(fault.kind, **fault.options)
        else:
            fake.clear_fault(fault.kind)


def _write_shortlists(context: RunContext, fake: FakeBroker) -> None:
    """Put the day's three shortlists where the loop will look for them.

    The loop still tries to run the scanner and the sweeps first, and still
    fails to, because the sandbox has no agent/ folder and no venv312. It then
    reads the file anyway, which is the path a real tick takes when a sister
    book has already run the scanner.
    """
    day = context.day
    rows = synthetic_shortlist(fake, day, context.scenario.symbols)
    output = context.sandbox.output
    (output / f"shortlist_{day:%Y-%m-%d}.json").write_text(
        json.dumps({"generated_at": f"{day:%Y-%m-%d}T09:35:00-04:00",
                    "source": "replay gate", "candidates": rows}, indent=2))
    (output / f"insider_shortlist_{day:%Y-%m-%d}.json").write_text(
        json.dumps({"candidates": synthetic_sweep(rows, "insider")}, indent=2))
    (output / f"congress_shortlist_{day:%Y-%m-%d}.json").write_text(
        json.dumps({"candidates": synthetic_sweep(rows, "congress")}, indent=2))

    # agent/loop.py's _fresh_enough() compares the file's modification time
    # against the tick's clock, and the replayed clock is a past Friday while
    # the file was written a moment ago. Left alone every scan tick would read
    # the age as negative, call the file stale and try to run the real scanner.
    # It would fail safely, because the sandbox holds no agent/ folder, but the
    # gate would then be testing the failure path rather than the normal one,
    # where a sister book has already written the shortlist.
    written_at = (eastern(day, clock_time(9, 31)) - timedelta(minutes=1)).timestamp()
    for path in sorted(output.glob("*shortlist_*.json")):
        os.utime(path, (written_at, written_at))
    context.notes.append(f"wrote a {len(rows)} name shortlist for {day:%Y-%m-%d}")


def _reconcile_note(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("Reconciliation:"):
            return line.split(":", 1)[1].strip()
    return ""


def _end_of_day(context: RunContext) -> dict:
    out = {}
    for book in context.books:
        state = context.state_for(book.order_ref)
        if state is None:
            continue
        summary = context.fake.book_summary(book.order_ref)
        out[book.order_ref] = {
            "book_id": book.book_id,
            "mode": str(book.mode),
            "halted": bool(state.halted),
            "halt_reason": state.halt_reason,
            "book_file_positions": {s: int(round(p.qty))
                                    for s, p in state.all_positions().items()},
            "broker_positions": {p["symbol"]: int(p["position"])
                                 for p in summary["positions"]},
            "entries_opened_today": int(state.entries_opened_today),
            "realized_pnl_today": round(_number(state.realized_pnl_today), 2),
            "broker_realized_net": round(_number(summary["realized_pnl_net"]), 2),
            "model_cost_today": round(_number(state.model_cost_today), 6),
            "picks": len(state.picks),
        }
    return out


# ---------------------------------------------------------------------- the CLI


def summarise(reports: list[GateReport]) -> str:
    """The plain language version, the one a person actually reads."""
    lines = ["THE REPLAY GATE", ""]
    passed = [r for r in reports if r.passed]
    lines.append(f"{len(passed)} of {len(reports)} scenarios passed.")
    if len(passed) != len(reports):
        lines.append("At least one scenario failed, so no book may be promoted.")
    else:
        lines.append("Every scenario passed on this recording.")
    lines.append("")
    for report in reports:
        mark = "PASS" if report.passed else "FAIL"
        lines.append(f"{mark}  {report.key}  {report.title}")
        lines.append(f"      what it proves: {report.proves}")
        for line in report.evidence:
            lines.append(f"      + {line}")
        for line in report.failures:
            lines.append(f"      ! {line}")
        if not report.fill_bridge_used:
            lines.append("      (ran with the fill bridge OFF, so this is the loop "
                         "exactly as it stands)")
        lines.append("")
    fired: set[str] = set()
    for report in reports:
        fired.update(report.rule_ids_fired)
    lines.append(f"Guardrail rule ids seen across every scenario: "
                 f"{', '.join(sorted(fired)) or 'none'}")
    spent = round(sum(r.model_cost_usd for r in reports), 6)
    lines.append(f"Model spend for the whole gate: {spent:.6f} dollars")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the replay gate: the real five book loop against the "
                    "fake broker on recorded data. No order can leave this "
                    "machine and no model is called.")
    parser.add_argument("--all", action="store_true",
                        help="run every scenario, which is the point of the gate")
    parser.add_argument("--scenario", metavar="KEY", action="append",
                        help="run one scenario by its key, repeatable")
    parser.add_argument("--list", action="store_true", help="list the scenarios")
    parser.add_argument("--fast", action="store_true",
                        help="skip the scenarios marked slow")
    parser.add_argument("--day", default=f"{DEFAULT_DAY:%Y-%m-%d}",
                        help="which recorded session to replay. Default: %(default)s")
    parser.add_argument("--out", default=None,
                        help="where the JSON report goes. Default: "
                             "output/replay_gate_<today>.json")
    parser.add_argument("--sandbox-root", default=None,
                        help="where the per scenario sandboxes are built. Default: "
                             "output/replay_sandbox/")
    args = parser.parse_args(argv)

    from agent.replay import scenarios as scenarios_mod   # noqa: PLC0415

    day = datetime.strptime(args.day, "%Y-%m-%d").date()
    every = scenarios_mod.all_scenarios(day=day)

    if args.list:
        for scenario in every:
            mark = " (slow)" if scenario.slow else ""
            print(f"{scenario.key:24s} {scenario.title}{mark}")
            print(f"{'':24s} proves: {scenario.proves}")
        return 0

    wanted = every
    if args.scenario:
        keys = {k.strip() for k in args.scenario}
        wanted = [s for s in every if s.key in keys]
        missing = keys - {s.key for s in wanted}
        if missing:
            print(f"harness: no scenario called {', '.join(sorted(missing))}",
                  file=sys.stderr)
            return 2
    elif not args.all:
        parser.error("pass --all to run the gate, or --scenario KEY, or --list")
    if args.fast:
        wanted = [s for s in wanted if not s.slow]

    sandbox_root = Path(args.sandbox_root or (REAL_OUTPUT / "replay_sandbox"))
    sandbox_root.mkdir(parents=True, exist_ok=True)

    reports: list[GateReport] = []
    for scenario in wanted:
        print(f"running {scenario.key}: {scenario.title}", flush=True)
        report = run_day("history", REAL_BOOKS_YAML, scenario, sandbox_root)
        reports.append(report)
        print(f"  {'PASS' if report.passed else 'FAIL'}"
              f"  {report.ticks} ticks, {report.orders_placed} orders, "
              f"{report.fills} fills", flush=True)
        for line in report.failures:
            print(f"  ! {line}", flush=True)

    summary = summarise(reports)
    payload = {
        "generated_at": datetime.now(EASTERN).isoformat(),
        "rules_commit": real_rules_commit(),
        "day_replayed": f"{day:%Y-%m-%d}",
        "passed": all(r.passed for r in reports),
        "scenarios": [r.as_dict() for r in reports],
        "summary": summary,
    }
    out = Path(args.out or (REAL_OUTPUT /
                            f"replay_gate_{datetime.now(EASTERN):%Y-%m-%d}.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str))

    print("\n" + summary)
    print(f"\nReport written to {out}")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

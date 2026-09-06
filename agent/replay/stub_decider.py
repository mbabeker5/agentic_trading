#!/usr/bin/env python3
"""A decide() that costs nothing, never varies, and can be told exactly what to say.

The real decision step is
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/decide.py. It
renders a prompt and calls a model through OpenRouter. That is exactly what the
replay gate must not do: a gate that costs money every time it runs will not be
run, and a gate whose answer changes between runs cannot tell you whether a
change to the loop broke something.

So the gate swaps decide() for the one in this file. It hands back the same
DecisionResult that agent/decide.py hands back, it is imported from that same
module so the two cannot drift apart, and it does two jobs:

  1. On its own, it ranks the shortlist by score and picks the top few. That is
     enough to give the momentum books real candidates on a replayed day.
  2. A scenario can script exact decisions, so a test can say "at 10:05, book A
     picks AAPL long with a 1.5 percent stop" and be certain that is what
     happens. Without that, forcing the loop into the exact situation a
     scenario wants to test would mean hoping the recorded bars happen to
     produce it.

Nothing in this file touches the network. There is no provider, no API key, no
token count and no cost. Every DecisionResult it returns carries cost_usd of
0.0 and model "stub", so a scenario can assert that no model was called by
checking that the day's model spend is exactly zero.

Used like this:

    from agent.replay.stub_decider import StubDecider, ScriptedPick

    decider = StubDecider(script=[
        ScriptedPick(at="10:05", book="A", symbol="AAPL", side="long",
                     stop_pct=1.5),
    ])
    # agent/loop.py holds the real module as loop.decide_mod, so this is the
    # one line that swaps it out:
    loop.decide_mod = decider

`decider.calls` then holds one row per decide() the loop made, which is what
the gate report uses to show that the model path was exercised and cost nothing.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent import decide as real_decide  # noqa: E402
from agent.decide import DecisionResult  # noqa: E402

STUB_MODEL = "stub"

#: What the stub charges. Zero, always, and asserted on by the gate.
STUB_COST = 0.0


def _number(value: Any, default: float | None = None) -> float | None:
    """A float, or the default when the value is missing, empty or not a number."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out != out or out in (float("inf"), float("-inf")):
        return default
    return out


def _hhmm(packet: dict) -> str:
    """The packet's own time as "HH:MM", which is how a script names a moment.

    agent/loop.py stamps every packet with generated_at, an ISO timestamp taken
    from the tick's clock. In a replay that clock is the frozen replay clock, so
    this is the replayed time of day and not the wall clock.
    """
    raw = str((packet or {}).get("generated_at") or "")
    # "2026-09-04T10:05:00-04:00" -> "10:05"
    if "T" in raw and len(raw) >= 16:
        return raw[11:16]
    if " " in raw and len(raw) >= 16:
        return raw[11:16]
    return ""


def _book_of(book: dict, packet: dict) -> str:
    for source in (book or {}, packet or {}):
        for key in ("id", "book", "book_id"):
            value = str((source or {}).get(key) or "").strip().upper()
            if value:
                return value
    return ""


def _price_of(row: dict) -> float | None:
    """The most useful price on a candidate row, in the order the loop prefers."""
    for key in ("last_close", "last", "marketPrice", "close", "price"):
        value = _number((row or {}).get(key))
        if value and value > 0:
            return round(value, 2)
    return None


def _score_of(row: dict) -> float:
    """How good a candidate looks, for ranking. Deterministic and boring.

    The scanner writes "score". The two sweeps do not, so the gain since the
    prior close stands in for it, and a row with neither sorts last. Ties are
    broken by symbol so two runs of the same day rank the same way.
    """
    for key in ("score", "gain_pct", "cluster_size", "crowding"):
        value = _number((row or {}).get(key))
        if value is not None:
            return value
    return 0.0


def _is_short(row: dict) -> bool:
    side = str((row or {}).get("side") or (row or {}).get("direction") or "").lower()
    if side in ("short", "sell"):
        return True
    gain = _number((row or {}).get("gain_pct"))
    return gain is not None and gain < 0


# --------------------------------------------------------------- the script


@dataclass(frozen=True)
class ScriptedPick:
    """One decision a scenario insists on, at one time, for one book.

    `at` is the replayed time of day as "HH:MM", matched against the packet's
    own generated_at, so it lines up with the tick that produced it. Leave `at`
    empty and the pick is made at every pick tick for that book, which is what
    a scenario wants when it does not care which tick it lands on.

    `entry` may be left as None, in which case the candidate's own last price is
    used, or the price in `entry_from`, which is the field on the candidate row
    to read the entry off. `stop_pct` and `target_pct` are percentages away from
    the entry, in the direction that makes sense for the side, so a scenario can
    say "stop 1.5 percent" without doing the arithmetic.
    """

    book: str
    symbol: str
    side: str = "long"
    at: str = ""
    entry: float | None = None
    entry_from: str = ""
    stop: float | None = None
    stop_pct: float | None = 1.5
    target: float | None = None
    target_pct: float | None = None
    target_r_multiple: float = 2.0
    qty_hint: int = 0
    rationale: str = "scripted by the replay scenario"

    @property
    def short(self) -> bool:
        return str(self.side).lower() in ("short", "sell")

    def matches(self, book_id: str, moment: str) -> bool:
        if str(self.book).upper() != str(book_id).upper():
            return False
        return not self.at or self.at == moment

    def build(self, candidates: dict[str, dict]) -> dict | None:
        """Turn the script line into the pick dict agent/loop.py expects."""
        row = candidates.get(self.symbol.upper()) or {}
        entry = self.entry
        if entry is None and self.entry_from:
            entry = _number(row.get(self.entry_from))
        if entry is None:
            entry = _price_of(row)
        if entry is None or entry <= 0:
            return None
        entry = round(float(entry), 2)

        stop = self.stop
        if stop is None and self.stop_pct is not None:
            move = entry * (float(self.stop_pct) / 100.0)
            stop = entry + move if self.short else entry - move
        stop = round(float(stop), 2) if stop is not None else 0.0

        target = self.target
        if target is None and self.target_pct is not None:
            move = entry * (float(self.target_pct) / 100.0)
            target = entry - move if self.short else entry + move
        if target is None and stop:
            risk = abs(entry - stop)
            target = (entry - self.target_r_multiple * risk if self.short
                      else entry + self.target_r_multiple * risk)
        target = round(float(target), 2) if target is not None else 0.0

        return {"symbol": self.symbol.upper(),
                "side": "short" if self.short else "long",
                "entry": entry, "stop": stop, "target": target,
                "qty_hint": int(self.qty_hint or 0),
                "rationale": self.rationale}


@dataclass(frozen=True)
class ScriptedExit:
    """A manage decision a scenario insists on: close this, or hold it.

    agent/loop.py reads `action` off each row and only acts on the word "exit".
    Anything else is written down beside whatever the rules decided, which is
    why "hold" is a useful thing to script: it proves the loop's own stop and
    target still close a position that the model wanted kept.
    """

    book: str
    symbol: str
    action: str = "exit"
    at: str = ""
    rationale: str = "scripted by the replay scenario"

    def matches(self, book_id: str, moment: str) -> bool:
        if str(self.book).upper() != str(book_id).upper():
            return False
        return not self.at or self.at == moment

    def build(self) -> dict:
        return {"symbol": self.symbol.upper(), "action": str(self.action).lower(),
                "rationale": self.rationale}


@dataclass
class DecideCall:
    """One decide() the loop made, kept so the gate report can show its working."""

    at: str
    book_id: str
    shape: str
    dry_run: bool
    candidates: int
    positions: int
    picks: list[dict] = field(default_factory=list)
    exits: list[dict] = field(default_factory=list)
    scripted: bool = False


# ------------------------------------------------------------- the decider


class StubDecider:
    """A stand in for agent/decide.py that answers from rules and a script.

    It exposes `decide` with the same signature as the real one, so the loop
    can be handed this object in place of the module and needs no other change.

    max_picks caps how many names come back from the ranked shortlist when
    nothing is scripted. stop_pct and target_r_multiple shape the stop and the
    target the same way strategies/momentum_rules/strategy.yaml does, so a
    replayed pick looks like a real one.
    """

    def __init__(self, script: list | None = None, max_picks: int = 3,
                 stop_pct: float = 1.5, target_r_multiple: float = 2.0,
                 pick_nothing_for: tuple[str, ...] = (),
                 on_pick: Callable[[dict, dict], list[dict]] | None = None):
        self.script = list(script or [])
        self.max_picks = int(max_picks)
        self.stop_pct = float(stop_pct)
        self.target_r_multiple = float(target_r_multiple)
        self.pick_nothing_for = tuple(str(b).upper() for b in pick_nothing_for)
        self.on_pick = on_pick
        self.calls: list[DecideCall] = []

    # The gate asserts on this: a stub that spent money is a broken stub.
    @property
    def total_cost_usd(self) -> float:
        return 0.0

    def __getattr__(self, name: str) -> Any:
        """Anything else the loop reads off the module comes from the real one.

        agent/loop.py holds the decision step as a module, loop.decide_mod, and
        reads more than decide() off it: PACKET_SCHEMA_VERSION, for one, which
        it stamps onto every decision packet. Every time that list grows, a stub
        that only offers decide() breaks the whole gate with an AttributeError
        that the loop catches, writes down as a failed phase, and carries on
        past, so the gate goes quietly wrong rather than loudly.

        So anything this class does not define itself is answered by
        agent/decide.py. Only decide() is replaced, which is the one thing that
        would cost money. A name neither of them has raises AttributeError the
        way it should.
        """
        if name.startswith("__"):
            raise AttributeError(name)
        try:
            return getattr(real_decide, name)
        except AttributeError:
            raise AttributeError(
                f"neither the replay stub decider nor agent/decide.py has {name!r}"
            ) from None

    # -- the one method agent/loop.py calls -------------------------------

    def decide(self, book: dict, strategy_dir: str | Path, shape: str, packet: dict,
               dry_run: bool = False, max_tokens: int | None = None) -> DecisionResult:
        """Same signature and same return type as agent/decide.py's decide()."""
        packet = packet or {}
        book_id = _book_of(book, packet)
        moment = _hhmm(packet)
        result = DecisionResult(book_id=book_id, model=STUB_MODEL, shape=str(shape),
                                prompt_hash="", cost_usd=STUB_COST, ok=True)
        result.notes.append("replay stub decider, no model was called")

        if shape == "manage":
            self._manage(result, book_id, moment, packet)
        elif shape == "pick":
            self._pick(result, book_id, moment, packet)
        else:
            result.ok = False
            result.error = f"the stub decider knows pick and manage, not {shape!r}"

        self.calls.append(DecideCall(
            at=moment, book_id=book_id, shape=str(shape), dry_run=bool(dry_run),
            candidates=len(packet.get("candidates") or []),
            positions=len(packet.get("positions") or []),
            picks=list(result.picks), exits=list(result.exits),
            scripted=any(getattr(s, "at", "") == moment
                         and str(getattr(s, "book", "")).upper() == book_id
                         for s in self.script)))
        return result

    # Being callable as a module attribute is not enough on its own: a caller
    # that does `from agent import decide as decide_mod` then `decide_mod.decide`
    # gets the bound method above, which is what the loop does.

    # -- the two shapes ---------------------------------------------------

    def _pick(self, result: DecisionResult, book_id: str, moment: str,
              packet: dict) -> None:
        rows = [r for r in (packet.get("candidates") or []) if isinstance(r, dict)]
        by_symbol = {str(r.get("symbol") or "").upper(): r for r in rows}

        scripted = [s for s in self.script
                    if isinstance(s, ScriptedPick) and s.matches(book_id, moment)]
        if scripted:
            for line in scripted:
                built = line.build(by_symbol)
                if built is None:
                    result.notes.append(
                        f"the script asked for {line.symbol} at {line.at or 'any tick'} "
                        "but that name carries no usable price in this packet, so no "
                        "pick was made for it")
                    continue
                result.picks.append(built)
            return

        if book_id in self.pick_nothing_for:
            result.notes.append(f"the scenario told book {book_id} to pick nothing")
            return

        if self.on_pick is not None:
            result.picks.extend(self.on_pick(packet, {}) or [])
            return

        ranked = sorted(rows, key=lambda r: (-_score_of(r),
                                             str(r.get("symbol") or "")))
        for row in ranked:
            symbol = str(row.get("symbol") or "").upper()
            if not symbol:
                continue
            if len(result.picks) >= self.max_picks:
                result.skips.append({"symbol": symbol,
                                     "rationale": "ranked below the stub's cut off"})
                continue
            price = _price_of(row)
            if price is None or price <= 0:
                result.skips.append({"symbol": symbol,
                                     "rationale": "no usable price on this row"})
                continue
            short = _is_short(row)
            move = price * (self.stop_pct / 100.0)
            stop = round(price + move if short else price - move, 2)
            risk = abs(price - stop)
            target = round(price - self.target_r_multiple * risk if short
                           else price + self.target_r_multiple * risk, 2)
            result.picks.append({
                "symbol": symbol, "side": "short" if short else "long",
                "entry": round(price, 2), "stop": stop, "target": target,
                "qty_hint": 0,
                "rationale": (f"ranked {len(result.picks) + 1} of "
                              f"{len(ranked)} by score, stub decider")})

    def _manage(self, result: DecisionResult, book_id: str, moment: str,
                packet: dict) -> None:
        scripted = {s.symbol.upper(): s for s in self.script
                    if isinstance(s, ScriptedExit) and s.matches(book_id, moment)}
        for position in (packet.get("positions") or []):
            if not isinstance(position, dict) or not position.get("symbol"):
                continue
            symbol = str(position["symbol"]).upper()
            line = scripted.get(symbol)
            if line is not None:
                result.exits.append(line.build())
            else:
                result.exits.append({"symbol": symbol, "action": "hold",
                                     "rationale": "the stub decider holds by default, "
                                                  "so the loop's own rules decide"})


def install(loop_module, decider: StubDecider) -> StubDecider:
    """Point agent/loop.py at the stub instead of agent/decide.py.

    The loop keeps the real module in loop.decide_mod and calls
    decide_mod.decide(...), so replacing that one attribute is the whole swap.
    Returns the decider so a caller can keep hold of it and read its calls.
    """
    loop_module.decide_mod = decider
    return decider

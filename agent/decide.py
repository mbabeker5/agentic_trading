"""The decision step: hand a book's packet to its model and get back picks with reasons.

This is the piece that `decide()` in agent/loop.py is a placeholder for. It does
four things and nothing else:

    render_prompt()      fill the {{placeholders}} in a strategy's prompt.md from
                         its strategy.yaml, so the prompt and the yaml can never
                         disagree about a limit
    build_user_message() squeeze the decision packet down to the fields a model
                         actually needs, because the raw packet is 300 KB of five
                         minute bars and every token is paid for
    decide()             call the model, parse its JSON, return a DecisionResult
    __main__ --measure   render every prompt shape against a realistic packet and
                         print what it would cost

Three rules this file lives by:

1. It never raises into the loop. A missing placeholder, a model that refuses, a
   reply that is not JSON: all of them come back as a DecisionResult with an
   empty list of picks and the reason written into `error`. A trading loop that
   crashes at 9:35 misses the whole day.
2. It never approves anything. Whatever the model says still goes through
   check_order in agent/guardrails.py afterwards. The model suggests a share
   count in `qty_hint` and the code is free to cut it to zero.
3. Every pick and every skip carries a written reason. A decision with no reason
   cannot be reviewed at the end of the month, which is the whole point of the eval.

Book B is the control: its yaml says `model: none`, so `decide()` returns a
deterministic rules-only answer and never touches a provider.

    source /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/activate
    python /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/decide.py --measure
    python /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/decide.py --measure --real

The first is free and prints estimated token counts. The second spends real money:
eight calls, one per prompt shape, capped at 600 output tokens each, and writes
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/model_cost_measurements.json.

What the loop needs to know
---------------------------
    result = decide(book, strategy_dir, "pick", packet, dry_run=True)

`book` is a dict from config/books.yaml with at least `id` and `model`.
`strategy_dir` is the folder holding prompt.md and strategy.yaml.
`shape` is "pick" or "manage".
`result.picks` are plain dicts: symbol, side, entry, stop, target, qty_hint,
rationale. Turn them into loop.Pick objects yourself and keep the rationale.
`result.exits` are dicts: symbol, action ("hold", "fade" or "exit"), rationale.
`result.prompt_hash`, `result.model`, `result.cost_usd` go straight into the
ledger columns of the same name.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from paths import project_root  # noqa: E402

PROJECT = project_root()
STRATEGIES = PROJECT / "strategies"
OUTPUT = PROJECT / "output"
DOCS = PROJECT / "docs"

if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from agent import models as models_mod  # noqa: E402

SHAPES = ("pick", "manage")
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")
SHAPE_MARKER = re.compile(r"^##\s*SHAPE:\s*([a-z_]+)\s*$", re.MULTILINE)

# How many output tokens each shape is allowed. A pick over 20 candidates has to
# write 20 rationales, so it needs more room than a manage tick over 5 positions.
DEFAULT_MAX_TOKENS = {"pick": 1500, "manage": 800}

# The last N five minute bars handed to the model. At 9:35 there is one bar and
# this does nothing. Later in the day it stops the packet from growing all day.
BARS_KEPT = 6


class PromptError(Exception):
    """A prompt could not be rendered. Raised by render_prompt, caught by decide."""


# --------------------------------------------------------------- the result

@dataclass
class DecisionResult:
    """One decision, everything about it, ready for the ledger."""

    picks: list[dict] = field(default_factory=list)
    skips: list[dict] = field(default_factory=list)
    exits: list[dict] = field(default_factory=list)
    raw_text: str = ""
    model_response: dict = field(default_factory=dict)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None
    prompt_hash: str = ""
    model: str = ""
    ok: bool = True
    error: str | None = None
    book_id: str | None = None
    shape: str = ""
    notes: list[str] = field(default_factory=list)

    def as_log_dict(self) -> dict:
        out = asdict(self)
        out["raw_text"] = self.raw_text[:2000]
        return out


def _empty(book_id: str | None, model: str, shape: str, prompt_hash: str,
           error: str, notes: list[str] | None = None) -> DecisionResult:
    """The answer when something went wrong: do nothing, and say why."""
    return DecisionResult(book_id=book_id, model=model, shape=shape,
                          prompt_hash=prompt_hash, ok=False, error=error,
                          notes=list(notes or []))


# ------------------------------------------------------- rendering the prompt

def _split_shapes(text: str) -> dict[str, str]:
    """Cut a prompt.md into its shapes.

    Everything before the first `## SHAPE:` line is a note for people and is
    never sent to a model.
    """
    marks = list(SHAPE_MARKER.finditer(text))
    out: dict[str, str] = {}
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out[mark.group(1)] = text[mark.end():end].strip()
    return out


def read_shape(strategy_dir: str | Path, shape: str) -> str:
    """The raw, unfilled text of one shape from a strategy's prompt.md."""
    path = Path(strategy_dir) / "prompt.md"
    if not path.exists():
        raise PromptError(f"no prompt at {path}")
    shapes = _split_shapes(path.read_text())
    if shape not in shapes:
        raise PromptError(
            f"{path} has no '## SHAPE: {shape}' section, it has {sorted(shapes) or 'none'}")
    body = shapes[shape]
    if not body.strip():
        raise PromptError(f"the '{shape}' section of {path} is empty")
    return body


def render_prompt(strategy_dir: str | Path, shape: str, params: dict) -> str:
    """Fill every {{placeholder}} in a strategy's prompt from `params`.

    A placeholder with no value is an error, never a blank. A prompt that quietly
    said "stop percent from entry" with the number missing would be worse than no
    prompt at all.
    """
    body = read_shape(strategy_dir, shape)
    wanted = {m.group(1) for m in PLACEHOLDER.finditer(body)}
    missing = sorted(w for w in wanted if params.get(w) is None)
    if missing:
        raise PromptError(
            f"{Path(strategy_dir) / 'prompt.md'} shape '{shape}' wants values for "
            f"{', '.join(missing)} and strategy.yaml does not supply them")
    return PLACEHOLDER.sub(lambda m: _as_text(params[m.group(1)]), body).strip()


def _as_text(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def prompt_hash(system_prompt: str) -> str:
    """sha256 of the exact bytes sent as the system prompt.

    Goes in the ledger. Two rows with the same hash were decided under exactly the
    same instructions, which is what makes a month of decisions comparable.
    """
    return hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()


# ------------------------------------------------ where the numbers come from

def _flatten(node: Any, prefix: str, into: dict) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, (dict, list)):
                _flatten(value, path, into)
            else:
                into[path] = value
                into[str(key)] = value          # the short name wins for prompts
    # lists are not useful as placeholder values, so they are skipped


def load_params(strategy_dir: str | Path) -> tuple[dict, list[str]]:
    """Read strategy.yaml and flatten it into placeholder names.

    Nested keys are offered under both their full path (`risk.stop_loss_pct`) and
    their short name (`stop_loss_pct`), so the prompt can use whichever reads
    better. A `prompt_params:` block in the yaml wins over everything else, which
    is the escape hatch when a prompt needs a name the yaml does not naturally have.

    Returns the values and any notes worth logging. If there is no strategy.yaml
    yet, the fallbacks below are used and that fact is a note, never a silence.
    """
    strategy_dir = Path(strategy_dir)
    path = strategy_dir / "strategy.yaml"
    notes: list[str] = []
    params: dict = dict(FALLBACK_PARAMS.get(strategy_dir.name, {}))
    if not path.exists():
        notes.append(f"no {path}, using the fallback numbers written into agent/decide.py")
        return params, notes
    try:
        import yaml
        loaded = yaml.safe_load(path.read_text()) or {}
    except Exception as exc:                    # noqa: BLE001
        notes.append(f"{path} would not parse ({exc!r}), using the fallback numbers")
        return params, notes
    if not isinstance(loaded, dict):
        notes.append(f"{path} is not a mapping, using the fallback numbers")
        return params, notes
    flat: dict = {}
    _flatten(loaded, "", flat)
    params.update({k: v for k, v in flat.items() if v is not None})
    extra = loaded.get("prompt_params")
    if isinstance(extra, dict):
        params.update({k: v for k, v in extra.items() if v is not None})
    return params, notes


# Fallback numbers. Every key here is the same key name the strategy.yaml uses, and
# the yaml wins on every one of them, so these can never quietly override a real
# setting. Two jobs: they let the prompts render before a yaml exists, and they
# supply the one number the yaml has no key for.
#
# `target_r_multiple` is that number. docs/STRATEGY.md offers "a target or a
# trailing rule" and fixes neither, so the momentum books take a target at twice
# the distance from entry to stop and it lives here until someone puts it in the yaml.
FALLBACK_PARAMS: dict[str, dict] = {
    "momentum_hybrid": {
        "entries_per_day_max": 5, "max_open_positions": 5, "max_position_pct": 15,
        "max_order_notional": 15000, "stop_loss_pct": 1.5, "max_daily_loss_pct": 2,
        "entries_until": "11:00", "flatten_at": "15:55", "price_floor": 5,
        "short_price_floor": 10, "min_avg_volume": 1000000, "rel_volume_min": 2.0,
        "allow_shorts": True, "gross_exposure_pct_max": 100, "target_r_multiple": 2,
        "loop_minutes": 5, "vwap_fade_closes": 2,
    },
    "momentum_rules": {
        "entries_per_day_max": 3, "max_open_positions": 5, "max_position_pct": 15,
        "stop_loss_pct": 1.5, "target_r_multiple": 2, "max_order_notional": 15000,
        "vwap_fade_closes": 2,
    },
    "insider": {
        "entries_per_day_max": 3, "max_open_positions": 10, "max_position_pct": 5,
        "max_order_notional": 5000, "stop_loss_pct": 8, "trailing_stop_pct": 10,
        "trailing_activation_pct": 8, "time_stop_trading_days": 30,
        "max_daily_loss_pct": 2, "price_floor": 5, "min_avg_volume": 500000,
        "min_buy_usd": 25000, "min_buy_usd_in_cluster": 10000,
        "cluster_window_trading_days": 10, "officer_score_multiplier": 2.0,
        "limit_over_last_close_pct": 1, "entries_until": "15:50", "max_candidates": 15,
    },
    "congress": {
        "entries_per_day_max": 2, "max_open_positions": 10, "max_position_pct": 5,
        "max_order_notional": 5000, "stop_loss_pct": 10, "trailing_stop_pct": 12,
        "trailing_activation_pct": 10, "time_stop_trading_days": 60,
        "max_daily_loss_pct": 2, "price_floor": 10, "min_avg_volume": 1000000,
        "runup_skip_pct": 15, "max_trade_age_days": 60, "crowding_window_days": 30,
        "crowding_min_members": 2, "min_band_usd_single": 15001,
        "min_band_usd_crowded": 1001, "limit_over_last_close_pct": 1,
        "entries_until": "15:50", "max_candidates": 15,
    },
}


# ------------------------------------------------------- trimming the packet

def _family(packet: dict) -> str:
    """Which of the three strategies this packet belongs to.

    Prefers an explicit `strategy_key`. Falls back to looking at what the rows
    actually hold, so a packet built by a sweep that forgot the key still works.
    """
    key = str(packet.get("strategy_key") or "").lower()
    if "insider" in key:
        return "insider"
    if "congress" in key:
        return "congress"
    if "momentum" in key:
        return "momentum"
    rows = list(packet.get("candidates") or []) + list(packet.get("positions") or [])
    blob = set()
    for row in rows[:5]:
        if isinstance(row, dict):
            blob |= set(row.keys())
    if blob & {"filings", "insiders", "insider", "cluster_size", "form4"}:
        return "insider"
    if blob & {"members", "member", "disclosures", "band", "committees"}:
        return "congress"
    text = str(packet.get("strategy") or "").lower()
    if "insider" in text:
        return "insider"
    if "congress" in text:
        return "congress"
    return "momentum"


def _num(value: Any, digits: int = 2) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return round(out, digits)


def _thin(row: dict, keys: tuple[str, ...]) -> dict:
    """Keep the named keys that actually have a value. Nothing else travels."""
    out = {}
    for key in keys:
        value = row.get(key)
        if value is None or value == "" or value == []:
            continue
        out[key] = value
    return out


def _compact_bars(bars: list, keep: int = BARS_KEPT) -> list:
    """Five minute bars as short arrays: [hh:mm, open, high, low, close, volume].

    The raw packet writes every bar as an object with eight named fields, which
    is 300 KB by the afternoon. This is the same information at about a tenth of
    the tokens, and the model is told what the columns mean once at the top.
    """
    out = []
    for bar in list(bars or [])[-keep:]:
        if not isinstance(bar, dict):
            continue
        stamp = str(bar.get("time") or "")
        hhmm = stamp[11:16] if len(stamp) >= 16 else stamp
        out.append([hhmm, _num(bar.get("open")), _num(bar.get("high")),
                    _num(bar.get("low")), _num(bar.get("close")),
                    int(_num(bar.get("volume"), 0) or 0)])
    return out


# No headline and no news, deliberately (2026-09-06). The momentum scanner reads
# IBKR's raw scan lists and daily bars and has no news feed behind it, so a
# headline field on a momentum row was either empty or carried whatever the
# shortlist happened to have lying about. Handing a model a field it cannot
# rely on and then asking it to weigh the story behind a gap invites it to
# invent one, and an invented reason reads exactly like a real one in the
# ledger. The insider and Congress rows below keep both keys, because their
# sweeps read filings and the text is real.
MOMENTUM_CANDIDATE_KEYS = (
    "symbol", "long_name", "stock_type", "last", "gain_pct", "opening_range_high",
    "opening_range_low", "rel_volume", "volume_today", "avg_volume_20d",
    "session_vwap", "last_close", "score", "flagged_by",
    "shortable", "borrow_note",
)
MOMENTUM_POSITION_KEYS = (
    "symbol", "side", "qty", "avg_cost", "entry", "stop", "target", "last",
    "last_close", "session_vwap", "opening_range_high", "opening_range_low",
    "unrealized_pct", "unrealized_pnl", "minutes_held", "closes_below_vwap",
    "entry_reason",
)
SLOW_CANDIDATE_KEYS = (
    "symbol", "company", "sector", "last_close", "avg_volume_20d", "score",
    "market_cap_usd", "headline", "news", "flagged_by",
)
INSIDER_EXTRA_KEYS = (
    "cluster_size", "cluster_window_days", "buys", "days_since_trade",
    "runup_since_trade_pct", "insider_history",
)
CONGRESS_EXTRA_KEYS = (
    "trades", "crowding", "days_since_trade", "days_since_filing",
    "runup_since_trade_pct", "committee_match",
)
SLOW_POSITION_KEYS = (
    "symbol", "company", "entry", "entry_date", "trading_days_held", "qty",
    "last_close", "high_close_since_entry", "unrealized_pct", "stop",
    "trailing_stop", "trailing_active", "trading_days_to_time_stop",
    "entry_reason", "headline", "news",
)


def build_user_message(shape: str, packet: dict) -> str:
    """The packet, cut down to what the model needs, as compact JSON.

    What gets dropped and why. The full five minute bar history goes, all but the
    last half hour of it, because a decision made at 11:00 does not turn on what
    happened at 9:50. The scanner's `reasons` list goes, because every line in it
    restates a number that is in the row already, and paying twice for the same
    fact on every call for a month is real money. Contract ids, exchange routing
    and the scanner's internal bookkeeping go, because the model cannot act on them.

    What stays: the prices and volumes the judgment rules name, the opening range,
    the session VWAP, the score, and why the scanner flagged it. A momentum row
    also drops its headline and its news, for the reason written above
    MOMENTUM_CANDIDATE_KEYS.
    """
    if shape not in SHAPES:
        raise ValueError(f"shape must be one of {SHAPES}, not {shape!r}")
    family = _family(packet)
    account = _thin(packet.get("account") or {}, (
        "equity", "day_start_equity", "cash", "realized_pnl_today", "unrealized_pnl",
        "open_positions", "day_pnl_pct", "buying_power"))
    body: dict = {
        "as_of": packet.get("generated_at") or packet.get("as_of"),
        "date": packet.get("date"),
        "book": packet.get("book") or packet.get("book_id"),
        "account": account,
    }
    if packet.get("schedule"):
        body["schedule"] = packet["schedule"]

    if shape == "pick":
        rows = []
        for row in packet.get("candidates") or []:
            if not isinstance(row, dict):
                continue
            if family == "momentum":
                thin = _thin(row, MOMENTUM_CANDIDATE_KEYS)
                bars = _compact_bars(row.get("bars_5m"))
                if bars:
                    thin["bars"] = bars
            elif family == "insider":
                thin = _thin(row, SLOW_CANDIDATE_KEYS + INSIDER_EXTRA_KEYS)
            else:
                thin = _thin(row, SLOW_CANDIDATE_KEYS + CONGRESS_EXTRA_KEYS)
            if thin.get("symbol"):
                rows.append(thin)
        body["candidates"] = rows
        if family == "momentum" and any("bars" in r for r in rows):
            body["bars_columns"] = "hh:mm, open, high, low, close, volume"
        body["open_positions"] = [
            _thin(p, ("symbol", "side", "qty", "avg_cost"))
            for p in (packet.get("positions") or []) if isinstance(p, dict)]
    else:
        rows = []
        for row in packet.get("positions") or []:
            if not isinstance(row, dict):
                continue
            if family == "momentum":
                thin = _thin(row, MOMENTUM_POSITION_KEYS)
                bars = _compact_bars(row.get("bars_5m"))
                if bars:
                    thin["bars"] = bars
            else:
                thin = _thin(row, SLOW_POSITION_KEYS)
            if thin.get("symbol"):
                rows.append(thin)
        body["positions"] = rows
        if family == "momentum" and any("bars" in r for r in rows):
            body["bars_columns"] = "hh:mm, open, high, low, close, volume"
        if packet.get("working_orders"):
            body["working_orders"] = [
                _thin(o, ("symbol", "side", "qty", "limit_price", "purpose"))
                for o in packet["working_orders"] if isinstance(o, dict)]

    body = {k: v for k, v in body.items() if v not in (None, "", [], {})}
    return json.dumps(body, separators=(",", ":"), default=str)


# --------------------------------------------------------- parsing the reply

def _extract_json(text: str) -> dict:
    """The model's JSON object, even if it wrapped it in a code fence."""
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\s*", "", stripped)
        stripped = re.sub(r"\s*```\s*$", "", stripped)
    try:
        loaded = json.loads(stripped)
    except json.JSONDecodeError:
        start, end = stripped.find("{"), stripped.rfind("}")
        if start < 0 or end <= start:
            raise
        loaded = json.loads(stripped[start:end + 1])
    if not isinstance(loaded, dict):
        raise ValueError(f"the reply parsed as {type(loaded).__name__}, not an object")
    return loaded


def _clean_pick(row: Any) -> dict | None:
    if not isinstance(row, dict):
        return None
    symbol = str(row.get("symbol") or "").strip().upper()
    rationale = str(row.get("rationale") or row.get("reason") or "").strip()
    if not symbol or not rationale:
        return None
    side = str(row.get("side") or "long").strip().lower()
    if side not in ("long", "short"):
        side = "long"
    qty = row.get("qty_hint", row.get("qty"))
    try:
        qty_hint = int(float(qty)) if qty is not None else None
    except (TypeError, ValueError):
        qty_hint = None
    return {"symbol": symbol, "side": side, "entry": _num(row.get("entry")),
            "stop": _num(row.get("stop")), "target": _num(row.get("target")),
            "qty_hint": qty_hint, "rationale": rationale}


def _clean_skip(row: Any) -> dict | None:
    if not isinstance(row, dict):
        return None
    symbol = str(row.get("symbol") or "").strip().upper()
    rationale = str(row.get("rationale") or row.get("reason") or "").strip()
    if not symbol or not rationale:
        return None
    return {"symbol": symbol, "rationale": rationale}


def _clean_exit(row: Any) -> dict | None:
    if not isinstance(row, dict):
        return None
    symbol = str(row.get("symbol") or "").strip().upper()
    action = str(row.get("action") or "").strip().lower()
    rationale = str(row.get("rationale") or row.get("reason") or "").strip()
    if not symbol or action not in ("hold", "fade", "exit") or not rationale:
        return None
    return {"symbol": symbol, "action": action, "rationale": rationale}


def parse_decision(text: str, shape: str) -> tuple[list, list, list, list[str]]:
    """Turn the model's reply into picks, skips and exits, plus notes on anything dropped.

    Strict about the container: the reply has to be one JSON object with the key
    the shape asked for. Forgiving about one row inside it, because losing a whole
    day's decision to one malformed entry would be worse than losing that entry.
    A dropped row is always written into the notes, never swallowed.
    """
    notes: list[str] = []
    loaded = _extract_json(text)

    if shape == "pick":
        if "picks" not in loaded and "skips" not in loaded:
            raise ValueError("the reply has neither a 'picks' nor a 'skips' key")
        raw_picks = loaded.get("picks") or []
        raw_skips = loaded.get("skips") or []
        if not isinstance(raw_picks, list) or not isinstance(raw_skips, list):
            raise ValueError("'picks' and 'skips' must both be lists")
        picks = [p for p in (_clean_pick(r) for r in raw_picks) if p]
        skips = [s for s in (_clean_skip(r) for r in raw_skips) if s]
        if len(picks) != len(raw_picks):
            notes.append(f"dropped {len(raw_picks) - len(picks)} pick(s) with no symbol "
                         "or no rationale")
        if len(skips) != len(raw_skips):
            notes.append(f"dropped {len(raw_skips) - len(skips)} skip(s) with no symbol "
                         "or no rationale")
        return picks, skips, [], notes

    raw = loaded.get("exits")
    if raw is None:
        raw = loaded.get("positions") or loaded.get("decisions")
        if raw is not None:
            notes.append("the reply used a key other than 'exits'; read it anyway")
    if raw is None:
        raise ValueError("the reply has no 'exits' key")
    if not isinstance(raw, list):
        raise ValueError("'exits' must be a list")
    exits = [e for e in (_clean_exit(r) for r in raw) if e]
    if len(exits) != len(raw):
        notes.append(f"dropped {len(raw) - len(exits)} position(s) with no symbol, no "
                     "rationale, or an action that was not hold, fade or exit")
    return [], [], exits, notes


# ------------------------------------------------------- the rules only book

def _short_candidate(row: dict) -> bool:
    side = str(row.get("side") or row.get("direction") or "").lower()
    if side in ("short", "sell"):
        return True
    gain = _num(row.get("gain_pct"))
    return gain is not None and gain < 0


def rules_only_decision(packet: dict, params: dict, shape: str,
                        book_id: str | None = None) -> DecisionResult:
    """Book B. No model, no judgment, no cost. The control the others are measured against.

    Picks: the top three candidates by score, entering at the opening range high,
    or at the opening range low for a candidate that gapped down. Stop is the
    percent stop from the spec, or the opposite end of the opening range when that
    is closer. Target is twice the distance from entry to stop. The reason on every
    row is "rules only", because there is no judgment to record.

    Manage: hold everything. The stop, the target and the flatten time in
    agent/loop.py do all the exiting for this book, and a rules-only book has no
    opinion about a fade.
    """
    result = DecisionResult(book_id=book_id, model="none", shape=shape,
                            prompt_hash="", cost_usd=0.0, ok=True)
    result.notes.append("rules only book, no model was called")

    if shape == "manage":
        for position in packet.get("positions") or []:
            if isinstance(position, dict) and position.get("symbol"):
                result.exits.append({"symbol": str(position["symbol"]).upper(),
                                     "action": "hold", "rationale": "rules only"})
        return result

    max_picks = int(params.get("max_picks") or 3)
    stop_pct = float(params.get("stop_loss_pct") or 1.5)
    r_multiple = float(params.get("target_r_multiple") or 2.0)
    equity = _num((packet.get("account") or {}).get("equity")) or \
        float(params.get("starting_equity") or params.get("capital") or 100000)
    position_pct = float(params.get("max_position_pct") or params.get("position_pct") or 15)
    max_notional = float(params.get("max_order_notional") or (equity * position_pct / 100.0))
    budget = min(equity * position_pct / 100.0, max_notional)

    candidates = sorted(
        [c for c in (packet.get("candidates") or []) if isinstance(c, dict)],
        key=lambda c: _num(c.get("score"), 4) or 0.0, reverse=True)

    for row in candidates:
        if len(result.picks) >= max_picks:
            result.skips.append({"symbol": str(row.get("symbol") or "").upper(),
                                 "rationale": "rules only"})
            continue
        symbol = str(row.get("symbol") or "").upper()
        high = _num(row.get("opening_range_high"))
        low = _num(row.get("opening_range_low"))
        short = _short_candidate(row)
        entry = low if short else high
        if not symbol or not entry or entry <= 0:
            if symbol:
                result.skips.append({"symbol": symbol, "rationale": "rules only"})
            continue
        if short:
            percent_stop = entry * (1.0 + stop_pct / 100.0)
            stop = round(min(percent_stop, high) if high and high > entry else percent_stop, 2)
            risk = stop - entry
            target = round(entry - r_multiple * risk, 2)
        else:
            percent_stop = entry * (1.0 - stop_pct / 100.0)
            stop = round(max(percent_stop, low) if low and 0 < low < entry else percent_stop, 2)
            risk = entry - stop
            target = round(entry + r_multiple * risk, 2)
        if risk <= 0:
            result.skips.append({"symbol": symbol, "rationale": "rules only"})
            continue
        result.picks.append({
            "symbol": symbol, "side": "short" if short else "long",
            "entry": round(entry, 2), "stop": stop, "target": target,
            "qty_hint": int(math.floor(budget / entry)) if entry > 0 else 0,
            "rationale": "rules only"})

    if candidates and not result.picks:
        # The rules-only path is an opening range idea, so it has nothing to say
        # about an insider or Congress shortlist. Better to say that out loud than
        # to look like a decision to buy nothing.
        result.notes.append(
            f"no pick: none of the {len(candidates)} candidates carried an opening range, "
            "which is the only entry the rules-only path knows how to work out")
    return result


# ---------------------------------------------------------------- the decision

def decide(book: dict, strategy_dir: str | Path, shape: str, packet: dict,
           dry_run: bool = False, max_tokens: int | None = None) -> DecisionResult:
    """Make one decision for one book. Never raises.

    `book` needs `model` and, for the ledger, `id`. A book whose model is "none"
    (book B) takes the deterministic path and never touches a provider.
    `dry_run=True` renders and hashes the prompt but makes no call, and hands back
    the rules-only answer so the loop still has something to write down. That is
    what lets the whole day be rehearsed for nothing.
    """
    book = book or {}
    book_id = book.get("id") or book.get("book") or book.get("book_id")
    model_field = str(book.get("model") or "none").strip()
    strategy_dir = Path(strategy_dir)
    shape = str(shape)
    if shape not in SHAPES:
        return _empty(book_id, model_field, shape, "",
                      f"shape must be one of {SHAPES}, not {shape!r}")

    params, notes = load_params(strategy_dir)
    for source in ("params", "prompt_params"):
        if isinstance(book.get(source), dict):
            params.update({k: v for k, v in book[source].items() if v is not None})

    if model_field.lower() in ("", "none", "null"):
        result = rules_only_decision(packet or {}, params, shape, book_id)
        result.notes = notes + result.notes
        return result

    try:
        system = render_prompt(strategy_dir, shape, params)
    except PromptError as exc:
        return _empty(book_id, model_field, shape, "", f"prompt: {exc}", notes)
    digest = prompt_hash(system)

    if dry_run:
        result = rules_only_decision(packet or {}, params, shape, book_id)
        result.model = model_field
        result.prompt_hash = digest
        result.cost_usd = 0.0
        result.notes = notes + [
            f"dry run: the {shape} prompt was rendered and hashed but no model was called, "
            "so these are the rules only answers"]
        return result

    try:
        user = build_user_message(shape, packet or {})
    except Exception as exc:                    # noqa: BLE001
        return _empty(book_id, model_field, shape, digest,
                      f"could not build the user message: {exc!r}", notes)

    # Both month one models think before they answer, and thinking tokens are billed
    # at the output price. A book may set `reasoning_effort: low` in its yaml to keep
    # a routine manage tick from spending more on deliberation than on the answer.
    adapter_kwargs: dict = {}
    effort = book.get("reasoning_effort")
    if effort:
        adapter_kwargs["effort" if model_field.startswith("anthropic/")
                       else "reasoning_effort"] = str(effort)
    try:
        adapter = models_mod.get_adapter(model_field, **adapter_kwargs)
    except models_mod.ModelError as exc:
        return _empty(book_id, model_field, shape, digest, f"model config: {exc}", notes)
    except TypeError as exc:
        return _empty(book_id, model_field, shape, digest,
                      f"model config: {model_field} does not take reasoning_effort ({exc})",
                      notes)

    cap = max_tokens or DEFAULT_MAX_TOKENS.get(shape, 1200)
    response = adapter.complete(system, user, max_tokens=cap, json_only=True)
    log = response.as_log_dict()

    if not response.ok:
        out = _empty(book_id, response.model or model_field, shape, digest,
                     response.error or "the model returned nothing usable", notes)
        out.raw_text = response.text or ""
        out.model_response = log
        out.tokens_in = response.input_tokens
        out.tokens_out = response.output_tokens
        out.cost_usd = response.cost_usd
        return out

    result = DecisionResult(
        raw_text=response.text, model_response=log, tokens_in=response.input_tokens,
        tokens_out=response.output_tokens, cost_usd=response.cost_usd,
        prompt_hash=digest, model=response.model or model_field, book_id=book_id,
        shape=shape, notes=list(notes))
    try:
        picks, skips, exits, parse_notes = parse_decision(response.text, shape)
    except Exception as exc:                    # noqa: BLE001
        result.ok = False
        result.error = f"the reply was not the JSON this shape asked for: {exc}"
        return result
    result.picks, result.skips, result.exits = picks, skips, exits
    result.notes.extend(parse_notes)
    return result


# ------------------------------------------------------------- the measuring

def estimate_tokens(text: str) -> int:
    """A rough token count, no network and no tokeniser library.

    English prose runs about 4 characters a token and dense JSON runs nearer 3,
    because every brace, quote and comma is its own token. This splits the
    difference by weighting the punctuation. It is an estimate and it is labelled
    as one everywhere it is printed. The real numbers come from --real, which
    reads what OpenRouter actually billed.
    """
    if not text:
        return 0
    punctuation = sum(text.count(c) for c in '{}[]",:')
    return int(len(text) / 4.0 + punctuation * 0.45)


def _sample_momentum_packet(shape: str) -> dict:
    """The real 9:36 packet from output/, or a stand in if it is not there."""
    path = OUTPUT / "decision_packet_2026-09-02_0936.json"
    if path.exists():
        packet = json.loads(path.read_text())
    else:
        packet = {"generated_at": "2026-09-02T09:36:00-04:00", "date": "2026-09-02",
                  "account": {"equity": 100000.0}, "candidates": []}
    packet["strategy_key"] = "momentum_hybrid"
    if shape == "pick":
        return packet
    # A manage tick: the loop is holding what it picked, mid morning.
    positions = []
    for row in (packet.get("candidates") or [])[:4]:
        bars = row.get("bars_5m") or []
        entry = _num(row.get("opening_range_high")) or _num(row.get("last")) or 10.0
        last = _num((bars[-1] or {}).get("close")) if bars else entry
        positions.append({
            "symbol": row.get("symbol"), "side": "long", "qty": 1200,
            "avg_cost": entry, "entry": entry,
            "stop": round(entry * 0.985, 2), "target": round(entry * 1.03, 2),
            "last_close": last, "session_vwap": row.get("session_vwap"),
            "opening_range_high": row.get("opening_range_high"),
            "opening_range_low": row.get("opening_range_low"),
            "unrealized_pct": _num(((last or entry) / entry - 1) * 100) if entry else 0,
            "minutes_held": 55, "closes_below_vwap": 0,
            "entry_reason": "broke the opening range high on 24 times normal volume",
            "bars_5m": bars})
    return {"generated_at": "2026-09-02T10:30:00-04:00", "date": "2026-09-02",
            "strategy_key": "momentum_hybrid", "account": packet.get("account") or {},
            "schedule": packet.get("schedule") or {}, "positions": positions,
            "working_orders": [{"symbol": "OPEN", "side": "BUY", "qty": 900,
                                "limit_price": 16.4, "purpose": "entry"}]}


_INSIDER_NAMES = [
    ("BIAF", "bioAffinity Technologies", "Healthcare"), ("CDLX", "Cardlytics", "Technology"),
    ("PRTA", "Prothena", "Healthcare"), ("HRTX", "Heron Therapeutics", "Healthcare"),
    ("BGFV", "Big 5 Sporting Goods", "Consumer"), ("SNDX", "Syndax Pharmaceuticals", "Healthcare"),
    ("VTLE", "Vital Energy", "Energy"), ("CENX", "Century Aluminum", "Materials"),
    ("AMBC", "Ambac Financial", "Financials"), ("KOP", "Koppers Holdings", "Materials"),
    ("EVRI", "Everi Holdings", "Consumer"), ("CRSR", "Corsair Gaming", "Technology"),
    ("NABL", "N-able", "Technology"), ("PGRE", "Paramount Group", "Real Estate"),
    ("TALO", "Talos Energy", "Energy"),
]
_ROLES = ["Chief Executive Officer", "Chief Financial Officer", "Director",
          "President and COO", "EVP and Chief Operating Officer"]


def _sample_insider_packet(shape: str) -> dict:
    """A realistic 9:45 insider shortlist of 15, or a half hourly manage tick over 8 holdings."""
    if shape == "pick":
        candidates = []
        for i, (symbol, company, sector) in enumerate(_INSIDER_NAMES):
            cluster = 1 + (i % 3)
            price = round(6.5 + i * 3.15, 2)
            buys = []
            for j in range(cluster):
                shares = 5000 + (i * 900) + j * 2500
                buys.append({
                    "insider": f"{'Smith' if j == 0 else 'Alvarez'} {chr(65 + j)}.",
                    "title": _ROLES[(i + j) % len(_ROLES)],
                    "trade_date": f"2026-09-0{1 + (i + j) % 3}",
                    "filing_date": f"2026-09-0{3 + (i + j) % 3}",
                    "shares": shares, "price": price,
                    "value_usd": int(shares * price),
                    "pct_of_prior_holding": round(3.0 + (i * 2.7 + j * 4.1) % 40, 1),
                    "pct_of_adv_dollars": round(0.4 + (i * 1.3 + j) % 18, 1),
                    "plan_10b5_1": False, "code": "P"})
            candidates.append({
                "symbol": symbol, "company": company, "sector": sector,
                "last_close": price, "avg_volume_20d": 420000 + i * 310000,
                "market_cap_usd": 90_000_000 + i * 240_000_000,
                "score": round(94.0 - i * 4.3, 1), "cluster_size": cluster,
                "cluster_window_days": 10, "days_since_trade": 2 + i % 5,
                "runup_since_trade_pct": round(-4.0 + i * 1.9, 1),
                "insider_history": ("first open market buy by this person in "
                                    f"{2 + i % 6} years") if i % 2 == 0 else
                                   "buys most quarters, roughly this size each time",
                "buys": buys,
                "headline": ("Q2 revenue beat, guidance raised" if i % 4 == 0 else
                             "no company news in the last five sessions"),
                "flagged_by": ["FORM4_CLUSTER"] if cluster > 1 else ["FORM4_SIZE"]})
        return {"generated_at": "2026-09-06T09:45:00-04:00", "date": "2026-09-06",
                "strategy_key": "insider", "book": "C",
                "account": {"equity": 100000.0, "day_start_equity": 100000.0,
                            "cash": 61000.0, "open_positions": 8, "unrealized_pnl": 1240.0},
                "candidates": candidates}

    positions = []
    for i, (symbol, company, _sector) in enumerate(_INSIDER_NAMES[:8]):
        entry = round(7.4 + i * 3.6, 2)
        last = round(entry * (1 + (-0.09 + i * 0.035)), 2)
        high = round(max(entry, last) * 1.04, 2)
        up_pct = round((last / entry - 1) * 100, 1)
        positions.append({
            "symbol": symbol, "company": company, "entry": entry,
            "entry_date": f"2026-08-{10 + i:02d}", "trading_days_held": 5 + i * 2,
            "qty": int(5000 / entry), "last_close": last,
            "high_close_since_entry": high, "unrealized_pct": up_pct,
            "stop": round(entry * 0.92, 2),
            "trailing_stop": round(high * 0.90, 2) if up_pct >= 8 else None,
            "trailing_active": up_pct >= 8,
            "trading_days_to_time_stop": 30 - (5 + i * 2),
            "entry_reason": "CEO and CFO both bought inside a week, 12 percent of holding",
            "headline": ("secondary offering priced at a discount" if i == 3 else
                         "no company news since entry")})
    return {"generated_at": "2026-09-06T11:00:00-04:00", "date": "2026-09-06",
            "strategy_key": "insider", "book": "C",
            "account": {"equity": 101240.0, "day_start_equity": 100900.0,
                        "open_positions": 8, "unrealized_pnl": 1240.0},
            "positions": positions,
            "working_orders": [{"symbol": "PRTA", "side": "BUY", "qty": 180,
                                "limit_price": 27.9, "purpose": "entry"}]}


_CONGRESS_NAMES = [
    ("LMT", "Lockheed Martin", "Industrials"), ("RTX", "RTX Corporation", "Industrials"),
    ("NVDA", "NVIDIA", "Technology"), ("PFE", "Pfizer", "Healthcare"),
    ("XOM", "Exxon Mobil", "Energy"), ("JPM", "JPMorgan Chase", "Financials"),
    ("CRWD", "CrowdStrike", "Technology"), ("UNH", "UnitedHealth", "Healthcare"),
    ("CAT", "Caterpillar", "Industrials"), ("NEE", "NextEra Energy", "Utilities"),
    ("TMUS", "T-Mobile US", "Communications"), ("GD", "General Dynamics", "Industrials"),
    ("MRK", "Merck", "Healthcare"), ("COP", "ConocoPhillips", "Energy"),
    ("AVGO", "Broadcom", "Technology"),
]
_BANDS = ["$1,001 to $15,000", "$15,001 to $50,000", "$50,001 to $100,000",
          "$100,001 to $250,000", "$250,001 to $500,000"]
_COMMITTEES = ["Armed Services", "Energy and Commerce", "Financial Services",
               "Ways and Means", "Intelligence", "Appropriations"]


def _sample_congress_packet(shape: str) -> dict:
    """A realistic 9:45 Congress shortlist of 15, or a half hourly manage tick over 8 holdings."""
    if shape == "pick":
        candidates = []
        for i, (symbol, company, sector) in enumerate(_CONGRESS_NAMES):
            crowd = 1 + (i % 3)
            trades = []
            for j in range(crowd):
                trades.append({
                    "member": f"Rep. {'Ellison' if j == 0 else 'Hartley'} {chr(65 + j)}.",
                    "chamber": "House" if (i + j) % 2 == 0 else "Senate",
                    "filed_by": "self" if j == 0 else "spouse",
                    "band": _BANDS[(i + j) % len(_BANDS)],
                    "trade_date": f"2026-07-{12 + (i + j) % 15:02d}",
                    "filing_date": f"2026-09-0{2 + (i + j) % 4}",
                    "committees": [_COMMITTEES[(i + j) % len(_COMMITTEES)]]})
            candidates.append({
                "symbol": symbol, "company": company, "sector": sector,
                "last_close": round(48.0 + i * 27.4, 2),
                "avg_volume_20d": 2_100_000 + i * 1_400_000,
                "market_cap_usd": 20_000_000_000 + i * 31_000_000_000,
                "score": round(88.0 - i * 3.6, 1), "crowding": crowd,
                "days_since_trade": 34 + i % 20, "days_since_filing": 1 + i % 4,
                "runup_since_trade_pct": round(-6.0 + i * 2.6, 1),
                "committee_match": ("Armed Services member buying a prime defence "
                                    "contractor") if sector == "Industrials" else
                                   ("no committee link to this sector" if i % 3 == 0 else
                                    "Energy and Commerce member, sector overlap is partial"),
                "trades": trades,
                "headline": ("defence appropriations markup scheduled for next month"
                             if i % 5 == 0 else "no company news in the last five sessions"),
                "flagged_by": ["PTR_BAND"] + (["PTR_CROWDING"] if crowd > 1 else [])})
        return {"generated_at": "2026-09-06T09:45:00-04:00", "date": "2026-09-06",
                "strategy_key": "congress", "book": "D",
                "account": {"equity": 100000.0, "day_start_equity": 100000.0,
                            "cash": 72000.0, "open_positions": 6, "unrealized_pnl": -320.0},
                "candidates": candidates}

    positions = []
    for i, (symbol, company, _sector) in enumerate(_CONGRESS_NAMES[:8]):
        entry = round(61.0 + i * 24.5, 2)
        last = round(entry * (1 + (-0.07 + i * 0.031)), 2)
        high = round(max(entry, last) * 1.03, 2)
        up_pct = round((last / entry - 1) * 100, 1)
        positions.append({
            "symbol": symbol, "company": company, "entry": entry,
            "entry_date": f"2026-08-{6 + i:02d}", "trading_days_held": 8 + i * 3,
            "qty": int(5000 / entry), "last_close": last,
            "high_close_since_entry": high, "unrealized_pct": up_pct,
            "stop": round(entry * 0.90, 2),
            "trailing_stop": round(high * 0.88, 2) if up_pct >= 10 else None,
            "trailing_active": up_pct >= 10,
            "trading_days_to_time_stop": 60 - (8 + i * 3),
            "entry_reason": "two Armed Services members bought in the 50k to 100k band",
            "headline": ("budget markup slipped to next session" if i == 2 else
                         "no company news since entry")})
    return {"generated_at": "2026-09-06T11:00:00-04:00", "date": "2026-09-06",
            "strategy_key": "congress", "book": "D",
            "account": {"equity": 99680.0, "day_start_equity": 99900.0,
                        "open_positions": 8, "unrealized_pnl": -320.0},
            "positions": positions}


SAMPLE_PACKETS = {
    "momentum_hybrid": _sample_momentum_packet,
    "insider": _sample_insider_packet,
    "congress": _sample_congress_packet,
}


def measure(real: bool = False, models_to_call: dict | None = None,
            max_tokens: int = 600, out_path: Path | None = None) -> dict:
    """Render every prompt shape against a realistic packet and report its size.

    Without --real this costs nothing and prints estimates. With --real it makes
    one call per entry in `models_to_call`, capped at `max_tokens` output tokens,
    and records what OpenRouter says it actually billed.
    """
    rows = []
    for strategy in ("momentum_hybrid", "insider", "congress"):
        strategy_dir = STRATEGIES / strategy
        params, notes = load_params(strategy_dir)
        packet_for = SAMPLE_PACKETS[strategy]
        for shape in SHAPES:
            packet = packet_for(shape)
            system = render_prompt(strategy_dir, shape, params)
            user = build_user_message(shape, packet)
            n = len(packet.get("candidates") or packet.get("positions") or [])
            rows.append({
                "strategy": strategy, "shape": shape, "rows_in_packet": n,
                "system_chars": len(system), "user_chars": len(user),
                "system_tokens_estimated": estimate_tokens(system),
                "user_tokens_estimated": estimate_tokens(user),
                "input_tokens_estimated": estimate_tokens(system) + estimate_tokens(user),
                "prompt_hash": prompt_hash(system),
                "params_notes": notes,
                "calls": {},
            })

    print(f"{'strategy':<17}{'shape':<9}{'rows':>5}{'sys tok':>10}{'user tok':>10}{'in tok':>9}")
    print("-" * 60)
    for row in rows:
        print(f"{row['strategy']:<17}{row['shape']:<9}{row['rows_in_packet']:>5}"
              f"{row['system_tokens_estimated']:>10}{row['user_tokens_estimated']:>10}"
              f"{row['input_tokens_estimated']:>9}")
    print("\nToken counts above are estimated with no tokeniser. Run with --real for "
          "OpenRouter's own accounting.")

    if not real:
        return {"measured_at": None, "estimates_only": True, "rows": rows}

    plan = models_to_call or {}
    spent = 0.0
    calls_made = 0
    for row in rows:
        for label, model_field in plan.get((row["strategy"], row["shape"]), []):
            packet = SAMPLE_PACKETS[row["strategy"]](row["shape"])
            book = {"id": label, "model": model_field}
            print(f"\ncalling {model_field} for {row['strategy']} {row['shape']} ...")
            result = decide(book, STRATEGIES / row["strategy"], row["shape"], packet,
                            dry_run=False, max_tokens=max_tokens)
            calls_made += 1
            spent += float(result.cost_usd or 0.0)
            row["calls"][model_field] = {
                "ok": result.ok, "error": result.error,
                "prompt_tokens": result.tokens_in, "completion_tokens": result.tokens_out,
                "cost_usd_reported": result.cost_usd,
                "latency_s": (result.model_response or {}).get("latency_s"),
                "finish_reason": (result.model_response or {}).get("stop_reason"),
                "picks": len(result.picks), "skips": len(result.skips),
                "exits": len(result.exits), "notes": result.notes,
                "raw_head": result.raw_text[:400],
            }
            print(f"  in {result.tokens_in} out {result.tokens_out} "
                  f"cost {result.cost_usd} ok {result.ok} "
                  f"picks {len(result.picks)} skips {len(result.skips)} "
                  f"exits {len(result.exits)}")

    payload = {"estimates_only": False, "calls_made": calls_made,
               "max_tokens_per_call": max_tokens,
               "reported_cost_sum_usd": round(spent, 6), "rows": rows}
    if out_path:
        out_path.write_text(json.dumps(payload, indent=2, default=str))
        print(f"\nwritten to {out_path}")
    print(f"\n{calls_made} real calls, OpenRouter reported {spent} dollars in the "
          "immediate responses (it finalises cost a few seconds later, so treat a "
          "zero as not yet known).")
    return payload


# The eight measurement calls: Fable on all six shapes, Astra on the two momentum
# shapes, which is the only place the two models are compared head to head.
FABLE = "openrouter/anthropic/claude-fable-5.1"
ASTRA = "openrouter/openai/gpt-6-astra"
MEASURE_PLAN = {
    ("momentum_hybrid", "pick"): [("A", FABLE), ("E", ASTRA)],
    ("momentum_hybrid", "manage"): [("A", FABLE), ("E", ASTRA)],
    ("insider", "pick"): [("C", FABLE)],
    ("insider", "manage"): [("C", FABLE)],
    ("congress", "pick"): [("D", FABLE)],
    ("congress", "manage"): [("D", FABLE)],
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render the decision prompts and measure what they cost.")
    parser.add_argument("--measure", action="store_true",
                        help="render every prompt shape against a realistic packet")
    parser.add_argument("--real", action="store_true",
                        help="with --measure, make the eight real OpenRouter calls. "
                             "This spends money.")
    parser.add_argument("--max-tokens", type=int, default=600,
                        help="output token cap for the real calls (default 600)")
    parser.add_argument("--out", default=str(DOCS / "model_cost_measurements.json"),
                        help="where --real writes its numbers")
    parser.add_argument("--show", nargs=2, metavar=("STRATEGY", "SHAPE"),
                        help="print one rendered system prompt and its user message")
    args = parser.parse_args(argv)

    if args.show:
        strategy, shape = args.show
        strategy_dir = STRATEGIES / strategy
        params, notes = load_params(strategy_dir)
        for note in notes:
            print(f"note: {note}", file=sys.stderr)
        system = render_prompt(strategy_dir, shape, params)
        packet = SAMPLE_PACKETS[strategy](shape)
        print("===== SYSTEM =====")
        print(system)
        print("\n===== USER =====")
        print(build_user_message(shape, packet))
        return 0

    if args.measure:
        measure(real=args.real, models_to_call=MEASURE_PLAN if args.real else None,
                max_tokens=args.max_tokens,
                out_path=Path(args.out) if args.real else None)
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

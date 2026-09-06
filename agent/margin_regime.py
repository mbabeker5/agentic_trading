"""Which day trading rulebook this account lives under, and the check that goes with it.

Two rulebooks exist in 2026 and they ask for completely different behaviour from
the trading loop.

The old one is the pattern day trader rule. Four or more round trip day trades
in five business days, in a margin account, makes you a pattern day trader, and
that account then has to hold at least 25,000 dollars or the broker stops it day
trading for 90 days. Counting is the whole defence, and that counting lives in
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/pdt.py.

The new one replaced it. FINRA retired the day trading margin rules with effect
from 2026-06-04 (Regulatory Notice 26-10, phase-in to 2027-10-20). A migrated
account has no 25,000 dollar floor and nothing counts to four. What replaces it
is the Intraday Margin Deficit framework: an order must not leave the account
short of the margin it needs during the day, a deficit has to be cured in about
three business days, and four uncured deficits in twelve months can bring a
90 day restriction. Counting day trades protects nobody under those rules. Not
creating a deficit does.

IBKR says new margin accounts are generally not subject to the old rule but may
still be during the transition, so the account's own status is the only honest
answer, and the account will say which it is if you ask it.

How the account is asked
------------------------

IBKR's account summary carries five tags: DayTradesRemaining and
DayTradesRemainingT+1 through T+4. Under the old rule they hold small
non-negative numbers, which is the broker counting down the day trades left.
Under the new one IBKR reports -1, its way of writing "unlimited", or does not
send the tags at all.

    old_pdt   three or more of the five tags came back holding non-negative
              numbers. This account is still counted the old way.
    new_imd   any tag came back as -1, or none of them came back at all.
    unknown   anything else. A value that is not a number, a negative that is
              not -1, or one or two lonely tags. Nothing is guessed; the raw
              evidence is kept on the reading so a person can look at it.

Read once by the pre-flight each morning and written into config/guardrails.yaml
under pdt.regime, so the trading loop reads a settled answer rather than asking
the broker mid-tick.

One warning worth repeating. The paper account DUT077572 is not the live account
U28440091, and IBKR does not apply either rulebook to simulated money. On
2026-09-06 the paper account sent none of the five tags at all, which reads as
new_imd by the rule above but is really just IBKR not bothering on paper. Until
the live account is funded and read, treat the paper reading as a rehearsal of
the plumbing, not as the answer.

What the code does under each regime
------------------------------------

Under old_pdt the counter in agent/pdt.py blocks the books that are held to a
hard limit and writes a note for the ones that are not, exactly as before.

Under new_imd the counter still records every fill, because the ledger still
wants the count at the end of the month, but it never blocks and never sets
would_have_blocked. In its place imd_check() below runs on every entry: gross
exposure after the order has to stay at or below 100 percent of book equity and
cash after the order has to stay at or above zero. A book that never borrows
cannot run an intraday margin deficit, which is the point.

assert_structurally_impossible() is the guard on that claim. Our settings make a
deficit impossible by construction, and this is what makes a settings change
that quietly removes that guarantee fail loudly instead.

Written 2026-09-06. This file talks to nothing: no network, no broker, no clock.
It reads tags it is handed and settings it is handed, and answers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

__all__ = [
    "RULE_ID_IMD",
    "DAY_TRADE_TAGS",
    "IBKR_UNLIMITED",
    "MIN_TAGS_FOR_OLD_PDT",
    "IMD_GROSS_EXPOSURE_PCT_MAX",
    "CENT_TOLERANCE",
    "Regime",
    "RegimeReading",
    "ImdDecision",
    "MarginRegimeConfigError",
    "detect_regime",
    "imd_check",
    "assert_structurally_impossible",
    "as_regime",
    "read_regime_setting",
    "write_regime_setting",
]


# The rule id written in the ledger whenever an order is refused for looking
# like it would create an intraday margin deficit.
RULE_ID_IMD = "intraday_margin_deficit"

# The five tags IBKR sends while an account is still counted the old way.
DAY_TRADE_TAGS = (
    "DayTradesRemaining",
    "DayTradesRemainingT+1",
    "DayTradesRemainingT+2",
    "DayTradesRemainingT+3",
    "DayTradesRemainingT+4",
)

# What IBKR puts in those tags when an account has no day trade limit at all.
IBKR_UNLIMITED = -1.0

# How many of the five tags have to come back as counts before this is read as
# the old regime. Three, because IBKR has been seen to send a short set, and one
# lonely tag is not enough to hang a rulebook on.
MIN_TAGS_FOR_OLD_PDT = 3

# The line the deficit check holds, whatever the settings say. Gross exposure at
# or under 100 percent of equity is the same sentence as "this book does not
# borrow", and a book that does not borrow cannot run a margin deficit.
IMD_GROSS_EXPOSURE_PCT_MAX = 100.0

# Money is compared to the cent. Floating point noise below that is not a breach.
CENT_TOLERANCE = 0.01


class MarginRegimeConfigError(ValueError):
    """Settings that would let an intraday margin deficit happen at all."""


class Regime(str, Enum):
    """Which day trading rulebook this account is under.

    It inherits from str so it writes itself into JSON and yaml as the plain
    word, and so a reading loaded from one place compares equal to the same
    reading built in another.
    """

    OLD_PDT = "old_pdt"
    NEW_IMD = "new_imd"
    UNKNOWN = "unknown"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class RegimeReading:
    """What the account said, and what that means.

    regime    the answer, one of the three above.
    values    the day trade tags that came back, as the broker wrote them, so
              the evidence survives even when it made no sense.
    numbers   the same tags for the ones that were readable as numbers.
    missing   the tags that were not there at all.
    account   the account the tags belong to, when the broker named it.
    note      one sentence a person can read in the morning log.
    """

    regime: Regime
    values: dict[str, str] = field(default_factory=dict)
    numbers: dict[str, float] = field(default_factory=dict)
    missing: tuple[str, ...] = ()
    account: str | None = None
    note: str = ""

    def as_dict(self) -> dict:
        """The shape that goes into the pre-flight JSON."""
        return {
            "regime": self.regime.value,
            "account": self.account,
            "tags_found": dict(self.values),
            "tags_as_numbers": dict(self.numbers),
            "tags_missing": list(self.missing),
            "note": self.note,
        }


@dataclass
class ImdDecision:
    """May this order go, as far as an intraday margin deficit is concerned.

    The same three fields as agent.guardrails.Decision, in the same order, so
    the loop can read a refusal from here the way it reads one from there.
    checked is false when the order could not be tested at all, which happens
    when there is no price on it or no account snapshot to test it against, and
    then the reason for that sits in note rather than in reasons.
    """

    allowed: bool = True
    reasons: list[str] = field(default_factory=list)
    rule_ids: list[str] = field(default_factory=list)
    checked: bool = True
    note: str = ""

    def add(self, rule_id: str, reason: str) -> None:
        """Record one broken limit and refuse the order."""
        self.rule_ids.append(rule_id)
        self.reasons.append(reason)
        self.allowed = False

    @property
    def summary(self) -> str:
        """One line for the log."""
        if self.allowed:
            return self.note or "allowed"
        return "blocked: " + "; ".join(self.reasons)


# ---------------------------------------------------------------------------
# Reading the account
# ---------------------------------------------------------------------------


def detect_regime(account_summary_items) -> RegimeReading:
    """Work out which rulebook the account is under from its summary tags.

    account_summary_items is what IBKR's account summary hands back, in any of
    the three shapes this project sees it in: the list of dictionaries that
    agent/mcp_client.py returns in summary["items"], the list of objects with
    .tag and .value that ib_async returns from accountSummary(), or a plain
    {tag: value} mapping. None and an empty list are read as no tags at all.

    Nothing is guessed. A tag holding something that is not a number makes the
    answer unknown rather than a best effort, and every tag that came back is
    kept on the reading whatever it said.
    """
    found, account = _tag_values(account_summary_items)
    values = {tag: found[tag] for tag in DAY_TRADE_TAGS if tag in found}
    missing = tuple(tag for tag in DAY_TRADE_TAGS if tag not in found)

    numbers: dict[str, float] = {}
    unreadable: list[str] = []
    for tag, raw in values.items():
        number = _as_number(raw)
        if number is None:
            unreadable.append(tag)
        else:
            numbers[tag] = number

    if not values:
        return RegimeReading(
            regime=Regime.NEW_IMD,
            missing=missing,
            account=account,
            note=(
                "The account sent none of the five day trades remaining tags, "
                "which is what an account that is no longer counted the old way "
                "looks like. Under the new rules nothing counts to four and the "
                "job is to avoid an intraday margin deficit instead."
            ),
        )

    if unreadable:
        return RegimeReading(
            regime=Regime.UNKNOWN,
            values=values,
            numbers=numbers,
            missing=missing,
            account=account,
            note=(
                "The account sent "
                + ", ".join(f"{tag} = {values[tag]!r}" for tag in unreadable)
                + ", which is not a number of day trades. Nothing is guessed "
                "from that, so the regime stays unknown and the conservative "
                "reading applies."
            ),
        )

    if any(number == IBKR_UNLIMITED for number in numbers.values()):
        return RegimeReading(
            regime=Regime.NEW_IMD,
            values=values,
            numbers=numbers,
            missing=missing,
            account=account,
            note=(
                "The account reports -1 day trades remaining, which is IBKR's "
                "way of writing unlimited. The old four in five business days "
                "count does not apply to it."
            ),
        )

    negatives = sorted(tag for tag, number in numbers.items() if number < 0)
    if negatives:
        return RegimeReading(
            regime=Regime.UNKNOWN,
            values=values,
            numbers=numbers,
            missing=missing,
            account=account,
            note=(
                "The account reports a negative number of day trades remaining "
                "that is not -1 on " + ", ".join(negatives) + ". Only -1 means "
                "unlimited, so this is not a reading anything should act on."
            ),
        )

    if len(numbers) >= MIN_TAGS_FOR_OLD_PDT:
        return RegimeReading(
            regime=Regime.OLD_PDT,
            values=values,
            numbers=numbers,
            missing=missing,
            account=account,
            note=(
                f"The account is counting day trades down for us: {len(numbers)} "
                "of the five day trades remaining tags came back as plain "
                "counts. That is the pattern day trader rule still applying, so "
                "the five business day counter is the thing that protects the "
                "account."
            ),
        )

    return RegimeReading(
        regime=Regime.UNKNOWN,
        values=values,
        numbers=numbers,
        missing=missing,
        account=account,
        note=(
            f"Only {len(numbers)} of the five day trades remaining tags came "
            f"back, and {MIN_TAGS_FOR_OLD_PDT} are wanted before this is read as "
            "the old rule. Too little to decide on, so the regime stays unknown."
        ),
    )


def _tag_values(items) -> tuple[dict[str, str], str | None]:
    """Pull {tag: value} and the account id out of whatever shape we were given."""
    found: dict[str, str] = {}
    account: str | None = None

    if items is None:
        return found, account

    if isinstance(items, dict):
        # Either {tag: value} or the whole {"account": ..., "items": [...]} answer
        # that agent/mcp_client.py hands back.
        inner = items.get("items")
        if isinstance(inner, (list, tuple)):
            found, account = _tag_values(inner)
            named = items.get("account")
            return found, (account or (str(named) if named else None))
        for tag, value in items.items():
            if isinstance(tag, str):
                found[tag] = "" if value is None else str(value)
        return found, None

    if isinstance(items, (str, bytes)):
        raise ValueError(
            "detect_regime wants the account summary tags, which is a list of "
            f"tag and value pairs, but it was handed the text {items!r}."
        )

    try:
        walk = list(items)
    except TypeError as exc:
        raise ValueError(
            "detect_regime wants the account summary tags, which is a list of "
            f"tag and value pairs, but it was handed a {type(items).__name__}."
        ) from exc

    for item in walk:
        if isinstance(item, dict):
            tag = item.get("tag")
            value = item.get("value")
            owner = item.get("account")
        else:
            tag = getattr(item, "tag", None)
            value = getattr(item, "value", None)
            owner = getattr(item, "account", None)
        if not isinstance(tag, str) or not tag.strip():
            continue
        found[tag.strip()] = "" if value is None else str(value)
        if account is None and isinstance(owner, str) and owner.strip():
            account = owner.strip()
    return found, account


def _as_number(raw) -> float | None:
    """A tag value as a number, or None when it is not one."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def as_regime(value, label: str = "regime") -> Regime:
    """Turn a word out of a settings file into a Regime, refusing anything else."""
    if isinstance(value, Regime):
        return value
    if value is None:
        return Regime.UNKNOWN
    if not isinstance(value, str):
        raise MarginRegimeConfigError(
            f"{label} has to be one of old_pdt, new_imd or unknown, but it is "
            f"{value!r}."
        )
    cleaned = value.strip().lower()
    for regime in Regime:
        if cleaned == regime.value:
            return regime
    raise MarginRegimeConfigError(
        f"{label} is {value!r}, which is not a day trading regime. It has to be "
        "old_pdt (the pattern day trader rule still applies), new_imd (the "
        "intraday margin deficit rules replaced it) or unknown (nobody has "
        "asked the account yet)."
    )


# ---------------------------------------------------------------------------
# The check that replaces counting under the new rules
# ---------------------------------------------------------------------------


def imd_check(g, state, intent) -> ImdDecision:
    """Could this order leave the account short of margin during the day?

    g is the book's settings, state is the account snapshot and intent is the
    order, the same three things agent/guardrails.py checks. All three are read
    with getattr and nothing is imported from guardrails here, so a small stand
    in object with the same shape works exactly like the real thing.

    Two tests, and an order has to pass both:

    1. Gross exposure after the order stays at or below 100 percent of what the
       book is worth. Longs and shorts add up rather than cancelling out,
       because both sides can lose money on the same morning.
    2. Cash after the order stays at or above zero. Money the book does not have
       is money it would be borrowing, and borrowing is what creates a deficit.
       This one only runs when the snapshot brought a real cash figure with it.
       Worked out from equity less positions, it is the same inequality as the
       first test and would only say the same thing twice.

    A short entry is treated as spending its full value in cash. The broker
    credits the sale and then holds more than that against the borrow, so
    counting it as spent is the conservative reading and it keeps this file from
    having to model Reg T.

    100 percent is written into this file rather than read from the settings, on
    purpose. It is the line that makes a deficit impossible, and a settings file
    that raised its own cap should not be able to move it.
    assert_structurally_impossible() below is what makes such a settings file
    fail loudly rather than silently loosening this.

    Orders that are not entries are never refused here: getting out of something
    reduces exposure, and an order that closes a position cannot create a
    deficit. An order with no price on it, or a snapshot with no equity in it,
    cannot be tested at all, and comes back allowed with checked false, which is
    the same thing the gross exposure cap in agent/guardrails.py does.
    """
    if state is None:
        return ImdDecision(
            checked=False,
            note=(
                "No account snapshot was handed to the day trade check, so the "
                "intraday margin deficit test could not run. The gross exposure "
                "cap in agent/guardrails.py still runs on every order."
            ),
        )

    purpose = str(getattr(intent, "purpose", "entry") or "entry").strip().lower()
    if purpose != "entry":
        return ImdDecision(
            note=(
                f"This order is an {purpose}, and getting out of a position "
                "cannot create an intraday margin deficit."
            )
        )

    notional = _order_notional(intent)
    if notional is None:
        return ImdDecision(
            checked=False,
            note=(
                "This order carries no limit price, so there is no value to add "
                "up and the intraday margin deficit test could not run. "
                "max_order_notional in agent/guardrails.py refuses it first."
            ),
        )

    equity = _finite(getattr(state, "equity", None))
    if equity is None or equity <= 0:
        return ImdDecision(
            checked=False,
            note=(
                "The account snapshot has no positive equity in it, so there is "
                "nothing to measure this order against. The daily loss cap owns "
                "the case of a book with nothing left in it."
            ),
        )

    held = _gross_exposure_now(state)
    pending = _finite(getattr(state, "pending_order_notional", 0.0)) or 0.0
    cap_pct = _imd_cap_pct(g)
    cap = equity * (cap_pct / 100.0)
    would_be = held + pending + notional

    decision = ImdDecision()

    if would_be > cap + CENT_TOLERANCE:
        share = would_be / equity * 100.0
        decision.add(
            RULE_ID_IMD,
            f"This order would put {_money(would_be)} to work against "
            f"{_money(equity)} of book equity: {_money(held)} already in "
            f"positions, {_money(pending)} on order and {_money(notional)} from "
            f"this order. That is {share:.1f} percent, over the "
            f"{_plain_number(cap_pct)} percent ({_money(cap)}) that keeps the "
            "book out of borrowed money. Under the intraday margin deficit "
            "rules that replaced the pattern day trader rule, an order that "
            "borrows is an order that can leave a deficit to cure.",
        )

    cash_now, given = _cash_now(state, equity, held)
    cash_after = cash_now - pending - notional
    # A snapshot with no cash figure on it gives cash as equity less what is
    # already in positions, and then "cash after stays at or above zero" is the
    # same inequality as the gross exposure test above, word for word. Running
    # it anyway would only put the same complaint in the log twice, so the cash
    # test runs when the snapshot brought a real cash figure with it.
    if given and cash_after < -CENT_TOLERANCE:
        decision.add(
            RULE_ID_IMD,
            f"This order would leave the book with {_money(cash_after)} of cash: "
            f"{_money(cash_now)} now, less {_money(pending)} already on order and "
            f"{_money(notional)} for this one. Anything below zero is money the "
            "book does not have, which is the borrowing the intraday margin "
            "deficit rules are about. A short counts as spending its full value "
            "here, because the broker holds more than the sale proceeds against "
            "the borrow.",
        )

    if decision.allowed:
        decision.note = (
            f"{_money(would_be)} of {_money(cap)} allowed, and {_money(cash_after)} "
            "of cash left, so this order cannot create an intraday margin deficit."
        )
    return decision


def assert_structurally_impossible(g) -> None:
    """Insist the settings still make an intraday margin deficit impossible.

    The claim this project makes, in docs/STRATEGY.md and to Mo, is that the
    100 percent gross exposure cap with no borrowing means the new rules cost us
    nothing: there is no order we could send that creates a deficit. That claim
    is only true while the settings say so, and settings get edited.

    So this raises MarginRegimeConfigError, which is a ValueError, if
    money.gross_exposure_pct_max is above 100, or if a setting appears that lets
    the book borrow. There is no borrowing setting today. The two names checked
    here are where one would go, so that adding it turns into a loud failure on
    the next run rather than a quiet loosening nobody notices.

    Call it once when the settings load under the new regime, not per order.
    """
    money = getattr(g, "money", None)
    where = _settings_source(g)

    cap = _finite(getattr(money, "gross_exposure_pct_max", None))
    if cap is None:
        raise MarginRegimeConfigError(
            f"The settings{where} have no money.gross_exposure_pct_max, so "
            "nothing stops this book borrowing, and under the intraday margin "
            "deficit rules borrowing is exactly what creates a deficit to cure. "
            "Set it to 100."
        )
    if cap > IMD_GROSS_EXPOSURE_PCT_MAX:
        raise MarginRegimeConfigError(
            f"money.gross_exposure_pct_max{where} is {_plain_number(cap)} "
            f"percent, above the {_plain_number(IMD_GROSS_EXPOSURE_PCT_MAX)} "
            "percent that keeps this book out of borrowed money. Above 100 the "
            "book buys with the broker's money, which under the intraday margin "
            "deficit rules that replaced the pattern day trader rule can leave a "
            "deficit that has to be cured in about three business days, and four "
            "uncured deficits in twelve months bring a 90 day restriction. Put "
            "it back to 100 or lower, or take this assertion out on purpose and "
            "write down why."
        )

    borrowing = getattr(money, "allow_margin_borrowing", None)
    if borrowing:
        raise MarginRegimeConfigError(
            f"money.allow_margin_borrowing{where} is {borrowing!r}. This book is "
            "built on never borrowing, which is the whole reason an intraday "
            "margin deficit cannot happen to it. Turning borrowing on needs a "
            "decision from Mo and a different set of checks, not a settings edit."
        )

    leverage = _finite(getattr(money, "max_leverage", None))
    if leverage is not None and leverage > 1.0:
        raise MarginRegimeConfigError(
            f"money.max_leverage{where} is {_plain_number(leverage)}, and "
            "anything above 1 is borrowing. A book that borrows can run an "
            "intraday margin deficit, which is the thing the new day trading "
            "rules count against the account."
        )


# ---------------------------------------------------------------------------
# The regime as a setting, read and written without touching the comments
# ---------------------------------------------------------------------------

#: The pdt block's own indent in config/guardrails.yaml. Two spaces, like every
#: other section in that file.
_REGIME_LINE = re.compile(
    r"^(?P<indent>[ \t]*)regime:(?P<gap>[ \t]*)(?P<value>[A-Za-z_]+)(?P<rest>.*)$"
)
_TOP_LEVEL_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*:")


def read_regime_setting(config_path: str | Path) -> tuple[Regime, Regime]:
    """The regime and the fallback, straight out of the pdt block of a yaml file.

    Comes back as (regime, treat_unknown_as). A file that is missing, broken or
    has no pdt block gives (unknown, old_pdt), which is the conservative pair:
    nobody has asked the account, so behave as though the old rule still binds.

    This reads the shared settings file rather than a book's own strategy.yaml,
    because the regime is a fact about the account, not about a strategy.
    """
    text = _read_text(config_path)
    if text is None:
        return Regime.UNKNOWN, Regime.OLD_PDT

    try:
        import yaml
    except ImportError:                                            # pragma: no cover
        return Regime.UNKNOWN, Regime.OLD_PDT

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return Regime.UNKNOWN, Regime.OLD_PDT

    section = data.get("pdt") if isinstance(data, dict) else None
    if not isinstance(section, dict):
        return Regime.UNKNOWN, Regime.OLD_PDT

    regime = as_regime(section.get("regime"), "pdt.regime")
    fallback = as_regime(section.get("treat_unknown_as"), "pdt.treat_unknown_as")
    if fallback is Regime.UNKNOWN:
        fallback = Regime.OLD_PDT
    return regime, fallback


def write_regime_setting(config_path: str | Path, regime) -> bool:
    """Put a regime into the pdt block of a yaml file, leaving the comments alone.

    Only the word after "regime:" inside the pdt block changes. Everything else
    in the file, every comment and every blank line, is left exactly as it was,
    which is why this edits the text rather than loading the yaml and writing it
    back out. Loading and dumping would throw away the comments that explain the
    file, and those comments are most of what makes it readable.

    Returns True when the file was changed and False when it already said that,
    and raises MarginRegimeConfigError when there is no regime line in a pdt
    block to change.
    """
    wanted = as_regime(regime, "regime")
    path = Path(config_path).expanduser()
    text = _read_text(path)
    if text is None:
        raise MarginRegimeConfigError(
            f"There is no settings file at {path} to write the day trading "
            "regime into."
        )

    lines = text.splitlines(keepends=True)
    in_pdt = False
    for number, line in enumerate(lines):
        bare = line.rstrip("\n")
        if _TOP_LEVEL_KEY.match(bare):
            in_pdt = bare.split(":", 1)[0] == "pdt"
            continue
        if not in_pdt:
            continue
        match = _REGIME_LINE.match(bare)
        if not match:
            continue
        if match.group("value") == wanted.value:
            return False
        ending = "\n" if line.endswith("\n") else ""
        lines[number] = (
            match.group("indent")
            + "regime:"
            + match.group("gap")
            + wanted.value
            + match.group("rest")
            + ending
        )
        path.write_text("".join(lines), encoding="utf-8")
        return True

    raise MarginRegimeConfigError(
        f"The settings file {path} has no regime line inside its pdt block, so "
        "there is nothing to write the detected day trading regime into. Add "
        "  regime: unknown  under pdt: and run this again."
    )


def _read_text(config_path: str | Path) -> str | None:
    path = Path(config_path).expanduser()
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------------------
# Small readers, all of them getattr so nothing here needs guardrails imported
# ---------------------------------------------------------------------------


def _order_notional(intent) -> float | None:
    """What the order would cost, from its own notional or its price and size."""
    notional = _finite(getattr(intent, "notional", None))
    if notional is not None:
        return abs(notional)
    price = _finite(getattr(intent, "limit_price", None))
    qty = _finite(getattr(intent, "qty", None))
    if price is None or qty is None:
        return None
    return abs(price * qty)


def _gross_exposure_now(state) -> float:
    """Every position added up, ignoring which way it points."""
    reader = getattr(state, "gross_exposure_now", None)
    if callable(reader):
        value = _finite(reader())
        if value is not None:
            return abs(value)
    given = _finite(getattr(state, "gross_exposure", None))
    if given is not None:
        return abs(given)
    total = 0.0
    for position in (getattr(state, "open_positions", None) or {}).values():
        value = _finite(getattr(position, "market_value", None))
        if value is not None:
            total += abs(value)
    return total


def _cash_now(state, equity: float, held: float) -> tuple[float, bool]:
    """Free cash, and whether the snapshot actually said so.

    Comes back as (cash, given). A snapshot with no cash figure on it is read as
    equity less what is already in positions, which is what free cash is in a
    book that does not borrow, and given is false to say the number was worked
    out rather than reported.
    """
    for name in ("cash", "cash_available", "available_cash"):
        value = _finite(getattr(state, name, None))
        if value is not None:
            return value, True
    return equity - held, False


def _imd_cap_pct(g) -> float:
    """The gross exposure line, never above the 100 percent that matters here."""
    money = getattr(g, "money", None)
    configured = _finite(getattr(money, "gross_exposure_pct_max", None))
    if configured is None:
        return IMD_GROSS_EXPOSURE_PCT_MAX
    return min(configured, IMD_GROSS_EXPOSURE_PCT_MAX)


def _settings_source(g) -> str:
    """" for book A", or nothing when the settings do not say which book."""
    book_id = getattr(g, "book_id", None)
    return f" for book {book_id}" if book_id else ""


def _finite(value) -> float | None:
    """A number, or None when it is not one or is not finite."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _money(value: float) -> str:
    """1,234.50 dollars, written the way a person says it."""
    return f"{value:,.2f} dollars"


def _plain_number(value: float) -> str:
    """100 rather than 100.0, and 12.5 still as 12.5."""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"

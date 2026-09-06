"""The daily check that the five books and the broker still agree.

Five virtual books, A, B, C, D and E, share one IBKR paper account, DUT077572.
Each book tags every order it sends with an order reference, "BOOK_A" for book
A, "BOOK_B" for book B and so on. That tag is the only way a fill inside one
shared account can be traced back to the book that asked for it.

Reconciliation is the daily check that all of this still adds up. What the five
books believe they hold has to equal what the broker actually holds, and no
order should be floating around the account unclaimed. When it does not add up,
the affected book stops trading until a human has looked, because a book that
has lost track of its own positions will size its next order off a number that
is not true.

This module is pure arithmetic. It never talks to the network, IB Gateway or a
broker, it never reads or writes a file, and it never places or cancels an
order. The trading loop collects the broker's positions and open orders,
collects what each book believes, hands all of it to reconcile() and acts on the
report that comes back. That is why this can be tested in under a second with no
account open.

The four rules, and one thing that is reported rather than refused
-----------------------------------------------------------------

1. Position quantities, checked one TICKER at a time. For every symbol at least
   one book claims, the quantities the books claim have to add up to exactly
   what the broker reports for that ticker. Whole shares, and the tolerance is
   zero. This also covers a symbol the books claim that the broker does not hold
   at all, because the broker's quantity is then simply zero.

   When a ticker does not add up, the books that stop are exactly the ones with
   a non-zero position in that ticker. Not all five, and not one picked out of
   the group. A book holding nothing in the disputed name carries on untouched,
   because nothing about its own numbers is in doubt.

2. Broker orders. Every order working at the broker has to carry an order
   reference that belongs to one of the books, and that book has to have the
   same order in its own working orders.

3. Book orders. Every working order a book believes in has to actually exist at
   the broker.

4. Orphans. A position at the broker that no book claims at all is an orphan.
   The paper account already holds 1 share of SPY left over from a manual test,
   so the trading loop passes expected_orphans={"SPY": 1} and that one share is
   not treated as a problem until it is sold.

Two books may hold the same ticker
----------------------------------

This was a fifth rule and is not any more. On 2026-09-06 the review team raised
cross-book symbol exclusivity as a blocking finding and it went in the same day:
no two books may claim the same symbol, whatever the quantities came to, and both
of them stop. The hub overturned it the same day.

The reasoning. IBKR does net positions by symbol inside the one shared account,
so the broker reports a single line for a shared name. But telling the two books
apart never depended on that line. Every order already carries an orderRef tag
naming the book that sent it, and every book keeps its own position record, and
those two together are what attribute a fill. And forbidding it would throw away
the thing month one exists to measure: two independent strategies picking the
same name on the same morning is agreement, and agreement is signal.

So a shared ticker is now written down and checked, not punished. Rule one
already asks the right question of it, because rule one adds up every book
holding the ticker before comparing. What is new is that the report says out loud
that a ticker is shared and whether the total added up, so the daily report can
print "two books hold NVDA and the numbers add up" rather than saying nothing at
all. Those records come back on report.shared with kind symbol_shared. They are
never mismatches and they halt nobody.

Mo can overturn this. Making a shared ticker a problem again means turning the
Shared records below back into Mismatch records, which is where they came from.

Three deliberate decisions
--------------------------

An order reference that belongs to no book is a real problem, so it makes the
report say ok is False, but there is nobody to punish for it. It therefore never
appears in books_to_halt. The five books that are behaving keep trading and the
loose order is left for a human to deal with. Halting every book over an order
none of them sent would be the wrong trade.

One disagreement can involve several books at once, and it is written up as one
sentence naming all of them. Each of those books gets its own Mismatch, so each
of them lands in books_to_halt, but the identical sentence is only written into
lines once, because it is one thing for a person to read.

An orphan is not a mismatch. It has no book to blame, so it halts nobody, but an
unexpected one still makes ok False. Expected orphans, such as that share of
SPY, get a line saying plainly that they were expected and are fine.

Written 2026-09-06. Every number lives in the data the caller hands in, not
here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

__all__ = [
    "KIND_POSITION_QTY",
    "KIND_SYMBOL_SHARED",
    "KIND_UNKNOWN_ORDER_REF",
    "KIND_ORDER_NOT_IN_BOOK",
    "KIND_MISSING_WORKING_ORDER",
    "KIND_ORPHAN_POSITION",
    "ORDER_REF_PREFIX",
    "Mismatch",
    "Orphan",
    "Shared",
    "ReconcileReport",
    "reconcile",
]


# What kind of thing a line is about. These strings are stable, in the same way
# the guardrail rule ids are stable, so the ledger can count how often each one
# turns up without reading the English.
#
# All but one of them mark a problem. KIND_SYMBOL_SHARED is the exception: since
# 2026-09-06 it marks a ticker that more than one book holds, which is allowed,
# and it says whether the total added up. It used to mean "two books are in the
# same name, which is forbidden". See the top of this file for why that changed.
KIND_POSITION_QTY = "position_qty"
KIND_SYMBOL_SHARED = "symbol_shared"
KIND_UNKNOWN_ORDER_REF = "unknown_order_ref"
KIND_ORDER_NOT_IN_BOOK = "order_not_in_book"
KIND_MISSING_WORKING_ORDER = "missing_working_order"
KIND_ORPHAN_POSITION = "orphan_position"

# The front of every order reference, so BOOK_A belongs to book A. This is the
# same string as ORDER_REF_PREFIX in agent/guardrails.py, and it is repeated
# here so that this module stays pure arithmetic with nothing to import. A test
# in tests/test_reconcile.py checks the two never drift apart.
ORDER_REF_PREFIX = "BOOK_"


# ---------------------------------------------------------------------------
# What comes back
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Mismatch:
    """One thing that does not add up, and the book to blame for it.

    book_id  is None when no book can be blamed, which today only happens for an
             order at the broker whose reference belongs to nobody.
    kind     one of the KIND_ constants above.
    symbol   the share this is about, or None when it is only about an order.
    order_id the order this is about, as text, or None when it is about a
             position rather than an order.
    line     one plain English sentence a person can read, ending in a full stop.
    """

    book_id: str | None
    kind: str
    symbol: str | None
    order_id: str | None
    line: str


@dataclass(frozen=True)
class Orphan:
    """A position at the broker that no book claims.

    expected is True when the caller told us about this one in advance, for
    example the single share of SPY left behind by a manual test. An expected
    orphan is not a problem and still gets a line, so a reader can see it was
    noticed and understood.
    """

    symbol: str
    qty: int
    avg_cost: float
    expected: bool
    line: str

    @property
    def kind(self) -> str:
        """The stable label for this kind of problem, for the ledger to count."""
        return KIND_ORPHAN_POSITION


@dataclass(frozen=True)
class Shared:
    """A ticker more than one book holds, and whether the total adds up.

    This is not a problem. It is a fact worth writing down, because two books
    picking the same name on the same morning is the agreement between strategies
    that month one is measuring, and because a reader of the daily report should
    not have to guess why one ticker has two books against it.

    holders    every book with a non-zero position in this ticker and what each
               one believes it holds, in alphabetical order of book id.
    total      what those add up to.
    broker_qty what the broker reports for the ticker, as one netted line.
    matches    True when total equals broker_qty, which is the ordinary case. A
               False here always comes with a KIND_POSITION_QTY mismatch against
               every one of these books, and that is what actually halts them.
    line       one plain English sentence a person can read.
    """

    symbol: str
    holders: tuple[tuple[str, int], ...]
    total: int
    broker_qty: int
    matches: bool
    line: str

    @property
    def kind(self) -> str:
        """The stable label for this kind of line, for the ledger to count."""
        return KIND_SYMBOL_SHARED

    @property
    def book_ids(self) -> tuple[str, ...]:
        """Just the books, for a caller that does not care about the quantities."""
        return tuple(book_id for book_id, _ in self.holders)


@dataclass(frozen=True)
class ReconcileReport:
    """The answer: did everything add up, and if not, what and who.

    ok            True only when there is nothing wrong at all. Shared tickers
                  never make it False, because sharing a ticker is allowed.
    mismatches    every disagreement, sorted so the same input always gives the
                  same order.
    orphans       every position no book claims, expected ones included.
    books_to_halt every book with at least one mismatch against its name, in
                  alphabetical order and each named once.
    lines         every sentence, ready to be written straight into a log.
    shared        every ticker more than one book holds, in alphabetical order.
                  Reporting, not a problem. See the Shared class above.
    """

    ok: bool
    mismatches: tuple[Mismatch, ...]
    orphans: tuple[Orphan, ...]
    books_to_halt: tuple[str, ...]
    lines: tuple[str, ...]
    shared: tuple[Shared, ...] = ()

    def mismatches_for(self, book_id: str) -> tuple[Mismatch, ...]:
        """Everything wrong with one book. A book id is read however it is typed."""
        wanted = _clean_book_id(book_id)
        return tuple(
            mismatch
            for mismatch in self.mismatches
            if mismatch.book_id is not None
            and _clean_book_id(mismatch.book_id) == wanted
        )

    @property
    def unexpected_orphans(self) -> tuple[Orphan, ...]:
        """The positions nobody claims and nobody warned us about."""
        return tuple(orphan for orphan in self.orphans if not orphan.expected)

    @property
    def summary(self) -> str:
        """One line for the log, such as "3 problems across books A, C"."""
        if self.ok:
            return "everything matched"
        count = len({mismatch.line for mismatch in self.mismatches}) + len(
            self.unexpected_orphans
        )
        problems = "1 problem" if count == 1 else f"{count} problems"
        if not self.books_to_halt:
            return f"{problems}, with no book to blame"
        if len(self.books_to_halt) == 1:
            return f"{problems} across book {self.books_to_halt[0]}"
        return f"{problems} across books {', '.join(self.books_to_halt)}"


# ---------------------------------------------------------------------------
# The check itself
# ---------------------------------------------------------------------------


def reconcile(
    broker_positions: list[dict],
    broker_open_orders: list[dict],
    books_state: dict[str, dict],
    expected_orphans=None,
) -> ReconcileReport:
    """Check what the five books believe against what the broker actually has.

    broker_positions   a list of dicts, each with "symbol", "qty" and
                       "avg_cost". A short position is a negative quantity. A
                       missing avg_cost is read as zero.
    broker_open_orders a list of dicts, each with "orderId", "symbol", "side",
                       "qty" and "order_ref". The reference may be missing.
    books_state        keyed by book id, so {"A": {...}, "B": {...}}. Each value
                       holds "positions", a plain {symbol: quantity} map, and
                       "working_orders", keyed by order id. Either may be
                       missing or empty, and a quantity of zero means the book
                       holds nothing rather than that it claims nothing.
    expected_orphans   the positions we already know nobody will claim, and
                       there are two ways to say it. A mapping such as
                       {"SPY": 1} only forgives that exact quantity, so if the
                       share count changes the orphan becomes a problem again. A
                       plain list of symbols such as ["SPY"] forgives any
                       quantity of that symbol. None means nothing is forgiven.

    Nothing here talks to a broker and nothing here places an order. Raises a
    plain ValueError when books_state is not a dictionary, when a book's entry
    in it is not a dictionary, or when a position has no symbol on it.
    """
    claims, working_orders = _clean_books_state(books_state)
    broker_qty, broker_cost = _clean_broker_positions(broker_positions)
    orders = _clean_broker_orders(broker_open_orders)
    expected = _clean_expected_orphans(expected_orphans)

    mismatches: list[Mismatch] = []
    mismatches.extend(_check_position_quantities(claims, broker_qty))
    mismatches.extend(_check_broker_orders(claims, working_orders, orders))
    mismatches.extend(_check_book_working_orders(working_orders, orders))
    mismatches.sort(key=_mismatch_sort_key)

    shared = _find_shared_symbols(claims, broker_qty)

    orphans = sorted(
        _find_orphans(claims, broker_qty, broker_cost, expected),
        key=lambda orphan: orphan.symbol,
    )

    books_to_halt = tuple(
        sorted({m.book_id for m in mismatches if m.book_id is not None})
    )
    unexpected = [orphan for orphan in orphans if not orphan.expected]

    # A shared ticker that adds up gets a sentence, because the daily report
    # should say "two books hold NVDA and the numbers add up" rather than being
    # silent about it. A shared ticker that does NOT add up gets none, because
    # rule one has already written one sentence naming every book involved, what
    # each believes, the total and who stops. Saying it twice is noise for the
    # person reading. Either way the full record is on report.shared.
    lines = _dedupe(
        [m.line for m in mismatches]
        + [orphan.line for orphan in orphans]
        + [record.line for record in shared if record.matches]
    )

    return ReconcileReport(
        ok=not mismatches and not unexpected,
        mismatches=tuple(mismatches),
        orphans=tuple(orphans),
        books_to_halt=books_to_halt,
        lines=lines,
        shared=shared,
    )


def _check_position_quantities(
    claims: dict[str, dict[str, int]], broker_qty: dict[str, int]
) -> list[Mismatch]:
    """Rule one: what the books claim between them has to be what the broker has.

    One ticker at a time. The broker reports a single netted line per symbol, so
    the only fair comparison is against the sum of every book holding that
    symbol. Since 2026-09-06 that sum can genuinely have several books in it,
    because two books are allowed to hold the same name.

    The books that stop are exactly the holders: every book with a non-zero
    position in the disputed ticker, and nobody else. A book holding none of it
    has nothing in doubt and carries on trading.

    Only symbols at least one book claims are looked at here. A symbol nobody
    claims is an orphan instead, which is a different problem with nobody to
    blame for it.
    """
    found: list[Mismatch] = []
    for symbol in sorted(_claimed_symbols(claims)):
        holders = [
            (book_id, claims[book_id][symbol])
            for book_id in sorted(claims)
            if claims[book_id].get(symbol)
        ]
        total = sum(qty for _, qty in holders)
        theirs = broker_qty.get(symbol, 0)
        if total == theirs:
            continue
        line = _position_line(symbol, holders, total, theirs)
        for book_id, _ in holders:
            found.append(
                Mismatch(
                    book_id=book_id,
                    kind=KIND_POSITION_QTY,
                    symbol=symbol,
                    order_id=None,
                    line=line,
                )
            )
    return found


def _find_shared_symbols(
    claims: dict[str, dict[str, int]], broker_qty: dict[str, int]
) -> tuple[Shared, ...]:
    """Every ticker more than one book holds, and whether the total adds up.

    This is not a rule and it refuses nothing. Until 2026-09-06 it was a rule:
    two books in one name stopped both of them. The hub retired that the same
    day, because the orderRef tag on every order plus each book's own position
    record are what attribute a fill, not the broker's netted line, and because
    two strategies picking the same name on the same morning is the agreement
    month one is meant to measure. The top of this file has the full reasoning.

    What is left is worth reporting. Rule one already checks the ticker properly,
    by adding up every book holding it before comparing against the broker, so
    the arithmetic needs nothing extra here. What a person reading the daily
    report needs is to be told the ticker is shared at all, and whether it came
    out right.
    """
    found: list[Shared] = []
    for symbol in sorted(_claimed_symbols(claims)):
        holders = [
            (book_id, claims[book_id][symbol])
            for book_id in sorted(claims)
            if claims[book_id].get(symbol)
        ]
        if len(holders) < 2:
            continue
        total = sum(qty for _, qty in holders)
        theirs = broker_qty.get(symbol, 0)
        found.append(
            Shared(
                symbol=symbol,
                holders=tuple(holders),
                total=total,
                broker_qty=theirs,
                matches=total == theirs,
                line=_shared_symbol_line(symbol, holders, total, theirs),
            )
        )
    return tuple(found)


def _check_broker_orders(
    claims: dict[str, dict[str, int]],
    working_orders: dict[str, dict[str, dict]],
    orders: list[dict],
) -> list[Mismatch]:
    """Rule two: every order at the broker names a book, and that book knows it."""
    found: list[Mismatch] = []
    for order in orders:
        book_id = _book_for_order_ref(order["order_ref"], claims)
        described = _order_words(order["symbol"], order["side"], order["qty"])
        order_id = order["order_id"]
        where = f"order id {order_id}" if order_id else "an order with no id on it"

        if book_id is None:
            if order["order_ref"]:
                middle = (
                    f"and its order reference {order['order_ref']} belongs to none "
                    "of the books"
                )
            else:
                middle = (
                    "and it carries no order reference at all, so there is no way "
                    "to tell which book sent it"
                )
            found.append(
                Mismatch(
                    book_id=None,
                    kind=KIND_UNKNOWN_ORDER_REF,
                    symbol=order["symbol"],
                    order_id=order_id or None,
                    line=(
                        f"The broker is working {described}, {where}, {middle}, so "
                        "there is no book to stop. Someone has to look at that "
                        "order by hand."
                    ),
                )
            )
            continue

        if order_id and order_id in working_orders[book_id]:
            continue

        found.append(
            Mismatch(
                book_id=book_id,
                kind=KIND_ORDER_NOT_IN_BOOK,
                symbol=order["symbol"],
                order_id=order_id or None,
                line=(
                    f"The broker is working {described}, {where}, tagged "
                    f"{order['order_ref']} for book {book_id}, but book {book_id} "
                    f"has no record of it. Book {book_id} stops trading until "
                    "someone looks."
                ),
            )
        )
    return found


def _check_book_working_orders(
    working_orders: dict[str, dict[str, dict]], orders: list[dict]
) -> list[Mismatch]:
    """Rule three: an order a book is waiting on has to exist at the broker."""
    at_broker = {order["order_id"] for order in orders if order["order_id"]}
    found: list[Mismatch] = []
    for book_id in sorted(working_orders):
        for order_id in sorted(working_orders[book_id], key=_order_sort_key):
            if order_id in at_broker:
                continue
            details = working_orders[book_id][order_id]
            described = _order_words(
                _optional_symbol(details.get("symbol")),
                _clean_side(details.get("side")),
                _optional_shares(details.get("qty")),
            )
            found.append(
                Mismatch(
                    book_id=book_id,
                    kind=KIND_MISSING_WORKING_ORDER,
                    symbol=_optional_symbol(details.get("symbol")),
                    order_id=order_id,
                    line=(
                        f"Book {book_id} believes it has order {order_id} working, "
                        f"{described}, but the broker has no order with that id. "
                        f"Book {book_id} stops trading until someone looks."
                    ),
                )
            )
    return found


def _find_orphans(
    claims: dict[str, dict[str, int]],
    broker_qty: dict[str, int],
    broker_cost: dict[str, float],
    expected: tuple[dict[str, int] | None, set[str]],
) -> list[Orphan]:
    """Rule four: a holding at the broker that no book has put its name to."""
    expected_quantities, expected_symbols = expected
    claimed = _claimed_symbols(claims)
    found: list[Orphan] = []
    for symbol, qty in broker_qty.items():
        if qty == 0 or symbol in claimed:
            continue
        cost = broker_cost.get(symbol, 0.0)
        if expected_quantities is not None and symbol in expected_quantities:
            is_expected = expected_quantities[symbol] == qty
        else:
            is_expected = symbol in expected_symbols
        found.append(
            Orphan(
                symbol=symbol,
                qty=qty,
                avg_cost=cost,
                expected=is_expected,
                line=_orphan_line(symbol, qty, cost, is_expected, expected_quantities),
            )
        )
    return found


# ---------------------------------------------------------------------------
# Writing the sentences
# ---------------------------------------------------------------------------


def _position_line(
    symbol: str, holders: list[tuple[str, int]], total: int, theirs: int
) -> str:
    """The one sentence that explains a disagreement about a symbol.

    It names every book involved, what each of them believes, what that comes to
    between them and what the broker says instead, then says who stops trading.
    """
    clauses = [
        _claim_clause(book_id, qty, symbol=symbol, first=index == 0)
        for index, (book_id, qty) in enumerate(holders)
    ]
    sentence = _join_with_and(clauses)
    if len(clauses) > 1:
        sentence += f", which is {_total_words(total)} between them"
    sentence += f", but the broker reports {_broker_words(theirs)}."
    return f"{sentence} {_halt_words([book_id for book_id, _ in holders])}"


def _shared_symbol_line(
    symbol: str, holders: list[tuple[str, int]], total: int, theirs: int
) -> str:
    """The one sentence that says a ticker is shared and whether it added up.

    Two shapes. When the total matches the broker, this is the whole story and
    nothing is wrong. When it does not, this says so plainly, but the sentence
    that actually gets logged is rule one's, which names the same books and says
    who stops.
    """
    clauses = [
        _claim_clause(book_id, qty, symbol=symbol, first=index == 0)
        for index, (book_id, qty) in enumerate(holders)
    ]
    named = [book_id for book_id, _ in holders]
    how_many = "Two books" if len(holders) == 2 else f"{len(holders)} books"
    opening = (
        f"{_join_with_and(clauses)}, which is {_total_words(total)} between them"
    )
    if total == theirs:
        return (
            f"{opening}, and the broker reports {_broker_words(theirs)}. "
            f"{how_many} holding {symbol} at once is allowed, and the numbers add "
            "up, so nothing is wrong and no book stops trading."
        )
    return (
        f"{opening}, but the broker reports {_broker_words(theirs)}. "
        f"{how_many} holding {symbol} at once is allowed, but the total still has "
        f"to match the broker and this one does not. {_halt_words(named)}"
    )


def _claim_clause(book_id: str, qty: int, symbol: str, first: bool) -> str:
    """One book's part of the sentence. Only the first one repeats the symbol."""
    verb = "is short" if qty < 0 else "holds"
    amount = _shares(abs(qty)) if first else str(abs(qty))
    name = f"Book {book_id}" if first else f"book {book_id}"
    tail = f" of {symbol}" if first else ""
    return f"{name} believes it {verb} {amount}{tail}"


def _halt_words(book_ids: list[str]) -> str:
    """Who stops trading, worded for one book or for several."""
    if len(book_ids) == 1:
        return f"Book {book_ids[0]} stops trading until someone looks."
    named = _join_with_and(
        [f"Book {book_ids[0]}"] + [f"book {book_id}" for book_id in book_ids[1:]]
    )
    return f"{named} stop trading until someone looks."


def _orphan_line(
    symbol: str,
    qty: int,
    cost: float,
    is_expected: bool,
    expected_quantities: dict[str, int] | None,
) -> str:
    """The sentence for a holding nobody claims, expected or not."""
    them = "it" if abs(qty) == 1 else "them"
    they = "it" if abs(qty) == 1 else "they"
    if qty < 0:
        holding = f"The broker is short {_shares(abs(qty))} of {symbol}"
    else:
        holding = f"The broker holds {_shares(qty)} of {symbol}"
    opening = (
        f"{holding} at an average cost of {_money(cost)} each, and no book claims "
        f"{them}"
    )
    if is_expected:
        return (
            f"{opening}, which is exactly what we expect to be left over there, so "
            "nothing is wrong and no book stops trading."
        )
    if expected_quantities is not None and symbol in expected_quantities:
        return (
            f"{opening}. We expected {_shares(expected_quantities[symbol])} of "
            f"{symbol} to be sitting there unclaimed, so the amount has changed and "
            "somebody has to look at it. No book is stopped, because no book owns "
            f"{them}."
        )
    return (
        f"{opening}, so nobody knows where {they} came from. No book is stopped, "
        f"because no book owns {them}, but somebody has to look at it."
    )


def _order_words(symbol: str | None, side: str | None, qty: int | None) -> str:
    """An order in plain words, as far as the details we were given allow."""
    verb = {"BUY": "buy", "SELL": "sell"}.get(side or "")
    if verb and qty and symbol:
        return f"an order to {verb} {_shares(abs(qty))} of {symbol}"
    if verb and symbol:
        return f"an order to {verb} {symbol}"
    if symbol:
        return f"an order for {symbol}"
    return "an order"


def _shares(count: int) -> str:
    """1 share, 2 shares, and never 1 shares."""
    return "1 share" if abs(count) == 1 else f"{abs(count)} shares"


def _total_words(total: int) -> str:
    if total < 0:
        return f"{abs(total)} short"
    if total == 0:
        return "nothing"
    return str(total)


def _broker_words(qty: int) -> str:
    if qty < 0:
        return f"{abs(qty)} short"
    if qty == 0:
        return "none at all"
    return str(qty)


def _join_with_and(parts: list[str]) -> str:
    """A, B and C, the way a person writes a list."""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _dedupe(lines: list[str]) -> tuple[str, ...]:
    """The same sentence twice is still one thing to read, so keep the first."""
    seen: set[str] = set()
    kept: list[str] = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            kept.append(line)
    return tuple(kept)


# ---------------------------------------------------------------------------
# Reading what the caller handed in, defensively
# ---------------------------------------------------------------------------


def _clean_books_state(
    books_state: dict[str, dict],
) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, dict]]]:
    """What each book believes, with the ids tidied and the empty claims dropped.

    Comes back as two maps keyed by book id: what each book says it holds, and
    the orders each book is waiting on.
    """
    if books_state is None:
        books_state = {}
    if not isinstance(books_state, dict):
        raise ValueError(
            "books_state has to be a dictionary keyed by book id, such as "
            '{"A": {"positions": {}, "working_orders": {}}}, but it is a '
            f"{type(books_state).__name__}."
        )

    claims: dict[str, dict[str, int]] = {}
    working: dict[str, dict[str, dict]] = {}
    for raw_book_id, raw_state in books_state.items():
        book_id = _clean_book_id(raw_book_id)
        if raw_state is None:
            raw_state = {}
        if not isinstance(raw_state, dict):
            raise ValueError(
                f"The entry for book {book_id} in books_state has to be a dictionary "
                'holding "positions" and "working_orders", but it is a '
                f"{type(raw_state).__name__}."
            )

        raw_positions = raw_state.get("positions") or {}
        if not isinstance(raw_positions, dict):
            raise ValueError(
                f"The positions of book {book_id} have to be a dictionary of symbol "
                "to number of shares, such as {\"AAPL\": 100}, but they are a "
                f"{type(raw_positions).__name__}."
            )
        book_claims: dict[str, int] = {}
        for raw_symbol, raw_qty in raw_positions.items():
            symbol = _need_symbol(raw_symbol, f"a position of book {book_id}")
            qty = _whole_shares(raw_qty, f"the {symbol} position of book {book_id}")
            if qty:
                book_claims[symbol] = book_claims.get(symbol, 0) + qty
        claims[book_id] = book_claims

        raw_orders = raw_state.get("working_orders") or {}
        if not isinstance(raw_orders, dict):
            raise ValueError(
                f"The working orders of book {book_id} have to be a dictionary keyed "
                f"by order id, but they are a {type(raw_orders).__name__}."
            )
        working[book_id] = {
            str(order_id).strip(): (details if isinstance(details, dict) else {})
            for order_id, details in raw_orders.items()
        }
    return claims, working


def _clean_broker_positions(
    broker_positions: list[dict],
) -> tuple[dict[str, int], dict[str, float]]:
    """The broker's holdings, as whole shares and an average cost per symbol.

    A symbol reported twice is added up, because two rows about one holding
    still describe one holding.
    """
    quantities: dict[str, int] = {}
    costs: dict[str, float] = {}
    for entry in broker_positions or []:
        if not isinstance(entry, dict):
            raise ValueError(
                "Every broker position has to be a dictionary with a symbol and a "
                f"quantity in it, but one of them is a {type(entry).__name__}."
            )
        symbol = _need_symbol(entry.get("symbol"), "a broker position")
        qty = _whole_shares(entry.get("qty"), f"the broker quantity of {symbol}")
        quantities[symbol] = quantities.get(symbol, 0) + qty
        costs[symbol] = _avg_cost(entry.get("avg_cost"), symbol)
    return quantities, costs


def _clean_broker_orders(broker_open_orders: list[dict]) -> list[dict]:
    """The broker's open orders, with every field read the same tolerant way."""
    cleaned: list[dict] = []
    for entry in broker_open_orders or []:
        if not isinstance(entry, dict):
            raise ValueError(
                "Every broker open order has to be a dictionary with an orderId in "
                f"it, but one of them is a {type(entry).__name__}."
            )
        order_ref = entry.get("order_ref")
        cleaned.append(
            {
                "order_id": str(entry.get("orderId", "")).strip(),
                "symbol": _optional_symbol(entry.get("symbol")),
                "side": _clean_side(entry.get("side")),
                "qty": _optional_shares(entry.get("qty")),
                "order_ref": str(order_ref).strip() if order_ref else "",
            }
        )
    return cleaned


def _clean_expected_orphans(
    expected_orphans,
) -> tuple[dict[str, int] | None, set[str]]:
    """Read the two ways of saying which orphans are already known about.

    A mapping of {symbol: quantity} comes back as that mapping, and only that
    exact quantity is forgiven. A plain list of symbols comes back as a set of
    symbols, and any quantity of them is forgiven. Nothing comes back as no
    mapping and an empty set.
    """
    if expected_orphans is None:
        return None, set()
    if isinstance(expected_orphans, dict):
        return (
            {
                _need_symbol(symbol, "an expected orphan"): _whole_shares(
                    qty, f"the expected orphan quantity of {symbol}"
                )
                for symbol, qty in expected_orphans.items()
            },
            set(),
        )
    if isinstance(expected_orphans, str):
        return None, {_need_symbol(expected_orphans, "an expected orphan")}
    try:
        symbols = list(expected_orphans)
    except TypeError as exc:
        raise ValueError(
            "expected_orphans has to be either a mapping such as {\"SPY\": 1} or a "
            'list of symbols such as ["SPY"], but it is a '
            f"{type(expected_orphans).__name__}."
        ) from exc
    return None, {_need_symbol(symbol, "an expected orphan") for symbol in symbols}


def _book_for_order_ref(
    order_ref: str, claims: dict[str, dict[str, int]]
) -> str | None:
    """Which book an order reference belongs to, or None when it belongs to none.

    BOOK_A means book A. The prefix is optional and the case and any surrounding
    spaces do not matter, so "book_a", " BOOK_A " and "A" all find book A. A
    caller who keyed books_state by the full reference is matched too.
    """
    if not order_ref:
        return None
    if order_ref in claims:
        return order_ref
    wanted = order_ref.strip().upper()
    if wanted.startswith(ORDER_REF_PREFIX):
        wanted = wanted[len(ORDER_REF_PREFIX):].strip()
    if not wanted:
        return None
    for book_id in claims:
        if book_id.strip().upper() == wanted:
            return book_id
    return None


def _claimed_symbols(claims: dict[str, dict[str, int]]) -> set[str]:
    """Every symbol at least one book says it holds something of."""
    claimed: set[str] = set()
    for book_claims in claims.values():
        claimed.update(book_claims)
    return claimed


def _clean_book_id(book_id) -> str:
    """Book ids are short and upper case, so "a" and " A " mean the same book."""
    return str(book_id).strip().upper()


def _need_symbol(symbol, where: str) -> str:
    """A symbol, tidied. Anything that is not one stops the whole check."""
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError(
            f"There is no symbol on {where}. Every position needs one, such as "
            f"AAPL, and this one has {symbol!r} instead."
        )
    return symbol.strip().upper()


def _optional_symbol(symbol) -> str | None:
    """A symbol where there may not be one, for example on a thin order record."""
    if not isinstance(symbol, str) or not symbol.strip():
        return None
    return symbol.strip().upper()


def _clean_side(side) -> str | None:
    if not isinstance(side, str) or not side.strip():
        return None
    return side.strip().upper()


def _optional_shares(qty) -> int | None:
    """A share count where there may not be one. Anything unreadable is None."""
    try:
        return _whole_shares(qty, "a quantity")
    except ValueError:
        return None


def _whole_shares(value, where: str) -> int:
    """Shares are whole numbers, so 100.0 from the broker is read as 100.

    Nothing at all counts as none. A number halfway between two share counts is
    rounded away from zero, which cannot happen with real share counts and is
    only here so the answer never depends on which way Python happens to round.
    """
    if value is None:
        return 0
    if isinstance(value, bool):
        raise ValueError(
            f"{where} is {value!r}, which is true or false rather than a number of "
            "shares."
        )
    if isinstance(value, int):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{where} is {value!r}, which is not a number of shares."
        ) from exc
    if not math.isfinite(number):
        raise ValueError(
            f"{where} is {value!r}, which is not a real number of shares."
        )
    return int(
        Decimal(repr(number)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def _avg_cost(value, symbol: str) -> float:
    """What the broker paid on average. Nothing at all is read as zero."""
    if value is None:
        return 0.0
    if isinstance(value, bool):
        raise ValueError(
            f"The average cost of {symbol} is {value!r}, which is true or false "
            "rather than a price."
        )
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"The average cost of {symbol} is {value!r}, which is not a price."
        ) from exc
    if not math.isfinite(number):
        raise ValueError(
            f"The average cost of {symbol} is {value!r}, which is not a real price."
        )
    return number


def _order_sort_key(order_id: str | None) -> tuple[int, int, str]:
    """Sort order 7 before order 55, the way a person counts them."""
    if not order_id:
        return (0, 0, "")
    text = str(order_id)
    if text.isdigit():
        return (1, int(text), "")
    return (2, 0, text)


def _mismatch_sort_key(mismatch: Mismatch) -> tuple:
    """By symbol, then book, then order id, so the same input reads the same way."""
    return (
        mismatch.symbol or "",
        mismatch.book_id or "",
        _order_sort_key(mismatch.order_id),
        mismatch.kind,
        mismatch.line,
    )

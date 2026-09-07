# Forgiving a position no book owns

`output/expected_orphans.json` is the list of holdings that belong to no book
and never will. **It is the only thing that stops one of them halting all five
books**, so it has to be right before the first tick of the day.

## What an unclaimed position actually does

A position at the broker that no book claims is an orphan. **An orphan this file
does not name HALTS EVERY BOOK and raises one alert.** Hub ruling, 2026-09-07,
recorded in `journal/2026-09-07.md` and item 0b of
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/BACKLOG.md`.
That decision is closed; this note records it rather than arguing it.

The reasoning. A holding nobody can account for means either a book has lost its
own record or somebody traded the account by hand, and in both of those cases
all five books are sizing their next order against a picture of the account that
is not true. That is the same reason a quantity mismatch halts the book it
belongs to. Nobody can be blamed for an orphan, so nobody can be singled out
either, and that leaves stopping all of them.

A halted book behaves the way it does under any reconciliation halt: it opens
nothing more that day and it may still close what it holds, because refusing to
close is its own kind of risk. The halt lifts on its own, on the next tick after
the orphan has gone away or been written into this file. Nobody has to override
anything.

**So this file is not a convenience any more.** Before 2026-09-07 it changed
whether Mo got one message a day; now it changes whether the account trades at
all. This paper account genuinely holds one unclaimed share of SPY, bought by
hand during the first manual test on 2026-09-02. Without this file naming it,
every tick of every day halts all five books over that share.

A missing file, or one with half written JSON in it, forgives **nothing**. That
is the safe way round on purpose: it halts rather than trades on a picture
nobody has checked.

## The one exception, and how exact it is

The forgiveness is a match on symbol AND quantity. `{"SPY": 1}` forgives exactly
one share of SPY. Two shares of SPY is a different fact, so it halts every book
and says so, naming what it expected and what it found. That is the point of the
dict shape: the thing worth halting on is not the share that has sat there for a
week, it is the one that turned up this morning.

## The two shapes

```json
["SPY"]
```

forgives any quantity of that symbol. Use it when you do not care how much.

```json
{"SPY": 1}
```

forgives EXACTLY that quantity and halts every book again the moment the number
changes. This is the better shape and it is what ships, because the thing worth
halting on is not the share that has sat there for a week, it is a second one
appearing.

Either way a forgiven orphan still gets its line in the record every tick, so a
reader can see it was noticed rather than missed. What it stops is the alert and
the halt.

## Where it lives, and the copy in this folder

The live file is
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/expected_orphans.json`.

`output/` is gitignored, so that file is NOT in the repository and a fresh clone
or the Mac Mini will not have it. That is why
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/expected_orphans.example.json`
is committed beside this note. To use it on a new machine:

```
cp /Users/mtalib/workspace_repos/personal_repo/agentic_trading/config/expected_orphans.example.json \
   /Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/expected_orphans.json
```

**Deleting the live file does not go back to being reminded once a day, it
halts every book.** Since the 2026-09-07 ruling that is what a missing file
means. There is no setting to change and nothing to restart: `expected_orphans()`
in `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/loop.py`
reads the file fresh on every tick and treats a missing or unreadable file as
forgiving nothing.

## What the quantity of 1 is based on

Confirmed by a live read. Before 04:00 New York on 2026-09-07 two read-only reads
against IB Gateway timed out on the positions request, the same condition
`c5c92a2` recorded; the Gateway had lost its upstream connection and was
restarted (see `journal/gateway_reads_2026-09-07.md`). After the restart a
read-only connection on client id 289 answered at once: exactly 1 SPY at an
average cost of 766.15, and one working order, id 4, SELL 1 SPY. So the 1 in
this file is a live reading, not only the written record.

The dict shape above is deliberately the one that halts if the number is wrong,
so a bad guess here is loud rather than silent, and since 2026-09-07 it is loud
in the strongest way the loop has. **Tuesday's pre-flight has to read the real
position and correct this file if it differs**, because a wrong number here now
costs a trading day rather than an email.

There is also an untagged working order, id 4, a market-on-open sell of that SPY
share for Tuesday 2026-09-08 from the same session. It is a separate thing from
this file, keyed by its order id rather than by a symbol, and it is deliberately
**not** treated the way an orphan position is: an order that is only working has
changed nothing about what any book holds, so nobody is sizing anything against
a wrong picture because of it. It is written down and alerted, and it halts
nobody. If it fills on Tuesday's open it disposes of the SPY share, and then the
orphan goes away on its own and this file has nothing left to forgive.

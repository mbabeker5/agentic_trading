# Forgiving a position no book owns

`output/expected_orphans.json` is the list of holdings that belong to no book
and never will, so reconciliation stops saying so once somebody has looked.

## What an unclaimed position actually does

A position at the broker that no book claims is an orphan. Since `58dfa67` on
2026-09-06 the answer is: **write a line into the record every tick, tell Mo
once per name per day, and halt nobody.**

Halting was considered and rejected, and the reasoning is worth keeping. This
paper account genuinely holds one unclaimed share of SPY, bought by hand during
the first manual test on 2026-09-02. Halting on an orphan would mean halting all
five books on every tick of every day for the rest of the month over a share
nobody is managing and nobody is at risk from, and a safety rule that fires
every five minutes forever is not a safety rule, it is noise with a halt
attached.

**Whether an UNEXPECTED orphan should also halt every book is an open decision
for Mo.** It is item 0b in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/BACKLOG.md`.
The argument for halting is that a holding nobody can account for means either a
book has lost its record or somebody traded the account by hand, and in both
cases every book is sizing its next order against a picture that is not true.
The argument against is the one above. Until Mo decides, an orphan alerts and
halts nobody, and this file is what stops the alert repeating.

So this file is a convenience, not a safety requirement. Nothing breaks without
it. What it changes is whether Mo gets one message a day about a share he
already knows about.

## The two shapes

```json
["SPY"]
```

forgives any quantity of that symbol. Use it when you do not care how much.

```json
{"SPY": 1}
```

forgives EXACTLY that quantity and complains again the moment the number
changes. This is the better shape and it is what ships, because the thing worth
being told about is not the share that has sat there for a week, it is a second
one appearing.

Either way a forgiven orphan still gets its line in the record every tick, so a
reader can see it was noticed rather than missed. It just stops raising an
alert, and it halts nobody in any case.

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

To go back to being reminded once a day, delete the live file. There is no
setting to change and nothing to restart: `expected_orphans()` in
`/Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/loop.py`
reads the file fresh on every tick and treats a missing file as forgiving
nothing.

## What the quantity of 1 is based on

The written record of the 2026-09-02 manual test, not a live read: IB Gateway
would not answer a position read while this was being written. The dict shape
above is deliberately the one that complains if the number is wrong, so a bad
guess here is loud rather than silent. Tuesday's pre-flight should read the real
position and correct this file if it differs.

There is also an untagged working order, id 4, a market-on-open sell for Tuesday
2026-09-08 from the same session. It is reported the same way, keyed by its
order id rather than by a symbol, and it is a separate thing from this file. If
it fills on Tuesday's open it disposes of the SPY share, and the orphan goes
away on its own.

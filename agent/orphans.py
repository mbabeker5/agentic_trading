"""The one reader of output/expected_orphans.json, shared by everything.

A position at the broker that no book claims is an orphan, and since the hub's
ruling of 2026-09-07 (journal/2026-09-07.md, docs/BACKLOG.md item 0b) an orphan
nobody wrote down in advance halts every book. The only thing that forgives one
is this file:

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/expected_orphans.json

It exists as its own module for one reason. The 9 AM pre-flight and the trading
loop have to answer the orphan question the same way, or a morning ends with the
pre-flight stopping the day over the single share of SPY that the loop itself
forgives on every tick, which is exactly what happened on 2026-09-08.
agent/reconcile.py is pure arithmetic and reads no files, and agent/loop.py is
5,000 lines that pull in the broker, the guardrails and the decider, so neither
of them is somewhere the pre-flight can cheaply borrow the reader from. Hence
this file: a dozen lines, one function, nothing imported.

Both callers pass the folder the file lives in rather than trusting a default,
because the pre-flight follows AGENTIC_TRADING_OUTPUT_DIR through
agent/paths.py and the tests point both of them at a temporary directory.

config/README_expected_orphans.md is the whole story in plain words.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: The name of the file, in one place, so nobody has to spell it twice.
FILE_NAME = "expected_orphans.json"


def expected_orphans(folder: Path) -> Any:
    """What the forgiveness file in this folder says, ready for reconcile().

    Comes back as one of three things, and agent/reconcile.py reads all three:

        {"SPY": 1}   forgives exactly that quantity of that symbol, and halts
                     again the moment the number changes
        ["SPY"]      forgives any quantity of that symbol
        None         forgives nothing

    A missing file, or one with half written JSON in it, is None. That is the
    safe way round on purpose: it halts rather than trades on a picture nobody
    has checked.
    """
    path = Path(folder) / FILE_NAME
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text())
    except Exception:                        # noqa: BLE001
        return None
    return loaded if isinstance(loaded, (list, dict)) else None

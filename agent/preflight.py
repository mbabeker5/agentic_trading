"""The 9 AM check that decides whether today is a trading day at all.

Runs half an hour before the market opens, once, on weekdays. It asks five
questions, writes the answers down, and if any of them is a no it creates the
file output/NO_TRADE_TODAY and tells Mo which check failed. It asks two more
questions after those, about whether IBKR's scanner filters work on this account
and which day trading rulebook the account is under. Neither of those two can
ever stop the day; they only ever record an answer.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/preflight.py

THE NO_TRADE_TODAY CONTRACT
---------------------------

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/output/NO_TRADE_TODAY

While that file exists, the trading loop must not open a new position. It may
still manage and close what is already open, exactly like output/STOP: getting
out is always allowed, getting in is not. The file holds a short note saying
which check failed and when, so anyone who finds it knows why it is there.

Only two things create it: this script, when a check fails, and a person. Two
things remove it: agent/reenable.sh, and deleting it by hand. It is not cleared
automatically at midnight, on purpose. A morning that failed its checks should
need a person to look before the agent trades again.

The five checks that can stop the day
-------------------------------------

1. gateway_login   IB Gateway is running, port 4002 is open, and a read only
                   connection comes back with the paper account DUT077572.
2. market_data     SPY quotes are real time rather than delayed. IBKR error 354
                   or 10089 means the subscription is missing. Error 10197 means
                   a live quote screen or the IBKR app is holding the data feed
                   and needs closing.
3. scanner         agent/scanner.py runs to completion and exits cleanly. At
                   9 AM the shortlist is usually empty, because the market has
                   not opened, and that is fine. It is the run that has to work,
                   not the result. Two things make it a hard failure: exit code
                   3, which is the scanner refusing to believe its own scan, and
                   any IBKR error 162, 165 or 365 sitting in the scan
                   diagnostics of the file it wrote.
4. reconcile       What the books think they hold matches what the broker says
                   they hold. The comparison is agent/reconcile.py's, the same
                   one the trading loop runs on every tick, forgiving the same
                   orphans through output/expected_orphans.json. It fails only
                   when a book would be halted. A holding no book claims that
                   the forgiveness file names, and an order at the broker with
                   no book's tag on it, are notes: the loop lets both through,
                   so the morning does too. With no book state files yet, this
                   reports "no books active" and passes.
5. day_trades      Every day trade counter file present can be read.
                   agent/pdt.py writes one per book as output/pdt_BOOK_A.json.
                   Missing files pass; a corrupt one fails.

The two questions that never fail the day
-----------------------------------------

6. scanner_filters_enabled

   One filtered scan, priceAbove 5, run through the same truth check as the real
   scans, purely to record whether IBKR's scanner filters work on this account
   today. On 2026-09-06 they did not: every filter made the scan return zero
   rows with error 162, "Scanner filter X is disabled", so agent/scanner.py
   stopped sending filters entirely and now does all its filtering in our own
   code. Mo has since paid for market data, and this probe is how the morning
   log answers whether that changed anything, without anyone having to remember
   to check by hand.

   It passes whatever it finds. A false here is the state the scanner is already
   built for, and a true would be good news, not an emergency. Read the answer
   in facts.filters_enabled in the day's report.

7. day_trade_regime

   Which day trading rulebook this account is under. FINRA retired the pattern
   day trader rule with effect from 2026-06-04 (Regulatory Notice 26-10) and
   replaced it with the intraday margin deficit rules, and IBKR says which one
   applies to an account through five account summary tags: DayTradesRemaining
   and DayTradesRemainingT+1 through T+4. Counts mean the old rule is still
   running, -1 or no tags at all means the new one, anything else is unknown.

   agent/margin_regime.py does the reading. This check opens its own read only
   connection to ask, records the answer, and never fails the morning. An
   unknown answer prints a warning line, because unknown makes agent/pdt.py
   fall back to the strict old behaviour and somebody should find out why.

   Worth knowing: these tags come from the paper account, and IBKR applies
   neither rulebook to simulated money, so the paper answer need not be the
   live account's answer. The report says as much in day_trade_regime_note.

What it writes
--------------

    output/preflight_YYYY-MM-DD.json    pass or fail per check, plus a verdict
    output/preflight_scan.json          whatever the scanner found
    output/NO_TRADE_TODAY               only when something failed

With --dry-run it writes output/preflight_dryrun.json instead, creates no
NO_TRADE_TODAY, and sends no alert. That is the safe way to try it.

With --write-regime the day trading regime it detected is written into
pdt.regime in config/guardrails.yaml. That is the one setting this script ever
changes, only that one line changes, and every comment in the file survives.
Without the flag nothing on disk moves. The Tuesday 2026-09-08 run passes it:

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/preflight.py \
      --write-regime

This script places no orders. The only broker connection it opens is read only,
and the only MCP tools it calls are the ones that read.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

import alerts as alerts_module  # noqa: E402

# SQLite is the system of record (docs/DATA.md), so every check lands in the
# preflight_results table as well as in the day's JSON report. Optional, because
# a database that cannot be opened is no reason to skip the 9 AM checks.
try:
    import db as db_module  # noqa: E402
except Exception:           # noqa: BLE001
    db_module = None        # type: ignore[assignment]
import mcp_client as mcp  # noqa: E402
import orphans as orphans_mod  # noqa: E402
import reconcile as reconcile_mod  # noqa: E402
import watchdog as wd  # noqa: E402
from margin_regime import (  # noqa: E402
    DAY_TRADE_TAGS,
    MarginRegimeConfigError,
    Regime,
    detect_regime,
    write_regime_setting,
)
from paths import (  # noqa: E402
    agent_dir,
    config_dir,
    no_trade_today_file,
    output_dir,
    project_root,
    venv_python,
)
import timezone_check  # noqa: E402

EASTERN = ZoneInfo("America/New_York")

#: Our own API client id, kept clear of 99 (smoke test), 100 (MCP server),
#: 201 (scanner) and 250 (watchdog).
CLIENT_ID = 251

#: A second id for the scanner filter probe, which opens its own short lived
#: read only connection so it cannot disturb the one above.
FILTER_PROBE_CLIENT_ID = 252

#: A third id, for the day trading regime probe. Same reason: its own short
#: lived read only connection, so a slow answer cannot hold up anything else.
REGIME_CLIENT_ID = 282

#: The live account this paper account stands in for. IBKR applies neither day
#: trading rulebook to simulated money, so the regime read off DUT077572 is a
#: rehearsal of the plumbing and not an answer about U28440091.
LIVE_ACCOUNT = "U28440091"

#: The scanner can take a few minutes when IBKR is slow. Past this it is broken.
SCANNER_TIMEOUT_SECONDS = 300

#: HOW LONG THE WHOLE MORNING CHECK MAY TAKE. Ten minutes: comfortably more than
#: a working morning needs, and comfortably less than the half hour between this
#: job at 09:00 and the open at 09:30.
#:
#: Why it exists. On 2026-09-07 IB Gateway lost its upstream connection to IBKR,
#: every broker read hung, and this script sat there for 44 minutes and never
#: wrote its verdict at all. output/NO_TRADE_TODAY was neither written nor
#: deliberately withheld, which is the worst of the three ways a morning can
#: end, because nothing downstream could tell the difference between "the checks
#: passed" and "the checks never finished". Mo killed it by hand.
#:
#: A pre-flight that runs out of time now stops the day and says why.
PREFLIGHT_BUDGET_SECONDS = 600.0

#: What the deadline reports itself as when it fires. Deliberately NOT in
#: CHECK_ORDER below: it is not a question about the broker, it is this script
#: saying it never reached the end of the list.
CHECK_IN_TIME = "finished_in_time"

#: What the pre-flight reports itself as when it stops before the end of the
#: list for any reason other than the clock: an unexpected error somewhere in
#: the run, or something outside killing the process. Also NOT in CHECK_ORDER,
#: for the same reason as CHECK_IN_TIME.
#:
#: Why it exists. On 2026-09-10 the 09:00 pre-flight could not reach Gateway on
#: 127.0.0.1:4002, and it wrote neither output/preflight_2026-09-10.json nor
#: output/NO_TRADE_TODAY. When Gateway came back at 11:27 there was no verdict
#: on file, so nothing told the loop to stay out, and only the fact that every
#: book was in dry run kept the morning safe. The rule now is that this script
#: writes a verdict whatever happens to it, and a verdict it could not reach is
#: a fail. Mo created the marker by hand at 11:35.
CHECK_RUN_COMPLETE = "run_completed"

#: agent/scanner.py returns this when a scan could not be trusted. Distinct from
#: 1, which means it could not reach Gateway at all.
SCANNER_EXIT_SCAN_FAILURE = 3

#: The single line of JSON agent/scanner.py prints on stderr when it exits 3.
SCAN_FAILURE_MARKER = "SCAN_FAILURE_JSON "

#: IBKR codes that mean a scan result cannot be believed. 162 is "Scanner filter
#: X is disabled", 165 is the scanner service refusing the query, 365 is "no
#: scanner subscription found". Any of them in a scan's diagnostics fails the
#: morning, even if the scanner itself exited 0.
SCAN_HARD_ERROR_CODES = (162, 165, 365)

#: The one benign 162. IBKR sends it to confirm a finished one-shot scan closed.
BENIGN_162_TEXT = "scanner subscription cancelled"

CHECK_GATEWAY = "gateway_login"
CHECK_MARKET_DATA = "market_data"
CHECK_SCANNER = "scanner"
CHECK_SCANNER_FILTERS = "scanner_filters_enabled"
CHECK_RECONCILE = "reconcile"
CHECK_DAY_TRADES = "day_trades"
CHECK_DAY_TRADE_REGIME = "day_trade_regime"
CHECK_TIME_ZONE = "time_zone"

CHECK_ORDER = (CHECK_GATEWAY, CHECK_MARKET_DATA, CHECK_SCANNER,
               CHECK_SCANNER_FILTERS, CHECK_RECONCILE, CHECK_DAY_TRADES,
               CHECK_TIME_ZONE, CHECK_DAY_TRADE_REGIME)

#: Checks that record an answer and never stop the day, whatever they find.
INFORMATIONAL_CHECKS = frozenset({CHECK_SCANNER_FILTERS, CHECK_DAY_TRADE_REGIME})


@dataclass
class Result:
    """One question and its answer, in a shape that goes straight into JSON."""
    name: str
    passed: bool
    detail: str
    facts: dict | None = None


# ------------------------------------------------------------------- checks

def check_gateway_and_data() -> tuple[Result, Result]:
    """Gateway is up and logged in, and the quotes coming out of it are live.

    Reuses the watchdog's checks rather than keeping a second copy of the
    ib_async plumbing, on its own client id so the two never collide.
    """
    process = wd.check_gateway_process()
    port = wd.check_gateway_port()
    connect, data = wd.check_ib_and_market_data(
        port_ok=port.ok, market_hours=True, client_id=CLIENT_ID)

    parts = [process, port, connect]
    failures = [c for c in parts if not c.ok and not c.skipped]
    login = Result(
        name=CHECK_GATEWAY,
        passed=not failures,
        detail=(failures[0].detail if failures
                else f"Gateway is up and logged into {wd.PAPER_ACCOUNT}."),
        facts={c.name: {"ok": c.ok, "skipped": c.skipped, "detail": c.detail}
               for c in parts},
    )

    if data.skipped:
        market = Result(CHECK_MARKET_DATA, passed=False,
                        detail=f"Could not check quotes: {data.detail}.")
    else:
        market = Result(CHECK_MARKET_DATA, passed=data.ok, detail=data.detail,
                        facts={"ibkr_code": data.code})
    return login, market


def read_scan_failure(stderr: str) -> dict:
    """The scanner's own account of why it refused to believe a scan.

    agent/scanner.py prints one line of JSON on stderr before it exits 3, so the
    error codes and messages survive the trip between the two processes and end
    up in the alert instead of being lost in a log nobody opens.
    """
    for line in reversed((stderr or "").splitlines()):
        line = line.strip()
        if line.startswith(SCAN_FAILURE_MARKER):
            try:
                loaded = json.loads(line[len(SCAN_FAILURE_MARKER):])
            except json.JSONDecodeError:
                return {}
            return loaded if isinstance(loaded, dict) else {}
    return {}


def hard_scan_errors(diagnostics) -> list[dict]:
    """Every 162, 165 or 365 sitting in a written scan_diagnostics block.

    Belt and braces. agent/scanner.py already refuses to write a file when a scan
    carries one of these, so finding one here means either an older file or a
    path through the scanner nobody thought of. Either way the morning stops.

    The one 162 that is skipped is "API scanner subscription cancelled", which
    IBKR sends to confirm a finished one-shot scan has closed. It arrives on
    every healthy run, so treating it as a failure would stop every morning.
    """
    found: list[dict] = []
    if not isinstance(diagnostics, dict):
        return found
    for scan_code, block in diagnostics.items():
        if not isinstance(block, dict):
            continue
        for entry in block.get("errors") or []:
            if not isinstance(entry, dict):
                continue
            try:
                code = int(entry.get("code"))
            except (TypeError, ValueError):
                continue
            message = str(entry.get("message") or "")
            if code not in SCAN_HARD_ERROR_CODES:
                continue
            if code == 162 and BENIGN_162_TEXT in message.lower():
                continue
            found.append({"scan_code": scan_code, "code": code, "message": message})
    return found


def check_scanner(out_path: Path) -> Result:
    """Run agent/scanner.py as its own process and insist it exits cleanly.

    Its own process because the scanner talks to IBKR's scanner service, which
    can hang, and a hung scanner must not take the pre-flight down with it.

    An empty shortlist at 9 AM is normal and passes: the market has not opened,
    so nothing has gapped yet. What must never pass is an empty shortlist that
    came from a broken scan, and there are two ways of catching that. Exit code
    3 is the scanner itself saying it did not believe its own scan, and it wrote
    nothing rather than leave an empty file behind. Error 162, 165 or 365 in the
    scan diagnostics of a file it did write is the same thing found afterwards.
    Both fail the morning and both name the codes in the alert.
    """
    script = agent_dir() / "scanner.py"
    python = venv_python()
    if not script.exists():
        return Result(CHECK_SCANNER, False, f"{script} does not exist.")
    if not python.exists():
        return Result(CHECK_SCANNER, False, f"{python} does not exist.")

    command = [str(python), str(script), "--out", str(out_path)]
    try:
        finished = subprocess.run(command, capture_output=True, text=True,
                                  timeout=SCANNER_TIMEOUT_SECONDS,
                                  cwd=str(script.parent.parent))
    except subprocess.TimeoutExpired:
        return Result(CHECK_SCANNER, False,
                      f"The scanner ran for more than {SCANNER_TIMEOUT_SECONDS} "
                      "seconds and was stopped.")
    except Exception as exc:                                      # noqa: BLE001
        return Result(CHECK_SCANNER, False, f"The scanner would not start: {exc}.")

    if finished.returncode == SCANNER_EXIT_SCAN_FAILURE:
        failure = read_scan_failure(finished.stderr or "")
        codes = failure.get("codes") or []
        errors = failure.get("errors") or []
        spoken = "; ".join(
            f"IBKR {e.get('code')}: {str(e.get('message') or '').strip()}"
            for e in errors if isinstance(e, dict)) or str(
                failure.get("message") or "no detail was given")
        return Result(
            CHECK_SCANNER, False,
            "The scanner did not believe its own scan and wrote nothing, so "
            f"{out_path.name} still holds whatever was there before. "
            f"{spoken}. An empty shortlist and a broken scanner must never look "
            "the same, which is why this stops the day.",
            facts={"exit_code": SCANNER_EXIT_SCAN_FAILURE,
                   "error_codes": codes,
                   "errors": errors,
                   "scan_diagnostics": failure.get("scan_diagnostics") or {},
                   "wrote_shortlist": False})

    if finished.returncode != 0:
        tail = (finished.stderr or finished.stdout or "").strip().splitlines()
        return Result(CHECK_SCANNER, False,
                      f"The scanner exited with code {finished.returncode}: "
                      f"{tail[-1] if tail else 'no message'}.",
                      facts={"exit_code": finished.returncode})

    found = 0
    diagnostics: dict = {}
    try:
        written = json.loads(out_path.read_text(encoding="utf-8"))
        if isinstance(written, dict):
            raw = written.get("scan_diagnostics")
            diagnostics = raw if isinstance(raw, dict) else {}
            for key in ("candidates", "shortlist", "results", "rows"):
                if isinstance(written.get(key), list):
                    found = len(written[key])
                    break
        elif isinstance(written, list):
            found = len(written)
    except (OSError, json.JSONDecodeError):
        return Result(CHECK_SCANNER, False,
                      f"The scanner exited cleanly but {out_path} is missing or "
                      "not readable JSON.")

    bad = hard_scan_errors(diagnostics)
    if bad:
        spoken = "; ".join(
            f"{e['scan_code']} got IBKR {e['code']}: {e['message'].strip()}"
            for e in bad)
        return Result(
            CHECK_SCANNER, False,
            "The scanner exited cleanly but its own diagnostics carry errors "
            f"that mean the results cannot be believed. {spoken}. A shortlist "
            "built on those is not evidence of anything.",
            facts={"exit_code": 0, "candidates": found,
                   "error_codes": sorted({e["code"] for e in bad}),
                   "errors": bad,
                   "scan_diagnostics": diagnostics})

    scans = ", ".join(sorted(diagnostics)) or "none recorded"
    return Result(CHECK_SCANNER, True,
                  f"The scanner ran cleanly and wrote {found} candidates to "
                  f"{out_path.name}. An empty list before the open is normal. "
                  f"Scans run: {scans}.",
                  facts={"candidates": found, "exit_code": 0,
                         "scan_diagnostics": diagnostics})


#: The filters the probe tries, and nothing else. priceAbove is the headline one,
#: because it is the filter the scanner used to send. stVolume5MinAbove is here
#: because it is the one a 9:35 gap scan would actually want, and because on
#: 2026-09-06 the two gave different answers on the same account within the same
#: minute: priceAbove worked and stVolume5MinAbove returned nothing. A single
#: filter is not evidence about the rest of them.
FILTER_PROBES = (("priceAbove", "5"), ("stVolume5MinAbove", "100000"))


def check_scanner_filters() -> Result:
    """Do IBKR's scanner filters work on this account today? Record, never block.

    Runs a filtered scan through the same truth check the real scans go through,
    and writes down true or false for each filter tried. On the morning of
    2026-09-06 the answer was false for every filter: they all returned zero rows
    with error 162, "Scanner filter X is disabled", while the unfiltered control
    returned 50. By that afternoon, after Mo paid for market data, priceAbove and
    volumeAbove had started working while stVolume5MinAbove and marketCapAbove
    still returned nothing.

    That mixed answer is the reason this probe exists and the reason
    agent/scanner.py still sends no filters at all. A filter set where some
    entries work and some silently return an empty list, with no way to tell
    which from the outside, is worse than one that is plainly off. Nothing here
    changes what the scanner does. It records what IBKR is doing today so the
    change is noticed the day it happens rather than a month later.

    It always passes. There is no state of the world where this probe alone
    should stop the agent trading.
    """
    facts: dict = {"filters_enabled": None, "probes": {},
                   "filter_tried": f"{FILTER_PROBES[0][0]} {FILTER_PROBES[0][1]}"}
    try:
        from ib_async import IB, ScannerSubscription, TagValue

        from scan_truth import ScanFailure, checked_scan
    except Exception as exc:                                      # noqa: BLE001
        facts["note"] = f"could not load the scanner libraries: {exc}"
        return Result(CHECK_SCANNER_FILTERS, True,
                      "Could not run the filter probe, so today's log has no "
                      f"answer about IBKR's scanner filters: {exc}.", facts=facts)

    ib = IB()
    try:
        ib.connect(wd.GATEWAY_HOST, wd.GATEWAY_PORT,
                   clientId=FILTER_PROBE_CLIENT_ID, readonly=True, timeout=20)
    except Exception as exc:                                      # noqa: BLE001
        facts["note"] = f"could not connect: {exc}"
        return Result(CHECK_SCANNER_FILTERS, True,
                      "Could not reach Gateway for the scanner filter probe, so "
                      f"today's log has no answer: {exc}.", facts=facts)

    def subscription():
        return ScannerSubscription(instrument="STK", locationCode="STK.US.MAJOR",
                                   scanCode="TOP_PERC_GAIN", numberOfRows=50)

    try:
        for tag, value in FILTER_PROBES:
            answer: dict = {"tag": tag, "value": value}
            try:
                filtered, control = checked_scan(
                    ib, subscription, [TagValue(tag, value)])
            except ScanFailure as failure:
                answer["enabled"] = False
                answer["rows"] = 0
                answer["errors"] = [{"code": code, "message": message}
                                    for code, message in failure.errors]
                answer["note"] = str(failure)
            else:
                answer["enabled"] = True
                answer["rows"] = len(filtered.rows)
                answer["control_rows"] = len(control.rows)
            facts["probes"][tag] = answer
    except Exception as exc:                                      # noqa: BLE001
        facts["note"] = f"the probe itself failed: {exc}"
        return Result(CHECK_SCANNER_FILTERS, True,
                      f"The scanner filter probe failed on its own: {exc}. No "
                      "answer today.", facts=facts)
    finally:
        try:
            ib.disconnect()
        except Exception:                                         # noqa: BLE001
            pass

    headline = facts["probes"].get(FILTER_PROBES[0][0], {})
    facts["filters_enabled"] = headline.get("enabled")
    working = sorted(t for t, a in facts["probes"].items() if a.get("enabled"))
    broken = sorted(t for t, a in facts["probes"].items() if a.get("enabled") is False)

    if working and broken:
        detail = (f"IBKR's scanner filters are half on for this account: {', '.join(working)} "
                  f"returned rows and {', '.join(broken)} returned nothing at all. "
                  "That mixture is worse than all of them being off, because there "
                  "is no way to tell from a result which kind you got. The scanner "
                  "sends no filters and does its own filtering, so nothing is "
                  "broken by this.")
    elif working:
        detail = (f"IBKR's scanner filters now work on this account: {', '.join(working)} "
                  "each returned rows against an unfiltered control. Worth telling "
                  "Mo, because the scanner has been doing all its filtering itself "
                  "since 2026-09-06.")
    else:
        detail = ("IBKR's scanner filters are still off for this account: "
                  f"{', '.join(broken)} returned nothing but errors against a healthy "
                  "unfiltered control. The scanner does not send filters, so nothing "
                  "is broken by this. Recorded for the record.")
    return Result(CHECK_SCANNER_FILTERS, True, detail, facts=facts)


def newest_book_files_by_book(folder: Path) -> dict[str, Path]:
    """The most recent state file for each book, keyed by the book it belongs to.

    agent/book_state.py writes one file per book per day, named like
    state_BOOK_A_2026-09-08.json. Adding every file in the folder together would
    count Monday's positions again on Tuesday, so the files are grouped by book
    and only the newest day of each is kept. ISO dates sort in date order, which
    is why a plain sort is enough to find it.

    The book id has to come back with the file, because agent/reconcile.py works
    book by book: which books stop over a disagreement depends on which books
    hold the disputed name.
    """
    by_book: dict[str, Path] = {}
    for path in sorted(folder.glob("state_BOOK_*.json")):
        tail = path.stem[len("state_BOOK_"):]
        book, _, maybe_date = tail.rpartition("_")
        if not (book and len(maybe_date) == 10 and maybe_date.count("-") == 2):
            book = tail          # no date on the end, so the whole tail is the book
        by_book[book] = path     # sorted order means the last one wins
    return by_book


def newest_book_files(folder: Path) -> list[Path]:
    """The same files as above, in book order, for a caller that wants the paths."""
    by_book = newest_book_files_by_book(folder)
    return [by_book[book] for book in sorted(by_book)]


def _quantity_from(item: dict) -> float | None:
    """One position's share count, negative for a short.

    agent/book_state.py stores the size in qty and the direction in side, and a
    short may be written either as a negative qty or as a positive one with
    side "short". Both have to come out negative here, or a short would look
    like a long that the broker disagrees about.
    """
    for key in ("position", "qty", "quantity", "shares"):
        if item.get(key) is not None:
            try:
                size = float(item[key])
            except (TypeError, ValueError):
                return None
            if str(item.get("side", "")).lower() == "short" and size > 0:
                size = -size
            return size
    return None


def _positions_from_book(loaded) -> dict[str, float]:
    """Pull {symbol: shares} out of a book's state file, whatever shape it is in.

    The multi book work is still settling, so three shapes are accepted rather
    than one: a list of position objects, a plain mapping of symbol to a number,
    and a mapping of symbol to an object with a quantity in it. Anything else is
    read as holding nothing, which shows up as a mismatch rather than passing
    quietly.
    """
    held: dict[str, float] = {}
    if not isinstance(loaded, dict):
        return held
    raw = loaded.get("positions")

    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or item.get("ticker"))
            size = _quantity_from(item)
            if size is not None:
                held[symbol] = held.get(symbol, 0.0) + size
    elif isinstance(raw, dict):
        for symbol, value in raw.items():
            size = (_quantity_from(value) if isinstance(value, dict)
                    else _as_float(value))
            if size is not None:
                held[str(symbol)] = held.get(str(symbol), 0.0) + size
    return held


def _as_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _working_orders_from_book(loaded) -> dict:
    """The orders one book believes are still working, keyed by broker order id.

    agent/book_state.py writes them as a dictionary under working_orders.
    Anything else is read as none at all, which shows up as the broker working an
    order no book has a record of rather than as everything being fine.
    """
    if not isinstance(loaded, dict):
        return {}
    raw = loaded.get("working_orders")
    return raw if isinstance(raw, dict) else {}


def broker_orders_for_reconcile(rows) -> list[dict]:
    """The account's working orders in the five fields agent/reconcile.py reads.

    The same field names as broker_orders_for_reconcile in agent/loop.py,
    because both of them are reading the same answer out of the same MCP tool.
    """
    out: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        out.append({
            "orderId": row.get("orderId") or row.get("order_id"),
            "symbol": row.get("symbol"),
            "side": row.get("action") or row.get("side"),
            "qty": row.get("totalQuantity") or row.get("qty") or row.get("remaining"),
            "order_ref": row.get("orderRef") or row.get("order_ref"),
        })
    return out


def _shares_in_words(qty) -> str:
    """1 share, 2 shares, and never 1 shares."""
    count = abs(int(qty))
    return "1 share" if count == 1 else f"{count} shares"


def reconcile_notes(report) -> list[str]:
    """Everything the reconciliation found that halts nobody, in short sentences.

    Three kinds, and all three are notes rather than failures because that is
    exactly what the trading loop does with them. The pre-flight must not stop a
    day over something the loop lets through on every tick.

    A FORGIVEN ORPHAN. A holding no book claims that output/expected_orphans.json
    names. This paper account holds one share of SPY, bought by hand during the
    first manual test on 2026-09-02, and the file forgives it. An orphan that
    file does NOT name is a different matter: it halts every book, so it lands in
    the failures below instead. See config/README_expected_orphans.md.

    A LOOSE ORDER. An order working at the broker whose reference belongs to no
    book, such as order 4, the market-on-open sell of that SPY share. An order
    that is only working has changed nothing about what any book holds, so nobody
    is sizing anything against a wrong picture, and agent/reconcile.py leaves it
    out of books_to_halt on purpose. Somebody still has to look at it by hand.

    A SHARED TICKER that adds up. Two books holding the same name has been
    allowed since 2026-09-06, and reconcile.py writes its own sentence for it.
    """
    notes: list[str] = []
    for orphan in report.orphans:
        if not orphan.expected:
            continue
        verb = "belongs" if abs(orphan.qty) == 1 else "belong"
        notes.append(f"{orphan.symbol}: {_shares_in_words(orphan.qty)} {verb} to no "
                     f"book, forgiven by output/{orphans_mod.FILE_NAME}.")
    for mismatch in report.mismatches:
        if mismatch.book_id is not None:
            continue
        where = (f"order {mismatch.order_id}" if mismatch.order_id
                 else "an order with no id on it")
        notes.append(f"{where} at the broker belongs to no book, so no book stops "
                     "for it, the same answer the trading loop gives. Someone has "
                     "to look at that order by hand.")
    notes.extend(record.line for record in report.shared if record.matches)
    return notes


def reconcile_problems(report) -> list[str]:
    """The reconciliation's own sentence for each thing that halts a book.

    agent/reconcile.py already writes one plain sentence per problem, naming the
    books involved, what each of them believes, what the broker says instead and
    who stops trading. The pre-flight quotes those rather than writing a second,
    differently worded description of the same disagreement. That is the other
    half of the 2026-09-08 bug: the pre-flight called an orphan a book mismatch,
    which is a different thing with a different sentence.

    One quantity mismatch can name several books and is one sentence shared
    between them, so the same line is only kept once.
    """
    lines = [m.line for m in report.mismatches if m.book_id is not None]
    lines += [orphan.line for orphan in report.orphans if not orphan.expected]
    kept: list[str] = []
    for line in lines:
        if line not in kept:
            kept.append(line)
    return kept


def check_reconcile() -> Result:
    """Does what the books think they hold match what the broker says?

    The comparison itself is agent/reconcile.py's, the same function the trading
    loop asks on every tick, handed the same forgiveness file through the same
    reader in agent/orphans.py. That is deliberate and it is the fix for the
    2026-09-08 morning: the pre-flight used to do its own arithmetic here, never
    opened output/expected_orphans.json, and stopped the whole day over the one
    unclaimed share of SPY that every tick of the loop was already forgiving.

    What is gathered here is only the two pictures. Book by book, the newest
    state file under output/state_BOOK_*.json gives what that book believes it
    holds and which orders it is waiting on. There is one file per book per day,
    so only the newest day of each book counts: adding every file in the folder
    together would count Monday's positions again on Tuesday. A book that has
    not started yet has no state file, and with no state files at all this
    passes with "no books active".

    IT PASSES WHEN NOBODY WOULD BE HALTED, which is books_to_halt being empty,
    and not when reconcile says ok. Those are two different questions. ok is
    False on every tick of every day while order 4 sits at the broker with no
    book's tag on it, and an untagged order halts nobody, so reading ok as the
    verdict would fail every morning forever. A forgiven orphan and a shared
    ticker that adds up are notes here for the same reason: the loop lets them
    through, so the morning must too.
    """
    by_book = newest_book_files_by_book(output_dir())
    books = [by_book[book] for book in sorted(by_book)]
    if not books:
        return Result(CHECK_RECONCILE, True,
                      "No books active: there are no output/state_BOOK_*.json "
                      "files yet, so there is nothing to reconcile.")

    books_state: dict[str, dict] = {}
    believed: dict[str, float] = {}
    unreadable: list[str] = []
    for book in sorted(by_book):
        path = by_book[book]
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            unreadable.append(f"{path.name} ({exc})")
            continue
        held = _positions_from_book(loaded)
        books_state[book] = {"positions": held,
                             "working_orders": _working_orders_from_book(loaded)}
        for symbol, shares in held.items():
            believed[symbol] = believed.get(symbol, 0.0) + shares

    if unreadable:
        return Result(CHECK_RECONCILE, False,
                      "Could not read these book state files: " + ", ".join(unreadable),
                      facts={"books": [p.name for p in books]})

    try:
        client = mcp.McpClient()
        holdings = client.portfolio() or {}
        values = client.account_values() or {}
        working = (client.open_orders() or {}).get("orders") or []
    except Exception as exc:                                      # noqa: BLE001
        return Result(CHECK_RECONCILE, False,
                      f"Could not read the account through the MCP server: {exc}")

    actual: dict[str, float] = {}
    broker_positions: list[dict] = []
    for position in holdings.get("positions") or []:
        symbol = str(position.get("symbol"))
        shares = _as_float(position.get("position") or 0.0)
        if shares is None:
            continue
        actual[symbol] = actual.get(symbol, 0.0) + shares
        broker_positions.append({"symbol": symbol, "qty": shares,
                                 "avg_cost": _as_float(position.get("avgCost")) or 0.0})

    forgiven = orphans_mod.expected_orphans(output_dir())
    facts = {
        "books": [p.name for p in books],
        "books_believe": believed,
        "broker_holds": actual,
        "broker_working_orders": len(working),
        "broker_cash": values.get("TotalCashValue"),
        "broker_net_liquidation": values.get("NetLiquidation"),
        "expected_orphans": forgiven,
        "expected_orphans_file": str(output_dir() / orphans_mod.FILE_NAME),
    }

    try:
        report = reconcile_mod.reconcile(
            broker_positions, broker_orders_for_reconcile(working), books_state,
            expected_orphans=forgiven)
    except ValueError as exc:
        return Result(CHECK_RECONCILE, False,
                      "The reconciliation could not make sense of what the books "
                      f"and the broker say: {exc}", facts=facts)

    notes = reconcile_notes(report)
    facts.update({
        "books_to_halt": list(report.books_to_halt),
        "orphans": [{"symbol": orphan.symbol, "qty": orphan.qty,
                     "expected": orphan.expected} for orphan in report.orphans],
        "reconcile_ok": bool(report.ok),
        "reconcile_lines": list(report.lines),
        "notes": notes,
    })
    spoken_notes = (" " + " ".join(notes)) if notes else ""

    if report.books_to_halt:
        return Result(CHECK_RECONCILE, False,
                      f"{report.summary}. "
                      + " ".join(reconcile_problems(report)) + spoken_notes,
                      facts=facts)
    return Result(CHECK_RECONCILE, True,
                  f"{len(books)} book state files agree with the broker on "
                  f"{len(actual)} positions. Broker cash "
                  f"{values.get('TotalCashValue', 'unknown')}." + spoken_notes,
                  facts=facts)


#: Where the day trade counters live. agent/pdt.py writes one file per book as
#: output/pdt_BOOK_A.json; the other two patterns are here in case the naming
#: moves, so this check keeps finding them rather than quietly finding nothing.
DAY_TRADE_PATTERNS = ("pdt_BOOK_*.json", "daytrades*.json", "day_trades*.json")


def check_day_trade_counters() -> Result:
    """Every day trade counter file that exists must be readable JSON.

    A corrupt one has to stop the morning here, at 09:00, rather than being
    discovered at 15:55 when the loop tries to work out whether it is allowed to
    close a position it opened an hour ago.
    """
    found: set[Path] = set()
    for pattern in DAY_TRADE_PATTERNS:
        found |= set(output_dir().glob(pattern))
    found = sorted(found)
    if not found:
        return Result(CHECK_DAY_TRADES, True,
                      "No day trade counter files exist yet, so there is nothing "
                      "to load. agent/pdt.py writes them as output/pdt_BOOK_A.json "
                      "once a book has traded.")
    broken = []
    for path in found:
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            broken.append(f"{path.name} ({exc})")
    if broken:
        return Result(CHECK_DAY_TRADES, False,
                      "Could not read: " + ", ".join(broken))
    return Result(CHECK_DAY_TRADES, True,
                  f"All {len(found)} day trade counter files load.",
                  facts={"files": [p.name for p in found]})


def guardrails_config_path() -> Path:
    """The shared settings file the detected regime is written into."""
    return config_dir() / "guardrails.yaml"


def check_day_trade_regime(write_regime: bool = False) -> Result:
    """Which day trading rulebook is this account under? Record, never block.

    FINRA retired the pattern day trader rule with effect from 2026-06-04
    (Regulatory Notice 26-10, phase-in to 2027-10-20) and replaced it with the
    intraday margin deficit rules. Which of the two an account is under is a
    fact about that account, and IBKR answers it in the account summary: five
    tags called DayTradesRemaining and DayTradesRemainingT+1 through T+4. Small
    non-negative numbers mean the old rule is still counting this account down.
    -1, which is IBKR writing "unlimited", or no tags at all, means it is not.

    The reading itself is agent/margin_regime.py's job. This opens a read only
    connection on its own client id, hands the tags over, writes down what came
    back and what it means, and never stops the morning whatever it finds. An
    unknown answer prints a warning line, because unknown means the code falls
    back to the strict old behaviour and somebody should look at why.

    With --write-regime the answer is written into pdt.regime in
    config/guardrails.yaml, which is where agent/pdt.py reads it. Without the
    flag nothing on disk changes, so this can be run any morning without moving
    the ground under the trading loop. An unknown answer is never written: it
    would overwrite a good reading from a previous day with a shrug.

    The connection here is its own rather than the MCP server's on purpose. The
    MCP server asks IBKR for 24 account summary tags and none of the five is
    among them, so an answer through it could never tell "this account has no
    day trade limit" apart from "nobody asked".
    """
    facts: dict = {
        "regime": Regime.UNKNOWN.value,
        "tags_requested": list(DAY_TRADE_TAGS),
        "paper_account": wd.PAPER_ACCOUNT,
        "live_account": LIVE_ACCOUNT,
        "paper_may_not_mirror_live": (
            f"These tags were read from the paper account {wd.PAPER_ACCOUNT}, "
            f"not from the live account {LIVE_ACCOUNT}. IBKR applies neither day "
            "trading rulebook to simulated money, so a paper account can report "
            "no day trade limit while the live account is still counted the old "
            "way. Only a reading taken on the live account settles it."
        ),
        "config_written": False,
        "config_path": str(guardrails_config_path()),
    }

    try:
        from ib_async import IB
    except Exception as exc:                                      # noqa: BLE001
        facts["note"] = f"could not load ib_async: {exc}"
        facts["warning"] = True
        return Result(CHECK_DAY_TRADE_REGIME, True,
                      "Could not load the IBKR library, so today's log has no "
                      f"answer about the day trading regime: {exc}.", facts=facts)

    ib = IB()
    try:
        ib.connect(wd.GATEWAY_HOST, wd.GATEWAY_PORT, clientId=REGIME_CLIENT_ID,
                   readonly=True, timeout=20)
    except Exception as exc:                                      # noqa: BLE001
        facts["note"] = f"could not connect: {exc}"
        facts["warning"] = True
        return Result(CHECK_DAY_TRADE_REGIME, True,
                      "Could not reach Gateway to ask which day trading regime "
                      f"this account is under, so today's log has no answer: {exc}.",
                      facts=facts)

    try:
        items = [{"account": row.account, "tag": row.tag, "value": row.value}
                 for row in (ib.accountSummary() or [])]
    except Exception as exc:                                      # noqa: BLE001
        facts["note"] = f"the account summary would not come back: {exc}"
        facts["warning"] = True
        return Result(CHECK_DAY_TRADE_REGIME, True,
                      f"Could not read the account summary: {exc}. No answer "
                      "about the day trading regime today.", facts=facts)
    finally:
        try:
            ib.disconnect()
        except Exception:                                         # noqa: BLE001
            pass

    reading = detect_regime(items)
    facts.update(reading.as_dict())
    facts["tags_requested"] = list(DAY_TRADE_TAGS)

    if write_regime and reading.regime is not Regime.UNKNOWN:
        try:
            changed = write_regime_setting(guardrails_config_path(), reading.regime)
        except (MarginRegimeConfigError, OSError) as exc:
            facts["config_error"] = str(exc)
            facts["warning"] = True
        else:
            facts["config_written"] = True
            facts["config_changed"] = changed
    elif write_regime:
        facts["config_note"] = (
            "The regime came back unknown, so nothing was written. Writing "
            "unknown would replace a good answer from an earlier day with a "
            "shrug, and unknown already means the strict old behaviour."
        )

    detail = reading.note
    if reading.regime is Regime.UNKNOWN:
        facts["warning"] = True
        detail = (
            f"The day trading regime is unknown. {reading.note} Until it is "
            "settled, pdt.treat_unknown_as in config/guardrails.yaml applies, "
            "which is old_pdt, so the day trade counter keeps behaving as though "
            "the pattern day trader rule still binds."
        )
    if facts.get("config_written"):
        detail += (
            f" Written into pdt.regime in {guardrails_config_path()}."
            if facts.get("config_changed")
            else f" pdt.regime in {guardrails_config_path()} already said that."
        )
    return Result(CHECK_DAY_TRADE_REGIME, True, detail, facts=facts)


# ------------------------------------------------------------------- the run

def check_time_zone(now: datetime | None = None) -> Result:
    """Will today's launchd jobs fire at the right New York minute?

    Not a question about the broker or the market at all. It sits second from
    last in the order, ahead of the day trading regime probe only because that
    one is slow and has always run last. It is a question about this Mac:
    launchd fires a job on
    the local clock, no plist can pin a zone, so scripts/gen_launchd.py writes
    the wake up times in local time and stamps the zone it converted for. This
    compares that stamp against the Mac as it is this morning.

    IT STOPS THE DAY WHEN IT FAILS, deliberately. A Mac that has changed zone
    has every job pointing at the wrong part of the day: the pre-flight itself
    may have run three hours late, the tick job will not wake at the open, and
    the dead man's handle will not be watching while the market is on. None of
    that is a day to be opening positions in. It is also a two minute fix, so
    NO_TRADE_TODAY costs little and the alert carries the command.

    Quiet when nothing is installed, so a fresh clone does not fail its first
    morning over jobs it has not loaded yet.

    Why it exists: on the night of 2026-09-06 this Mac relinked /etc/localtime
    to America/Los_Angeles by itself, because macOS is set to choose the zone
    from the current location, and all nine jobs became three hours late with
    nothing anywhere to say so. Automatic zone selection is still on, so this
    can happen again on any night.
    """
    try:
        verdict = timezone_check.check(project_root(), when=now)
    except Exception as exc:                                      # noqa: BLE001
        return Result(CHECK_TIME_ZONE, passed=True,
                      detail=f"not checked, the time zone check itself failed: {exc}",
                      facts={"warning": True})
    return Result(
        CHECK_TIME_ZONE,
        passed=verdict.ok,
        detail=verdict.detail if verdict.ok else f"{verdict.detail} Fix: {verdict.fix}",
        facts=verdict.as_dict,
    )


class PreflightTimeout(RuntimeError):
    """The pre-flight passed its budget and stopped where it stood."""


def out_of_time_result(spent: float, missed: list[str],
                       budget: float = PREFLIGHT_BUDGET_SECONDS) -> Result:
    """The one answer the pre-flight gives when it runs out of time.

    It fails, so it lands in NO_TRADE_TODAY and in the alert like any other
    failed check. A morning whose checks did not finish is not a morning to open
    positions in: nobody knows whether the broker is fine or on fire.
    """
    return Result(
        CHECK_IN_TIME, False,
        f"The pre-flight ran for {spent:.0f} seconds, past its {budget:.0f} second "
        "budget: the broker could not be read in time. "
        + (f"Checks that never ran: {', '.join(missed)}."
           if missed else
           "Every check ran, but too slowly to be worth anything before the open."),
        facts={"budget_seconds": budget, "spent_seconds": round(spent, 1),
               "checks_not_run": missed})


def check_crashed_result(name: str, exc: BaseException) -> Result:
    """One check that threw, written down as that check failing.

    Before this existed, a check that threw took the whole pre-flight with it
    and the morning ended with no verdict at all. Now it fails its own line,
    the error text goes in the detail so the alert carries it, and the checks
    after it still run.
    """
    return Result(
        name, False,
        f"The check stopped with an unexpected error and could not answer: "
        f"{exc!r}.",
        facts={"error": repr(exc), "error_type": type(exc).__name__})


def run_stopped_result(missed: list[str], exc: BaseException | None = None) -> Result:
    """The pre-flight itself stopping short, rather than any one check failing.

    Two ways in. Something threw outside any single check, in which case the
    error text is here. Or the run ended without an error and without reaching
    the end of the list, which is what a killed process looks like from the
    inside. Either way it fails, so the day stops: checks that never ran must
    never be mistaken for checks that passed.
    """
    if exc is not None:
        detail = (f"The pre-flight stopped with an unexpected error: {exc!r}. "
                  "Nothing about the broker was proved, so the day stops.")
    else:
        detail = ("The pre-flight stopped before it reached the end of its "
                  "checks. Nothing about the broker was proved, so the day "
                  "stops.")
    if missed:
        detail += f" Checks that never ran: {', '.join(missed)}."
    facts: dict = {"checks_not_run": missed}
    if exc is not None:
        facts["error"] = repr(exc)
        facts["error_type"] = type(exc).__name__
    return Result(CHECK_RUN_COMPLETE, False, detail, facts=facts)


def arm_deadline(seconds: float) -> bool:
    """Ask the operating system to interrupt us if the morning runs long.

    The wall clock check inside run_checks is the ordinary way a slow morning
    ends: it notices between two checks and stops tidily. This alarm sits
    underneath that, for the case where one single check is what is hanging and
    control never comes back to the loop at all.

    Returns False when the alarm could not be set, which is what happens off the
    main thread. The checks then run with the between-checks clock alone, which
    is still a great deal better than the 44 minutes of 2026-09-07.
    """
    def ring(signum, frame):                                      # noqa: ARG001
        raise PreflightTimeout(
            f"the pre-flight passed its {seconds:.0f} second budget while a check "
            "was still waiting on the broker")

    try:
        signal.signal(signal.SIGALRM, ring)
        signal.setitimer(signal.ITIMER_REAL, float(seconds))
        return True
    except (AttributeError, OSError, ValueError):
        return False


def disarm_deadline() -> None:
    """Put the alarm away. Safe to call whether or not one was ever set."""
    with contextlib.suppress(AttributeError, OSError, ValueError):
        signal.setitimer(signal.ITIMER_REAL, 0.0)


def run_checks(scan_out: Path, write_regime: bool = False,
               collected: list[Result] | None = None,
               budget_seconds: float = PREFLIGHT_BUDGET_SECONDS,
               clock=time.monotonic) -> list[Result]:
    """Every check, in order, stopping if the morning runs out of time.

    The clock is read between checks rather than during one, because a check
    halfway through a broker read has no safe place to be interrupted. What
    stops a single check hanging forever is its own bound: the MCP reads carry
    the wall clock deadline in agent/mcp_client.py, the scanner has
    SCANNER_TIMEOUT_SECONDS, and main() arms a SIGALRM underneath all of it.

    `collected` is how main keeps the answers of the checks that did finish even
    when the alarm goes off in the middle of one. It is the same list that comes
    back, so callers that only want the return value can ignore it.

    A check that throws fails its own line and the rest still run. Only the
    deadline is allowed through, because that is the alarm asking the whole run
    to stop.
    """
    results = collected if collected is not None else []
    started = clock()

    def guarded(name: str, run):
        try:
            return run()
        except PreflightTimeout:
            raise
        except Exception as exc:                                  # noqa: BLE001
            return check_crashed_result(name, exc)

    # The two that come out of one connection, so they are never split. A
    # Gateway that refuses the connection is the ordinary case and comes back
    # as two failed results; one that throws instead of answering, which is
    # what happened on 2026-09-10, now does the same rather than ending the run.
    try:
        login, market = check_gateway_and_data()
    except PreflightTimeout:
        raise
    except Exception as exc:                                      # noqa: BLE001
        login = check_crashed_result(CHECK_GATEWAY, exc)
        market = check_crashed_result(CHECK_MARKET_DATA, exc)
    results.append(login)
    results.append(market)

    rest = [
        (CHECK_SCANNER, lambda: check_scanner(scan_out)),
        (CHECK_SCANNER_FILTERS, check_scanner_filters),
        (CHECK_RECONCILE, check_reconcile),
        (CHECK_DAY_TRADES, check_day_trade_counters),
        (CHECK_TIME_ZONE, check_time_zone),
        (CHECK_DAY_TRADE_REGIME, lambda: check_day_trade_regime(write_regime=write_regime)),
    ]

    for index, (name, run) in enumerate(rest):
        spent = clock() - started
        if spent >= budget_seconds:
            results.append(out_of_time_result(
                spent, [n for n, _ in rest[index:]], budget_seconds))
            return results
        results.append(guarded(name, run))
    return results


def report_path(now: datetime, dry_run: bool) -> Path:
    if dry_run:
        return output_dir() / "preflight_dryrun.json"
    return output_dir() / f"preflight_{now:%Y-%m-%d}.json"


def write_no_trade_today(failed: list[str], now: datetime) -> Path:
    path = no_trade_today_file()
    path.write_text(
        f"Written by agent/preflight.py at {now:%Y-%m-%d %H:%M:%S %Z}.\n"
        f"Failed checks: {', '.join(failed)}.\n\n"
        "While this file exists the trading loop must not open a new position.\n"
        "Closing and managing what is already open is still allowed.\n\n"
        "Remove it with:\n"
        "  /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/reenable.sh\n",
        encoding="utf-8")
    return path


def record_checks(results, verdict: str, now: datetime) -> int:
    """Every check into the database, one row per check per day. Returns how many.

    Written for a dry run too. A rehearsal nobody wrote down is worth very
    little, and record_preflight updates the row rather than adding a second
    opinion, so running the checks twice in a morning leaves one honest row.

    Never raises. A pre-flight that fell over because it could not write down
    its own answer would be a worse morning than one with no database.
    """
    if db_module is None:
        return 0
    written = 0
    for result in results:
        try:
            db_module.record_preflight(
                check_name=result.name, passed=result.passed,
                detail={"detail": result.detail, "facts": result.facts},
                verdict=verdict, date=now.date(), ts=now)
            written += 1
        except Exception as exc:                                  # noqa: BLE001
            print(f"preflight: could not record {result.name} in the database: "
                  f"{exc!r}", file=sys.stderr)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="The 9 AM check that says whether today is a trading day. "
                    "Places no orders.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Write output/preflight_dryrun.json, create no "
                             "NO_TRADE_TODAY, and send no alert.")
    parser.add_argument("--write-regime", action="store_true",
                        help="Write the day trading regime this account is "
                             "under into pdt.regime in config/guardrails.yaml. "
                             "Without it the regime is only recorded in the "
                             "report and nothing on disk changes.")
    args = parser.parse_args(argv)

    now = datetime.now(EASTERN)
    scan_out = output_dir() / ("preflight_dryrun_scan.json" if args.dry_run
                               else "preflight_scan.json")

    print(f"{now:%Y-%m-%d %H:%M:%S %Z} pre-flight"
          f"{' (dry run)' if args.dry_run else ''}")

    # The budget. Whatever happens below, this run writes its report, and if it
    # ran out of time it writes NO_TRADE_TODAY and says the broker could not be
    # read in time. What it must never do again is hang for 44 minutes and write
    # nothing either way.
    #
    # The verdict is written in a finally block, so a run that throws, or one
    # that is killed where it stands, still leaves an answer on disk. That is
    # the 2026-09-10 lesson: a morning with no verdict file is worse than a
    # morning that failed, because nothing downstream can tell it from a pass.
    results: list[Result] = []
    began = time.monotonic()
    arm_deadline(PREFLIGHT_BUDGET_SECONDS)
    exit_code = 1
    try:
        try:
            run_checks(scan_out, write_regime=args.write_regime, collected=results)
        except PreflightTimeout:
            done = {r.name for r in results}
            results.append(out_of_time_result(
                time.monotonic() - began,
                [name for name in CHECK_ORDER if name not in done]))
        except Exception as exc:                                  # noqa: BLE001
            done = {r.name for r in results}
            results.append(run_stopped_result(
                [name for name in CHECK_ORDER if name not in done], exc))
    finally:
        disarm_deadline()
        exit_code = write_verdict(results, now, scan_out, dry_run=args.dry_run)
    return exit_code


def write_verdict(results: list[Result], now: datetime, scan_out: Path,
                  dry_run: bool = False) -> int:
    """Print the answers, write the report, and stop the day if anything failed.

    Split out of main so it can sit in a finally block: every way out of the
    checks, tidy or not, comes through here and leaves a verdict file behind.

    One guard is worth naming. If the run stopped early without recording a
    failure, which is what being killed looks like from in here, a fail is
    added for the checks that never ran. Checks that did not run must never be
    counted as checks that passed.
    """
    done = {r.name for r in results}
    missed = [name for name in CHECK_ORDER if name not in done]
    if missed and all(r.passed for r in results):
        results.append(run_stopped_result(missed))

    failed = [r.name for r in results if not r.passed]
    verdict = "fail" if failed else "pass"

    for result in results:
        if result.name in INFORMATIONAL_CHECKS:
            # A note that carries a warning still prints differently, so an
            # unknown day trading regime is not lost among the passing lines.
            label = "warn" if (result.facts or {}).get("warning") else "note"
        else:
            label = "pass" if result.passed else "FAIL"
        print(f"  [{label}] {result.name}: {result.detail}")

    by_name = {r.name: r for r in results}
    filters = by_name.get(CHECK_SCANNER_FILTERS)
    regime = by_name.get(CHECK_DAY_TRADE_REGIME)
    regime_facts = (regime.facts or {}) if regime else {}
    report = {
        "run_at": now.isoformat(),
        "verdict": verdict,
        "dry_run": dry_run,
        "failed_checks": failed,
        # Lifted to the top so Tuesday's log answers the question without anyone
        # having to dig through the checks block. true, false, or null when the
        # probe could not run at all.
        "scanner_filters_enabled": (
            (filters.facts or {}).get("filters_enabled") if filters else None),
        # The other Tuesday question: old_pdt, new_imd, or unknown. Read with
        # day_trade_regime_note, which says why this account may not be the one
        # that matters.
        "day_trade_regime": regime_facts.get("regime"),
        "day_trade_regime_note": regime_facts.get("paper_may_not_mirror_live"),
        "day_trade_regime_written": regime_facts.get("config_written", False),
        "checks": {r.name: asdict(r) for r in results},
        "scan_file": str(scan_out),
    }
    path = report_path(now, dry_run)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    record_checks(results, verdict, now)
    print(f"\nverdict: {verdict}")
    print(f"report: {path}")

    if dry_run:
        if failed:
            print(f"dry run, so no NO_TRADE_TODAY was created and no alert was "
                  f"sent. A real run would have stopped trading for "
                  f"{', '.join(failed)}.")
        else:
            print("dry run, nothing was created and no alert was sent.")
        return 0 if not failed else 1

    if failed:
        marker = write_no_trade_today(failed, now)
        print(f"created: {marker}")
        body = "\n".join(
            f"- {r.name}: {r.detail}" for r in results if not r.passed)
        delivered = alerts_module.alert(
            "error",
            f"Pre-flight failed: {', '.join(failed)}",
            f"The 9 AM check failed, so the agent will not open anything today.\n\n"
            f"{body}\n\n"
            f"Full report: {path}\n"
            f"When it is fixed, clear it with agent/reenable.sh")
        print(f"alert delivered through: {', '.join(delivered) or 'nothing'}")
        return 1

    marker = no_trade_today_file()
    if marker.exists():
        print(f"note: {marker} still exists from an earlier day. Today's checks "
              "all passed, but the loop will keep refusing to open positions "
              "until you clear it with agent/reenable.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

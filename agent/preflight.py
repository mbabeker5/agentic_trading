"""The 9 AM check that decides whether today is a trading day at all.

Runs half an hour before the market opens, once, on weekdays. It asks five
questions, writes the answers down, and if any of them is a no it creates the
file output/NO_TRADE_TODAY and tells Mo which check failed. It asks a sixth
question too, about whether IBKR's scanner filters work on this account, but
that one only ever records an answer and can never stop the day.

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
                   they hold, symbol by symbol. With no book state files yet,
                   this reports "no books active" and passes.
5. day_trades      Every day trade counter file present can be read.
                   agent/pdt.py writes one per book as output/pdt_BOOK_A.json.
                   Missing files pass; a corrupt one fails.

The sixth question, which never fails the day
---------------------------------------------

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

What it writes
--------------

    output/preflight_YYYY-MM-DD.json    pass or fail per check, plus a verdict
    output/preflight_scan.json          whatever the scanner found
    output/NO_TRADE_TODAY               only when something failed

With --dry-run it writes output/preflight_dryrun.json instead, creates no
NO_TRADE_TODAY, and sends no alert. That is the safe way to try it.

This script places no orders. The only broker connection it opens is read only,
and the only MCP tools it calls are the ones that read.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

import alerts as alerts_module  # noqa: E402
import mcp_client as mcp  # noqa: E402
import watchdog as wd  # noqa: E402
from paths import agent_dir, no_trade_today_file, output_dir, venv_python  # noqa: E402

EASTERN = ZoneInfo("America/New_York")

#: Our own API client id, kept clear of 99 (smoke test), 100 (MCP server),
#: 201 (scanner) and 250 (watchdog).
CLIENT_ID = 251

#: A second id for the scanner filter probe, which opens its own short lived
#: read only connection so it cannot disturb the one above.
FILTER_PROBE_CLIENT_ID = 252

#: The scanner can take a few minutes when IBKR is slow. Past this it is broken.
SCANNER_TIMEOUT_SECONDS = 300

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

#: How far the books and the broker may disagree on a share count before it is a
#: problem. Shares are whole numbers, so this is only here to absorb the way
#: IBKR reports quantities as floats.
POSITION_TOLERANCE = 0.001

CHECK_GATEWAY = "gateway_login"
CHECK_MARKET_DATA = "market_data"
CHECK_SCANNER = "scanner"
CHECK_SCANNER_FILTERS = "scanner_filters_enabled"
CHECK_RECONCILE = "reconcile"
CHECK_DAY_TRADES = "day_trades"

CHECK_ORDER = (CHECK_GATEWAY, CHECK_MARKET_DATA, CHECK_SCANNER,
               CHECK_SCANNER_FILTERS, CHECK_RECONCILE, CHECK_DAY_TRADES)

#: Checks that record an answer and never stop the day, whatever they find.
INFORMATIONAL_CHECKS = frozenset({CHECK_SCANNER_FILTERS})


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


def newest_book_files(folder: Path) -> list[Path]:
    """The most recent state file for each book, and only that one.

    agent/book_state.py writes one file per book per day, named like
    state_BOOK_A_2026-09-08.json. Adding every file in the folder together would
    count Monday's positions again on Tuesday, so the files are grouped by book
    and only the newest day of each is kept. ISO dates sort in date order, which
    is why a plain sort is enough to find it.
    """
    by_book: dict[str, Path] = {}
    for path in sorted(folder.glob("state_BOOK_*.json")):
        tail = path.stem[len("state_BOOK_"):]
        book, _, maybe_date = tail.rpartition("_")
        if not (book and len(maybe_date) == 10 and maybe_date.count("-") == 2):
            book = tail          # no date on the end, so the whole tail is the book
        by_book[book] = path     # sorted order means the last one wins
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


def check_reconcile() -> Result:
    """Does what the books think they hold match what the broker says?

    Book by book, the newest state file under output/state_BOOK_*.json is added
    up per symbol and compared with the broker's own position list. There is one
    file per book per day, so only the newest day of each book counts: adding
    every file in the folder together would count Monday's positions again on
    Tuesday. A book that has not started yet has no state file, and with no state
    files at all this passes with "no books active".
    """
    books = newest_book_files(output_dir())
    if not books:
        return Result(CHECK_RECONCILE, True,
                      "No books active: there are no output/state_BOOK_*.json "
                      "files yet, so there is nothing to reconcile.")

    believed: dict[str, float] = {}
    unreadable: list[str] = []
    for path in books:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            unreadable.append(f"{path.name} ({exc})")
            continue
        for symbol, shares in _positions_from_book(loaded).items():
            believed[symbol] = believed.get(symbol, 0.0) + shares

    if unreadable:
        return Result(CHECK_RECONCILE, False,
                      "Could not read these book state files: " + ", ".join(unreadable),
                      facts={"books": [p.name for p in books]})

    try:
        client = mcp.McpClient()
        holdings = client.portfolio() or {}
        values = client.account_values() or {}
    except Exception as exc:                                      # noqa: BLE001
        return Result(CHECK_RECONCILE, False,
                      f"Could not read the account through the MCP server: {exc}")

    actual: dict[str, float] = {}
    for position in holdings.get("positions") or []:
        symbol = str(position.get("symbol"))
        try:
            actual[symbol] = actual.get(symbol, 0.0) + float(position.get("position") or 0.0)
        except (TypeError, ValueError):
            pass

    mismatches = []
    for symbol in sorted(set(believed) | set(actual)):
        theirs = actual.get(symbol, 0.0)
        ours = believed.get(symbol, 0.0)
        if abs(theirs - ours) > POSITION_TOLERANCE:
            mismatches.append(f"{symbol}: the books say {ours:g}, the broker says {theirs:g}")

    facts = {
        "books": [p.name for p in books],
        "books_believe": believed,
        "broker_holds": actual,
        "broker_cash": values.get("TotalCashValue"),
        "broker_net_liquidation": values.get("NetLiquidation"),
    }
    if mismatches:
        return Result(CHECK_RECONCILE, False,
                      "The books and the broker disagree. " + "; ".join(mismatches),
                      facts=facts)
    return Result(CHECK_RECONCILE, True,
                  f"{len(books)} book state files agree with the broker on "
                  f"{len(actual)} positions. Broker cash "
                  f"{values.get('TotalCashValue', 'unknown')}.",
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


# ------------------------------------------------------------------- the run

def run_checks(scan_out: Path) -> list[Result]:
    login, market = check_gateway_and_data()
    return [login, market, check_scanner(scan_out), check_scanner_filters(),
            check_reconcile(), check_day_trade_counters()]


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="The 9 AM check that says whether today is a trading day. "
                    "Places no orders.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Write output/preflight_dryrun.json, create no "
                             "NO_TRADE_TODAY, and send no alert.")
    args = parser.parse_args(argv)

    now = datetime.now(EASTERN)
    scan_out = output_dir() / ("preflight_dryrun_scan.json" if args.dry_run
                               else "preflight_scan.json")

    print(f"{now:%Y-%m-%d %H:%M:%S %Z} pre-flight"
          f"{' (dry run)' if args.dry_run else ''}")
    results = run_checks(scan_out)

    failed = [r.name for r in results if not r.passed]
    verdict = "fail" if failed else "pass"

    for result in results:
        if result.name in INFORMATIONAL_CHECKS:
            label = "note"
        else:
            label = "pass" if result.passed else "FAIL"
        print(f"  [{label}] {result.name}: {result.detail}")

    by_name = {r.name: r for r in results}
    filters = by_name.get(CHECK_SCANNER_FILTERS)
    report = {
        "run_at": now.isoformat(),
        "verdict": verdict,
        "dry_run": args.dry_run,
        "failed_checks": failed,
        # Lifted to the top so Tuesday's log answers the question without anyone
        # having to dig through the checks block. true, false, or null when the
        # probe could not run at all.
        "scanner_filters_enabled": (
            (filters.facts or {}).get("filters_enabled") if filters else None),
        "checks": {r.name: asdict(r) for r in results},
        "scan_file": str(scan_out),
    }
    path = report_path(now, args.dry_run)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nverdict: {verdict}")
    print(f"report: {path}")

    if args.dry_run:
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

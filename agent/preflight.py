"""The 9 AM check that decides whether today is a trading day at all.

Runs half an hour before the market opens, once, on weekdays. It asks five
questions, writes the answers down, and if any of them is a no it creates the
file output/NO_TRADE_TODAY and tells Mo which check failed.

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

The five checks
---------------

1. gateway_login   IB Gateway is running, port 4002 is open, and a read only
                   connection comes back with the paper account DUT077572.
2. market_data     SPY quotes are real time rather than delayed. IBKR error 354
                   or 10089 means the subscription is missing. Error 10197 means
                   a live quote screen or the IBKR app is holding the data feed
                   and needs closing.
3. scanner         agent/scanner.py runs to completion and exits cleanly. At
                   9 AM the shortlist is usually empty, because the market has
                   not opened, and that is fine. It is the run that has to work,
                   not the result.
4. reconcile       What the books think they hold matches what the broker says
                   they hold, symbol by symbol. With no book state files yet,
                   this reports "no books active" and passes.
5. day_trades      Any day trade counter files present can be read. Missing
                   files pass; a corrupt one fails.

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

#: The scanner can take a few minutes when IBKR is slow. Past this it is broken.
SCANNER_TIMEOUT_SECONDS = 300

#: How far the books and the broker may disagree on a share count before it is a
#: problem. Shares are whole numbers, so this is only here to absorb the way
#: IBKR reports quantities as floats.
POSITION_TOLERANCE = 0.001

CHECK_GATEWAY = "gateway_login"
CHECK_MARKET_DATA = "market_data"
CHECK_SCANNER = "scanner"
CHECK_RECONCILE = "reconcile"
CHECK_DAY_TRADES = "day_trades"

CHECK_ORDER = (CHECK_GATEWAY, CHECK_MARKET_DATA, CHECK_SCANNER,
               CHECK_RECONCILE, CHECK_DAY_TRADES)


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


def check_scanner(out_path: Path) -> Result:
    """Run agent/scanner.py as its own process and insist it exits cleanly.

    Its own process because the scanner talks to IBKR's scanner service, which
    can hang, and a hung scanner must not take the pre-flight down with it.

    An empty shortlist at 9 AM is normal and passes. Only a crash, a timeout or
    a non zero exit code fails.
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

    if finished.returncode != 0:
        tail = (finished.stderr or finished.stdout or "").strip().splitlines()
        return Result(CHECK_SCANNER, False,
                      f"The scanner exited with code {finished.returncode}: "
                      f"{tail[-1] if tail else 'no message'}.",
                      facts={"exit_code": finished.returncode})

    found = 0
    try:
        written = json.loads(out_path.read_text(encoding="utf-8"))
        if isinstance(written, dict):
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

    return Result(CHECK_SCANNER, True,
                  f"The scanner ran cleanly and wrote {found} candidates to "
                  f"{out_path.name}. An empty list before the open is normal.",
                  facts={"candidates": found, "exit_code": 0})


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
            symbol = item.get("symbol") or item.get("ticker")
            for key in ("position", "qty", "quantity", "shares"):
                if item.get(key) is not None:
                    try:
                        held[str(symbol)] = held.get(str(symbol), 0.0) + float(item[key])
                    except (TypeError, ValueError):
                        pass
                    break
    elif isinstance(raw, dict):
        for symbol, value in raw.items():
            if isinstance(value, dict):
                for key in ("position", "qty", "quantity", "shares"):
                    if value.get(key) is not None:
                        value = value[key]
                        break
            try:
                held[str(symbol)] = held.get(str(symbol), 0.0) + float(value)
            except (TypeError, ValueError):
                pass
    return held


def check_reconcile() -> Result:
    """Does what the books think they hold match what the broker says?

    Book by book, the state files under output/state_BOOK_*.json are added up
    per symbol and compared with the broker's own position list. A book that has
    not started yet has no state file, and with no state files at all this
    passes with "no books active".
    """
    books = sorted(output_dir().glob("state_BOOK_*.json"))
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


def check_day_trade_counters() -> Result:
    """Any day trade counter files that exist must be readable JSON.

    Nothing writes these yet. The check is here so that the day the pattern day
    trade counter arrives, a corrupt one stops the morning rather than being
    discovered at 15:55.
    """
    found = sorted(set(output_dir().glob("daytrades*.json"))
                   | set(output_dir().glob("day_trades*.json")))
    if not found:
        return Result(CHECK_DAY_TRADES, True,
                      "No day trade counter files exist yet, so there is nothing "
                      "to load.")
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
    return [login, market, check_scanner(scan_out), check_reconcile(),
            check_day_trade_counters()]


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
        print(f"  [{'pass' if result.passed else 'FAIL'}] {result.name}: {result.detail}")

    report = {
        "run_at": now.isoformat(),
        "verdict": verdict,
        "dry_run": args.dry_run,
        "failed_checks": failed,
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

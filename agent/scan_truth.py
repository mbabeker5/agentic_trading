"""Tell a real empty scanner result from a failed scan.

Proved on 2026-09-06 against the paper Gateway: on an account without the scanner
data entitlement, a filtered scan returns ZERO rows and the only sign of trouble is
an error callback, code 162, "Scanner filter X is disabled". A loop that reads the
empty list as "nothing gapped today" would sit idle all month and never know.

Rules enforced here, every scan, every time:
1. Error callbacks are captured keyed by request id and attached to the result.
2. A control scan runs alongside every scan we care about and must return at least
   CONTROL_MIN_ROWS rows. The market is never empty, so fewer rows means the scanner
   itself is broken or unsubscribed.
3. Every scan must deliver its end-of-scan signal within the timeout.
4. Any error code in HARD_ERROR_CODES for the request, an empty result that carries
   any error, a short control, or a timeout raises ScanFailure. Pre-flight and the
   loop treat ScanFailure as a hard failure that alerts, never as an empty day.

The only benign message is 162 "API scanner subscription cancelled", which IBKR sends
when a completed snapshot scan is closed; it is recognised by text and ignored.

Since 2026-09-06 agent/scanner.py sends no filters at all, so the scan being judged
is usually itself unfiltered. Nothing here changes for that case: the checks are
about whether a result can be believed, not about whether filters were sent. Use
run_scan_async from inside an event loop and run_scan from ordinary code.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

CONTROL_MIN_ROWS = 20
DEFAULT_TIMEOUT_S = 30.0
HARD_ERROR_CODES = {162, 165, 365, 492}
BENIGN_162_TEXT = "scanner subscription cancelled"

#: How long to wait after a scan returns for its error callbacks to catch up.
#: IBKR sends the rows and the complaint about them separately, and the complaint
#: can land a moment later. Reading the errors immediately would sometimes find
#: none and call a broken scan healthy. Tests set this to zero.
ERROR_SETTLE_S = 0.3


class ScanFailure(Exception):
    """A scan that must not be read as an empty result."""

    def __init__(self, message: str, errors: list[tuple[int, str]] | None = None):
        super().__init__(message)
        self.errors = errors or []


@dataclass
class ScanResult:
    scan_code: str
    filters: list[tuple[str, str]]
    rows: list
    req_id: int | None
    errors: list[tuple[int, str]] = field(default_factory=list)
    elapsed_s: float = 0.0
    completed: bool = True

    @property
    def symbols(self) -> list[str]:
        out = []
        for r in self.rows:
            try:
                out.append(r.contractDetails.contract.symbol)
            except AttributeError:
                out.append(str(r))
        return out


def is_benign(code: int, msg: str) -> bool:
    return code == 162 and BENIGN_162_TEXT in (msg or "").lower()


def hard_errors(errors: list[tuple[int, str]]) -> list[tuple[int, str]]:
    return [(c, m) for c, m in errors if c in HARD_ERROR_CODES and not is_benign(c, m)]


class ErrorCapture:
    """Subscribe to ib.errorEvent and keep messages keyed by request id."""

    NOISE = {2104, 2106, 2107, 2108, 2158}

    def __init__(self, ib):
        self.ib = ib
        self.by_req: dict[int, list[tuple[int, str]]] = {}
        ib.errorEvent += self._on_error

    def _on_error(self, reqId, code, msg, *args):
        if code in self.NOISE:
            return
        self.by_req.setdefault(int(reqId), []).append((int(code), str(msg)))

    def close(self):
        try:
            self.ib.errorEvent -= self._on_error
        except Exception:  # noqa: BLE001
            pass

    def for_req(self, req_id: int) -> list[tuple[int, str]]:
        return list(self.by_req.get(int(req_id), []))


def next_req_id(ib) -> int | None:
    """The request id ib_async will hand the next request on this client.

    ib_async keeps a counter on the client and hands out its current value before
    stepping it, so reading it just before a call tells us which id the errors for
    that call will be keyed under. It only holds while requests are made one at a
    time, which is why the scanner runs its scans in sequence rather than together.
    """
    return getattr(ib.client, "_reqIdSeq", None)


async def run_scan_async(ib, subscription, filters, capture: ErrorCapture,
                         timeout_s: float = DEFAULT_TIMEOUT_S) -> ScanResult:
    """Run one scanner request from inside an event loop.

    `ib` is an ib_async.IB, `subscription` a ScannerSubscription, `filters` a list of
    TagValue (send an empty list for an unfiltered scan). Errors that arrive on this
    request's own id are attached to the result rather than logged and forgotten.
    """
    req_id = next_req_id(ib)
    t0 = time.time()
    completed = True
    try:
        rows = await asyncio.wait_for(
            ib.reqScannerDataAsync(subscription, [], filters), timeout_s)
    except asyncio.TimeoutError:
        rows, completed = [], False
    # give late error callbacks a moment to arrive
    if ERROR_SETTLE_S > 0:
        await asyncio.sleep(ERROR_SETTLE_S)
    errors = capture.for_req(req_id) if req_id is not None else []
    return ScanResult(subscription.scanCode, [(f.tag, f.value) for f in filters],
                      list(rows), req_id, errors, time.time() - t0, completed)


def run_scan(ib, subscription, filters, capture: ErrorCapture,
             timeout_s: float = DEFAULT_TIMEOUT_S) -> ScanResult:
    """The same request from ordinary code that is not already in an event loop."""
    return ib.run(run_scan_async(ib, subscription, filters, capture, timeout_s))


def assert_trustworthy(scan: ScanResult, control: ScanResult) -> None:
    """Raise ScanFailure unless both results can be believed.

    `scan` is the result we actually want, filtered or not. `control` is the scan
    that proves the scanner service itself is answering.
    """
    problems = []
    if not control.completed:
        problems.append(f"control scan {control.scan_code} did not finish within the timeout")
    ctrl_hard = hard_errors(control.errors)
    if ctrl_hard:
        problems.append(f"control scan errors: {ctrl_hard}")
    if len(control.rows) < CONTROL_MIN_ROWS:
        problems.append(
            f"control scan returned {len(control.rows)} rows, need at least {CONTROL_MIN_ROWS}; "
            "the market is never this empty, the scanner is broken or unsubscribed")
    if not scan.completed:
        problems.append(f"scan {scan.scan_code} did not finish within the timeout")
    scan_hard = hard_errors(scan.errors)
    if scan_hard:
        problems.append(f"scan {scan.scan_code} errors: {scan_hard}")
    if not scan.rows and any(not is_benign(c, m) for c, m in scan.errors):
        problems.append(
            f"scan {scan.scan_code} came back empty with errors attached; "
            "not a real empty list")
    if problems:
        raise ScanFailure("; ".join(problems), scan.errors + control.errors)


def checked_scan(ib, make_subscription, filters, timeout_s: float = DEFAULT_TIMEOUT_S):
    """Run a filtered scan plus its no-filter control and return (filtered, control).

    `make_subscription()` must return a fresh ScannerSubscription each call.
    Raises ScanFailure when either result cannot be trusted.
    """
    capture = ErrorCapture(ib)
    try:
        control = run_scan(ib, make_subscription(), [], capture, timeout_s)
        filtered = run_scan(ib, make_subscription(), filters, capture, timeout_s)
    finally:
        capture.close()
    assert_trustworthy(filtered, control)
    return filtered, control

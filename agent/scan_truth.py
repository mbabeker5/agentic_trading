"""Tell a real empty scanner result from a failed scan.

Proved on 2026-09-06 against the paper Gateway: on an account without the scanner
data entitlement, a filtered scan returns ZERO rows and the only sign of trouble is
an error callback, code 162, "Scanner filter X is disabled". A loop that reads the
empty list as "nothing gapped today" would sit idle all month and never know.

Rules enforced here, every scan, every time:
1. Error callbacks are captured keyed by request id and attached to the result.
2. A control scan with no filters runs alongside every filtered scan and must return
   at least CONTROL_MIN_ROWS rows. The market is never empty, so fewer rows means
   the scanner itself is broken or unsubscribed.
3. Every scan must deliver its end-of-scan signal within the timeout.
4. Any error code in HARD_ERROR_CODES for the request, an empty filtered result that
   carries any error, a short control, or a timeout raises ScanFailure. Pre-flight and
   the loop treat ScanFailure as a hard failure that alerts, never as an empty day.

The only benign message is 162 "API scanner subscription cancelled", which IBKR sends
when a completed snapshot scan is closed; it is recognised by text and ignored.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

CONTROL_MIN_ROWS = 20
DEFAULT_TIMEOUT_S = 30.0
HARD_ERROR_CODES = {162, 165, 365, 492}
BENIGN_162_TEXT = "scanner subscription cancelled"


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


def run_scan(ib, subscription, filters, capture: ErrorCapture,
             timeout_s: float = DEFAULT_TIMEOUT_S) -> ScanResult:
    """Run one scanner request and attach its own error callbacks to the result.

    `ib` is an ib_async.IB, `subscription` a ScannerSubscription, `filters` a list of
    TagValue. The request id is read from the client's sequence before the call, which
    is how ib_async assigns it.
    """
    req_id = getattr(ib.client, "_reqIdSeq", None)
    t0 = time.time()
    completed = True
    try:
        rows = ib.run(asyncio.wait_for(
            ib.reqScannerDataAsync(subscription, [], filters), timeout_s))
    except asyncio.TimeoutError:
        rows, completed = [], False
    # give late error callbacks a moment to arrive
    ib.sleep(0.3)
    errors = capture.for_req(req_id) if req_id is not None else []
    return ScanResult(subscription.scanCode, [(f.tag, f.value) for f in filters], rows,
                      req_id, errors, time.time() - t0, completed)


def assert_trustworthy(filtered: ScanResult, control: ScanResult) -> None:
    """Raise ScanFailure unless both results can be believed."""
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
    if not filtered.completed:
        problems.append(f"filtered scan {filtered.scan_code} did not finish within the timeout")
    filt_hard = hard_errors(filtered.errors)
    if filt_hard:
        problems.append(f"filtered scan errors: {filt_hard}")
    if not filtered.rows and any(not is_benign(c, m) for c, m in filtered.errors):
        problems.append("filtered scan came back empty with errors attached; not a real empty list")
    if problems:
        raise ScanFailure("; ".join(problems), filtered.errors + control.errors)


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

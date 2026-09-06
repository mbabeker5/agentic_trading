"""The scanner truth check must never read a failed scan as an empty day."""
import pytest

from agent.scan_truth import (
    CONTROL_MIN_ROWS, ScanFailure, ScanResult, assert_trustworthy, hard_errors, is_benign,
)


def rows(n):
    return [object() for _ in range(n)]


def result(code="TOP_PERC_GAIN", n=0, errors=None, completed=True, filters=None):
    return ScanResult(code, filters or [], rows(n), 7, errors or [], 0.2, completed)


def test_unsubscribed_filter_empty_with_162_raises():
    filtered = result(n=0, errors=[(162, "Historical Market Data Service error message:"
                                         "Scanner filter stVolume5MinAbove is disabled.")],
                      filters=[("stVolume5MinAbove", "100000")])
    control = result(n=50)
    with pytest.raises(ScanFailure) as exc:
        assert_trustworthy(filtered, control)
    assert "162" in str(exc.value)


def test_165_is_hard():
    filtered = result(n=0, errors=[(165, "Historical Market Data Service query message")])
    with pytest.raises(ScanFailure):
        assert_trustworthy(filtered, result(n=50))


def test_short_control_raises_even_when_filtered_has_rows():
    with pytest.raises(ScanFailure) as exc:
        assert_trustworthy(result(n=12), result(n=CONTROL_MIN_ROWS - 1))
    assert "never this empty" in str(exc.value)


def test_timeout_raises():
    with pytest.raises(ScanFailure) as exc:
        assert_trustworthy(result(n=0, completed=False), result(n=50))
    assert "timeout" in str(exc.value)


def test_genuine_empty_filtered_result_passes():
    # a real "nothing qualified" day: control healthy, filtered empty, no errors at all
    assert_trustworthy(result(n=0), result(n=50)) is None


def test_benign_cancelled_message_is_ignored():
    benign = [(162, "Historical Market Data Service error message:API scanner subscription cancelled: 3")]
    assert is_benign(*benign[0])
    assert hard_errors(benign) == []
    assert_trustworthy(result(n=0, errors=benign), result(n=50, errors=benign)) is None


def test_365_no_subscription_found_is_hard():
    filtered = result(n=0, errors=[(365, "No scanner subscription found for ticker id:4")])
    with pytest.raises(ScanFailure):
        assert_trustworthy(filtered, result(n=50))


def test_result_symbols_fallback():
    r = ScanResult("X", [], ["AAPL", "MSFT"], 1)
    assert r.symbols == ["AAPL", "MSFT"]

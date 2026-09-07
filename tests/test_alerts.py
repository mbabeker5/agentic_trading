"""Tests for the alert path.

Every channel is replaced with a stand in, so nothing here sends a Slack
message, a text, or a notification. What is being tested is the wiring: that a
broken channel does not stop the next one, and that the log line is written
whatever else happens.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest /Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_alerts.py -q
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import alerts  # noqa: E402


def isolate(monkeypatch, tmp_path: Path, imessage_to: str = "") -> Path:
    """Point every file the alerts module touches at a throwaway folder."""
    env = tmp_path / "alerts.env"
    if imessage_to:
        env.write_text(f"IMESSAGE_TO={imessage_to}\n", encoding="utf-8")
    monkeypatch.setattr(alerts, "alerts_env_path", lambda: env)
    monkeypatch.setattr(alerts, "alerts_log_path", lambda: tmp_path / "alerts.log")
    monkeypatch.setattr(alerts, "slack_token_path", lambda: tmp_path / "token.txt")
    return tmp_path


def silence_all(monkeypatch, slack=True, macos=True, imessage=True):
    monkeypatch.setattr(alerts, "send_slack", lambda *a, **k: slack)
    monkeypatch.setattr(alerts, "send_macos_notification", lambda *a, **k: macos)
    monkeypatch.setattr(alerts, "send_imessage", lambda *a, **k: imessage)


# ------------------------------------------------------------ the settings file

def test_a_missing_settings_file_reads_as_empty(tmp_path):
    assert alerts.read_env_file(tmp_path / "nothing.env") == {}


def test_comments_blank_lines_and_quotes_are_handled(tmp_path):
    path = tmp_path / "alerts.env"
    path.write_text('# a comment\n\nIMESSAGE_TO="+15551234567"\nSLACK_USER_ID=U123\n',
                    encoding="utf-8")
    assert alerts.read_env_file(path) == {"IMESSAGE_TO": "+15551234567",
                                          "SLACK_USER_ID": "U123"}


def test_writing_a_value_leaves_the_other_lines_alone(tmp_path):
    path = tmp_path / "alerts.env"
    path.write_text("# keep me\nIMESSAGE_TO=+15551234567\n", encoding="utf-8")
    alerts.write_env_value(path, "SLACK_USER_ID", "U999")
    text = path.read_text(encoding="utf-8")
    assert "# keep me" in text
    assert alerts.read_env_file(path) == {"IMESSAGE_TO": "+15551234567",
                                          "SLACK_USER_ID": "U999"}


def test_writing_a_value_that_is_already_there_replaces_it(tmp_path):
    path = tmp_path / "alerts.env"
    alerts.write_env_value(path, "SLACK_USER_ID", "U111")
    alerts.write_env_value(path, "SLACK_USER_ID", "U222")
    assert alerts.read_env_file(path)["SLACK_USER_ID"] == "U222"
    settings = [line for line in path.read_text(encoding="utf-8").splitlines()
                if line.startswith("SLACK_USER_ID=")]
    assert settings == ["SLACK_USER_ID=U222"], "replaced, not appended a second time"


def test_levels_are_tidied_into_three_words():
    assert alerts.normalise_level("info") == "INFO"
    assert alerts.normalise_level("Warning") == "WARN"
    assert alerts.normalise_level("critical") == "ERROR"
    assert alerts.normalise_level("error") == "ERROR"


# --------------------------------------------------------------- the channels

def test_everything_working_delivers_through_everything(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path, imessage_to="+15551234567")
    silence_all(monkeypatch)
    assert alerts.alert("error", "Gateway down", "port 4002 is shut") == [
        "imessage", "slack", "macos", "log"]


def test_imessage_is_skipped_when_no_number_is_configured(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    silence_all(monkeypatch)
    assert alerts.alert("info", "hello", "body") == ["slack", "macos", "log"]


def test_a_broken_channel_does_not_stop_the_next_one(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path, imessage_to="+15551234567")
    silence_all(monkeypatch)

    def explode(*a, **k):
        raise RuntimeError("Messages is not running")
    monkeypatch.setattr(alerts, "send_imessage", explode)

    assert alerts.alert("error", "Gateway down", "port shut") == ["slack", "macos", "log"]


def test_the_log_line_is_written_even_when_every_channel_fails(monkeypatch, tmp_path):
    folder = isolate(monkeypatch, tmp_path, imessage_to="+15551234567")

    def explode(*a, **k):
        raise RuntimeError("nope")
    monkeypatch.setattr(alerts, "send_imessage", explode)
    monkeypatch.setattr(alerts, "send_slack", explode)
    monkeypatch.setattr(alerts, "send_macos_notification", explode)

    assert alerts.alert("error", "Gateway down", "port shut") == ["log"]

    line = (folder / "alerts.log").read_text(encoding="utf-8")
    assert "ERROR | Gateway down" in line
    assert "delivered=none" in line
    assert "channels that failed" in line


def test_a_channel_that_reports_failure_without_raising_is_noticed(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    silence_all(monkeypatch, macos=False)
    assert alerts.alert("warn", "quotes are delayed", "code 10168") == ["slack", "log"]


def test_the_log_keeps_every_alert_one_line_each(monkeypatch, tmp_path):
    folder = isolate(monkeypatch, tmp_path)
    silence_all(monkeypatch)
    alerts.alert("info", "first", "one")
    alerts.alert("error", "second", "two\nacross two lines")
    lines = (folder / "alerts.log").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert "two / across two lines" in lines[1], "a multi line body is folded onto one line"


def test_alert_never_raises_even_with_nothing_set_up(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(alerts, "send_macos_notification", lambda *a, **k: False)
    # No Slack token file exists in the temporary folder, so Slack fails for real.
    delivered = alerts.alert("error", "no setup at all", "body")
    assert delivered == ["log"]


def test_a_cached_slack_user_id_is_used_without_asking_slack(monkeypatch, tmp_path):
    folder = isolate(monkeypatch, tmp_path)
    (folder / "alerts.env").write_text("SLACK_USER_ID=U0CACHED\n", encoding="utf-8")

    def should_not_be_called(*a, **k):
        raise AssertionError("Slack was asked for a user id it already had")
    monkeypatch.setattr(alerts, "_slack_call", should_not_be_called)

    assert alerts.slack_user_id("xoxb-not-a-real-token") == "U0CACHED"


# ------------------------------------------------------- the stamp on each line

def test_the_log_line_is_stamped_in_new_york_whatever_the_mac_is_set_to(
        monkeypatch, tmp_path):
    """Item 20. This Mac runs on Pacific and the log has to read as New York.

    On 2026-09-07 an alert sent by hand from a Pacific shell landed as
    "07:00:31 PDT" between lines the loop had stamped in EDT, three hours out of
    place for anyone reading the file in order or sorting it by time.
    """
    folder = isolate(monkeypatch, tmp_path)
    silence_all(monkeypatch)

    monkeypatch.setenv("TZ", "America/Los_Angeles")
    time.tzset()
    try:
        expected = datetime.now(ZoneInfo("America/New_York"))
        alerts.alert("info", "sent from a Pacific shell", "body")
    finally:
        monkeypatch.delenv("TZ", raising=False)
        time.tzset()

    stamp = (folder / "alerts.log").read_text(encoding="utf-8").split(" | ")[0]
    assert stamp.endswith(("EDT", "EST")), f"stamped in the wrong zone: {stamp!r}"
    assert stamp.startswith(f"{expected:%Y-%m-%d %H:%M}"), (
        f"{stamp!r} is not the New York clock, which said {expected:%Y-%m-%d %H:%M}")


def test_a_moment_from_another_zone_is_converted_rather_than_relabelled():
    """A datetime handed in keeps its instant and gains the New York clock."""
    pacific = datetime(2026, 9, 7, 7, 0, 31, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert alerts.log_stamp(pacific) == "2026-09-07 10:00:31 EDT"

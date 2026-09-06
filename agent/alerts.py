"""How the trading agent gets hold of Mo when something is wrong.

One function matters:

    from alerts import alert
    alert("error", "IB Gateway is down", "Nothing is listening on port 4002.")

It tries four channels, in this order, and returns the list of the ones that
actually delivered, for example ["slack", "macos", "log"].

    1. iMessage, to the phone number in .secrets/alerts.env under IMESSAGE_TO.
       Skipped when that key is not there, which is the case until Mo adds it.
    2. Slack, as a direct message from the bot whose token is at
       .secrets/slack_bot_token.txt, to whichever Slack user has the email
       address mo@thetaste.ai.
    3. A macOS notification, the banner in the top right corner of the screen.
       Only useful when Mo is sitting at this Mac, which is why it is third.
    4. A line appended to output/alerts.log. This one always happens, even when
       the other three all fail, so there is always a written record.

Every channel is wrapped in its own try block. A channel that is missing,
broken, or slow does not stop the next one, and none of them can raise out of
alert() and take a caller down with it. An alert that cannot be delivered is
never worth crashing the watchdog over.

Set up, once
------------

.secrets/slack_bot_token.txt is a symlink to the Goldenstone bot token in the
work repo, so there is only ever one copy of that token on this Mac:

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/.secrets/slack_bot_token.txt
      points at
    /Users/mtalib/workspace_repos/work_repo/.secrets/goldenstone_slack_bot_token.txt

The Slack user id is looked up once from the email address and then cached in
.secrets/alerts.env as SLACK_USER_ID, so every alert after the first is a single
call to Slack rather than two.

To turn iMessage on, add one line to
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/.secrets/alerts.env

    IMESSAGE_TO=+15551234567

The first iMessage will make macOS ask for permission to control Messages.
Approve it once and it stays approved.

Try it
------

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/alerts.py --test

That sends one harmless test through all four channels and prints which of them
delivered.

This file talks to Slack, Messages and the screen. It never talks to IB Gateway
and it cannot place, change or cancel an order.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from paths import output_dir, secrets_dir  # noqa: E402

# SQLite is the system of record, so every alert lands in the alerts table as
# well as in output/alerts.log. This is the one funnel every alerting caller in
# the project already goes through, which is why the row is written here rather
# than in each of them: the loop, the watchdog, the pre-flight, the kill switch
# and the dead man's handle all call alert(), and none of them has to remember.
# Optional, because an alert that cannot be recorded is still worth sending.
try:
    import db as _db                        # noqa: E402
except Exception:                           # noqa: BLE001
    _db = None                              # type: ignore[assignment]

#: The Slack account the alerts go to. Looked up by email, once, then cached.
SLACK_EMAIL = "mo@thetaste.ai"

#: Mo's other addresses, tried in order when the first one is not in the
#: workspace this bot token belongs to. The token in .secrets/slack_bot_token.txt
#: is the Goldenstone one, and checked on 2026-09-06 that workspace knows Mo as
#: mo@tastelabs.com, not mo@thetaste.ai. Rather than hardcode the answer, the
#: lookup asks for the addresses in this order and remembers whichever works.
SLACK_EMAIL_FALLBACKS = ("mo@tastelabs.com",)

#: Where the small settings and cache file lives. Gitignored.
ALERTS_ENV_NAME = "alerts.env"

#: Where the Slack bot token lives. A symlink to the work repo's copy.
SLACK_TOKEN_NAME = "slack_bot_token.txt"

#: How long to wait on anything that leaves this process, in seconds. Short on
#: purpose: an alert that takes a minute to send is an alert that has already
#: failed at its job.
NETWORK_TIMEOUT = 10.0
OSASCRIPT_TIMEOUT = 20.0

#: macOS notification banners quietly drop anything much longer than this.
NOTIFICATION_MAX = 200

_LEVELS = {
    "info": "INFO",
    "warn": "WARN",
    "warning": "WARN",
    "error": "ERROR",
    "critical": "ERROR",
    "crit": "ERROR",
}


# ------------------------------------------------------------------ settings

def alerts_env_path() -> Path:
    """.secrets/alerts.env, holding IMESSAGE_TO and the cached SLACK_USER_ID."""
    return secrets_dir() / ALERTS_ENV_NAME


def slack_token_path() -> Path:
    """.secrets/slack_bot_token.txt, a symlink to the work repo's token."""
    return secrets_dir() / SLACK_TOKEN_NAME


def read_env_file(path: Path) -> dict[str, str]:
    """Read a plain KEY=VALUE file. Missing file means an empty answer.

    Blank lines and lines starting with # are ignored, surrounding quotes are
    stripped, and anything malformed is skipped rather than raising, because a
    typo in this file must not stop an alert going out.
    """
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def write_env_value(path: Path, key: str, value: str) -> bool:
    """Set one KEY=VALUE in the file, leaving every other line as it was.

    Returns True when it was written. Used to remember the Slack user id after
    the first lookup so later alerts do not have to ask again.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        if path.exists():
            lines = path.read_text(encoding="utf-8").splitlines()
        replaced = False
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                continue
            if stripped.partition("=")[0].strip() == key:
                lines[index] = f"{key}={value}"
                replaced = True
                break
        if not replaced:
            if not lines:
                lines = [
                    "# Settings for agent/alerts.py. Gitignored, never committed.",
                    "# IMESSAGE_TO is the phone number alerts are texted to. Add it to",
                    "# switch iMessage alerts on. SLACK_USER_ID is filled in automatically",
                    "# the first time an alert goes to Slack.",
                ]
            lines.append(f"{key}={value}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.chmod(path, 0o600)
        return True
    except OSError:
        return False


def normalise_level(level: str) -> str:
    """Turn whatever the caller passed into INFO, WARN or ERROR."""
    return _LEVELS.get(str(level or "").strip().lower(), str(level or "INFO").upper())


# ------------------------------------------------------------------- channels

def _applescript_quote(text: str) -> str:
    """Escape a string so it survives being pasted into an AppleScript literal."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def send_imessage(text: str, number: str) -> bool:
    """Text one message to one number through the Messages app.

    Returns True when osascript reported success. macOS will ask for permission
    to control Messages the first time, and refuse until it is granted.
    """
    script = (
        'tell application "Messages"\n'
        '  set targetService to 1st account whose service type = iMessage\n'
        f'  set targetBuddy to participant "{_applescript_quote(number)}" of targetService\n'
        f'  send "{_applescript_quote(text)}" to targetBuddy\n'
        "end tell"
    )
    finished = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=OSASCRIPT_TIMEOUT,
    )
    return finished.returncode == 0


def send_macos_notification(title: str, body: str, level: str) -> bool:
    """Put a banner in the top right corner of this Mac's screen."""
    short = body if len(body) <= NOTIFICATION_MAX else body[:NOTIFICATION_MAX - 3] + "..."
    script = (
        f'display notification "{_applescript_quote(short)}" '
        f'with title "{_applescript_quote(title)}" '
        f'subtitle "agentic trading, {_applescript_quote(level.lower())}"'
    )
    finished = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=OSASCRIPT_TIMEOUT,
    )
    return finished.returncode == 0


def _slack_call(token: str, method: str, payload: dict | None = None,
                query: str = "") -> dict:
    """One call to the Slack web API. Raises on anything that is not a clean OK."""
    url = f"https://slack.com/api/{method}"
    if query:
        url = f"{url}?{query}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(url, data=data, headers=headers,
                                     method="POST" if data is not None else "GET")
    with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT) as response:
        answer = json.loads(response.read().decode("utf-8", "replace"))
    if not answer.get("ok"):
        raise RuntimeError(f"Slack refused {method}: {answer.get('error')}")
    return answer


def read_slack_token() -> str | None:
    """The bot token, or None when the file is missing or empty."""
    try:
        token = slack_token_path().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None


def slack_user_id(token: str, email: str = SLACK_EMAIL) -> str | None:
    """Mo's Slack user id, from the cache when we have it, from Slack when not.

    Slack charges a round trip for users.lookupByEmail and the answer never
    changes, so the first successful lookup is written to .secrets/alerts.env
    and every later alert reads it from there.

    Tries the given address first, then the ones in SLACK_EMAIL_FALLBACKS. A
    workspace that has never heard of an address answers users_not_found, which
    is a normal answer here and not a failure worth reporting.
    """
    cached = read_env_file(alerts_env_path()).get("SLACK_USER_ID", "").strip()
    if cached:
        return cached

    tried: list[str] = []
    refusals: list[str] = []
    for candidate in (email, *SLACK_EMAIL_FALLBACKS):
        if candidate in tried:
            continue
        tried.append(candidate)
        try:
            answer = _slack_call(token, "users.lookupByEmail",
                                 query=urllib.parse.urlencode({"email": candidate}))
        except Exception as exc:                                  # noqa: BLE001
            refusals.append(f"{candidate}: {exc}")
            continue
        found = (answer.get("user") or {}).get("id")
        if found:
            write_env_value(alerts_env_path(), "SLACK_USER_ID", found)
            write_env_value(alerts_env_path(), "SLACK_USER_EMAIL", candidate)
            return found
        refusals.append(f"{candidate}: Slack answered with no user id")
    raise RuntimeError("no Slack user found. " + "; ".join(refusals))


def send_slack(title: str, body: str, level: str) -> bool:
    """Direct message Mo on Slack. True when Slack accepted the message."""
    token = read_slack_token()
    if not token:
        raise RuntimeError(f"no Slack token at {slack_token_path()}")
    user = slack_user_id(token)
    text = f"*[{level}] {title}*\n{body}"
    _slack_call(token, "chat.postMessage", {"channel": user, "text": text})
    return True


def alerts_log_path() -> Path:
    """output/alerts.log, one line per alert, oldest first."""
    return output_dir() / "alerts.log"


def append_log(level: str, title: str, body: str, delivered: list[str]) -> bool:
    """Write the alert down. This is the channel that must never fail quietly."""
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    one_line = " / ".join(part.strip() for part in body.splitlines() if part.strip())
    line = (f"{stamp} | {level} | {title} | {one_line} | "
            f"delivered={','.join(delivered) if delivered else 'none'}\n")
    path = alerts_log_path()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
    return True


# ------------------------------------------------------------- the front door

def alert(level: str, title: str, body: str) -> list[str]:
    """Tell Mo something. Returns the names of the channels that delivered.

    level is "info", "warn" or "error". title is one short line. body is the
    detail, and may run to several lines.

    Every channel is attempted, not just the first one that works, because an
    alert worth sending is worth sending twice. Nothing raised inside a channel
    escapes: the worst case is that this returns ["log"], or on a truly broken
    machine an empty list.
    """
    level = normalise_level(level)
    title = str(title or "").strip() or "agentic trading"
    body = str(body or "").strip()
    delivered: list[str] = []
    problems: list[str] = []

    settings = read_env_file(alerts_env_path())
    number = settings.get("IMESSAGE_TO", "").strip()
    if number:
        try:
            if send_imessage(f"[{level}] {title}\n{body}", number):
                delivered.append("imessage")
            else:
                problems.append("iMessage: osascript refused the send")
        except Exception as exc:                                  # noqa: BLE001
            problems.append(f"iMessage: {exc}")

    try:
        if send_slack(title, body, level):
            delivered.append("slack")
    except Exception as exc:                                      # noqa: BLE001
        problems.append(f"Slack: {exc}")

    try:
        if send_macos_notification(title, body, level):
            delivered.append("macos")
        else:
            problems.append("macOS notification: osascript refused the send")
    except Exception as exc:                                      # noqa: BLE001
        problems.append(f"macOS notification: {exc}")

    detail = body
    if problems:
        detail = f"{body} [channels that failed: {'; '.join(problems)}]"

    # The database first, because it is the system of record and it is a file on
    # the same disk. It never raises for the ordinary reasons and this swallows
    # the rest, because an alert that cannot be recorded is still worth sending
    # and the caller is usually in the middle of handling a real problem.
    if _db is not None:
        try:
            _db.record_alert(level=level, title=title, body=detail,
                             channels=list(delivered))
        except Exception as exc:                                  # noqa: BLE001
            print(f"alerts: could not record the alert in the database: {exc!r}",
                  file=sys.stderr)

    try:
        append_log(level, title, detail, delivered)
        delivered.append("log")
    except Exception:                                             # noqa: BLE001
        # Nothing sensible left to do. Say so on stderr and carry on, because a
        # caller in the middle of handling a real problem must not be derailed
        # by the logging of that problem.
        print(f"alerts: could not write {alerts_log_path()}", file=sys.stderr)

    return delivered


# --------------------------------------------------------------------- the CLI

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Send an alert to Mo through iMessage, Slack, a macOS "
                    "banner and output/alerts.log.")
    parser.add_argument("--test", action="store_true",
                        help="Send one harmless test alert through every channel.")
    parser.add_argument("--level", default="info",
                        help="info, warn or error. Default: %(default)s")
    parser.add_argument("--title", default="", help="One short line.")
    parser.add_argument("--body", default="", help="The detail.")
    args = parser.parse_args(argv)

    if args.test:
        level = "info"
        title = "alerts test"
        body = ("This is a test from agent/alerts.py. Nothing is wrong, nothing "
                "was traded, and no order was placed. If you can read this, the "
                "alert path works.")
    else:
        if not args.title:
            parser.error("give me a --title, or use --test")
        level, title, body = args.level, args.title, args.body

    delivered = alert(level, title, body)
    print(f"delivered through: {', '.join(delivered) if delivered else 'nothing'}")
    print(f"written to: {alerts_log_path()}")
    return 0 if delivered else 1


if __name__ == "__main__":
    raise SystemExit(main())

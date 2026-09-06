"""The one place that knows where this project lives on disk.

Everything else asks here rather than writing the folder out again. That way a
move, a rename, or a second copy on another Mac is one edit in one file.

The root is read from the environment variable AGENTIC_TRADING_ROOT. When that
is not set, it falls back to the folder this project has always lived in:

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading

So nothing has to be configured for the normal case, and a different machine or
a test can point the whole project somewhere else by setting one variable.

Use it like this:

    from paths import project_root, output_dir, secrets_dir

    log = output_dir() / "alerts.log"

Nothing here touches the network or the broker. It is folders and nothing else.
"""
from __future__ import annotations

import os
from pathlib import Path

#: The environment variable that overrides where the project lives.
ROOT_ENV_VAR = "AGENTIC_TRADING_ROOT"

#: Where the project lives when nothing overrides it.
DEFAULT_ROOT = Path("/Users/mtalib/workspace_repos/personal_repo/agentic_trading")


def project_root() -> Path:
    """The project folder, the one holding agent/, config/ and output/.

    Reads AGENTIC_TRADING_ROOT when it is set to something, and falls back to
    DEFAULT_ROOT when it is not. A leading ~ is expanded, so
    AGENTIC_TRADING_ROOT=~/agentic_trading works.

    It does not check that the folder exists. A caller that cares can check,
    and a caller that is about to create files inside it does not need to.
    """
    raw = (os.environ.get(ROOT_ENV_VAR) or "").strip()
    if not raw:
        return DEFAULT_ROOT
    return Path(raw).expanduser()


def output_dir(create: bool = True) -> Path:
    """output/, where logs, state files and the day's JSON reports go.

    Created if it is missing, because every caller writes into it. Pass
    create=False when you only want to look.
    """
    path = project_root() / "output"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def secrets_dir() -> Path:
    """.secrets/, the gitignored folder holding tokens and logins.

    Never created here. If it is missing that is a real problem worth seeing,
    not something to paper over by making an empty folder.
    """
    return project_root() / ".secrets"


def config_dir() -> Path:
    """config/, holding guardrails.yaml, books.yaml and the launchd files."""
    return project_root() / "config"


def agent_dir() -> Path:
    """agent/, holding the scripts that do the work."""
    return project_root() / "agent"


def venv_python() -> Path:
    """The project's Python 3.12, the one IB Gateway and the MCP server need.

    Scripts that shell out to another script in this project should use this
    rather than whatever python happens to be on the path, because launchd
    starts jobs with almost no environment at all.
    """
    return project_root() / "venv312" / "bin" / "python"


def stop_file() -> Path:
    """output/STOP. While it exists the loop closes positions but opens none."""
    return output_dir() / "STOP"


def loop_disabled_file() -> Path:
    """output/LOOP_DISABLED. While it exists run_tick.sh refuses to run at all."""
    return output_dir() / "LOOP_DISABLED"


def no_trade_today_file() -> Path:
    """output/NO_TRADE_TODAY. Written by the pre-flight when a check fails."""
    return output_dir() / "NO_TRADE_TODAY"

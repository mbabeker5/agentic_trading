"""The one place that knows where this project lives on disk.

Everything else asks here rather than writing the folder out again. That way a
move, a rename, or a second copy on another Mac is one edit in one file, and
usually no edit at all.

HOW THE ROOT IS FOUND, in order:

1. The environment variable AGENTIC_TRADING_ROOT, when it is set to something.
   The launchd jobs set it, and a test sets it to a temporary folder.
2. Otherwise, the folder two levels above this file. This file is
   <root>/agent/paths.py, so its grandparent is <root>. That means a plain
   `git clone` anywhere on any Mac just works with nothing configured. Clone it
   to ~/agentic_trading, to an external disk, to a second checkout for a
   test: all of them find themselves.

There is deliberately no hard coded fallback to Mo's laptop any more. A path
written into the code is a path that has to be edited on every new machine, and
the whole point of the move to the Mac Mini is that nothing has to be edited.

On this machine, today, the root resolves to:

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading

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

#: The environment variable that overrides where IB Gateway is installed.
GATEWAY_DIR_ENV_VAR = "IB_GATEWAY_DIR"

#: The environment variable that overrides which IB Gateway version we want.
GATEWAY_VERSION_ENV_VAR = "IB_GATEWAY_VERSION"

#: The version to assume when config/gateway.env is missing or unreadable.
#: The real answer lives in that file, which the shell scripts read too, so the
#: number is written down once for both languages. This constant only stops an
#: import from blowing up on a half built checkout.
DEFAULT_GATEWAY_VERSION = "10.45"

#: The folder the venv lives in, under the root.
VENV_NAME = "venv312"


def _clone_root() -> Path:
    """The folder two levels above this file, which is the checkout root."""
    return Path(__file__).resolve().parent.parent


def project_root() -> Path:
    """The project folder, the one holding agent/, config/ and output/.

    Reads AGENTIC_TRADING_ROOT when it is set to something, and otherwise works
    it out from where this file sits. A leading ~ is expanded, so
    AGENTIC_TRADING_ROOT=~/agentic_trading works.

    It does not check that the folder exists. A caller that cares can check,
    and a caller that is about to create files inside it does not need to.
    """
    raw = (os.environ.get(ROOT_ENV_VAR) or "").strip()
    if not raw:
        return _clone_root()
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


def data_dir(create: bool = True) -> Path:
    """data/, holding trading.sqlite, the system of record, and its backups.

    This is where the database lives, and it is the one folder in the project
    that is state rather than source. The whole of it is gitignored apart from
    data/schema.sql and data/migrations/, because a database belongs to the
    machine it runs on, not to git.

    Created if it is missing, like output/, because the first thing anything
    does here is write into it. Pass create=False when you only want to look.
    """
    path = project_root() / "data"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def secrets_dir() -> Path:
    """.secrets/, the gitignored folder holding tokens and logins.

    Always under the project root and nowhere else. Never created here. If it
    is missing that is a real problem worth seeing, not something to paper over
    by making an empty folder.
    """
    return project_root() / ".secrets"


def config_dir() -> Path:
    """config/, holding guardrails.yaml, books.yaml and the launchd files."""
    return project_root() / "config"


def agent_dir() -> Path:
    """agent/, holding the scripts that do the work."""
    return project_root() / "agent"


def scripts_dir() -> Path:
    """scripts/, holding the tools that build things, such as gen_launchd.py."""
    return project_root() / "scripts"


def venv_python() -> Path:
    """The project's Python 3.12, the one IB Gateway and the MCP server need.

    Scripts that shell out to another script in this project should use this
    rather than whatever python happens to be on the path, because launchd
    starts jobs with almost no environment at all.
    """
    return project_root() / VENV_NAME / "bin" / "python"


def gateway_version() -> str:
    """Which IB Gateway version this project is pinned to, as a string.

    Read from, in order: the IB_GATEWAY_VERSION environment variable, then the
    line IB_GATEWAY_VERSION=... in config/gateway.env, then the constant above.
    The shell scripts source the same file, so the number lives in one place for
    both languages and a Gateway upgrade is one edit.
    """
    raw = (os.environ.get(GATEWAY_VERSION_ENV_VAR) or "").strip()
    if raw:
        return raw
    env_file = config_dir() / "gateway.env"
    try:
        text = env_file.read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_GATEWAY_VERSION
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == GATEWAY_VERSION_ENV_VAR:
            return value.strip().strip("'\"") or DEFAULT_GATEWAY_VERSION
    return DEFAULT_GATEWAY_VERSION


def gateway_app_dir() -> Path:
    """The folder IB Gateway is installed in.

    IB's macOS installer puts it in ~/Applications/IB Gateway <version>, one
    folder per version, side by side. So the default is exactly that, with the
    version from gateway.env. Set IB_GATEWAY_DIR to point somewhere else, which
    is what a machine with Gateway in /Applications needs.

    This returns the versioned folder itself, not its parent. IBC wants the
    parent, and agent/start_gateway.sh passes the parent as TWS_PATH.
    """
    raw = (os.environ.get(GATEWAY_DIR_ENV_VAR) or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / "Applications" / f"IB Gateway {gateway_version()}"


def ibc_dir() -> Path:
    """ibc/, the IB Gateway auto-login helper.

    Gitignored and downloaded by agent/install_ibc.sh, so it is present on a
    working machine and absent on a fresh clone. That is the point: it is a
    third party binary, not our source.
    """
    return project_root() / "ibc"


def stop_file() -> Path:
    """output/STOP. While it exists the loop closes positions but opens none."""
    return output_dir() / "STOP"


def loop_disabled_file() -> Path:
    """output/LOOP_DISABLED. While it exists run_tick.sh refuses to run at all."""
    return output_dir() / "LOOP_DISABLED"


def no_trade_today_file() -> Path:
    """output/NO_TRADE_TODAY. Written by the pre-flight when a check fails."""
    return output_dir() / "NO_TRADE_TODAY"


if __name__ == "__main__":  # pragma: no cover - a hand check, not a code path
    print(f"project root:  {project_root()}")
    print(f"config:        {config_dir()}")
    print(f"secrets:       {secrets_dir()}")
    print(f"output:        {output_dir(create=False)}")
    print(f"venv python:   {venv_python()}")
    print(f"gateway ver:   {gateway_version()}")
    print(f"gateway app:   {gateway_app_dir()}")
    print(f"ibc:           {ibc_dir()}")

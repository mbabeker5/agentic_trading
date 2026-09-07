"""The tick wrapper must never outlive its launchd slot.

WHY THIS FILE EXISTS. On 2026-09-07 IB Gateway lost its upstream connection to
IBKR, every read through the MCP server hung, and the tick that started at 07:37
New York did not finish until 09:25. launchd will not start a second copy of a
job that is already running, so every one minute pre-open wake up between 09:00
and 09:26 was lost. agent/run_tick.sh now caps one tick and kills it if it
overruns, so the next wake up starts fresh.

Everything here runs against a throwaway project folder: a stub `nc`, a stub
`curl` and a stub venv whose "python" is a shell script that sleeps. Nothing
touches IB Gateway, the MCP server, the real output folder or the real loop.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python \
      -m pytest /Users/mtalib/workspace_repos/personal_repo/agentic_trading/tests/test_run_tick.py -q
"""
from __future__ import annotations

import os
import subprocess
import time
from datetime import date
from pathlib import Path

ROOT = Path(os.environ.get("AGENTIC_TRADING_ROOT")
            or Path(__file__).resolve().parent.parent)
SCRIPT = ROOT / "agent" / "run_tick.sh"


def write_executable(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)
    return path


def fake_project(tmp_path: Path, loop_body: str) -> Path:
    """A project folder run_tick.sh will accept, with a stub loop inside it.

    The stub venv's activate does what a real one does, puts its own bin at the
    front of PATH, so the `python` the script then calls is the stub loop.
    """
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    (tmp_path / "agent").mkdir(parents=True, exist_ok=True)
    (tmp_path / "agent" / "loop.py").write_text("# never read, the stub ignores it\n")

    venv_bin = tmp_path / "venv312" / "bin"
    venv_bin.mkdir(parents=True, exist_ok=True)
    (venv_bin / "activate").write_text(f'export PATH="{venv_bin}:$PATH"\n')
    write_executable(venv_bin / "python", loop_body)
    return tmp_path


def stub_tools(tmp_path: Path) -> Path:
    """A `nc` that always finds Gateway and a `curl` that always finds the MCP."""
    stub_bin = tmp_path / "stub_bin"
    write_executable(stub_bin / "nc", "#!/bin/sh\nexit 0\n")
    write_executable(stub_bin / "curl", "#!/bin/sh\nprintf 200\n")
    return stub_bin


def run_script(project: Path, stub_bin: Path, **extra_env):
    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}:{env['PATH']}"
    env["AGENTIC_TRADING_ROOT"] = str(project)
    env.pop("AGENTIC_TRADING_LIVE_ORDERS", None)
    env.update(extra_env)
    began = time.monotonic()
    finished = subprocess.run(["bash", str(SCRIPT)], env=env,
                              capture_output=True, text=True, timeout=100)
    return finished, time.monotonic() - began


def tick_log(project: Path) -> str:
    path = project / "output" / f"tick_{date.today():%Y-%m-%d}.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


# ---------------------------------------------------------------- the script itself

def test_bash_syntax():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_the_cap_is_inside_the_launchd_gap():
    """A killed tick has to be over before the next wake up is due."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "TICK_MAX_SECONDS=\"${AGENTIC_TRADING_TICK_MAX_SECONDS:-240}\"" in text
    assert "LAUNCHD_GAP_SECONDS=\"${AGENTIC_TRADING_LAUNCHD_GAP:-300}\"" in text
    assert 240 < 300


def test_the_loop_is_never_run_uncapped():
    """Both the first tick and every fast window sub-tick go through the cap."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "python \"$PROJECT/agent/loop.py\"" not in text.replace(
        "  python \"$PROJECT/agent/loop.py\" >> \"$LOG\" 2>&1 &", "")
    assert text.count("run_loop_once\n  STATUS=$?") == 1   # the fast window one
    assert text.count("\nrun_loop_once\nSTATUS=$?") == 1   # the first tick


# ------------------------------------------------------------------ a tick that hangs

def test_a_tick_that_overruns_is_killed_and_the_run_exits_non_zero(tmp_path):
    """The 2026-09-07 shape: a loop that never comes back."""
    project = fake_project(tmp_path, "#!/bin/sh\nexec sleep 120\n")
    stub_bin = stub_tools(tmp_path)

    finished, spent = run_script(project, stub_bin,
                                 AGENTIC_TRADING_TICK_MAX_SECONDS="2")

    assert finished.returncode == 124, finished.stdout + finished.stderr
    assert spent < 30, f"the wrapper itself took {spent:.0f} seconds to give up"
    log = tick_log(project)
    assert "KILLED: this tick ran longer than 2 seconds" in log
    assert "the next launchd wake up starts fresh" in log
    assert "tick finished BADLY, exit code 124" in log


def test_a_killed_tick_writes_nothing_to_the_heartbeat(tmp_path):
    """The dead man's handle has to be able to see that this tick never ran."""
    project = fake_project(tmp_path, "#!/bin/sh\nexec sleep 120\n")
    stub_bin = stub_tools(tmp_path)

    run_script(project, stub_bin, AGENTIC_TRADING_TICK_MAX_SECONDS="2")

    assert not (project / "output" / "heartbeat").exists()


def test_a_killed_tick_never_enters_the_fast_window(tmp_path):
    """A loop that had to be killed should be looked at, not run nine more times."""
    project = fake_project(tmp_path, "#!/bin/sh\nexec sleep 120\n")
    stub_bin = stub_tools(tmp_path)
    (project / "output" / "next_tick_seconds").write_text("30\n")

    finished, _ = run_script(project, stub_bin,
                             AGENTIC_TRADING_TICK_MAX_SECONDS="2")

    assert finished.returncode == 124
    assert "fast window: sub-tick" not in tick_log(project)


# ------------------------------------------------------------- an ordinary tick

def test_a_tick_that_finishes_in_time_is_left_alone(tmp_path):
    project = fake_project(tmp_path, "#!/bin/sh\nexit 0\n")
    stub_bin = stub_tools(tmp_path)

    finished, spent = run_script(project, stub_bin,
                                 AGENTIC_TRADING_TICK_MAX_SECONDS="10")

    assert finished.returncode == 0, finished.stdout + finished.stderr
    assert spent < 10, "a clean tick should not wait out the cap"
    log = tick_log(project)
    assert "tick finished cleanly" in log
    assert "KILLED" not in log


def test_the_loops_own_exit_code_still_comes_through(tmp_path):
    """The cap must not swallow a loop that failed on its own account."""
    project = fake_project(tmp_path, "#!/bin/sh\nexit 3\n")
    stub_bin = stub_tools(tmp_path)

    finished, _ = run_script(project, stub_bin,
                             AGENTIC_TRADING_TICK_MAX_SECONDS="10")

    assert finished.returncode == 3
    log = tick_log(project)
    assert "tick finished BADLY, exit code 3" in log
    assert "KILLED" not in log

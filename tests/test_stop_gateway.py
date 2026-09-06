"""The Gateway stop path must not depend on telnet and must fall back to killing by process."""
import os
import subprocess
from pathlib import Path

ROOT = Path(os.environ.get("AGENTIC_TRADING_ROOT",
                           "/Users/mtalib/workspace_repos/personal_repo/agentic_trading"))
SCRIPT = ROOT / "agent" / "stop_gateway.sh"


def test_script_has_no_telnet_and_has_a_process_fallback():
    text = SCRIPT.read_text()
    assert "telnet" not in text.replace("(macOS no longer ships it)", "").lower().replace(
        "without telnet", "")
    assert "pkill" in text and "ibcalpha.ibc.IbcGateway" in text
    assert "socket.create_connection" in text


def test_bash_syntax():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_dry_run_never_kills_and_exits_zero(tmp_path):
    env = dict(os.environ)
    # point the script at a temp project with an ini whose command port is off
    (tmp_path / "config").mkdir()
    (tmp_path / "output").mkdir()
    (tmp_path / "config" / "ibc.ini").write_text("CommandServerPort=0\n")
    env["AGENTIC_TRADING_ROOT"] = str(tmp_path)
    r = subprocess.run(["bash", str(SCRIPT), "--dry-run"], env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    # either nothing is running, or the dry run explains both attempts without acting
    assert ("not running" in out) or ("dry run" in out and "would" in out)
    assert "FAILED" not in out

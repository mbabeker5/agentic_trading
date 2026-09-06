"""Tests for the one thing that makes this project movable: where it thinks it is.

The whole point of agent/paths.py is that no file in this project should ever
have to say

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading

in code again. Written in a comment or a docstring it helps a reader; written in
code it is one machine's home folder baked into a program, and it is the reason
the project could not move to the Mac Mini.

So these tests check four things:

1. project_root() reads AGENTIC_TRADING_ROOT when it is set, and otherwise works
   itself out from where the file sits, so a plain clone anywhere just works.
2. No Python file that this work owns has that path in its code. Comments and
   docstrings are stripped out before the check, because there it is welcome.
3. Every shell script works out the project folder the same way.
4. scripts/gen_launchd.py writes plists that actually parse, with the right
   number of wake ups in each.

Run them with:

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python -m pytest -q
"""
from __future__ import annotations

import ast
import importlib.util
import io
import plistlib
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
AGENT = REPO / "agent"

if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

import paths  # noqa: E402

#: The home folder we must never find in code. Built from pieces so that this
#: file does not trip its own test.
FORBIDDEN = "/" + "Users" + "/mtalib"

#: Every Python file the portability work owns. Files owned by other work are
#: left out on purpose and swept later.
PYTHON_FILES = [
    "agent/paths.py",
    "agent/alerts.py",
    "agent/book_state.py",
    "agent/broker.py",
    "agent/decide.py",
    "agent/guardrails.py",
    "agent/mcp_client.py",
    "agent/models.py",
    "agent/pdt.py",
    "agent/reconcile.py",
    "agent/smoke_test.py",
    "agent/sweep_congress.py",
    "agent/sweep_insider.py",
    "agent/watchdog.py",
    "ledger/create_ledger_sheet.py",
    "ledger/ledger_writer.py",
    "scripts/gen_launchd.py",
    "tests/test_paths.py",
]

#: Every shell script the portability work owns.
SHELL_FILES = [
    "agent/install_ibc.sh",
    "agent/kill_switch.sh",
    "agent/reenable.sh",
    "agent/run_tick.sh",
    "agent/start_gateway.sh",
    "agent/start_mcp.sh",
    "agent/stop_gateway.sh",
    "agent/stop_mcp.sh",
]

#: The one line every shell script must use to find the project.
PROJECT_LINE = 'PROJECT="${AGENTIC_TRADING_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"'

#: How many times a week each generated job should wake up.
EXPECTED_WAKE_UPS = {
    "tick": 550,        # 110 a day, Monday to Friday: 84 plus the 26 pre-open
                        # minutes from 09:00 to 09:26 that are not already on
                        # the five minute grid (09:25 is on both)
    "watchdog": 533,    # 97 a weekday, 24 a weekend day
    "preflight": 5,     # one a weekday
    "recorder": 405,    # 81 a day, Monday to Friday
    "learning": 5,      # one a weekday, after the close
    "weekly": 1,        # Friday only
}


# ------------------------------------------------------------------ helpers

def strip_comments_and_docstrings(source: str) -> str:
    """The same file with every comment and every docstring blanked out.

    Exact rather than approximate: comments come from Python's own tokenizer, so
    a hash inside a string is not mistaken for one, and docstrings come from the
    parsed syntax tree, so a normal string that happens to sit at the top of a
    function is not mistaken for one either.
    """
    lines = source.splitlines()
    blanked: set[int] = set()

    tree = ast.parse(source)
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, holders):
            continue
        body = getattr(node, "body", [])
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            for number in range(first.value.lineno, (first.value.end_lineno or 0) + 1):
                blanked.add(number)

    cuts: dict[int, int] = {}
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            line, column = token.start
            cuts[line] = min(cuts.get(line, column), column)

    out = []
    for number, line in enumerate(lines, start=1):
        if number in blanked:
            out.append("")
        elif number in cuts:
            out.append(line[:cuts[number]])
        else:
            out.append(line)
    return "\n".join(out)


def load_generator():
    """Import scripts/gen_launchd.py without it having to be a package."""
    spec = importlib.util.spec_from_file_location(
        "gen_launchd", REPO / "scripts" / "gen_launchd.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------ 1. the root

def test_project_root_reads_the_environment_variable(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ROOT_ENV_VAR, str(tmp_path))
    assert paths.project_root() == tmp_path


def test_project_root_expands_a_leading_tilde(monkeypatch):
    monkeypatch.setenv(paths.ROOT_ENV_VAR, "~/somewhere_else")
    assert paths.project_root() == Path.home() / "somewhere_else"


def test_an_empty_environment_variable_counts_as_unset(monkeypatch):
    monkeypatch.setenv(paths.ROOT_ENV_VAR, "   ")
    assert paths.project_root() == REPO


def test_project_root_falls_back_to_this_checkout(monkeypatch):
    monkeypatch.delenv(paths.ROOT_ENV_VAR, raising=False)
    assert paths.project_root() == REPO


def test_a_copy_somewhere_else_finds_itself(tmp_path, monkeypatch):
    """A plain clone anywhere works with nothing configured.

    This is the real test of the fallback: copy the module into a folder that
    has never heard of Mo's laptop, import that copy, and it should call its own
    grandparent the project root.
    """
    monkeypatch.delenv(paths.ROOT_ENV_VAR, raising=False)
    clone = tmp_path / "some_other_place"
    (clone / "agent").mkdir(parents=True)
    (clone / "agent" / "paths.py").write_text(
        (AGENT / "paths.py").read_text(encoding="utf-8"), encoding="utf-8")

    spec = importlib.util.spec_from_file_location(
        "paths_clone", clone / "agent" / "paths.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.project_root() == clone
    assert module.secrets_dir() == clone / ".secrets"
    assert module.config_dir() == clone / "config"
    assert module.venv_python() == clone / "venv312" / "bin" / "python"
    assert module.ibc_dir() == clone / "ibc"


def test_the_folders_all_hang_off_the_root(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ROOT_ENV_VAR, str(tmp_path))
    assert paths.output_dir() == tmp_path / "output"
    assert paths.output_dir().is_dir()          # output/ is made when asked for
    assert paths.secrets_dir() == tmp_path / ".secrets"
    assert not paths.secrets_dir().exists()     # .secrets/ never is
    assert paths.config_dir() == tmp_path / "config"
    assert paths.agent_dir() == tmp_path / "agent"
    assert paths.scripts_dir() == tmp_path / "scripts"
    assert paths.venv_python() == tmp_path / "venv312" / "bin" / "python"
    assert paths.stop_file() == tmp_path / "output" / "STOP"
    assert paths.loop_disabled_file() == tmp_path / "output" / "LOOP_DISABLED"
    assert paths.no_trade_today_file() == tmp_path / "output" / "NO_TRADE_TODAY"


# ------------------------------------------------------------------ the Gateway

def test_gateway_version_comes_from_the_config_file(monkeypatch):
    monkeypatch.delenv(paths.GATEWAY_VERSION_ENV_VAR, raising=False)
    monkeypatch.delenv(paths.ROOT_ENV_VAR, raising=False)
    assert paths.gateway_version() == "10.45"


def test_gateway_version_can_be_overridden(monkeypatch):
    monkeypatch.setenv(paths.GATEWAY_VERSION_ENV_VAR, "10.50")
    assert paths.gateway_version() == "10.50"


def test_gateway_version_falls_back_when_the_file_is_missing(tmp_path, monkeypatch):
    monkeypatch.delenv(paths.GATEWAY_VERSION_ENV_VAR, raising=False)
    monkeypatch.setenv(paths.ROOT_ENV_VAR, str(tmp_path))
    assert paths.gateway_version() == paths.DEFAULT_GATEWAY_VERSION


def test_gateway_app_dir_defaults_under_the_home_folder(monkeypatch):
    monkeypatch.delenv(paths.GATEWAY_DIR_ENV_VAR, raising=False)
    monkeypatch.setenv(paths.GATEWAY_VERSION_ENV_VAR, "10.45")
    assert paths.gateway_app_dir() == Path.home() / "Applications" / "IB Gateway 10.45"


def test_gateway_app_dir_can_be_pointed_anywhere(monkeypatch):
    monkeypatch.setenv(paths.GATEWAY_DIR_ENV_VAR, "/Applications/IB Gateway 10.45")
    assert paths.gateway_app_dir() == Path("/Applications/IB Gateway 10.45")


def test_the_gateway_version_file_says_what_the_shell_scripts_read(monkeypatch):
    """One number, one file, both languages."""
    monkeypatch.delenv(paths.ROOT_ENV_VAR, raising=False)
    text = (REPO / "config" / "gateway.env").read_text(encoding="utf-8")
    assert "IB_GATEWAY_VERSION=" in text
    line = [ln for ln in text.splitlines() if ln.startswith("IB_GATEWAY_VERSION=")]
    assert len(line) == 1
    assert line[0].split("=", 1)[1].strip() == paths.gateway_version()


# ------------------------------------------------------------------ 2. no laptop paths in code

@pytest.mark.parametrize("relative", PYTHON_FILES)
def test_no_hard_coded_home_folder_in_python_code(relative):
    path = REPO / relative
    source = path.read_text(encoding="utf-8")
    if FORBIDDEN not in source:
        return                      # not there at all, nothing to strip
    code = strip_comments_and_docstrings(source)
    offenders = [f"  line {number}: {line.strip()}"
                 for number, line in enumerate(code.splitlines(), start=1)
                 if FORBIDDEN in line]
    assert not offenders, (
        f"{path} has one machine's home folder in its code, not in a comment or "
        f"a docstring. Ask agent/paths.py instead.\n" + "\n".join(offenders))


def test_the_stripper_does_what_it_says():
    """The check above is only worth anything if the stripping is right."""
    sample = (
        '"""A docstring mentioning /Users/somebody/thing."""\n'
        'import os\n'
        '# a comment mentioning /Users/somebody/thing\n'
        'KEEP = "/Users/somebody/thing"   # trailing comment\n'
        'HASH = "not # a comment"\n'
    )
    stripped = strip_comments_and_docstrings(sample)
    assert stripped.count("/Users/somebody/thing") == 1
    assert 'KEEP = "/Users/somebody/thing"' in stripped
    assert "trailing comment" not in stripped
    assert 'HASH = "not # a comment"' in stripped


# ------------------------------------------------------------------ 3. the shell scripts

@pytest.mark.parametrize("relative", SHELL_FILES)
def test_every_shell_script_finds_the_project_the_same_way(relative):
    path = REPO / relative
    text = path.read_text(encoding="utf-8")
    assert text.count(PROJECT_LINE) == 1, (
        f"{path} must work out the project folder with exactly this line:\n"
        f"  {PROJECT_LINE}")


@pytest.mark.parametrize("relative", SHELL_FILES)
def test_no_shell_script_assigns_a_hard_coded_home_folder(relative):
    path = REPO / relative
    offenders = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#") or FORBIDDEN not in stripped:
            continue
        if "=" in stripped.split(FORBIDDEN)[0]:
            offenders.append(f"  line {number}: {stripped}")
    assert not offenders, (
        f"{path} assigns one machine's home folder to a variable:\n" + "\n".join(offenders))


@pytest.mark.parametrize("relative", SHELL_FILES)
def test_every_shell_script_is_valid_bash(relative):
    result = subprocess.run(["bash", "-n", str(REPO / relative)],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_start_gateway_reads_the_version_from_the_config_file():
    text = (REPO / "agent" / "start_gateway.sh").read_text(encoding="utf-8")
    assert "config/gateway.env" in text
    assert 'TWS_MAJOR_VRSN="${IB_GATEWAY_VERSION:-' in text


def test_the_ibc_settings_file_has_no_hard_coded_folder():
    """IbDir is left empty so TWS_SETTINGS_PATH from start_gateway.sh wins."""
    lines = (REPO / "config" / "ibc.ini").read_text(encoding="utf-8").splitlines()
    settings = [ln for ln in lines if ln.startswith("IbDir=")]
    assert settings == ["IbDir="]


# ------------------------------------------------------------------ 4. the generator

def test_the_generator_writes_plists_that_parse(tmp_path):
    generator = load_generator()
    subs = generator.substitutions(
        root=REPO,
        venv_python=REPO / "venv312" / "bin" / "python",
        home=Path.home(),
        label_prefix=generator.DEFAULT_LABEL_PREFIX,
        claude="/usr/local/bin/claude",
    )
    rendered = generator.generate(REPO, tmp_path, subs)
    assert len(rendered) == len(EXPECTED_WAKE_UPS)

    counts = {}
    for path, text in rendered.items():
        loaded = plistlib.loads(text.encode("utf-8"))   # strict XML, not plutil
        job = path.stem.rsplit(".", 1)[1]
        counts[job] = len(loaded["StartCalendarInterval"])
        assert loaded["Label"] == f"{generator.DEFAULT_LABEL_PREFIX}.{job}"
        assert loaded["RunAtLoad"] is False
        assert loaded["AbandonProcessGroup"] is False
        assert loaded["EnvironmentVariables"]["AGENTIC_TRADING_ROOT"] == str(REPO)
        assert loaded["WorkingDirectory"] == str(REPO)
    assert counts == EXPECTED_WAKE_UPS


def test_the_tick_job_wakes_every_minute_through_the_pre_open():
    """09:00 to 09:26, every minute, on every weekday, and none on the weekend.

    agent/preopen.py may send four historical requests a minute and a tick is
    over in a second or two, so a tick can never send more than four. Twenty
    seven wake ups pay for about a hundred requests, which is what the morning
    needs; five minute wake ups pay for about twenty. This is the launchd half
    of that, and it is the half that was missing until 2026-09-06.
    """
    loaded = plistlib.loads(
        (REPO / "config" / "launchd"
         / "com.mtalib.agentic-trading.tick.plist").read_bytes())
    entries = loaded["StartCalendarInterval"]

    for weekday in (1, 2, 3, 4, 5):
        minutes = {(e["Hour"], e["Minute"]) for e in entries
                   if e["Weekday"] == weekday}
        wanted = {(9, minute) for minute in range(0, 27)}
        assert wanted <= minutes, (
            f"weekday {weekday} is missing "
            f"{sorted(f'09:{m:02d}' for _, m in wanted - minutes)}")

    weekend = [e for e in entries if e["Weekday"] in (0, 6)]
    assert weekend == [], "the market is shut at the weekend"

    # One entry per minute, never two. The five minute grid also carries 09:25,
    # and expand_schedule() drops the duplicate rather than firing twice.
    monday = [(e["Hour"], e["Minute"]) for e in entries if e["Weekday"] == 1]
    assert len(monday) == len(set(monday))
    assert len(monday) == 110


def test_the_files_on_disk_match_the_templates():
    """A template edit that was never generated is the bug this catches."""
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "gen_launchd.py"), "--check"],
        capture_output=True, text=True, check=False, cwd=str(REPO))
    assert result.returncode == 0, (
        "config/launchd/ is out of date with config/launchd/templates/. Run:\n"
        "  python3 scripts/gen_launchd.py\n" + result.stdout + result.stderr)


def test_the_generated_plists_have_no_other_machine_in_them(tmp_path):
    """Point the generator at a different root and nothing of this Mac survives."""
    generator = load_generator()
    fake_home = tmp_path / "home"
    fake_root = fake_home / "agentic_trading"
    subs = generator.substitutions(
        root=fake_root,
        venv_python=fake_root / "venv312" / "bin" / "python",
        home=fake_home,
        label_prefix="com.example.trading",
        claude=str(fake_home / ".local" / "bin" / "claude"),
    )
    for path, text in generator.generate(REPO, tmp_path, subs).items():
        assert FORBIDDEN not in text, f"{path.name} still mentions the old Mac"
        assert str(fake_root) in text


def test_the_schedule_language():
    generator = load_generator()
    assert generator.expand_rule("at 09:00 on weekdays") == [
        (1, 9, 0), (2, 9, 0), (3, 9, 0), (4, 9, 0), (5, 9, 0)]
    assert generator.expand_rule("at 16:45 on friday") == [(5, 16, 45)]
    assert len(generator.expand_rule(
        "every 5 minutes from 09:25 to 16:05 on weekdays")) == 81 * 5
    assert len(generator.expand_rule("hourly from 00:00 to 23:00 on weekends")) == 24 * 2
    # The same time asked for twice only fires once.
    assert len(generator.expand_schedule(
        ["at 09:00 on weekdays", "hourly from 09:00 to 09:00 on weekdays"])) == 5


def test_the_schedule_language_refuses_nonsense():
    generator = load_generator()
    for rule in ("sometimes on weekdays",
                 "at 25:00 on weekdays",
                 "at 09:00 on caturday",
                 "every 5 minutes from 16:00 to 09:00 on weekdays"):
        with pytest.raises(generator.TemplateError):
            generator.expand_rule(rule)


def test_a_double_hyphen_in_a_comment_is_refused(tmp_path):
    """XML forbids it inside a comment, and plutil does not catch it.

    The recorder plist really did carry one, and Python refused to read the file
    while `plutil -lint` called it fine. Better to fail here than there.
    """
    generator = load_generator()
    template = tmp_path / "bad.template"
    template.write_text(
        "[job]\nname = bad\n\n[program]\n/bin/echo\n\n"
        "[schedule]\nat 09:00 on friday\n\n"
        "[comment]\nrun it with the " + "--" + "once flag\n",
        encoding="utf-8")
    job = generator.parse_template(template)
    subs = generator.substitutions(REPO, REPO, Path.home(), "com.example", "claude")
    with pytest.raises(generator.TemplateError):
        generator.render(job, subs)

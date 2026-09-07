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
4. scripts/gen_launchd.py finds every template in the folder, whichever of
   the two endings it uses, and writes plists that actually parse with the
   right number of wake ups in each.

Run them with:

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/venv312/bin/python -m pytest -q
"""
from __future__ import annotations

import ast
import importlib.util
import io
import plistlib
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
AGENT = REPO / "agent"
TEMPLATE_DIR = REPO / "config" / "launchd" / "templates"

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


# --------------------------------------------- 5. finding every template there is

def temp_project(tmp_path):
    """A throwaway copy of the templates folder, with its own output folder.

    These tests delete plists and add templates on purpose. Doing that inside
    the repo would fight whatever else is running, and would leave the real
    config/launchd/ in a state the next person did not ask for.
    """
    root = tmp_path / "project"
    templates = root / "config" / "launchd" / "templates"
    templates.mkdir(parents=True)
    for path in TEMPLATE_DIR.iterdir():
        if path.is_file():
            shutil.copy2(path, templates / path.name)
    return root


def run_generator(root, *flags):
    """The generator run the way a person runs it, so the exit code is real."""
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "gen_launchd.py"),
         "--root", str(root), *flags],
        capture_output=True, text=True, check=False, cwd=str(REPO))


def test_the_generator_reads_both_template_endings():
    """Six templates end .template and three end .plist.tmpl.

    It globbed the first ending alone until 2026-09-06, so the other three were
    never read and no plist was ever written for any of them. Both endings are
    accepted rather than the three being renamed, because their names are
    written down in the journal and inside the files themselves, and a rename
    would break anybody's notes that point at them.
    """
    generator = load_generator()
    names = [path.name for path in generator.discover_templates(TEMPLATE_DIR)]
    assert "tick.template" in names
    assert "backup_db.plist.tmpl" in names
    assert "deadman.plist.tmpl" in names
    assert "sheet_sync.plist.tmpl" in names
    # Sorted with no repeats, so two runs go through the files in one order.
    assert names == sorted(set(names))


def test_a_plist_tmpl_file_is_not_a_job_called_plist():
    """Path.stem takes one ending off, which is one too few here.

    It would make sheet_sync.plist.tmpl the job "sheet_sync.plist", and the
    plist would be written to a filename with .plist in the middle of it.
    """
    generator = load_generator()
    job_name = generator.job_name_from_filename
    assert job_name(Path("sheet_sync.plist.tmpl")) == "sheet_sync"
    assert job_name(Path("deadman.plist.tmpl")) == "deadman"
    assert job_name(Path("backup_db.plist.tmpl")) == "backup_db"
    assert job_name(Path("tick.template")) == "tick"


def test_every_template_the_generator_can_read_has_a_plist_on_disk():
    """A template the generator CAN read and never generated from.

    Every other test in this section starts from the generator's own list of
    files, and a template the generator cannot see is missing from that list
    too, so all of them passed while three jobs quietly had no plist at all.
    This one starts from the folder instead.

    IT WOULD NOT HAVE CAUGHT THE ORIGINAL BUG, and saying so matters more than
    the reassurance of pretending otherwise. It skips the pre-rendered files,
    and all three of the jobs that are actually missing are pre-rendered, so it
    passes today with backup_db, deadman and sheet_sync still absent. What it
    guards is the next one: a real template added to that folder and never
    generated from. The synthetic version of that is
    test_check_fails_when_a_template_has_no_plist below, which invents its own
    template so it can prove the check fires.
    """
    generator = load_generator()
    prefix = generator.DEFAULT_LABEL_PREFIX
    out_dir = REPO / "config" / "launchd"
    missing = []
    for path in generator.discover_templates(TEMPLATE_DIR):
        if generator.is_pre_rendered_plist(path):
            continue
        job = generator.job_name_from_filename(path)
        if not (out_dir / f"{prefix}.{job}.plist").exists():
            missing.append(path.name)
    assert missing == [], (
        "no plist was ever generated from " + ", ".join(missing)
        + ", so nothing runs it. Run: python3 scripts/gen_launchd.py")


def test_the_hand_made_plists_are_named_out_loud():
    """The real lesson of the bug is that a silent file is the dangerous one.

    backup_db, deadman and sheet_sync are finished plists rather than templates
    in the generator's format, so nothing is generated from them, and that stays
    true until somebody converts them on purpose. What must never happen again
    is that being silent, so the generator names every one of them on every run
    and this checks that it does.
    """
    generator = load_generator()
    held_back = generator.pre_rendered_templates(REPO)
    result = run_generator(REPO, "--check")
    for path in held_back:
        assert path.name in result.stdout, (
            f"{path.name} sits in the templates folder, nothing generates it, "
            "and the generator said nothing about it")


def test_check_fails_when_a_plist_is_deleted(tmp_path):
    """A job whose file has gone would silently stop being installed."""
    root = temp_project(tmp_path)
    assert run_generator(root).returncode == 0
    assert run_generator(root, "--check").returncode == 0

    (root / "config" / "launchd"
     / "com.mtalib.agentic-trading.weekly.plist").unlink()
    result = run_generator(root, "--check")
    assert result.returncode != 0, result.stdout
    assert "weekly.template" in result.stdout


def test_check_fails_when_a_template_has_no_plist(tmp_path):
    """A template nobody generated was invisible to --check until now.

    The new template is given the .plist.tmpl ending on purpose, because that is
    the ending the generator used to be blind to, so this is both halves of the
    bug in one test.
    """
    root = temp_project(tmp_path)
    assert run_generator(root).returncode == 0

    (root / "config" / "launchd" / "templates" / "brand_new.plist.tmpl").write_text(
        "[job]\nname = brand_new\n\n[program]\n/bin/echo\n\n"
        "[schedule]\nat 12:00 on friday\n", encoding="utf-8")
    result = run_generator(root, "--check")
    assert result.returncode != 0, result.stdout
    assert "brand_new.plist.tmpl" in result.stdout
    # The job is brand_new, so the file it wants has .plist once and at the end.
    assert "com.mtalib.agentic-trading.brand_new.plist" in result.stdout


def test_check_fails_when_a_plist_has_no_template(tmp_path):
    """The mirror image, and no safer: --install still loads a stale job."""
    root = temp_project(tmp_path)
    assert run_generator(root).returncode == 0

    (root / "config" / "launchd" / "templates" / "weekly.template").unlink()
    result = run_generator(root, "--check")
    assert result.returncode != 0, result.stdout
    assert "ORPHAN" in result.stdout
    assert "com.mtalib.agentic-trading.weekly.plist" in result.stdout


def test_a_hand_rendered_plist_is_not_condemned_as_an_orphan(tmp_path):
    """The dead man's handle, rendered the way its own header tells you to.

    Each of the three held-back files says to render it with sed into
    config/launchd/. Nothing generates it, so the orphan check has to count
    those three as templates anyway, otherwise --check tells you to delete the
    dead man's handle three lines above naming the file that made it.
    """
    root = temp_project(tmp_path)
    assert run_generator(root).returncode == 0

    source = (root / "config" / "launchd" / "templates" / "deadman.plist.tmpl")
    target = (root / "config" / "launchd"
              / "com.mtalib.agentic-trading.deadman.plist")
    target.write_text(source.read_text(encoding="utf-8").replace("{ROOT}", str(root)),
                      encoding="utf-8")

    result = run_generator(root, "--check")
    assert result.returncode == 0, result.stdout
    assert "ORPHAN" not in result.stdout
    assert "deadman.plist.tmpl" in result.stdout, "it is still named out loud"


def test_the_plists_on_disk_all_parse_and_carry_a_label():
    """Read the real files, not the rendered text, and read them strictly.

    plistlib refuses things `plutil -lint` waves through, and plistlib is the
    one that matters, because launchd is no more forgiving than it is.
    """
    plists = sorted((REPO / "config" / "launchd")
                    .glob("com.mtalib.agentic-trading.*.plist"))
    assert len(plists) == len(EXPECTED_WAKE_UPS)
    for path in plists:
        loaded = plistlib.loads(path.read_bytes())
        job = path.stem.rsplit(".", 1)[1]
        assert loaded["Label"] == f"com.mtalib.agentic-trading.{job}"
        assert loaded["StartCalendarInterval"], f"{path.name} has no schedule"


def test_the_tick_job_keeps_its_pre_open_minutes_and_its_five_minute_grid():
    """A guard on the job that matters most, in case the generator changes.

    Widening the template glob has no business touching the tick job, so this
    says out loud what that job's day looks like: 27 one minute wake ups from
    09:00 to 09:26, then the five minute grid on to 16:05.
    """
    loaded = plistlib.loads(
        (REPO / "config" / "launchd"
         / "com.mtalib.agentic-trading.tick.plist").read_bytes())
    monday = {(entry["Hour"], entry["Minute"])
              for entry in loaded["StartCalendarInterval"]
              if entry["Weekday"] == 1}

    pre_open = {(9, minute) for minute in range(0, 27)}
    assert pre_open <= monday, (
        "the pre-open minutes are gone: "
        + ", ".join(sorted(f"09:{m:02d}" for _, m in pre_open - monday)))

    # 09:30 to 16:05. The grid starts at 09:25, which the pre-open half hour
    # already carries, and expand_schedule() writes it once.
    grid = {(t // 60, t % 60) for t in range(9 * 60 + 30, 16 * 60 + 6, 5)}
    assert grid <= monday, (
        "the five minute grid is gone: "
        + ", ".join(sorted(f"{h:02d}:{m:02d}" for h, m in grid - monday)))

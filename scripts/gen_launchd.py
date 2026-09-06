#!/usr/bin/env python3
"""Write the launchd job files from the templates, so nobody hand edits 420 lines.

WHY THIS EXISTS. A launchd job that has to run every five minutes needs one
entry per wake up, written out in full. The trading loop's job has 420 of them,
the watchdog's has 533. Nobody can keep those correct by hand, and every one of
them had this Mac's own home folder written into it, which is exactly what
stopped the project moving to another machine.

So the schedule is now written once, in English, in a template:

    every 5 minutes from 09:25 to 16:05 on weekdays

and this script turns that into the entries launchd wants, with the project
root, the venv python, the home folder and the label prefix filled in from
wherever the script is actually running.

USE IT

    python3 /Users/mtalib/workspace_repos/personal_repo/agentic_trading/scripts/gen_launchd.py

    ... writes every plist in config/launchd/ from config/launchd/templates/

    python3 .../scripts/gen_launchd.py --check

    ... says whether the files on disk already match, changes nothing, and
        exits 1 if they do not. This is the one to run after editing a template.

    python3 .../scripts/gen_launchd.py --install

    ... copies the generated files to ~/Library/LaunchAgents and asks launchd to
        load them. THIS STARTS THE JOBS RUNNING. Nothing else here does.

    python3 .../scripts/gen_launchd.py --uninstall

    ... unloads them and removes the copies. Leaves config/launchd/ alone.

It runs on any Python 3.9 or newer with nothing installed, on purpose: it has to
work on a fresh Mac before the project's own virtual environment exists.

THE TEMPLATE FORMAT. One file per job in config/launchd/templates/, named
<job>.template. Sections are marked with [name] on a line of their own:

    [job]
    name = tick
    exit_timeout = 240
    run_at_load = false
    stdin = {ROOT}/config/prompts/something.md      (optional)

    [program]                one line per argument, exactly as launchd gets them
    /bin/bash
    {ROOT}/agent/run_tick.sh

    [environment]            one KEY = value per line
    TZ = America/New_York

    [schedule]               one rule per line, see below
    at 07:00 on weekdays
    every 5 minutes from 09:25 to 16:05 on weekdays

    [comment]                free text, copied into the top of the plist
    Whatever a person needs to know when they open the file.

The placeholders {ROOT}, {VENV_PYTHON}, {HOME}, {LABEL_PREFIX} and {CLAUDE} are
replaced everywhere they appear.

THE SCHEDULE RULES. Three shapes, and that is all:

    at HH:MM on DAYS
    every N minutes from HH:MM to HH:MM on DAYS
    hourly from HH:MM to HH:MM on DAYS          (the same as every 60 minutes)

DAYS is one of: weekdays (Monday to Friday), weekends (Saturday and Sunday),
every day, or a comma separated list of day names such as "friday" or
"monday, wednesday". Rules add together and duplicates are dropped, so a job can
have a five minute grid during the day and an hourly one at night without
firing twice at 10:00.

ONE THING TO WATCH. launchd works in the Mac's own time zone. There is no
setting inside a plist that pins one. The market keeps New York hours whatever
the Mac thinks, so every one of these jobs also sets TZ so the scripts agree,
but the WAKE UP TIMES are the Mac's local clock. Move to a Mac set to another
time zone and either set that Mac to Eastern or shift every time in the
templates. The generated files say so at the top.

This script never loads a job unless you type --install, and it never places an
order under any circumstances.
"""
from __future__ import annotations

import argparse
import os
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ------------------------------------------------------------------ where things are

#: The project root, found the same way agent/paths.py finds it: the environment
#: variable first, otherwise two folders above this file. This script sits in
#: <root>/scripts/, so its grandparent is the root.
ROOT_ENV_VAR = "AGENTIC_TRADING_ROOT"


def default_root() -> Path:
    raw = (os.environ.get(ROOT_ENV_VAR) or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(__file__).resolve().parent.parent


DEFAULT_LABEL_PREFIX = "com.mtalib.agentic-trading"

#: Monday is 1 in launchd, Sunday is 0. Saturday is 6.
DAY_NUMBERS = {
    "sunday": 0, "monday": 1, "tuesday": 2, "wednesday": 3,
    "thursday": 4, "friday": 5, "saturday": 6,
}
WEEKDAYS = [1, 2, 3, 4, 5]
WEEKENDS = [0, 6]
EVERY_DAY = [0, 1, 2, 3, 4, 5, 6]


class TemplateError(Exception):
    """A template could not be read. The message names the file and the line."""


# ------------------------------------------------------------------ the schedule language

_AT = re.compile(r"^at\s+(\d{1,2}):(\d{2})\s+on\s+(.+)$", re.I)
_EVERY = re.compile(
    r"^every\s+(\d+)\s+minutes?\s+from\s+(\d{1,2}):(\d{2})\s+to\s+(\d{1,2}):(\d{2})\s+on\s+(.+)$",
    re.I,
)
_HOURLY = re.compile(
    r"^hourly\s+from\s+(\d{1,2}):(\d{2})\s+to\s+(\d{1,2}):(\d{2})\s+on\s+(.+)$", re.I
)


def parse_days(text: str) -> list[int]:
    """Turn "weekdays", "weekends", "every day" or "monday, friday" into numbers."""
    word = text.strip().lower().rstrip(".")
    if word in ("weekdays", "weekday"):
        return list(WEEKDAYS)
    if word in ("weekends", "weekend"):
        return list(WEEKENDS)
    if word in ("every day", "all days", "everyday"):
        return list(EVERY_DAY)
    days: list[int] = []
    for part in word.replace(" and ", ",").split(","):
        name = part.strip()
        if name not in DAY_NUMBERS:
            raise TemplateError(f"unknown day {name!r} in {text!r}")
        days.append(DAY_NUMBERS[name])
    if not days:
        raise TemplateError(f"no days in {text!r}")
    return days


def _minutes(hour: str, minute: str) -> int:
    h, m = int(hour), int(minute)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise TemplateError(f"{h:02d}:{m:02d} is not a time of day")
    return h * 60 + m


def expand_rule(rule: str) -> list[tuple[int, int, int]]:
    """One English rule to a list of (weekday, hour, minute)."""
    rule = rule.strip()

    match = _AT.match(rule)
    if match:
        total = _minutes(match.group(1), match.group(2))
        days = parse_days(match.group(3))
        return [(d, total // 60, total % 60) for d in days]

    match = _EVERY.match(rule)
    if match:
        step = int(match.group(1))
        start = _minutes(match.group(2), match.group(3))
        end = _minutes(match.group(4), match.group(5))
        days = parse_days(match.group(6))
    else:
        match = _HOURLY.match(rule)
        if not match:
            raise TemplateError(
                f"cannot read the schedule rule {rule!r}. It has to be one of:\n"
                "  at HH:MM on DAYS\n"
                "  every N minutes from HH:MM to HH:MM on DAYS\n"
                "  hourly from HH:MM to HH:MM on DAYS"
            )
        step = 60
        start = _minutes(match.group(1), match.group(2))
        end = _minutes(match.group(3), match.group(4))
        days = parse_days(match.group(5))

    if step <= 0:
        raise TemplateError(f"a step of {step} minutes in {rule!r} would never finish")
    if end < start:
        raise TemplateError(f"{rule!r} ends before it starts")
    times = list(range(start, end + 1, step))
    return [(d, t // 60, t % 60) for d in days for t in times]


def expand_schedule(rules: list[str]) -> list[dict[str, int]]:
    """Every rule added together, duplicates dropped, in clock order per day.

    Sorting matters only so that two runs of this script give byte identical
    files. launchd does not care what order the entries come in.
    """
    seen: set[tuple[int, int, int]] = set()
    for rule in rules:
        seen.update(expand_rule(rule))
    return [{"Weekday": w, "Hour": h, "Minute": m} for w, h, m in sorted(seen)]


# ------------------------------------------------------------------ reading a template

SECTIONS = ("job", "program", "environment", "schedule", "comment")


def parse_template(path: Path) -> dict:
    """Read one .template file into a plain dictionary."""
    blocks: dict[str, list[str]] = {name: [] for name in SECTIONS}
    current: str | None = None
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            name = stripped[1:-1].strip().lower()
            if name not in SECTIONS:
                raise TemplateError(f"{path}: line {number}: unknown section [{name}]")
            current = name
            continue
        if current is None:
            if not stripped or stripped.startswith("#"):
                continue
            raise TemplateError(f"{path}: line {number}: text before the first section")
        if current == "comment":
            blocks[current].append(line)
            continue
        if not stripped or stripped.startswith("#"):
            continue
        blocks[current].append(stripped)

    job: dict[str, str] = {}
    for line in blocks["job"]:
        key, sep, value = line.partition("=")
        if not sep:
            raise TemplateError(f"{path}: [job] line {line!r} needs a = in it")
        job[key.strip().lower()] = value.strip()

    environment: dict[str, str] = {}
    for line in blocks["environment"]:
        key, sep, value = line.partition("=")
        if not sep:
            raise TemplateError(f"{path}: [environment] line {line!r} needs a = in it")
        environment[key.strip()] = value.strip()

    if "name" not in job:
        raise TemplateError(f"{path}: [job] has no name")
    if not blocks["program"]:
        raise TemplateError(f"{path}: [program] is empty, so there is nothing to run")
    if not blocks["schedule"]:
        raise TemplateError(f"{path}: [schedule] is empty, so the job would never run")

    return {
        "source": path,
        "name": job["name"],
        "exit_timeout": int(job.get("exit_timeout", "300")),
        "run_at_load": job.get("run_at_load", "false").strip().lower() == "true",
        "stdin": job.get("stdin", ""),
        "program": list(blocks["program"]),
        "environment": environment,
        "schedule": list(blocks["schedule"]),
        "comment": "\n".join(blocks["comment"]).strip("\n"),
    }


# ------------------------------------------------------------------ writing a plist

def substitutions(root: Path, venv_python: Path, home: Path,
                  label_prefix: str, claude: str) -> dict[str, str]:
    return {
        "{ROOT}": str(root),
        "{VENV_PYTHON}": str(venv_python),
        "{HOME}": str(home),
        "{LABEL_PREFIX}": label_prefix,
        "{CLAUDE}": claude,
    }


def fill(text: str, subs: dict[str, str]) -> str:
    for placeholder, value in subs.items():
        text = text.replace(placeholder, value)
    return text


def _xml(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def render(template: dict, subs: dict[str, str]) -> str:
    """One template plus one set of substitutions to one plist, as text."""
    label = f"{subs['{LABEL_PREFIX}']}.{template['name']}"
    root = subs["{ROOT}"]
    entries = expand_schedule([fill(rule, subs) for rule in template["schedule"]])

    comment = fill(template["comment"], subs)
    if "--" in comment:
        raise TemplateError(
            f"{template['source']}: the [comment] contains a double hyphen. XML "
            "forbids that inside a comment, and a strict parser refuses the whole "
            "file even though `plutil -lint` lets it through. Rephrase the line, "
            "for example write \"the once flag\" rather than the flag itself."
        )

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
        "<!--",
        "  GENERATED FILE. Do not edit it by hand, your edit will be overwritten.",
        f"  Written by {root}/scripts/gen_launchd.py",
        f"  from {root}/config/launchd/templates/{template['source'].name}",
        "",
        "  launchd works in this Mac's own local time. There is no setting in here",
        "  that pins a time zone, so the times below are this Mac's clock. The",
        "  market keeps New York hours whatever the Mac thinks. Keep the Mac on",
        "  Eastern, or change every time in the template and generate again.",
        "",
        "  NOT LOADED by writing this file. Loading is a separate, deliberate step,",
        "  one command, written out in full in:",
        f"  {root}/docs/LAUNCHD.md",
        "-->",
    ]
    if comment:
        lines += ["<!--"] + [f"  {line}" if line else "" for line in comment.splitlines()] + ["-->"]

    lines += [
        '<plist version="1.0">',
        "<dict>",
        "    <key>Label</key>",
        f"    <string>{_xml(label)}</string>",
        "",
        "    <key>ProgramArguments</key>",
        "    <array>",
    ]
    for argument in template["program"]:
        lines.append(f"      <string>{_xml(fill(argument, subs))}</string>")
    lines += [
        "    </array>",
        "",
        "    <key>WorkingDirectory</key>",
        f"    <string>{_xml(root)}</string>",
        "",
        "    <key>StandardOutPath</key>",
        f"    <string>{_xml(root)}/output/launchd_{template['name']}.out.log</string>",
        "    <key>StandardErrorPath</key>",
        f"    <string>{_xml(root)}/output/launchd_{template['name']}.err.log</string>",
    ]
    if template["stdin"]:
        lines += [
            "",
            "    <!-- The prompt is fed in on standard input rather than as an",
            "         argument, which keeps a long prompt out of the process list. -->",
            "    <key>StandardInPath</key>",
            f"    <string>{_xml(fill(template['stdin'], subs))}</string>",
        ]

    lines += ["", "    <key>EnvironmentVariables</key>", "    <dict>"]
    for key in sorted(template["environment"]):
        value = fill(template["environment"][key], subs)
        lines.append(f"      <key>{_xml(key)}</key><string>{_xml(value)}</string>")
    lines += [
        "    </dict>",
        "",
        "    <!-- A run that overruns must never have a second one land on top of it. -->",
        "    <key>AbandonProcessGroup</key>",
        "    <false/>",
        "    <key>ExitTimeOut</key>",
        f"    <integer>{template['exit_timeout']}</integer>",
        "",
        "    <!-- Do not fire the moment the job is loaded, only on the times below. -->",
        "    <key>RunAtLoad</key>",
        f"    <{'true' if template['run_at_load'] else 'false'}/>",
        "",
        f"    <!-- {len(entries)} wake ups a week. -->",
        "    <key>StartCalendarInterval</key>",
        "    <array>",
    ]
    for entry in entries:
        lines += [
            "      <dict>",
            f"        <key>Weekday</key><integer>{entry['Weekday']}</integer>",
            f"        <key>Hour</key><integer>{entry['Hour']}</integer>",
            f"        <key>Minute</key><integer>{entry['Minute']}</integer>",
            "      </dict>",
        ]
    lines += ["    </array>", "", "</dict>", "</plist>", ""]
    return "\n".join(lines)


# ------------------------------------------------------------------ the work

def find_claude() -> str:
    """The full path to the claude command, for the two headless jobs.

    launchd starts a job with almost no PATH, so "claude" on its own would not
    be found. Look in the usual places and fall back to the bare name with a
    warning, so generating still works on a machine that has not installed it
    yet and the missing piece is obvious in the output.
    """
    found = shutil.which("claude")
    if found:
        return found
    for candidate in (
        Path.home() / ".local" / "bin" / "claude",
        Path.home() / ".claude" / "local" / "claude",
        Path("/opt/homebrew/bin/claude"),
        Path("/usr/local/bin/claude"),
    ):
        if candidate.exists():
            return str(candidate)
    print("WARNING: claude was not found on this Mac. The learning loop and the "
          "weekly review jobs will be written with the bare name 'claude', which "
          "launchd cannot find. Install Claude Code and generate again.",
          file=sys.stderr)
    return "claude"


def generate(root: Path, out_dir: Path, subs: dict[str, str]) -> dict[Path, str]:
    """Every template rendered, keyed by the file it belongs in."""
    template_dir = root / "config" / "launchd" / "templates"
    templates = sorted(template_dir.glob("*.template"))
    if not templates:
        raise TemplateError(f"no templates found in {template_dir}")
    written: dict[Path, str] = {}
    for path in templates:
        job = parse_template(path)
        text = render(job, subs)
        plistlib.loads(text.encode("utf-8"))  # refuse to write anything unreadable
        written[out_dir / f"{subs['{LABEL_PREFIX}']}.{job['name']}.plist"] = text
    return written


def do_install(files: list[Path]) -> int:
    """Copy the plists into ~/Library/LaunchAgents and ask launchd to load them.

    THIS STARTS THE JOBS. It is the only thing in this file that does.
    """
    agents = Path.home() / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    problems = 0
    for source in files:
        target = agents / source.name
        shutil.copy2(source, target)
        print(f"copied {source} to {target}")
        label = target.stem
        subprocess.run(["launchctl", "bootout", f"{domain}/{label}"],
                       capture_output=True, check=False)
        result = subprocess.run(["launchctl", "bootstrap", domain, str(target)],
                                capture_output=True, text=True, check=False)
        if result.returncode == 0:
            print(f"loaded {label}")
        else:
            problems += 1
            print(f"FAILED to load {label}: {result.stderr.strip()}", file=sys.stderr)
    print(f"\nCheck them with:  launchctl list | grep {files[0].stem.rsplit('.', 1)[0]}")
    return 1 if problems else 0


def do_uninstall(files: list[Path]) -> int:
    """Unload the jobs and remove the copies. config/launchd/ is left alone."""
    agents = Path.home() / "Library" / "LaunchAgents"
    domain = f"gui/{os.getuid()}"
    for source in files:
        target = agents / source.name
        label = target.stem
        subprocess.run(["launchctl", "bootout", f"{domain}/{label}"],
                       capture_output=True, check=False)
        print(f"unloaded {label}")
        if target.exists():
            target.unlink()
            print(f"removed {target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write the launchd job files from config/launchd/templates/.")
    parser.add_argument("--root", default=None,
                        help="project root (default: AGENTIC_TRADING_ROOT, else "
                             "the folder above this script)")
    parser.add_argument("--out-dir", default=None,
                        help="where to write the plists (default: <root>/config/launchd)")
    parser.add_argument("--venv-python", default=None,
                        help="python for the jobs (default: <root>/venv312/bin/python)")
    parser.add_argument("--home", default=None, help="home folder (default: this user's)")
    parser.add_argument("--label-prefix", default=DEFAULT_LABEL_PREFIX,
                        help=f"job label prefix (default: {DEFAULT_LABEL_PREFIX}). "
                             "Changing it renames every job, so the launchctl commands "
                             "in the docs would need changing too.")
    parser.add_argument("--claude", default=None,
                        help="path to the claude command for the headless jobs "
                             "(default: found on this Mac)")
    parser.add_argument("--check", action="store_true",
                        help="say whether the files on disk already match, change nothing")
    parser.add_argument("--install", action="store_true",
                        help="copy to ~/Library/LaunchAgents and load. STARTS THE JOBS.")
    parser.add_argument("--uninstall", action="store_true",
                        help="unload the jobs and remove the copies")
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser().resolve() if args.root else default_root()
    out_dir = Path(args.out_dir).expanduser() if args.out_dir else root / "config" / "launchd"
    venv_python = (Path(args.venv_python).expanduser() if args.venv_python
                   else root / "venv312" / "bin" / "python")
    home = Path(args.home).expanduser() if args.home else Path.home()
    claude = args.claude or find_claude()

    subs = substitutions(root, venv_python, home, args.label_prefix, claude)

    try:
        rendered = generate(root, out_dir, subs)
    except TemplateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.uninstall:
        return do_uninstall(sorted(rendered))

    if args.check:
        differences = 0
        for path, text in sorted(rendered.items()):
            if not path.exists():
                print(f"MISSING  {path}")
                differences += 1
            elif path.read_text(encoding="utf-8") != text:
                print(f"DIFFERS  {path}")
                differences += 1
            else:
                print(f"same     {path}")
        if differences:
            print(f"\n{differences} file(s) out of date. Run this script without "
                  "--check to rewrite them.")
        return 1 if differences else 0

    out_dir.mkdir(parents=True, exist_ok=True)
    for path, text in sorted(rendered.items()):
        path.write_text(text, encoding="utf-8")
        count = text.count("<key>Weekday</key>")
        print(f"wrote {path}  ({count} wake ups a week)")

    print(f"\nroot:        {root}")
    print(f"venv python: {venv_python}")
    print(f"claude:      {claude}")
    print("\nNothing has been loaded. To load, and only when you mean it:")
    print(f"  python3 {root}/scripts/gen_launchd.py --install")

    if args.install:
        print()
        return do_install(sorted(rendered))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

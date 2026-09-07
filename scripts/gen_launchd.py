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
        It fails three ways, not one: a template whose plist is out of date, a
        template with no plist at all, and a plist whose template has gone. The
        middle one is how three jobs stayed missing for a week, and the last one
        is its mirror, a job that still gets loaded from a definition nobody
        keeps any more.

    python3 .../scripts/gen_launchd.py --install

    ... copies the generated files to ~/Library/LaunchAgents and asks launchd to
        load them. THIS STARTS THE JOBS RUNNING. Nothing else here does.

    python3 .../scripts/gen_launchd.py --uninstall

    ... unloads them and removes the copies. Leaves config/launchd/ alone.

It runs on any Python 3.9 or newer with nothing installed, on purpose: it has to
work on a fresh Mac before the project's own virtual environment exists.

THE TEMPLATE FORMAT. One file per job in config/launchd/templates/, named
<job>.template or <job>.plist.tmpl. Both endings are read, and the reason there
are two is written above discover_templates() below. Sections are marked with
[name] on a line of their own:

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

THE TIME ZONE, WHICH IS THE SUBTLE PART. launchd fires a job on the Mac's own
clock and there is no setting inside a plist that pins a zone. The market keeps
New York hours whatever the Mac thinks.

So every [schedule] line is written in New York time and this script converts
it. It asks the operating system what zone the Mac is actually in, works out the
gap to New York in minutes, moves every wake up by that gap, and stamps the zone
and the gap into the plist it writes. On a Mac in Pacific, "every 5 minutes from
09:30 to 16:00" comes out as 06:30 to 13:00 local, which is the same real
moments. On a Mac in Eastern the gap is zero and the conversion changes nothing.

A wake up pushed across midnight takes its weekday with it, because a job that
fires on Sunday at 22:00 New York is a Monday job in Tokyo.

--check refuses to pass when the stamp no longer matches the Mac, which is how
this stops being a note in the docs that everybody trusts and nobody rereads.
agent/watchdog.py asks the same question every hour and agent/preflight.py asks
it at 09:00, so a zone that moves overnight is caught rather than discovered
from a day of ticks that never happened. All of that lives in
agent/timezone_check.py, which is the one place that knows the answer.

Why this exists: on the night of 2026-09-06 this Mac relinked /etc/localtime to
America/Los_Angeles on its own, because macOS was set to pick the zone from the
current location, and all nine jobs silently became three hours late. Nothing
noticed, because a plist that says "Hour 9" looks correct in every way.

A FILE IN THAT FOLDER MAY NOT BE A TEMPLATE AT ALL, whatever its name suggests.
A whole finished plist with {ROOT} written through it, made by hand, holds no
[schedule] in English for this script to expand, so nothing here can render one.
Any such file is found and named out loud on every run that writes or checks
anything, so that a file this script quietly skips can never go unnoticed again.
--uninstall is the one mode that stays quiet about them, because it is about
what launchd is running and not about what this folder holds.

There were three of those until 2026-09-07: backup_db.plist.tmpl,
deadman.plist.tmpl and sheet_sync.plist.tmpl, each one a job that had never run
and each one saying inside itself that it was held back on purpose. Mo approved
unattended operation on 2026-09-06 and the hub ruled the next day that all three
should be armed, so each was rewritten as a proper <job>.template beside the
other six and the hand made file deleted. The detection stays for the next file
that arrives in the wrong format; today it finds nothing.

This script never loads a job unless you type --install, and it never places an
order under any circumstances.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path


def _load_timezone_check():
    """Import agent/timezone_check.py without this script being a package.

    From THIS FILE's own folder and never from --root. A test runs the generator
    with --root pointing at a throwaway copy of the templates folder, which has
    no agent/ beside it, and the zone arithmetic still has to work there.

    It is stdlib only on the other side, so importing it costs nothing and does
    not break the promise that this script runs on a fresh Mac before the
    virtual environment exists.
    """
    here = Path(__file__).resolve().parent.parent / "agent" / "timezone_check.py"
    spec = importlib.util.spec_from_file_location("agentic_timezone_check", here)
    if spec is None or spec.loader is None:      # pragma: no cover
        raise ImportError(f"cannot load {here}")
    module = importlib.util.module_from_spec(spec)
    # In sys.modules BEFORE it runs. A frozen dataclass in there asks
    # sys.modules for its own module while the class is being built, and gets
    # None and an AttributeError if the module is not registered yet.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tz = _load_timezone_check()

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


def to_local(entries: list[dict[str, int]], shift: int) -> list[dict[str, int]]:
    """New York wake ups moved onto the Mac's clock.

    A constant shift, so it is a one to one mapping and the number of wake ups
    never changes, which is what lets EXPECTED_WAKE_UPS in tests/test_paths.py
    stay a single number per job whatever zone the Mac is in.

    Re-sorted afterwards, because a wrap across midnight moves entries to
    another weekday and two runs of this script must write the same bytes.
    """
    if shift == 0:
        return list(entries)
    moved = [tz.shift_entry(entry["Weekday"], entry["Hour"], entry["Minute"], shift)
             for entry in entries]
    return [{"Weekday": w, "Hour": h, "Minute": m} for w, h, m in sorted(moved)]


def expand_schedule(rules: list[str]) -> list[dict[str, int]]:
    """Every rule added together, duplicates dropped, in clock order per day.

    Sorting matters only so that two runs of this script give byte identical
    files. launchd does not care what order the entries come in.
    """
    seen: set[tuple[int, int, int]] = set()
    for rule in rules:
        seen.update(expand_rule(rule))
    return [{"Weekday": w, "Hour": h, "Minute": m} for w, h, m in sorted(seen)]


# ------------------------------------------------------------------ finding the templates

#: The two endings a template file may have.
#:
#: TWO RATHER THAN ONE ON PURPOSE. Every template is named <job>.template today,
#: but three were named <job>.plist.tmpl until 2026-09-07 and this script was
#: blind to that ending until 2026-09-06, which is how three jobs came to have
#: no plist at all. Both endings stay readable so that a checkout, a note or a
#: journal entry from before the rename still works, and so that the next file
#: dropped in with the other ending is read rather than silently skipped.
TEMPLATE_ENDINGS = (".template", ".plist.tmpl")


def discover_templates(template_dir: Path) -> list[Path]:
    """Every template file in the folder, whichever of the two endings it uses.

    Duplicates dropped and sorted, so two runs of this script go through the
    files in the same order and write the same bytes.

    This globbed "*.template" alone until 2026-09-06, which is how three jobs
    went missing: backup_db, deadman and sheet_sync were all named *.plist.tmpl
    then, so the generator never looked at them, no plist was ever written, and
    nothing ran them. Nothing noticed either, because --check went through the
    list the generator handed it, and a file the generator cannot see is missing
    from that list too. All three are ordinary templates since 2026-09-07.
    """
    found: set[Path] = set()
    for ending in TEMPLATE_ENDINGS:
        found.update(template_dir.glob(f"*{ending}"))
    return sorted(found)


def job_name_from_filename(path: Path) -> str:
    """The job a template file belongs to, worked out from its name alone.

    tick.template is the job "tick", and sheet_sync.plist.tmpl is the job
    "sheet_sync" and not "sheet_sync.plist". Path.stem gets the second one
    wrong, because it only takes one ending off the end.

    A template that parses states its own name in [job], and that is the name
    that counts. This is for the checks, which have to work out which plist
    belongs to a file that may not parse at all.
    """
    name = path.name
    for ending in TEMPLATE_ENDINGS:
        if name.endswith(ending):
            return name[: -len(ending)]
    return path.stem


def is_pre_rendered_plist(path: Path) -> bool:
    """True for the old hand made kind: a finished plist rather than a template.

    Three files in the templates folder were whole plists with {ROOT} written
    through them, from before this script existed, until all three were
    rewritten as proper templates on 2026-09-07. Such a file holds no schedule
    in English to expand, so nothing here can render one, and handing one to
    parse_template only produces "text before the first section" off its XML
    declaration on line 1.

    Nothing in the folder answers yes today. The check stays because the next
    person to drop a finished plist in there should get a file named out loud
    rather than a stack trace. Telling them apart by the first real line rather
    than by the name is what lets a job written in this script's own format be
    read normally whichever of the two endings its file uses.
    """
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        return line.startswith("<?xml")
    return False


def pre_rendered_templates(root: Path) -> list[Path]:
    """The files in the templates folder that this script cannot render."""
    template_dir = root / "config" / "launchd" / "templates"
    return [path for path in discover_templates(template_dir)
            if is_pre_rendered_plist(path)]


def report_pre_rendered(root: Path) -> list[Path]:
    """Name every file nothing was generated from, and hand them back.

    Called by every run that writes or checks. Skipping a file in that folder
    without saying so is the whole of the original bug, so this is the one thing
    here that is never quiet.
    """
    held_back = pre_rendered_templates(root)
    if not held_back:
        return []
    print("\nfound but NOT generated, and not by accident:")
    for path in held_back:
        print(f"  {path}   (job {job_name_from_filename(path)})")
    print("  Each of these is a finished plist with {ROOT} written through it\n"
          "  rather than a template in this script's format, so it carries no\n"
          "  schedule in English for this script to expand and nothing here can\n"
          "  render it. Rewrite it as config/launchd/templates/<job>.template,\n"
          "  taking the program, the environment and the comment straight from\n"
          "  the file and writing the schedule as one English line, then add the\n"
          "  wake up count to EXPECTED_WAKE_UPS in tests/test_paths.py and\n"
          "  delete the hand made file. That is what was done on 2026-09-07 to\n"
          "  the three that used to be listed here.")
    return held_back


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
                  label_prefix: str, claude: str,
                  local_zone: str = tz.MARKET_ZONE,
                  shift: int = 0) -> dict[str, str]:
    """The placeholder table, plus the two values the conversion needs.

    local_zone and shift default to New York and zero, which is the same as no
    conversion at all. That default is for callers that only care about the
    paths, and for the tests that predate the conversion. main() always passes
    the real answers.
    """
    return {
        "{ROOT}": str(root),
        "{VENV_PYTHON}": str(venv_python),
        "{HOME}": str(home),
        "{LABEL_PREFIX}": label_prefix,
        "{CLAUDE}": claude,
        "{LOCAL_ZONE}": local_zone,
        "{SHIFT_MINUTES}": str(shift),
    }


def fill(text: str, subs: dict[str, str]) -> str:
    for placeholder, value in subs.items():
        text = text.replace(placeholder, value)
    return text


def _xml(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def zone_note(local_zone: str, shift: int) -> list[str]:
    """The lines in the generated plist that say what was converted into what.

    Written for whoever opens the file at 09:31 wondering why nothing fired.
    Kept free of any double hyphen, because XML forbids that inside a comment.
    """
    if shift == 0:
        return [
            f"  TIME ZONE: this Mac is in {local_zone}, the market's own zone, so",
            "  the wake up times below are New York times exactly as the template",
            "  writes them. Nothing was converted.",
        ]
    hours = abs(shift) / 60
    way = "behind" if shift < 0 else "ahead of"
    example_w, example_h, example_m = tz.shift_entry(1, 9, 30, shift)
    days = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
            "Saturday")
    return [
        f"  TIME ZONE: this Mac is in {local_zone}, which is {hours:g} hours "
        f"{way}",
        f"  New York. The template's schedule is written in "
        f"{tz.MARKET_ZONE}, and every",
        f"  wake up below has been moved by {shift} minutes so that it lands on the",
        "  New York minute the template asked for. Monday 09:30 New York is "
        f"{days[example_w]}",
        f"  {example_h:02d}:{example_m:02d} on this Mac's clock, and that is what "
        "launchd is given.",
        "",
        "  Move this Mac to another zone and every time below is wrong. Run the",
        "  generator again and it fixes itself. The watchdog and the pre-flight",
        "  both check this every day, so a zone that moves overnight is caught.",
    ]


def render(template: dict, subs: dict[str, str]) -> str:
    """One template plus one set of substitutions to one plist, as text."""
    label = f"{subs['{LABEL_PREFIX}']}.{template['name']}"
    root = subs["{ROOT}"]
    local_zone = subs.get("{LOCAL_ZONE}", tz.MARKET_ZONE)
    shift = int(subs.get("{SHIFT_MINUTES}", "0"))

    # The template's times are New York times. These are the Mac's.
    market_entries = expand_schedule([fill(rule, subs) for rule in template["schedule"]])
    entries = to_local(market_entries, shift)

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
        "  that pins a time zone, so the times below are this Mac's clock, and the",
        "  market keeps New York hours whatever the Mac thinks.",
        "",
    ] + zone_note(local_zone, shift) + [
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

    # The stamp. agent/timezone_check.py reads these two back out of the
    # installed plist and says whether they still describe the Mac, which is
    # what the watchdog, the pre-flight and --check all ask.
    environment = dict(template["environment"])
    environment[tz.ZONE_KEY] = local_zone
    environment[tz.SHIFT_KEY] = str(shift)

    lines += ["", "    <key>EnvironmentVariables</key>", "    <dict>"]
    for key in sorted(environment):
        value = fill(environment[key], subs)
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
        f"    <!-- {len(entries)} wake ups a week, on this Mac's clock. -->",
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
    """Every template rendered, keyed by the file it belongs in.

    The pre-rendered plists are the one thing left out, and report_pre_rendered()
    names each of them on every run so the gap is never silent.
    """
    template_dir = root / "config" / "launchd" / "templates"
    templates = discover_templates(template_dir)
    if not templates:
        raise TemplateError(f"no templates found in {template_dir}")
    written: dict[Path, str] = {}
    for path in templates:
        if is_pre_rendered_plist(path):
            continue
        job = parse_template(path)
        text = render(job, subs)
        plistlib.loads(text.encode("utf-8"))  # refuse to write anything unreadable
        written[out_dir / f"{subs['{LABEL_PREFIX}']}.{job['name']}.plist"] = text
    return written


def check_zone(out_dir: Path, label_prefix: str, local_zone: str, shift: int,
               root: Path, skip: set[str] | None = None) -> int:
    """Do the plists on disk still describe this Mac's clock? Returns problems.

    Read out of the files rather than worked out again, because the stamp is
    the only record of what the times in a plist actually mean. A plist with no
    stamp was written before the conversion existed and is reported as needing
    a regeneration rather than as a fault, which is the same restraint the
    watchdog shows.
    """
    if not out_dir.is_dir():
        return 0
    # A plist rendered by hand from a finished plist in the templates folder
    # carries no stamp and never will, because nothing here wrote it. Judging
    # it would mean telling you to regenerate a file this script cannot make.
    ignore = skip or set()
    plists = [path for path in sorted(out_dir.glob(f"{label_prefix}.*.plist"))
              if path.name not in ignore]
    if not plists:
        return 0

    unstamped = [path for path in plists if tz.read_stamp(path) is None]
    stamps = {path: tz.read_stamp(path) for path in plists}
    wrong = {path: stamp for path, stamp in stamps.items()
             if stamp and (stamp.zone != local_zone or stamp.shift != shift)}

    if unstamped:
        print(f"NO ZONE  {len(unstamped)} plist(s) carry no time zone stamp, so "
              "there is no way to tell")
        print("         what clock their wake up times are on. Generate again.")
        for path in unstamped[:3]:
            print(f"         {path}")
        return 1

    if not wrong:
        print(f"zone     {local_zone}, {shift} minutes from {tz.MARKET_ZONE}, "
              "matches every plist")
        return 0

    example = sorted(wrong.values(), key=lambda s: s.zone)[0]
    print(f"WRONG ZONE  the plists were written for {example.zone} at "
          f"{example.shift} minutes from {tz.MARKET_ZONE},")
    print(f"            and this Mac is now in {local_zone} at {shift} minutes. "
          f"{len(wrong)} of {len(plists)}")
    print("            plist(s) are firing at the wrong minute of the day.")
    print(f"            Fix it, which also loads them:  {tz.fix_command(root)}")
    return 1


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
    parser.add_argument("--local-zone", default=None,
                        help="the zone to convert the New York schedules into "
                             "(default: whatever /etc/localtime says this Mac "
                             "is set to). Only pass this to see what another "
                             "machine's files would look like.")
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

    # The zone the wake up times get converted into, and the gap in minutes
    # that does the converting. Asked once here so that every plist in one run
    # carries the same stamp even if the run straddles a clock change.
    try:
        local_zone = args.local_zone or tz.system_zone_name()
        shift = tz.shift_minutes(local_zone)
    except tz.ZoneUnknown as exc:
        print(f"ERROR: {exc}\n\nThis script will not guess a time zone. Every "
              "wake up time in every plist depends\non the answer, and a wrong "
              "guess is a day of ticks that never happened.", file=sys.stderr)
        return 2

    subs = substitutions(root, venv_python, home, args.label_prefix, claude,
                         local_zone, shift)

    try:
        rendered = generate(root, out_dir, subs)
    except TemplateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.uninstall:
        return do_uninstall(sorted(rendered))

    if args.check:
        problems = 0
        template_dir = root / "config" / "launchd" / "templates"

        # The zone first, on its own, before any file is compared. A Mac that
        # has moved zone makes every plist differ, and "DIFFERS, no longer
        # matches its template" would send you looking at a template that is
        # perfectly fine. This says what actually happened.
        hand_made = {f"{args.label_prefix}.{job_name_from_filename(path)}.plist"
                     for path in pre_rendered_templates(root)}
        problems += check_zone(out_dir, args.label_prefix, local_zone, shift,
                               root, hand_made)

        # Start from the templates, not from the plists on disk. A template that
        # nobody ever generated has no plist to compare, so a check that walks
        # the plists cannot see it, and that is exactly how three missing jobs
        # went unnoticed. Re-parsing here is safe: generate() above has already
        # been through the same files, so a template that could not be read has
        # stopped this run before now with its own message.
        sources: dict[Path, Path] = {}      # the plist wanted, and its template
        for path in discover_templates(template_dir):
            if is_pre_rendered_plist(path):
                continue
            name = parse_template(path)["name"]
            sources[out_dir / f"{args.label_prefix}.{name}.plist"] = path

        for plist in sorted(sources):
            template = sources[plist]
            if not plist.exists():
                print(f"NO PLIST {template}")
                print(f"         was never generated. It wants {plist}")
                problems += 1
            elif plist.read_text(encoding="utf-8") != rendered[plist]:
                print(f"DIFFERS  {plist}")
                print(f"         no longer matches {template}")
                problems += 1
            else:
                print(f"same     {plist}")

        # The mirror image of a missing plist: a plist whose template has gone.
        # It is worse than untidy, because --install still copies it and launchd
        # still runs it, so a job goes on firing from a definition nobody keeps.
        # Only this run's own label prefix is looked at, so generating under a
        # different prefix does not condemn the real files sitting beside it.
        # A held-back file counts as a template here even though nothing renders
        # it. Each of the three that used to be here told you to render it by
        # hand with sed into config/launchd/, so a hand made plist had a
        # definition behind it and was not an orphan. Without this, --check
        # would have told you to delete the dead man's handle three lines above
        # naming the file that made it.
        wanted = {plist.name for plist in sources} | {
            f"{args.label_prefix}.{job_name_from_filename(path)}.plist"
            for path in pre_rendered_templates(root)}
        if out_dir.is_dir():
            for plist in sorted(out_dir.glob(f"{args.label_prefix}.*.plist")):
                if plist.name not in wanted:
                    print(f"ORPHAN   {plist}")
                    print(f"         nothing in {template_dir} makes this file "
                          "any more")
                    problems += 1

        report_pre_rendered(root)

        if problems:
            print(f"\n{problems} problem(s) above. A plist that is missing or "
                  "out of date is fixed by\nrunning this script without --check, "
                  "and a wrong time zone by running it\nwith --install, which "
                  "rewrites them and reloads them in one step. An orphan\nhas to "
                  "be deleted by hand, on purpose, because a loaded job's file is "
                  "not\nsomething this script should remove behind your back.")
        return 1 if problems else 0

    out_dir.mkdir(parents=True, exist_ok=True)
    for path, text in sorted(rendered.items()):
        path.write_text(text, encoding="utf-8")
        count = text.count("<key>Weekday</key>")
        print(f"wrote {path}  ({count} wake ups a week)")

    report_pre_rendered(root)

    print(f"\nroot:        {root}")
    print(f"venv python: {venv_python}")
    print(f"claude:      {claude}")
    print(f"this Mac:    {local_zone}")
    if shift:
        moved = tz.shift_entry(1, 9, 30, shift)
        print(f"converted:   every wake up moved {shift} minutes from "
              f"{tz.MARKET_ZONE}, so 09:30")
        print(f"             New York fires at {moved[1]:02d}:{moved[2]:02d} on "
              "this Mac's clock")
    else:
        print(f"converted:   nothing, this Mac is already on {tz.MARKET_ZONE}")
    print("\nNothing has been loaded. To load, and only when you mean it:")
    print(f"  python3 {root}/scripts/gen_launchd.py --install")

    if args.install:
        print()
        return do_install(sorted(rendered))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

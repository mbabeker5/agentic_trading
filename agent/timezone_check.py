"""The one place that knows what time zone the launchd jobs were built for.

    /Users/mtalib/workspace_repos/personal_repo/agentic_trading/agent/timezone_check.py

THE PROBLEM THIS SOLVES
-----------------------
launchd fires a job on the Mac's own clock. There is no setting inside a plist
that pins a time zone, and there never has been. The market keeps New York
hours whatever the Mac thinks.

For the first week of this project that was a note in the docs saying "keep the
Mac on Eastern" and nothing more. Then on the night of 2026-09-06 the Mac
relinked /etc/localtime to America/Los_Angeles on its own, because macOS has
"Set time zone automatically using your current location" switched on, and every
one of the nine jobs silently became three hours late: the 09:30 tick would have
fired at 12:30 New York, after the open and after the pick. Nothing noticed,
because a plist that says "Hour 9" looks correct in every way.

So the times are no longer written into the plists as New York times and hoped
over. The templates still say New York, because that is the only sane way to
write a market schedule, and scripts/gen_launchd.py converts every wake up into
the Mac's current zone as it writes the plist. It stamps the zone it converted
for into each plist, and this module is what reads that stamp back and says
whether it still holds.

Three callers:

    scripts/gen_launchd.py      converts, stamps, and refuses to pass --check
                                when the stamp no longer matches the Mac
    agent/watchdog.py           the time_zone check, hourly and every five
                                minutes in market hours
    agent/preflight.py          the same question at 09:00, where a wrong
                                answer writes NO_TRADE_TODAY

WHY AN OFFSET AND NOT A ZONE NAME ALONE
---------------------------------------
What actually matters is the gap between the Mac's clock and New York's, in
minutes. Both United States zones change their clocks on the same day, so while
the Mac is anywhere in the US that gap is fixed all year and a plist generated
in September is still right in January.

That is not true of a zone outside the US. The United Kingdom ends summer time
on the last Sunday in October and the US on the first Sunday in November, so for
one week each autumn London is four hours from New York rather than five, and for
three weeks each spring it is four rather than five again. A plist generated
outside those windows is an hour wrong inside them.

So the stamp records both the zone name and the gap in minutes, and the check
fails if either has moved. On a US Mac that means it fires when the Mac changes
zone and never otherwise. On a London Mac it also fires on the two days a year
the gap changes, which is exactly when the plists need rewriting.

NOTHING HERE TALKS TO THE NETWORK, THE BROKER OR THE DATABASE. It reads
/etc/localtime, the zoneinfo database that ships with the operating system, and
the plist files. It runs on any Python 3.9 or newer with nothing installed,
because scripts/gen_launchd.py has to work on a fresh Mac before this project's
virtual environment exists.
"""
from __future__ import annotations

import os
import plistlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:                                    # Python 3.9 and newer, standard library
    from zoneinfo import ZoneInfo
except ImportError:                     # pragma: no cover - 3.8 and older
    ZoneInfo = None                     # type: ignore[assignment]

#: The market's zone. Every schedule line in config/launchd/templates/ is
#: written in this zone and nothing else, on purpose: a template is read by
#: people and the market opens at 09:30 New York wherever the Mac is sitting.
MARKET_ZONE = "America/New_York"

#: Where the operating system keeps the answer to "what zone is this Mac in".
#: A symlink into the zoneinfo database, so its target carries the zone name.
LOCALTIME_LINK = Path("/etc/localtime")

#: The two environment variables scripts/gen_launchd.py writes into every plist
#: it generates. They are the stamp: the zone the wake up times were converted
#: into, and the gap from New York in minutes that was used to convert them.
#:
#: EnvironmentVariables rather than a key of their own, for two reasons. launchd
#: is documented to accept this key and nobody has to wonder whether it will
#: refuse an invented one, and the running job can read its own stamp out of its
#: own environment if it ever needs to.
ZONE_KEY = "AGENTIC_TRADING_PLIST_ZONE"
SHIFT_KEY = "AGENTIC_TRADING_PLIST_SHIFT_MINUTES"

DEFAULT_LABEL_PREFIX = "com.mtalib.agentic-trading"


class ZoneUnknown(Exception):
    """The Mac's own time zone could not be worked out. Nothing should guess."""


# ------------------------------------------------------------------ what zone is this Mac in

def system_zone_name(link: Path | None = None) -> str:
    """The zone this Mac is set to, for example "America/Los_Angeles".

    From /etc/localtime, which macOS keeps as a symlink into the zoneinfo
    database, so the tail of the target is the zone name. On this Mac tonight
    that target is /var/db/timezone/zoneinfo/America/Los_Angeles.

    The TZ environment variable is deliberately NOT consulted. Every plist in
    this project sets TZ to America/New_York so the scripts think in market
    time, so a check that read TZ would ask a job about the very thing the job
    was told to pretend, and always get "Eastern, everything is fine".
    """
    path = link or LOCALTIME_LINK
    try:
        target = os.readlink(str(path))
    except OSError as exc:
        raise ZoneUnknown(f"{path} is not a symlink into the zone database: {exc}")
    marker = "/zoneinfo/"
    if marker not in target:
        raise ZoneUnknown(
            f"{path} points at {target}, which has no /zoneinfo/ in it, so the "
            "zone name cannot be read out of it")
    name = target.split(marker, 1)[1].strip("/")
    if not name:
        raise ZoneUnknown(f"{path} points at {target}, which names no zone")
    return name


def _zone(name: str) -> ZoneInfo:
    if ZoneInfo is None:                # pragma: no cover - 3.8 and older
        raise ZoneUnknown(
            "this Python has no zoneinfo module, so no time zone arithmetic is "
            "possible. Python 3.9 or newer is needed.")
    try:
        return ZoneInfo(name)
    except Exception as exc:            # ZoneInfoNotFoundError and friends
        raise ZoneUnknown(f"{name!r} is not a zone this Mac knows about: {exc}")


def shift_minutes(local_zone: str, when: datetime | None = None) -> int:
    """How far the Mac's clock is ahead of New York's, in minutes.

    Negative when the Mac is behind New York, which is the ordinary case in
    North America. Pacific in September is 180 minutes behind Eastern, so this
    returns -180 and 09:30 New York becomes 06:30 on the Mac's clock.

    `when` is the moment the question is asked about, and it matters: the answer
    is a property of a date as well as of two zones. It defaults to now.
    """
    moment = (when or datetime.now(timezone.utc)).astimezone(timezone.utc)
    here = moment.astimezone(_zone(local_zone)).utcoffset()
    market = moment.astimezone(_zone(MARKET_ZONE)).utcoffset()
    if here is None or market is None:  # pragma: no cover - both are aware
        raise ZoneUnknown("a zone answered with no offset at all")
    return int((here - market).total_seconds() // 60)


def shift_entry(weekday: int, hour: int, minute: int,
                minutes: int) -> tuple[int, int, int]:
    """One launchd calendar entry moved by a number of minutes, day wrap included.

    launchd counts Sunday as 0 and Saturday as 6. Moving a time across midnight
    has to move the weekday with it or the job fires on the wrong day, which is
    the whole reason this is a function rather than one line of arithmetic. A
    London Mac shifts New York forward five hours, so the 17:00 database backup
    becomes 22:00 the same evening; a Tokyo Mac shifts it forward thirteen, so
    the same backup becomes 06:00 the following morning and Sunday's copy is
    taken on Monday.
    """
    total = hour * 60 + minute + minutes
    days, total = divmod(total, 24 * 60)
    return (weekday + days) % 7, total // 60, total % 60


# ------------------------------------------------------------------ what the plists say

@dataclass(frozen=True)
class Stamp:
    """What one generated plist says it was built for."""
    zone: str
    shift: int
    source: Path


def read_stamp(plist: Path) -> Stamp | None:
    """The zone and offset stamped into one plist, or None if it carries none.

    None is the honest answer for a plist written before this stamping existed,
    and every caller treats it as "cannot tell" rather than as a fault.
    """
    try:
        loaded = plistlib.loads(plist.read_bytes())
    except Exception:
        return None
    environment = loaded.get("EnvironmentVariables") or {}
    zone = environment.get(ZONE_KEY)
    raw = environment.get(SHIFT_KEY)
    if not zone or raw is None:
        return None
    try:
        shift = int(str(raw))
    except ValueError:
        return None
    return Stamp(zone=str(zone), shift=shift, source=plist)


def stamp_search_paths(root: Path, label_prefix: str = DEFAULT_LABEL_PREFIX,
                       home: Path | None = None) -> list[Path]:
    """Where to look for a generated plist, best answer first.

    ~/Library/LaunchAgents before config/launchd/, because launchd runs the copy
    in the first folder and the question being asked is about what is actually
    firing. The repo copy is the fallback so that the checks still say something
    useful on a machine where nothing has been installed yet.
    """
    agents = (home or Path.home()) / "Library" / "LaunchAgents"
    found = sorted(agents.glob(f"{label_prefix}.*.plist"))
    if found:
        return found
    return sorted((root / "config" / "launchd").glob(f"{label_prefix}.*.plist"))


# ------------------------------------------------------------------ the check itself

@dataclass(frozen=True)
class Verdict:
    """The answer to "are the loaded jobs still pointing at the right minutes".

    ok        False only when something is genuinely wrong. A machine with no
              plists at all is ok and says so in detail, the same restraint the
              watchdog's heartbeat check shows when the tick job is not loaded.
    detail    one line, written for a person reading an alert on a phone.
    fix       the command that puts it right, or an empty string when there is
              nothing to put right.
    """
    ok: bool
    detail: str
    fix: str = ""
    system_zone: str = ""
    stamped_zone: str = ""
    current_shift: int | None = None
    stamped_shift: int | None = None

    @property
    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "fix": self.fix,
            "system_zone": self.system_zone,
            "stamped_zone": self.stamped_zone,
            "current_shift": self.current_shift,
            "stamped_shift": self.stamped_shift,
        }


def fix_command(root: Path) -> str:
    return f"python3 {root}/scripts/gen_launchd.py --install"


def check(root: Path, *, when: datetime | None = None,
          label_prefix: str = DEFAULT_LABEL_PREFIX,
          home: Path | None = None,
          link: Path | None = None) -> Verdict:
    """Do the installed launchd jobs still fire at the right New York minute?

    Four ways to answer:

    1. No plist anywhere. Nothing is loaded, so nothing is wrong. ok.
    2. Plists with no stamp. Written before this existed, so no opinion can be
       formed. ok, and the detail says to generate again.
    3. The stamp matches the Mac. ok, and the detail names the zone so a log
       line is worth reading.
    4. The stamp does not match. NOT ok. Either the Mac has changed zone or the
       gap to New York has changed under it, and every wake up in every plist is
       now at the wrong minute until the generator is run again.
    """
    fix = fix_command(root)

    try:
        here = system_zone_name(link)
    except ZoneUnknown as exc:
        return Verdict(False, f"cannot tell what zone this Mac is in: {exc}", fix)

    plists = stamp_search_paths(root, label_prefix, home)
    if not plists:
        return Verdict(True, f"no launchd job is installed, so there is nothing "
                             f"to be at the wrong minute. This Mac is in {here}.",
                       system_zone=here)

    stamps = [stamp for stamp in (read_stamp(path) for path in plists) if stamp]
    if not stamps:
        return Verdict(True,
                       f"the installed jobs carry no time zone stamp, so they "
                       f"were written before the conversion existed and this "
                       f"check has no opinion. This Mac is in {here}.",
                       fix, system_zone=here)

    try:
        current = shift_minutes(here, when)
    except ZoneUnknown as exc:
        return Verdict(False, f"cannot work out the gap to New York: {exc}", fix)

    zones = sorted({stamp.zone for stamp in stamps})
    shifts = sorted({stamp.shift for stamp in stamps})
    if len(zones) > 1 or len(shifts) > 1:
        return Verdict(
            False,
            "the installed jobs disagree with each other about the time zone "
            f"they were built for: {', '.join(zones)} at "
            f"{', '.join(str(s) for s in shifts)} minutes from New York. Some "
            "of them were generated on a different day from the others, so "
            "some are firing at the wrong minute.",
            fix, system_zone=here, stamped_zone=zones[0],
            current_shift=current, stamped_shift=shifts[0])

    stamped_zone, stamped_shift = zones[0], shifts[0]

    if stamped_zone != here:
        return Verdict(
            False,
            f"this Mac has moved from {stamped_zone} to {here} since the launchd "
            f"jobs were written. They fire on the Mac's clock, so every wake up "
            f"is now {abs(current - stamped_shift)} minutes out and the market "
            "hours ones are pointing at the wrong part of the day.",
            fix, system_zone=here, stamped_zone=stamped_zone,
            current_shift=current, stamped_shift=stamped_shift)

    if stamped_shift != current:
        return Verdict(
            False,
            f"this Mac is still in {here}, but the gap to New York has changed "
            f"from {stamped_shift} minutes to {current}, so summer time started "
            "or ended on a different day here than it did in New York. Every "
            "wake up is an hour out until the jobs are written again.",
            fix, system_zone=here, stamped_zone=stamped_zone,
            current_shift=current, stamped_shift=stamped_shift)

    if current == 0:
        detail = (f"this Mac is in {here}, the same clock as the market, so the "
                  "launchd wake up times are New York times as written.")
    else:
        detail = (f"this Mac is in {here}, {current} minutes from New York, and "
                  "the launchd jobs were written for exactly that, so they fire "
                  "at the right New York minute.")
    return Verdict(True, detail, system_zone=here, stamped_zone=stamped_zone,
                   current_shift=current, stamped_shift=stamped_shift)

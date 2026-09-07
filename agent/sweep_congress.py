#!/usr/bin/env python3
"""Congress disclosure sweep for the agentic trading project.

Reads the Periodic Transaction Reports that members of the US House and Senate
must file under the STOCK Act, keeps the purchases, scores them by size band,
committee link and how many members bought the same name, and writes a
shortlist of at most fifteen tickers to a JSON file. Claude reads that file at
9:45 AM and decides which names, if any, are worth buying.

This script only reads public disclosure data over plain HTTPS. It never
connects to IB Gateway and it contains no order code of any kind.

Run it like this, from the project folder:

    venv312/bin/python agent/sweep_congress.py \
        --since 2026-08-01 \
        --out output/congress_shortlist_2026-09-06.json

Exit code is 0 whenever at least one source answered, even if nothing survived
the filters. It is 1 only when every source was unreachable.

Where the data comes from, checked on 2026-09-06
------------------------------------------------
The community mirrors this project was originally going to use are gone. Both
House Stock Watcher and Senate Stock Watcher now answer "Access Denied" on
their S3 buckets, and the GitHub repository behind the House one has been
deleted. Capitol Trades' own backend was returning a server error the same day.
So this script goes straight to the two official sources instead, which turn
out to be healthier than the mirrors that were meant to save us the work:

1. The House Clerk publishes a ZIP file of every financial filing for the year
   at disclosures-clerk.house.gov. Inside is a tab separated index listing the
   member, the filing type and the date the filing was received. Each Periodic
   Transaction Report in that index has a PDF, and since those are filed
   electronically the PDFs carry a real text layer, so the trades can be read
   out of them without any guesswork about handwriting.

2. The Senate runs a search site at efdsearch.senate.gov. It asks you to accept
   a terms page first, then it answers with clean JSON listing the filings, and
   each electronically filed report is a tidy HTML table of transactions.

3. A volunteer rebuild of the old House Stock Watcher feed is kept as a last
   resort, at raw.githubusercontent.com under TattooedHead. It is one JSON file,
   refreshed daily from the same Clerk filings, covering the House only. Checked
   against this script on 17 shared filings it agreed on 12, and lost or invented
   rows on the other five, so it is a safety net and never a primary source.
   Capitol Trades was the intended fallback but is unreachable, so it is not
   implemented: its site answers every request with a bot challenge behind an
   HTTP 429, and its own data service returns HTTP 503 on every path.

Senators who still file on paper show up in the Senate list as "paper" filings.
Those are scans with no text, so they are counted and reported but not read.
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import io
import json
import logging
import re
import sys
import time
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

try:
    import yaml
except ImportError:  # pragma: no cover - pyyaml is in requirements-312.txt
    yaml = None

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - pypdf is in requirements-312.txt
    PdfReader = None


_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from paths import project_root  # noqa: E402

PROJECT_ROOT = project_root()
DEFAULT_CACHE_DIR = PROJECT_ROOT / "output" / "congress_cache"

# Be a polite visitor. These are public government sites paid for by taxpayers,
# but they are not built for heavy traffic, so the script identifies itself and
# keeps the number of parallel requests modest.
USER_AGENT = (
    "agentic-trading congress sweep (personal research, contact mo@thetaste.ai)"
)
HTTP_TIMEOUT = 45
DOWNLOAD_WORKERS = 6
HTTP_RETRIES = 3

HOUSE_INDEX_URL = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.ZIP"
HOUSE_PTR_PDF_URL = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{doc_id}.pdf"
HOUSE_VIEW_URL = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{doc_id}.pdf"

SENATE_BASE = "https://efdsearch.senate.gov"
SENATE_HOME = SENATE_BASE + "/search/home/"
SENATE_SEARCH = SENATE_BASE + "/search/"
SENATE_DATA = SENATE_BASE + "/search/report/data/"
SENATE_PTR_REPORT_TYPE = "[11]"  # the site's own code for a Periodic Transaction Report

# An independent GitHub feed, refreshed daily by its own scraper from the same
# Clerk filings this script reads directly. Only used when the official sources
# are unreachable. See the notes on fetch_mirror for why it is not trusted
# further than that.
#
# NOT a mirror or a rebuild of the old House Stock Watcher feed, whatever the
# name of this constant suggests. It shares a repository name with it and
# nothing else: its own scraper reads disclosures-clerk.house.gov directly. The
# constant keeps the old name because renaming it would touch code that has
# nothing to do with the correction. Checked 2026-09-06.
MIRROR_URL = (
    "https://raw.githubusercontent.com/TattooedHead/house-stock-watcher-data/"
    "main/data/all_transactions.json"
)

LEGISLATORS_BASE = (
    "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/"
)
LEGISLATOR_FILES = (
    "legislators-current.yaml",
    "committee-membership-current.yaml",
    "committees-current.yaml",
)

# How long a downloaded reference file is trusted before it is fetched again.
# Filings never change once filed, so their PDFs are cached forever. The index
# and the committee lists do change, so they get a short life.
INDEX_CACHE_HOURS = 6

# Strategy numbers, from docs/STRATEGY_CONGRESS.md.
STALENESS_LIMIT_DAYS = 60      # skip a trade that was already this old when disclosed
CROWD_WINDOW_DAYS = 30         # how close together two members' buys must be to count
SOURCE_STALE_AFTER_DAYS = 3    # flag the source if its newest filing is older than this
MAX_CANDIDATES = 15
MIN_BAND_ALONE = 2             # $15,001 to $50,000 is band 2, and qualifies on its own
MIN_BAND_WITH_CROWD = 1        # $1,001 to $15,000 needs two or more members

log = logging.getLogger("sweep_congress")


# ---------------------------------------------------------------------------
# Disclosed amount bands
# ---------------------------------------------------------------------------

# Members disclose a range, never an amount. These are the ranges the forms
# offer, in order, smallest first. The index is what the score uses; the
# midpoint is only there to give a rough sense of size in dollars.
AMOUNT_BANDS: tuple[tuple[int, str, int, int | None], ...] = (
    (1, "$1,001 - $15,000", 1_001, 15_000),
    (2, "$15,001 - $50,000", 15_001, 50_000),
    (3, "$50,001 - $100,000", 50_001, 100_000),
    (4, "$100,001 - $250,000", 100_001, 250_000),
    (5, "$250,001 - $500,000", 250_001, 500_000),
    (6, "$500,001 - $1,000,000", 500_001, 1_000_000),
    (7, "$1,000,001 - $5,000,000", 1_000_001, 5_000_000),
    (8, "$5,000,001 - $25,000,000", 5_000_001, 25_000_000),
    (9, "$25,000,001 - $50,000,000", 25_000_001, 50_000_000),
    (10, "Over $50,000,000", 50_000_001, None),
)
BAND_BY_LOW = {low: band for band, _label, low, _high in AMOUNT_BANDS}


def parse_amount_band(text: str) -> tuple[int | None, str, float | None]:
    """Turn a disclosed range like "$15,001 - $50,000" into a band and midpoint.

    Returns the band index (1 is smallest), a tidy label, and the midpoint in
    dollars. Anything unrecognisable comes back as (None, original text, None)
    rather than raising, because one odd row should never stop the sweep.
    """
    tidy = re.sub(r"\s+", " ", (text or "")).strip()
    figures = [int(f.replace(",", "")) for f in re.findall(r"\$\s?([\d,]+)", tidy)]
    if not figures:
        return None, tidy, None

    open_ended = bool(re.search(r"\bover\b", tidy, re.IGNORECASE)) and len(figures) == 1

    if open_ended:
        # A form that says "Over $1,000,000" means anything above that line, so
        # the right band is the one that starts just past it. Some spouse and
        # dependent forms use this shorter set of ranges.
        floor = figures[0]
        band = AMOUNT_BANDS[-1][0]
        for index, _label, band_low, _band_high in AMOUNT_BANDS:
            if band_low > floor:
                band = index
                break
        # Keep what was actually disclosed as the label, and take the floor as
        # the midpoint. It understates the size, which is the safe direction.
        return band, tidy, float(floor)

    low = figures[0]
    high = figures[1] if len(figures) > 1 else None

    band = BAND_BY_LOW.get(low)
    if band is None:
        # An unfamiliar range. Fall back to whichever standard band the lower
        # figure sits in.
        band = 1
        for index, _label, band_low, _band_high in AMOUNT_BANDS:
            if low >= band_low:
                band = index

    label = next((lbl for idx, lbl, _l, _h in AMOUNT_BANDS if idx == band), tidy)
    midpoint = float(low) if high is None else round((low + high) / 2.0)
    return band, label, midpoint


# ---------------------------------------------------------------------------
# Committees and the sectors they touch
# ---------------------------------------------------------------------------

# The codes are the ones the unitedstates/congress-legislators project uses
# (they call them thomas_id). HS is a House committee, SS a Senate one, HL and
# SL the select committees.
COMMITTEE_SECTORS: dict[str, tuple[str, ...]] = {
    # Armed Services, both chambers, writes the defence budget.
    "HSAS": ("defense", "aerospace"),
    "SSAS": ("defense", "aerospace"),
    # House Energy and Commerce has an unusually wide brief.
    "HSIF": ("health care", "pharma", "energy", "telecom"),
    # Financial Services in the House, Banking in the Senate.
    "HSBA": ("financials",),
    "SSBK": ("financials",),
    # Agriculture.
    "HSAG": ("agriculture", "food"),
    "SSAF": ("agriculture", "food"),
    # Transport. The House calls it Transportation and Infrastructure.
    "HSPW": ("airlines", "rail", "autos"),
    # Intelligence and homeland security.
    "HLIG": ("defense", "cyber"),
    "SLIN": ("defense", "cyber"),
    "HSHM": ("defense", "cyber"),
    "SSGA": ("defense", "cyber"),
    # Judiciary handles antitrust, Senate Commerce handles tech regulation.
    "HSJU": ("technology",),
    "SSJU": ("technology",),
    "SSCM": ("technology", "airlines", "rail", "autos"),
    # Natural Resources in the House, Energy and Natural Resources in the Senate.
    "HSII": ("oil gas", "mining"),
    "SSEG": ("oil gas", "mining", "energy"),
    # Veterans Affairs buys a great deal of health care.
    "HSVR": ("health care",),
    "SSVA": ("health care",),
    # Senate health committee, the closest match to House Energy and Commerce.
    "SSHR": ("health care", "pharma"),
}

# Plain-language names, used in the output so a reader does not have to know
# what HSAS means.
COMMITTEE_NAMES: dict[str, str] = {
    "HSAS": "House Armed Services",
    "SSAS": "Senate Armed Services",
    "HSIF": "House Energy and Commerce",
    "HSBA": "House Financial Services",
    "SSBK": "Senate Banking",
    "HSAG": "House Agriculture",
    "SSAF": "Senate Agriculture",
    "HSPW": "House Transportation and Infrastructure",
    "HLIG": "House Intelligence",
    "SLIN": "Senate Intelligence",
    "HSHM": "House Homeland Security",
    "SSGA": "Senate Homeland Security and Governmental Affairs",
    "HSJU": "House Judiciary",
    "SSJU": "Senate Judiciary",
    "SSCM": "Senate Commerce, Science and Transportation",
    "HSII": "House Natural Resources",
    "SSEG": "Senate Energy and Natural Resources",
    "HSVR": "House Veterans Affairs",
    "SSVA": "Senate Veterans Affairs",
    "SSHR": "Senate Health, Education, Labor and Pensions",
}

# Words that give away what business a company is in, read off the name the
# member disclosed. This is a stopgap, not a sector classification. The real
# sector comes from IBKR contract details once the loop looks the ticker up,
# which is why every candidate ships with ticker_sector set to null. Until then
# this is enough to tell a defence contractor from a soft drinks maker.
SECTOR_KEYWORDS: dict[str, tuple[str, ...]] = {
    "defense": (
        "lockheed", "raytheon", "rtx corp", "northrop", "general dynamics",
        "l3harris", "huntington ingalls", "leidos", "booz allen", "textron",
        "kratos", "aerovironment", "palantir", "axon", "curtiss-wright",
        "mercury systems", "caci", "parsons corp", "defense", "defence",
    ),
    "aerospace": (
        "boeing", "aerospace", "heico", "transdigm", "howmet", "spirit aero",
        "rocket lab", "aerojet", "airbus", "gd corp",
    ),
    "health care": (
        "unitedhealth", "elevance", "cigna", "humana", "centene", "molina",
        "mckesson", "cardinal health", "cencora", "cvs health", "medtronic",
        "abbott", "stryker", "becton", "baxter", "steris", "danaher",
        "thermo fisher", "intuitive surgical", "edwards lifesciences",
        "boston scientific", "zimmer", "hca healthcare", "health", "medical",
        "hospital", "dexcom", "idexx", "resmed",
    ),
    "pharma": (
        "pfizer", "merck", "eli lilly", "lilly", "bristol-myers", "abbvie",
        "amgen", "gilead", "biogen", "regeneron", "vertex pharm", "moderna",
        "novartis", "astrazeneca", "glaxo", "sanofi", "johnson & johnson",
        "novo nordisk", "pharma", "therapeutics", "biosciences", "biotech",
        "viatris", "zoetis", "alnylam", "united therapeutics",
    ),
    "energy": (
        "exxon", "chevron", "conocophillips", "occidental", "eog resources",
        "devon energy", "diamondback", "marathon", "phillips 66", "valero",
        "schlumberger", "slb ", "halliburton", "baker hughes", "kinder morgan",
        "williams companies", "energy", "petroleum", "nextera", "duke energy",
        "southern company", "dominion", "exelon", "aes corp", "vistra",
        "constellation energy", "utilities", "electric",
    ),
    "oil gas": (
        "exxon", "chevron", "conocophillips", "occidental", "eog resources",
        "devon energy", "diamondback", "marathon oil", "marathon petroleum",
        "phillips 66", "valero", "schlumberger", "halliburton", "baker hughes",
        "kinder morgan", "williams companies", "oneok", "cheniere",
        "petroleum", "oil", "natural gas", "midstream", "pipeline", "drilling",
    ),
    "mining": (
        "newmont", "barrick", "freeport", "southern copper", "alcoa",
        "cleveland-cliffs", "nucor", "steel dynamics", "mosaic", "albemarle",
        "mining", "minerals", "gold corp", "copper", "steel", "metals",
    ),
    "telecom": (
        "at&t", "verizon", "t-mobile", "comcast", "charter communications",
        "lumen", "frontier communications", "telecom", "communications",
        "viasat", "echostar", "iridium", "american tower", "crown castle",
    ),
    "financials": (
        "jpmorgan", "bank of america", "wells fargo", "citigroup", "goldman",
        "morgan stanley", "charles schwab", "blackrock", "blackstone", "kkr",
        "apollo global", "ares management", "american express", "visa inc",
        "mastercard", "paypal", "capital one", "truist", "pnc financial",
        "us bancorp", "berkshire hathaway", "bank", "bancorp", "financial",
        "insurance", "allstate", "progressive corp", "chubb", "travelers",
        "marsh &", "aon plc", "s&p global", "moody's", "nasdaq inc", "cme group",
        "intercontinental exchange",
    ),
    "agriculture": (
        "deere", "corteva", "mosaic", "nutrien", "cf industries",
        "archer-daniels", "archer daniels", "bunge", "fmc corp", "agri",
        "farm", "tractor supply", "agco",
    ),
    "food": (
        "kraft", "general mills", "kellanova", "kellogg", "hormel", "tyson",
        "conagra", "campbell", "hershey", "mondelez", "pepsico", "coca-cola",
        "sysco", "food", "beverage", "keurig", "monster beverage",
        "constellation brands", "anheuser-busch", "mccormick",
    ),
    "airlines": (
        "delta air", "united airlines", "american airlines", "southwest airlines",
        "alaska air", "jetblue", "airlines", "air lines", "boeing",
    ),
    "rail": (
        "union pacific", "csx corp", "norfolk southern", "canadian national",
        "canadian pacific", "railway", "railroad", "westinghouse air brake",
        "wabtec", "greenbrier", "trinity industries",
    ),
    "autos": (
        "ford motor", "general motors", "tesla", "rivian", "lucid group",
        "stellantis", "aptiv", "borgwarner", "magna international", "autoliv",
        "motor company", "automotive", "paccar", "cummins", "harley-davidson",
    ),
    "cyber": (
        "crowdstrike", "palo alto networks", "fortinet", "zscaler", "okta",
        "cloudflare", "sentinelone", "rapid7", "tenable", "cyber", "varonis",
        "check point", "qualys", "gen digital",
    ),
    "technology": (
        "apple inc", "microsoft", "alphabet", "amazon.com", "meta platforms",
        "nvidia", "broadcom", "advanced micro", "intel corp", "qualcomm",
        "texas instruments", "micron", "applied materials", "lam research",
        "kla corp", "asml", "oracle", "salesforce", "adobe", "servicenow",
        "snowflake", "datadog", "cisco", "international business machines",
        "accenture", "arista networks", "dell technologies", "hewlett",
        "technologies", "software", "semiconductor", "systems inc", "digital",
        "cloud", "netflix", "uber technologies", "airbnb", "shopify",
        "workday", "intuit", "synopsys", "cadence design", "marvell",
        "analog devices", "equinix", "arm holdings", "supermicro",
        "super micro",
    ),
}

# A small hand-written safety net for the case where the committee dataset on
# GitHub cannot be reached. It covers members who trade often and sit on
# committees that matter for this strategy. It is deliberately incomplete and
# the output says so whenever it is used.
FALLBACK_MEMBER_COMMITTEES: dict[str, tuple[str, ...]] = {
    "pelosi": (),
    "green mark": ("HSHM",),
    "khanna": ("HSAS",),
    "gottheimer": ("HSBA", "HLIG"),
    "moulton": ("HSAS",),
    "garbarino": ("HSHM",),
    "fallon": ("HSAS", "HSGO"),
    "mccaul": ("HSFA", "HLIG"),
    "carper": (),
    "tuberville": ("SSAS", "SSAF"),
    "whitehouse": ("SSFI", "SSEV"),
    "capito": ("SSAP", "SSEV"),
    "hern": ("HSWM",),
    "banks": ("SSAS",),
    "sessions": ("HSGO",),
    "kelly mark": ("HSAG", "HSFA"),
    "wittman": ("HSAS",),
    "norcross": ("HSAS",),
    "crenshaw": ("HSIF", "HLIG"),
    "gooden": ("HSBA", "HSHM"),
    "harshbarger": ("HSIF",),
    "self": ("HSFA", "HSHM"),
    "nunn": ("HSBA", "HSAG"),
    "hoyle": ("HSIF",),
    "allred": (),
    "meuser": ("HSBA",),
    "moore blaine": ("HSWM",),
    "collins": ("SSAP",),
    "boozman": ("SSAF", "SSAP", "SSVA"),
    "cornyn": ("SSFI", "SSJU", "SLIN"),
    "coons": ("SSAP", "SSFR", "SSJU"),
    "mccormick": ("SSBK", "SSAS"),
    "sheehy": ("SSAS", "SSCM", "SSVA"),
    "moreno": ("SSBK", "SSAS"),
    "husted": ("SSCM", "SSAS"),
    "curtis": ("SSEG", "SSFR"),
    "slotkin": ("SSAS", "SSAF"),
    "rounds": ("SSAS", "SSBK", "SLIN"),
    "daines": ("SSFI", "SSAP"),
    "britt": ("SSAP", "SSBK"),
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def normalise_name(value: str) -> str:
    """Fold a name down to something two sources can be compared on."""
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"\b(hon|mr|mrs|ms|dr|jr|sr|ii|iii|iv|the honorable)\b\.?", " ", text)
    text = re.sub(r"[^a-z ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_us_date(value: str) -> date | None:
    """Read a date written the American way, or ISO, and give back a date."""
    text = (value or "").strip()
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%d %b %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text[:24], fmt).date()
        except ValueError:
            continue
    return None


def http_get(
    session: requests.Session, url: str, **kwargs: Any
) -> requests.Response | None:
    """Fetch a URL, retrying a couple of times, and never raise.

    A source that is down should thin the results, not stop the sweep, so every
    failure here comes back as None and the caller decides what to do.
    """
    last_error = ""
    for attempt in range(HTTP_RETRIES):
        try:
            response = session.get(url, timeout=HTTP_TIMEOUT, **kwargs)
            if response.status_code == 200:
                return response
            last_error = f"HTTP {response.status_code}"
            # Too many requests, or the server is unwell. Back off and retry.
            if response.status_code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1))
                continue
            break
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(1.0 * (attempt + 1))
    log.debug("Gave up on %s (%s)", url, last_error)
    return None


def cache_is_fresh(path: Path, max_age_hours: float) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    age = time.time() - path.stat().st_mtime
    return age < max_age_hours * 3600


# ---------------------------------------------------------------------------
# One disclosed purchase
# ---------------------------------------------------------------------------


@dataclass
class Purchase:
    """A single purchase read off one member's filing."""

    ticker: str
    asset_description: str
    member_name: str
    chamber: str
    state: str = ""
    district: str = ""
    party: str = ""
    owner: str = "self"          # self, spouse, dependent child or joint
    amount_band: int | None = None
    amount_band_label: str = ""
    band_midpoint_usd: float | None = None
    transaction_date: date | None = None
    disclosure_date: date | None = None
    source_url: str = ""
    source_name: str = ""
    member_resolved: bool = False
    committees: list[str] = field(default_factory=list)   # plain-language names
    committee_codes: list[str] = field(default_factory=list)

    @property
    def gap_days(self) -> int | None:
        if self.transaction_date is None or self.disclosure_date is None:
            return None
        return (self.disclosure_date - self.transaction_date).days

    @property
    def member_key(self) -> str:
        """Two filings by the same person should count as one member."""
        return f"{normalise_name(self.member_name)}|{self.chamber}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.member_name,
            "chamber": self.chamber,
            "party": self.party or None,
            "state": self.state or None,
            "district": self.district or None,
            "owner": self.owner,
            "committees": list(self.committees),
            "amount_band": self.amount_band,
            "amount_band_label": self.amount_band_label,
            "band_midpoint_usd": self.band_midpoint_usd,
            "transaction_date": (
                self.transaction_date.isoformat() if self.transaction_date else None
            ),
            "disclosure_date": (
                self.disclosure_date.isoformat() if self.disclosure_date else None
            ),
            "gap_days": self.gap_days,
            "source_url": self.source_url,
        }


# ---------------------------------------------------------------------------
# Who sits on what: the congress-legislators dataset
# ---------------------------------------------------------------------------


class CommitteeBook:
    """Looks up which committees a member sits on.

    First choice is the unitedstates/congress-legislators dataset on GitHub,
    which publishes current members and current committee membership as YAML
    and is updated within days. If that cannot be reached, a small hand-written
    table takes over and the output is marked incomplete so nobody mistakes it
    for the real thing.
    """

    def __init__(self) -> None:
        self.by_bioguide: dict[str, list[str]] = {}
        self.members: list[dict[str, Any]] = []
        self.complete = False
        self.source = "hand-written fallback table (incomplete)"
        self.last_updated: str | None = None
        # Lookup indexes, most specific first.
        self._by_state_district: dict[tuple[str, str], dict[str, Any]] = {}

    def load(self, session: requests.Session, cache_dir: Path) -> None:
        if yaml is None:
            log.warning(
                "pyyaml is not installed, so committee membership falls back to "
                "the small built-in table"
            )
            return
        raw: dict[str, Any] = {}
        for filename in LEGISLATOR_FILES:
            path = cache_dir / "legislators" / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            if not cache_is_fresh(path, INDEX_CACHE_HOURS):
                response = http_get(session, LEGISLATORS_BASE + filename)
                if response is None:
                    log.warning("Could not download %s", filename)
                    if not path.exists():
                        return
                else:
                    path.write_bytes(response.content)
            try:
                loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
                raw[filename] = yaml.load(path.read_text(encoding="utf-8"), Loader=loader)
            except Exception as exc:
                log.warning("Could not read %s (%s)", path, exc)
                return

        legislators = raw.get("legislators-current.yaml") or []
        membership = raw.get("committee-membership-current.yaml") or {}
        if not legislators or not membership:
            return

        for code, people in membership.items():
            # Keys like HSAS13 are subcommittees of HSAS. Roll them up to the
            # parent committee, since the sector table only knows parents.
            parent = code[:4]
            for person in people or []:
                bioguide = person.get("bioguide")
                if not bioguide:
                    continue
                slot = self.by_bioguide.setdefault(bioguide, [])
                if parent not in slot:
                    slot.append(parent)

        for person in legislators:
            terms = person.get("terms") or []
            if not terms:
                continue
            term = terms[-1]
            name = person.get("name") or {}
            last = normalise_name(name.get("last", ""))
            # Sources disagree about where a surname starts. The House index
            # files April McClain Delaney under "Delaney, April McClain", while
            # this dataset calls her surname "McClain Delaney". So keep every
            # word of the name and match on the words rather than on the split.
            words = " ".join(
                str(part)
                for part in (
                    name.get("first", ""),
                    name.get("middle", ""),
                    name.get("nickname", ""),
                    name.get("last", ""),
                    name.get("official_full", ""),
                )
                if part
            )
            record = {
                "bioguide": (person.get("id") or {}).get("bioguide", ""),
                "full_name": name.get(
                    "official_full",
                    f"{name.get('first','')} {name.get('last','')}".strip(),
                ),
                "last_words": set(last.split()),
                "words": set(normalise_name(words).split()),
                "state": (term.get("state") or "").upper(),
                "district": str(term.get("district", "") or ""),
                "party": term.get("party", "") or "",
                "chamber": "House" if term.get("type") == "rep" else "Senate",
            }
            self.members.append(record)
            if record["district"]:
                self._by_state_district[
                    (record["state"], record["district"].zfill(2))
                ] = record

        self.complete = True
        self.source = "unitedstates/congress-legislators on GitHub"
        path = cache_dir / "legislators" / "committee-membership-current.yaml"
        if path.exists():
            self.last_updated = (
                datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                .date()
                .isoformat()
            )
        log.info(
            "Committee book loaded: %d current members, %d with committee seats",
            len(self.members),
            len(self.by_bioguide),
        )

    def look_up(
        self, last: str, first: str, state: str, district: str, chamber: str
    ) -> dict[str, Any] | None:
        """Find the member behind a filing, from the little the filing tells us.

        A House filing carries the state and the district number, and only one
        person holds a given district, so that is an exact answer. A Senate
        filing carries nothing but a name, so that falls back to comparing the
        words in the two names.
        """
        state = (state or "").upper()
        wanted = set(normalise_name(f"{first} {last}").split())
        wanted.discard("")
        if not wanted:
            return None

        if chamber == "House" and state and district:
            record = self._by_state_district.get((state, district.zfill(2)))
            # Check the surname before trusting the seat. A member who has since
            # left Congress can still be filing, and this dataset only lists
            # sitting members, so the seat now belongs to their replacement.
            # Without this check their trade would be filed under the wrong
            # person, along with the wrong committees. Returning nothing is the
            # safe answer, and the caller reports it.
            if record and (record["words"] & wanted):
                return record

        pool = [r for r in self.members if r["chamber"] == chamber]
        if state:
            narrowed = [r for r in pool if r["state"] == state]
            if narrowed:
                pool = narrowed

        best = None
        best_overlap = 0
        for record in pool:
            # The surname has to appear somewhere in the filed name, otherwise
            # two people who merely share a first name would match.
            if not (record["last_words"] & wanted):
                continue
            overlap = len(record["words"] & wanted)
            if overlap > best_overlap:
                best, best_overlap = record, overlap
        return best

    def committees_for(self, purchase: Purchase, first: str = "") -> None:
        """Fill in a purchase's committee codes and plain-language names."""
        codes: list[str] = []
        last = purchase.member_name.split(",")[0] if "," in purchase.member_name else ""
        if not last:
            parts = purchase.member_name.split()
            last = parts[-1] if parts else ""

        record = None
        if self.complete:
            record = self.look_up(
                last, first, purchase.state, purchase.district, purchase.chamber
            )
        if record is not None:
            codes = list(self.by_bioguide.get(record["bioguide"], []))
            if record["party"] and not purchase.party:
                purchase.party = record["party"]
            if record["full_name"]:
                purchase.member_name = record["full_name"]
        else:
            key = normalise_name(last)
            codes = list(FALLBACK_MEMBER_COMMITTEES.get(key, ()))
            if not codes and first:
                codes = list(
                    FALLBACK_MEMBER_COMMITTEES.get(
                        f"{key} {normalise_name(first).split(' ')[0]}", ()
                    )
                )

        purchase.member_resolved = record is not None
        purchase.committee_codes = codes
        purchase.committees = [
            COMMITTEE_NAMES.get(code, code)
            for code in codes
            if code in COMMITTEE_SECTORS
        ]


# ---------------------------------------------------------------------------
# Source one: the House Clerk
# ---------------------------------------------------------------------------

# The transaction table in a House PTR reads like this once the PDF text is
# pulled out, with the asset type in square brackets sitting right before the
# transaction type and the two dates:
#
#   JT Boeing Company (BA) [ST] P 08/13/2026 08/27/2026 $15,001 - $50,000
#
# So the bracketed asset type is the anchor: everything before it is the owner
# code and the company name, everything after it is the trade itself.
HOUSE_ROW = re.compile(
    r"(?<![A-Za-z0-9])(?P<tx_type>[PSE](?:\s*\(partial\))?)\s+"
    r"(?P<tx_date>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<notified>\d{2}/\d{2}/\d{4})\s+"
    r"(?:Spouse/DC\s+)?"
    r"(?P<amount>\$[\d,]+\s*-\s*\$[\d,]+|Over\s+\$[\d,]+)"
)
# The ticker and the asset type code normally sit together, as "(BA) [ST]",
# at the end of the text that comes before the trade.
HOUSE_ASSET_IN_HEAD = re.compile(
    r"(?:\(([A-Z][A-Z0-9.\-]{0,6})\)\s*)?\[([A-Z0-9]{2})\]\s*$"
)
# Sometimes only the ticker lands before the trade and the type code lands after.
HOUSE_TICKER_IN_HEAD = re.compile(r"\(([A-Z][A-Z0-9.\-]{0,6})\)\s*$")
HOUSE_TYPE_IN_TAIL = re.compile(r"^\s*\[([A-Z0-9]{2})\]")
# And when a long company name wraps onto a second line, the whole of
# "(ticker) [type]" lands after the trade, behind the tail of the name.
HOUSE_ASSET_IN_TAIL = re.compile(
    r"^(?P<fragment>[^()\[\]]{0,30}?)\(([A-Z][A-Z0-9.\-]{0,6})\)\s*\[([A-Z0-9]{2})\]"
)
# Anything matching this in front of a company name is left over from a row that
# came before it, so the name starts after the last one of these.
HOUSE_LEFTOVER = re.compile(
    r"\[[A-Z0-9]{2}\]|\$[\d,]+\s*-\s*\$[\d,]+|Over\s+\$[\d,]+|\d{2}/\d{2}/\d{4}"
)
HOUSE_OWNER = re.compile(r"^(SP|DC|JT)\b\s*")
# Pooled funds. A member buying an index fund tells us nothing about a company,
# and there is no committee to link it to, so this book leaves them alone. The
# leveraged and inverse ones are doubly unwanted, for the same reason the
# momentum scanner throws them out.
FUND_WORDS = (
    " etf", " etn", "ishares", "spdr", "vanguard", "proshares", "direxion",
    "invesco", "index fund", "mutual fund", " fund ", "unit trust",
    "select sector", "tradr ", " 2x ", " 3x ",
)


def looks_like_a_fund(description: str) -> bool:
    haystack = f" {(description or '').lower()} "
    return any(word in haystack for word in FUND_WORDS)


HOUSE_OWNER_LABELS = {
    "SP": "spouse",
    "DC": "dependent child",
    "JT": "joint",
    "": "self",
}
# Boilerplate that repeats on every page of the form and is not part of a trade.
HOUSE_BOILERPLATE = re.compile(
    r"(^ID Owner Asset|^Type$|^Date Notification$|^Gains >|^\$200\?$|^Amount Cap\.|"
    r"^Filing ID #|^\* For the complete|^Digitally Signed|^I CERTIFY|^my knowledge|"
    r"^Clerk of the House|^Name:|^Status:|^State/District:|^Date$|^ Yes  No$)"
)


def house_pdf_to_text(data: bytes) -> str:
    """Pull the readable text out of a House PTR and drop the form furniture.

    The form prints its own labels ("FILING STATUS", "SUBHOLDING OF") in a small
    capitals font that the PDF text layer hands back as null bytes. That turns
    out to be useful: any line carrying a null byte is a label or a heading, not
    a trade, so those lines can go. What is left is the company names and the
    transaction rows.
    """
    if PdfReader is None:
        raise RuntimeError("pypdf is not installed, so House filings cannot be read")
    reader = PdfReader(io.BytesIO(data))
    raw = "\n".join((page.extract_text() or "") for page in reader.pages)
    keep: list[str] = []
    for line in raw.split("\n"):
        if "\x00" in line:
            continue
        stripped = line.strip()
        if not stripped or HOUSE_BOILERPLATE.search(stripped):
            continue
        keep.append(stripped)
    return re.sub(r"\s+", " ", " ".join(keep))


def parse_house_ptr(
    data: bytes, member: dict[str, Any], url: str
) -> tuple[list[Purchase], int]:
    """Read one House filing. Returns its purchases and how many rows it held."""
    text = house_pdf_to_text(data)
    purchases: list[Purchase] = []
    matches = list(HOUSE_ROW.finditer(text))
    rows = len(matches)

    for position, match in enumerate(matches):
        # The form normally prints a row as "owner, company name, (ticker),
        # [asset type], then the trade". But when a long company name wraps onto
        # a second line the PDF hands the text back out of order and part of it,
        # sometimes including the ticker, lands after the trade instead of
        # before it. Three layouts turn up in real filings, so check for them in
        # order and never guess beyond them. Guessing is how a municipal bond
        # with no ticker ends up borrowing the ticker of the row below it.
        head_start = matches[position - 1].end() if position else 0
        tail_end = (
            matches[position + 1].start()
            if position + 1 < len(matches)
            else len(text)
        )
        head = text[head_start : match.start()].rstrip()
        tail = text[match.end() : tail_end].lstrip()

        ticker = asset_type = None
        name_region = ""

        found = HOUSE_ASSET_IN_HEAD.search(head)
        if found is not None:
            # Everything about the asset came before the trade, which is the
            # ordinary case. A missing ticker here means the asset has none, for
            # example a municipal bond, so the row is simply not tradeable.
            ticker, asset_type = found.group(1), found.group(2)
            name_region = head[: found.start()]
        else:
            in_head = HOUSE_TICKER_IN_HEAD.search(head)
            in_tail = HOUSE_TYPE_IN_TAIL.match(tail)
            if in_head is not None and in_tail is not None:
                ticker, asset_type = in_head.group(1), in_tail.group(1)
                name_region = head[: in_head.start()]
            else:
                wrapped = HOUSE_ASSET_IN_TAIL.match(tail)
                # Only accept this when the piece sitting between the trade and
                # the ticker is a short scrap of the same name, with no owner
                # code in it. Anything longer is the next row starting.
                if wrapped is not None and not HOUSE_OWNER.search(
                    wrapped.group("fragment").strip()
                ):
                    ticker, asset_type = wrapped.group(2), wrapped.group(3)
                    name_region = head + " " + wrapped.group("fragment")

        # Only ordinary shares. Options, municipal bonds, funds and private
        # partnerships either have no ticker to trade or are a different
        # instrument from the one this book buys.
        if not ticker or asset_type != "ST":
            continue
        if not match.group("tx_type").startswith("P"):
            continue

        description = HOUSE_LEFTOVER.split(name_region)[-1].strip()
        # Some filings print a bare document number in front of the first row.
        description = re.sub(r"^\d{6,}\s*", "", description)
        owner_match = HOUSE_OWNER.match(description)
        owner_code = owner_match.group(1) if owner_match else ""
        description = HOUSE_OWNER.sub("", description).strip(" .,-")

        if looks_like_a_fund(description):
            continue

        band, label, midpoint = parse_amount_band(match.group("amount"))
        purchases.append(
            Purchase(
                ticker=ticker.upper(),
                asset_description=description,
                member_name=f"{member['last']}, {member['first']}".strip(", "),
                chamber="House",
                state=member["state"],
                district=member["district"],
                owner=HOUSE_OWNER_LABELS.get(owner_code, "self"),
                amount_band=band,
                amount_band_label=label,
                band_midpoint_usd=midpoint,
                transaction_date=parse_us_date(match.group("tx_date")),
                disclosure_date=member["filing_date"],
                source_url=url,
                source_name="House Clerk",
            )
        )
    return purchases, rows


def fetch_house(
    session: requests.Session, since: date, cache_dir: Path, report: dict[str, Any]
) -> list[Purchase]:
    """Download the House filing index, then read every new transaction report."""
    years = sorted({since.year, date.today().year})
    filings: list[dict[str, Any]] = []
    newest = None

    for year in years:
        url = HOUSE_INDEX_URL.format(year=year)
        path = cache_dir / f"house_index_{year}.zip"
        if not cache_is_fresh(path, INDEX_CACHE_HOURS):
            response = http_get(session, url)
            if response is None:
                report["errors"].append(
                    f"Could not download the House filing index for {year}"
                )
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(response.content)
        try:
            with zipfile.ZipFile(path) as archive:
                name = next(n for n in archive.namelist() if n.lower().endswith(".txt"))
                body = archive.read(name).decode("utf-8-sig", errors="replace")
        except Exception as exc:
            report["errors"].append(f"House index for {year} could not be opened: {exc}")
            continue

        for line in body.splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) < 9:
                continue
            _prefix, last, first, _suffix, filing_type, state_dst, _yr, filed, doc_id = (
                parts[:9]
            )
            filing_date = parse_us_date(filed)
            if filing_date is None:
                continue
            if newest is None or filing_date > newest:
                newest = filing_date
            if filing_type.strip() != "P" or filing_date < since:
                continue
            state_dst = (state_dst or "").strip()
            filings.append(
                {
                    "last": last.strip(),
                    "first": first.strip(),
                    "state": state_dst[:2],
                    "district": state_dst[2:],
                    "filing_date": filing_date,
                    "doc_id": doc_id.strip(),
                    "year": year,
                }
            )

    report["house_filings_found"] = len(filings)
    report["house_index_newest_filing"] = newest.isoformat() if newest else None
    if not filings:
        return []

    log.info(
        "House: %d transaction report(s) filed on or after %s, downloading them",
        len(filings),
        since.isoformat(),
    )

    pdf_dir = cache_dir / "house_ptr"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    def load_one(filing: dict[str, Any]) -> tuple[dict[str, Any], bytes | None, str]:
        url = HOUSE_PTR_PDF_URL.format(year=filing["year"], doc_id=filing["doc_id"])
        path = pdf_dir / f"{filing['doc_id']}.pdf"
        # A filing never changes once it is filed, so a cached PDF is always good.
        if path.exists() and path.stat().st_size > 0:
            return filing, path.read_bytes(), url
        response = http_get(session, url)
        if response is None:
            return filing, None, url
        path.write_bytes(response.content)
        return filing, response.content, url

    purchases: list[Purchase] = []
    rows_seen = 0
    unreadable = 0
    image_only = []
    with futures.ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
        for filing, data, url in pool.map(load_one, filings):
            if not data:
                unreadable += 1
                continue
            try:
                found, rows = parse_house_ptr(data, filing, url)
            except Exception as exc:
                unreadable += 1
                log.debug("Could not read House filing %s: %s", filing["doc_id"], exc)
                continue
            if rows == 0:
                # Members who still file on paper send in a scan, and a scan has
                # no text to read. Nothing can be done about those here short of
                # optical character recognition, so they are counted and named.
                image_only.append(filing["doc_id"])
            rows_seen += rows
            purchases.extend(found)

    report["house_rows_scanned"] = rows_seen
    report["house_filings_unreadable"] = unreadable
    report["house_filings_with_no_readable_text"] = len(image_only)
    if unreadable:
        report["errors"].append(
            f"{unreadable} House filing(s) could not be downloaded or read"
        )
    if image_only:
        report["errors"].append(
            f"{len(image_only)} House filing(s) were scans of paper forms with no "
            f"text to read, so their trades are not in this sweep: "
            + ", ".join(image_only[:10])
        )
    log.info(
        "House: read %d transaction row(s), of which %d were share purchases",
        rows_seen,
        len(purchases),
    )
    return purchases


# ---------------------------------------------------------------------------
# Source two: the Senate electronic filing site
# ---------------------------------------------------------------------------

# The Senate writes the owner out in words rather than as a code.
SENATE_OWNER_LABELS = {
    "self": "self",
    "spouse": "spouse",
    "joint": "joint",
    "child": "dependent child",
    "dependent child": "dependent child",
}

SENATE_LINK = re.compile(r'href="(/search/view/(ptr|paper)/[^"]+/)"')
SENATE_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
SENATE_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
SENATE_TAG = re.compile(r"<[^>]+>")


def strip_tags(html: str) -> str:
    text = SENATE_TAG.sub(" ", html)
    text = (
        text.replace("&amp;", "&")
        .replace("&nbsp;", " ")
        .replace("&#35;", "#")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    return re.sub(r"\s+", " ", text).strip()


def senate_session(session: requests.Session) -> bool:
    """Accept the Senate site's terms page, which it requires before searching."""
    home = http_get(session, SENATE_HOME)
    if home is None:
        return False
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', home.text)
    if not token:
        return False
    try:
        session.post(
            SENATE_HOME,
            data={"prohibition_agreement": "1", "csrfmiddlewaretoken": token.group(1)},
            headers={"Referer": SENATE_HOME},
            timeout=HTTP_TIMEOUT,
        )
    except Exception as exc:
        log.debug("Senate terms page refused: %s", exc)
        return False
    return True


def fetch_senate(
    session: requests.Session, since: date, cache_dir: Path, report: dict[str, Any]
) -> list[Purchase]:
    """Search the Senate site for new transaction reports and read each one."""
    if not senate_session(session):
        report["errors"].append("Could not get past the Senate site's terms page")
        return []

    search = http_get(session, SENATE_SEARCH)
    token = None
    if search is not None:
        found = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', search.text)
        token = found.group(1) if found else None
    if token is None:
        token = session.cookies.get("csrftoken", "")

    rows: list[list[str]] = []
    start = 0
    newest = None
    while True:
        payload = {
            "start": str(start),
            "length": "100",
            "report_types": SENATE_PTR_REPORT_TYPE,
            "filer_types": "[]",
            "submitted_start_date": since.strftime("%m/%d/%Y") + " 00:00:00",
            "submitted_end_date": "",
            "candidate_state": "",
            "senator_state": "",
            "office_id": "",
            "first_name": "",
            "last_name": "",
            "csrfmiddlewaretoken": token,
        }
        try:
            response = session.post(
                SENATE_DATA,
                data=payload,
                headers={"Referer": SENATE_SEARCH, "X-Requested-With": "XMLHttpRequest"},
                timeout=HTTP_TIMEOUT,
            )
            batch = response.json().get("data", []) if response.status_code == 200 else []
        except Exception as exc:
            report["errors"].append(f"Senate search failed: {exc}")
            break
        if not batch:
            break
        rows.extend(batch)
        start += len(batch)
        if len(batch) < 100 or start > 1000:
            break

    filings: list[dict[str, Any]] = []
    paper = 0
    for row in rows:
        if len(row) < 5:
            continue
        first, last, _office, link_html, filed = row[0], row[1], row[2], row[3], row[4]
        filing_date = parse_us_date(filed)
        if filing_date is None:
            continue
        if newest is None or filing_date > newest:
            newest = filing_date
        if filing_date < since:
            continue
        link = SENATE_LINK.search(link_html)
        if not link:
            continue
        if link.group(2) == "paper":
            # A scanned paper filing. There is no text in it to read.
            paper += 1
            continue
        filings.append(
            {
                "first": first.strip(),
                "last": last.strip(),
                "url": SENATE_BASE + link.group(1),
                "filing_date": filing_date,
            }
        )

    report["senate_filings_found"] = len(filings)
    report["senate_paper_filings_skipped"] = paper
    report["senate_newest_filing"] = newest.isoformat() if newest else None
    if paper:
        log.info(
            "Senate: %d filing(s) were scanned paper forms with no readable text, "
            "so their trades are not in this sweep",
            paper,
        )
    if not filings:
        return []

    log.info("Senate: %d electronic transaction report(s) to read", len(filings))
    html_dir = cache_dir / "senate_ptr"
    html_dir.mkdir(parents=True, exist_ok=True)

    def load_one(filing: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        key = filing["url"].rstrip("/").split("/")[-1]
        path = html_dir / f"{key}.html"
        if path.exists() and path.stat().st_size > 0:
            return filing, path.read_text(encoding="utf-8", errors="replace")
        response = http_get(session, filing["url"], headers={"Referer": SENATE_SEARCH})
        if response is None:
            return filing, None
        path.write_text(response.text, encoding="utf-8")
        return filing, response.text

    purchases: list[Purchase] = []
    rows_seen = 0
    unreadable = 0
    with futures.ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
        for filing, html in pool.map(load_one, filings):
            if not html:
                unreadable += 1
                continue
            try:
                found, seen = parse_senate_ptr(html, filing)
            except Exception as exc:
                unreadable += 1
                log.debug("Could not read Senate filing %s: %s", filing["url"], exc)
                continue
            rows_seen += seen
            purchases.extend(found)

    report["senate_rows_scanned"] = rows_seen
    report["senate_filings_unreadable"] = unreadable
    if unreadable:
        report["errors"].append(
            f"{unreadable} Senate filing(s) could not be downloaded or read"
        )
    log.info(
        "Senate: read %d transaction row(s), of which %d were share purchases",
        rows_seen,
        len(purchases),
    )
    return purchases


def parse_senate_ptr(html: str, filing: dict[str, Any]) -> tuple[list[Purchase], int]:
    """Read one Senate report. Its transactions are a plain HTML table.

    The columns are: number, transaction date, owner, ticker, asset name,
    asset type, transaction type, amount, comment.
    """
    purchases: list[Purchase] = []
    seen = 0
    for row_html in SENATE_ROW.findall(html):
        cells = [strip_tags(cell) for cell in SENATE_CELL.findall(row_html)]
        if len(cells) < 8:
            continue
        if not re.fullmatch(r"\d+", cells[0] or ""):
            continue  # the header row, or something that is not a transaction
        seen += 1
        _number, tx_date, owner, ticker, asset, asset_type, tx_type, amount = cells[:8]

        if not tx_type.lower().startswith("purchase"):
            continue
        # The site's own asset types are Stock, Stock Option, Non-Public Stock,
        # Municipal Security, Corporate Bond and Other. Only the first is an
        # ordinary listed share, so match it exactly. A loose match here quietly
        # turns options trades into share purchases.
        if asset_type.strip().lower() != "stock":
            continue
        ticker = (ticker or "").strip().upper()
        if not ticker or ticker in {"--", "N/A", ""}:
            continue
        if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,6}", ticker):
            continue
        asset = re.sub(r"\s+", " ", asset).strip()
        if looks_like_a_fund(asset):
            continue

        band, label, midpoint = parse_amount_band(amount)
        owner_label = SENATE_OWNER_LABELS.get(
            (owner or "").strip().lower(), "self"
        )
        purchases.append(
            Purchase(
                ticker=ticker,
                asset_description=asset,
                member_name=f"{filing['last']}, {filing['first']}".strip(", "),
                chamber="Senate",
                owner=owner_label,
                amount_band=band,
                amount_band_label=label,
                band_midpoint_usd=midpoint,
                transaction_date=parse_us_date(tx_date),
                disclosure_date=filing["filing_date"],
                source_url=filing["url"],
                source_name="Senate EFD",
            )
        )
    return purchases, seen


# ---------------------------------------------------------------------------
# Source three, last resort: a community mirror of the House filings
# ---------------------------------------------------------------------------


def fetch_mirror(
    session: requests.Session, since: date, cache_dir: Path, report: dict[str, Any]
) -> list[Purchase]:
    """Last resort: an independent GitHub feed that scrapes the House Clerk.

    This is one JSON file on GitHub, rebuilt daily by its own scraper from the
    same House Clerk filings this script normally reads itself. It covers the
    House only, so the Senate is simply missing when this path runs.

    It is not a mirror or a rebuild of the old House Stock Watcher feed. It
    shares a repository name with it and nothing else, which this docstring got
    wrong until 2026-09-06. The practical consequence is the useful part: there
    is no third party dataset in this book's chain at all, so no third party
    data licence applies on any path, official or degraded.

    It is a fallback and not a primary source, for a measured reason. Checked on
    2026-09-06 against 17 filings both it and this script had parsed, they agreed
    on 12. Every one of the five disagreements was theirs:

    - It misses rows where a long company name wraps in the PDF, which cost it
      real purchases of CMS Energy and UDR.
    - It drops tickers containing a dot, so it lost a Berkshire Hathaway buy.
    - Worst, on two filings it invented a ticker. Its own asset description
      still had the raw null bytes the form's small capitals leave behind, and
      out of that wreckage it pulled the ticker "K" twice. The securities were
      really Alphabet and Microsoft. A phantom ticker is how a strategy ends up
      buying a cereal company because a congressman bought Microsoft.

    So records whose description carries those null bytes are dropped here, since
    that is the visible tell that their parser failed on that row. Anything this
    function returns is flagged in the output as coming from a degraded source.
    """
    log.warning(
        "Both official sources failed. Falling back to the community mirror, "
        "which covers the House only and is known to miss and occasionally "
        "invent rows. Treat the results with suspicion."
    )
    path = cache_dir / "mirror_all_transactions.json"
    if not cache_is_fresh(path, INDEX_CACHE_HOURS):
        response = http_get(session, MIRROR_URL)
        if response is None:
            report["errors"].append("The community mirror could not be downloaded")
            return []
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
    try:
        rows = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        report["errors"].append(f"The community mirror could not be read: {exc}")
        return []

    purchases: list[Purchase] = []
    newest = None
    corrupted = 0
    for row in rows:
        disclosed = parse_us_date(row.get("disclosure_date", ""))
        if disclosed is None:
            continue
        if newest is None or disclosed > newest:
            newest = disclosed
        if disclosed < since:
            continue
        if row.get("type") != "Purchase" or row.get("asset_type") != "Stock":
            continue
        ticker = str(row.get("ticker") or "").strip().upper()
        if not ticker or ticker in {"--", "N/A"}:
            continue
        if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,6}", ticker):
            continue
        description = str(row.get("asset_description") or "")
        if "\x00" in description:
            # Their parser failed on this row and the ticker cannot be trusted.
            corrupted += 1
            continue
        description = re.sub(r"\s+", " ", description).strip()
        if looks_like_a_fund(description):
            continue

        district = str(row.get("district") or "")
        band, label, midpoint = parse_amount_band(row.get("amount", ""))
        purchases.append(
            Purchase(
                ticker=ticker,
                asset_description=description,
                member_name=str(row.get("representative") or "unknown"),
                chamber="House",
                state=district[:2],
                district=district[2:],
                owner=str(row.get("owner") or "self").strip().lower() or "self",
                amount_band=band,
                amount_band_label=label,
                band_midpoint_usd=midpoint,
                transaction_date=parse_us_date(row.get("transaction_date", "")),
                disclosure_date=disclosed,
                source_url=str(row.get("source_url") or ""),
                source_name="community mirror",
            )
        )

    report["mirror_rows_total"] = len(rows)
    report["mirror_newest_disclosure"] = newest.isoformat() if newest else None
    report["mirror_rows_dropped_as_corrupted"] = corrupted
    if corrupted:
        report["errors"].append(
            f"{corrupted} mirror row(s) were dropped because the mirror's own "
            f"parser had mangled them and their ticker could not be trusted"
        )
    return purchases


# ---------------------------------------------------------------------------
# Filtering, grouping and scoring
# ---------------------------------------------------------------------------


def widest_crowd(dates: list[date]) -> int:
    """How many of these buys fall inside any single 30-day window."""
    if not dates:
        return 0
    ordered = sorted(dates)
    best = 1
    left = 0
    for right in range(len(ordered)):
        while (ordered[right] - ordered[left]).days > CROWD_WINDOW_DAYS:
            left += 1
        best = max(best, right - left + 1)
    return best


def company_sectors(description: str, ticker: str) -> list[str]:
    """Guess what business a company is in from the name the member disclosed.

    This is a placeholder for the real thing. The loop replaces it with the
    industry IBKR reports for the contract, which is why every candidate goes
    out with ticker_sector set to null.
    """
    haystack = f" {description.lower()} "
    hits = []
    for sector, words in SECTOR_KEYWORDS.items():
        if any(word in haystack for word in words):
            hits.append(sector)
    return hits


def committee_relevance(
    purchases: list[Purchase], description: str, ticker: str
) -> tuple[int, list[str], list[str]]:
    """Score the committee link on a scale of 0 to 2.

    0 means no member who bought this sits on a committee that this strategy
      thinks matters.
    1 means at least one does, but the company's name gives no clue that it
      trades in that committee's patch.
    2 means at least one does and the company's name points straight at one of
      that committee's sectors, for example an Armed Services member buying a
      company with "defense" in its name.

    A 1 can still turn into a 2 later. The loop looks the ticker up with IBKR
    and learns the real industry, which is a far better answer than reading the
    company's name.
    """
    covered: list[str] = []
    matched: list[str] = []
    guessed = set(company_sectors(description, ticker))
    for purchase in purchases:
        for code in purchase.committee_codes:
            sectors = COMMITTEE_SECTORS.get(code)
            if not sectors:
                continue
            name = COMMITTEE_NAMES.get(code, code)
            if name not in covered:
                covered.append(name)
            overlap = guessed.intersection(sectors)
            if overlap:
                for sector in sorted(overlap):
                    entry = f"{name} covers {sector}"
                    if entry not in matched:
                        matched.append(entry)
    if matched:
        return 2, covered, matched
    if covered:
        return 1, covered, matched
    return 0, covered, matched


def build_reasons(
    ticker: str,
    purchases: list[Purchase],
    crowd: int,
    relevance: int,
    covered: list[str],
    matched: list[str],
    best_band_label: str,
    guessed_sectors: list[str],
) -> list[str]:
    """Write the plain-language notes Claude reads alongside the numbers."""
    reasons: list[str] = []
    names = sorted({p.member_name for p in purchases})
    if crowd >= 2:
        reasons.append(
            f"{crowd} different members bought {ticker} within 30 days of each "
            f"other: {', '.join(names)}"
        )
    else:
        who = names[0] if names else "a member"
        reasons.append(f"Bought by one member, {who}")

    reasons.append(f"Largest disclosed size was {best_band_label}")

    gaps = [p.gap_days for p in purchases if p.gap_days is not None]
    if gaps:
        if min(gaps) == max(gaps):
            reasons.append(
                f"The filing came {min(gaps)} days after the trade, so the price "
                f"has had that long to react"
            )
        else:
            reasons.append(
                f"The filings came between {min(gaps)} and {max(gaps)} days after "
                f"the trades, so the price has had that long to react"
            )

    if relevance == 2:
        reasons.append(
            "Committee link looks real: " + "; ".join(matched)
        )
    elif relevance == 1:
        reasons.append(
            "A buyer sits on a committee this strategy watches ("
            + ", ".join(covered)
            + "), but the company name does not say whether it is in that "
            "committee's patch. The loop settles this once IBKR reports the "
            "industry."
        )
    else:
        reasons.append(
            "No buyer sits on a committee this strategy links to a sector"
        )

    owners = sorted({p.owner for p in purchases})
    if owners != ["self"]:
        reasons.append(
            "Filed under: " + ", ".join(owners) + " (the form covers a member's "
            "spouse and dependent children as well as the member)"
        )

    if guessed_sectors:
        reasons.append(
            "The company name suggests "
            + ", ".join(guessed_sectors)
            + ", which is a guess from the name only until IBKR confirms it"
        )

    chambers = sorted({p.chamber for p in purchases})
    reasons.append("Disclosed in the " + " and ".join(chambers))
    return reasons


def score_candidate(best_band: int, relevance: int, crowd: int) -> float:
    """Add up the three things the strategy says matter.

    Each step up the size bands is worth two points, so a million dollar buy
    comfortably outranks a ten thousand dollar one. A confirmed committee link
    is worth three points a step, and every extra member buying the same name is
    worth four, because two members arriving at the same stock within a month of
    each other is the strongest thing in this data.
    """
    return (best_band * 2.0) + (relevance * 3.0) + ((crowd - 1) * 4.0)


# ---------------------------------------------------------------------------
# The whole run
# ---------------------------------------------------------------------------


def run_sweep(since: date, cache_dir: Path, max_candidates: int) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    report: dict[str, Any] = {"errors": []}
    cache_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    committees = CommitteeBook()
    committees.load(session, cache_dir)
    if not committees.complete:
        report["errors"].append(
            "Could not load the public committee membership dataset, so committee "
            "links come from a small hand-written table and are incomplete"
        )

    sources_used: list[str] = []
    sources_failed: list[str] = []
    purchases: list[Purchase] = []

    try:
        house = fetch_house(session, since, cache_dir, report)
    except Exception as exc:
        house = []
        report["errors"].append(f"The House sweep failed outright: {exc}")
    if house or report.get("house_filings_found"):
        sources_used.append("House Clerk (disclosures-clerk.house.gov)")
        purchases.extend(house)
    else:
        sources_failed.append("House Clerk")

    try:
        senate = fetch_senate(session, since, cache_dir, report)
    except Exception as exc:
        senate = []
        report["errors"].append(f"The Senate sweep failed outright: {exc}")
    if senate or report.get("senate_filings_found"):
        sources_used.append("Senate EFD (efdsearch.senate.gov)")
        purchases.extend(senate)
    else:
        sources_failed.append("Senate EFD")

    degraded = False
    if not sources_used:
        try:
            fallback = fetch_mirror(session, since, cache_dir, report)
        except Exception as exc:
            fallback = []
            report["errors"].append(f"The community mirror fallback failed: {exc}")
        if fallback:
            degraded = True
            sources_used.append(
                "community mirror of House filings (fallback, House only, "
                "known to miss and occasionally invent rows)"
            )
            purchases.extend(fallback)
        else:
            sources_failed.append("community mirror")

    transactions_scanned = int(report.get("house_rows_scanned", 0)) + int(
        report.get("senate_rows_scanned", 0)
    )
    purchase_count = len(purchases)

    # Fill in each buyer's committees before anything is scored.
    for purchase in purchases:
        first = ""
        if "," in purchase.member_name:
            first = purchase.member_name.split(",", 1)[1].strip()
        committees.committees_for(purchase, first)

    unresolved = sorted(
        {p.member_name for p in purchases if not p.member_resolved}
    )
    if unresolved and committees.complete:
        # Almost always someone who has since left Congress, since the dataset
        # only lists sitting members. Their trades still count, they just have
        # no committee link, so the reason is worth saying out loud.
        report["errors"].append(
            f"{len(unresolved)} filer(s) are not in the current roster of "
            f"members, so they get no committee link. Usually this means they "
            f"have left Congress since filing: " + ", ".join(unresolved[:8])
        )

    # Staleness. A filing that arrives describing a trade made more than sixty
    # days ago is a late filer, and the strategy skips those on principle.
    fresh: list[Purchase] = []
    dropped_stale = 0
    for purchase in purchases:
        gap = purchase.gap_days
        if gap is None or gap > STALENESS_LIMIT_DAYS or gap < 0:
            dropped_stale += 1
            continue
        fresh.append(purchase)

    # Group by ticker.
    by_ticker: dict[str, list[Purchase]] = {}
    for purchase in fresh:
        by_ticker.setdefault(purchase.ticker, []).append(purchase)

    candidates: list[dict[str, Any]] = []
    dropped_band = 0
    for ticker, group in by_ticker.items():
        members = {}
        for purchase in group:
            members.setdefault(purchase.member_key, []).append(purchase)

        # Crowding is a count of distinct people, not of filings, so a member
        # who files the same stock three times still counts once.
        first_buy_per_member = [
            min(p.transaction_date for p in items if p.transaction_date)
            for items in members.values()
            if any(p.transaction_date for p in items)
        ]
        crowd = widest_crowd(first_buy_per_member)

        bands = [p.amount_band for p in group if p.amount_band]
        best_band = max(bands) if bands else 0

        # The floor from the strategy: a mid-sized buy stands on its own, the
        # smallest band only counts when someone else bought the same name.
        if best_band < MIN_BAND_ALONE and not (
            best_band >= MIN_BAND_WITH_CROWD and crowd >= 2
        ):
            dropped_band += 1
            continue

        description = max(
            (p.asset_description for p in group), key=lambda s: len(s or ""), default=""
        )
        relevance, covered, matched = committee_relevance(group, description, ticker)
        guessed = company_sectors(description, ticker)
        best_label = next(
            (label for idx, label, _l, _h in AMOUNT_BANDS if idx == best_band), ""
        )
        score = score_candidate(best_band, relevance, crowd)

        candidates.append(
            {
                "ticker": ticker,
                "asset_description": description,
                "members": [p.as_dict() for p in sorted(
                    group, key=lambda p: (p.disclosure_date or date.min), reverse=True
                )],
                "crowd_count": crowd,
                "committee_relevance": relevance,
                "committees_in_play": covered,
                "committee_matches": matched,
                "best_amount_band": best_band,
                "best_amount_band_label": best_label,
                "ticker_sector": None,
                "ticker_sector_note": (
                    "Left empty on purpose. The loop fills this in from the "
                    "industry IBKR reports for the contract, and the committee "
                    "score can be recomputed once it does."
                ),
                "guessed_sectors_from_name": guessed,
                "score": round(score, 2),
                "reasons": build_reasons(
                    ticker, group, crowd, relevance, covered, matched, best_label, guessed
                ),
                "last_price": None,
                "avg_volume_20d": None,
            }
        )

    candidates.sort(key=lambda c: (-c["score"], c["ticker"]))
    after_filters = len(candidates)
    shortlist = candidates[:max_candidates]

    newest_dates = [
        parse_us_date(report.get("house_index_newest_filing") or ""),
        parse_us_date(report.get("senate_newest_filing") or ""),
        parse_us_date(report.get("mirror_newest_disclosure") or ""),
    ]
    newest = max([d for d in newest_dates if d], default=None)
    stale_by_days = (date.today() - newest).days if newest else None
    staleness_flag = bool(
        newest is None or stale_by_days is None or stale_by_days > SOURCE_STALE_AFTER_DAYS
    )

    return {
        "timestamp": started.astimezone().isoformat(),
        "timestamp_utc": started.isoformat(),
        "since": since.isoformat(),
        "source_used": ", ".join(sources_used) if sources_used else "none",
        "source_is_degraded": degraded,
        "sources_tried_and_failed": sources_failed,
        "source_last_updated": newest.isoformat() if newest else None,
        "source_stale_by_days": stale_by_days,
        "staleness_flag": staleness_flag,
        "staleness_note": (
            f"The newest filing any source has is {newest.isoformat()}, which is "
            f"{stale_by_days} day(s) old. The strategy flags anything older than "
            f"{SOURCE_STALE_AFTER_DAYS} days."
            if newest
            else "No source reported a filing date, so freshness is unknown."
        ),
        "transactions_scanned": transactions_scanned,
        "purchases": purchase_count,
        "after_filters": after_filters,
        "dropped_stale_over_60_days": dropped_stale,
        "dropped_below_minimum_band": dropped_band,
        "committee_data_source": committees.source,
        "committee_data_complete": committees.complete,
        "counts": {
            key: value
            for key, value in report.items()
            if key != "errors" and value is not None
        },
        "warnings": report["errors"],
        "candidates": shortlist,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def valid_date(value: str) -> date:
    parsed = parse_us_date(value)
    if parsed is None:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a date I understand. Write it as 2026-08-01."
        )
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    today = date.today().isoformat()
    default_out = PROJECT_ROOT / "output" / f"congress_shortlist_{today}.json"
    default_since = date.today() - timedelta(days=45)
    parser = argparse.ArgumentParser(
        description=(
            "Read new US Congress stock disclosures, keep the purchases, and "
            "write a scored shortlist. Reads public data only, never trades."
        )
    )
    parser.add_argument(
        "--since",
        type=valid_date,
        default=default_since,
        help="Earliest disclosure date to include, by the date the filing was "
        "received, not the date of the trade. Default: 45 days ago.",
    )
    parser.add_argument(
        "--out",
        default=str(default_out),
        help="Where to write the shortlist JSON. Default: %(default)s",
    )
    parser.add_argument(
        "--cache-dir",
        default=str(DEFAULT_CACHE_DIR),
        help="Where downloaded filings are kept so repeat runs are quick. "
        "Default: %(default)s",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=MAX_CANDIDATES,
        help="How many names to write out at most. Default: %(default)s",
    )
    parser.add_argument("--verbose", action="store_true", help="Chattier logging")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    log.info(
        "Looking for purchases disclosed on or after %s", args.since.isoformat()
    )
    result = run_sweep(args.since, Path(args.cache_dir), max(1, args.max_candidates))

    out_path = Path(args.out).expanduser()
    if not out_path.is_absolute():
        out_path = (Path.cwd() / out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2) + "\n")

    log.info("Source used: %s", result["source_used"])
    log.info(
        "Newest filing seen: %s (%s)",
        result["source_last_updated"],
        "flagged as stale" if result["staleness_flag"] else "fresh enough",
    )
    log.info(
        "Scanned %d transaction row(s), found %d share purchase(s), %d name(s) "
        "cleared the filters, wrote the top %d",
        result["transactions_scanned"],
        result["purchases"],
        result["after_filters"],
        len(result["candidates"]),
    )
    for warning in result["warnings"]:
        log.warning(warning)
    for candidate in result["candidates"][:5]:
        log.info(
            "  %-6s score %5.1f  %d member(s)  committee link %d  %s",
            candidate["ticker"],
            candidate["score"],
            candidate["crowd_count"],
            candidate["committee_relevance"],
            candidate["best_amount_band_label"],
        )
    log.info("Wrote %s", out_path)

    if result["source_used"] == "none":
        log.error("Every source was unreachable, so there is nothing to act on")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

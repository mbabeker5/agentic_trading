#!/usr/bin/env python3
"""Insider-buying sweep for the agentic trading project.

Reads Form 4 filings from SEC EDGAR, keeps only the open-market cash purchases
that were not pre-scheduled, scores them, and writes a shortlist of at most
fifteen companies to a JSON file. Claude reads that file later in the morning
and decides which names, if any, are worth buying.

The strategy behind it is written up in plain English in
/Users/mtalib/workspace_repos/personal_repo/agentic_trading/docs/STRATEGY_INSIDER.md

This script talks to exactly one place on the internet: www.sec.gov. There is no
broker code in it, it never opens a connection to IB Gateway, and it cannot
place an order. It only reads public filings and writes a file.

Run it like this, from the project folder:

    venv312/bin/python agent/sweep_insider.py \
        --since "2026-09-04T00:00" \
        --out output/insider_shortlist_2026-09-06.json

Exit code is 0 whenever the sweep ran, even if nothing survived the filters.
It is 1 only when EDGAR could not be reached at all.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "output" / "edgar_cache"

EASTERN = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

# EDGAR asks that automated readers identify themselves and stay under ten
# requests a second. We sit a little under that on purpose, so a burst of
# retries can never tip us over the line.
USER_AGENT = "agentic_trading research mtalib.personal@gmail.com"
MAX_REQUESTS_PER_SECOND = 8.0
DOWNLOAD_WORKERS = 8
REQUEST_TIMEOUT = 30
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2.0

ARCHIVES = "https://www.sec.gov/Archives"
DAILY_INDEX = ARCHIVES + "/edgar/daily-index/{year}/QTR{quarter}/form.{stamp}.idx"
LATEST_FEED = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcurrent&type=4&count=100&output=atom&start={start}"
)
# The feed holds roughly the last 4,800 entries and returns an error page past
# that, so there is no point asking for more. Measured 2026-09-06.
FEED_PAGE_SIZE = 100
FEED_MAX_PAGES = 48

# Thresholds from docs/STRATEGY_INSIDER.md. Code owns these numbers.
MIN_VALUE_ALONE = 25_000.0
MIN_VALUE_IN_CLUSTER = 10_000.0
CLUSTER_WINDOW_TRADING_DAYS = 10
MAX_CANDIDATES = 15

# What a buyer's job is worth. A chief executive or finance chief putting cash
# in says more than a director topping up, and an outside holder with a big
# stake says least of all.
ROLE_WEIGHT_CEO_CFO = 2.0
ROLE_WEIGHT_OTHER_OFFICER = 1.5
ROLE_WEIGHT_DIRECTOR = 1.0
ROLE_WEIGHT_TEN_PERCENT = 0.8

# A holding that doubles is already the strongest signal this measure can give,
# so anything above that is treated the same. Stops one insider who owned two
# hundred shares from swamping the whole list.
PCT_INCREASE_CAP = 100.0

CEO_CFO_PATTERN = re.compile(
    r"\bC\.?E\.?O\.?\b|\bC\.?F\.?O\.?\b"
    r"|chief\s+executive|chief\s+financial|principal\s+financial"
    r"|principal\s+executive|finance\s+director",
    re.IGNORECASE,
)

# A Form 4 can report a buy of any security the insider holds, including
# preferred shares and units, and those are not the thing this book trades. The
# ticker on the filing still points at the common stock, so the security has to
# be named in the output or Claude would be shown a share class it cannot buy.
COMMON_STOCK_PATTERN = re.compile(r"\b(common|ordinary)\b", re.IGNORECASE)
NOT_COMMON_PATTERN = re.compile(
    r"\b(preferred|preference|warrant|option|note|debenture|unit|right)s?\b",
    re.IGNORECASE,
)

ACCESSION_PATTERN = re.compile(r"(\d{10}-\d{2}-\d{6})")
OWNERSHIP_PATTERN = re.compile(r"<ownershipDocument>.*?</ownershipDocument>", re.DOTALL)
ACCEPTANCE_PATTERN = re.compile(r"<ACCEPTANCE-DATETIME>\s*(\d{14})")
# Catches "10b5-1", "10b5 1" and the versions typed with a fancy dash.
PLAN_TEXT_PATTERN = re.compile(r"10b5[^A-Za-z0-9]{0,3}1", re.IGNORECASE)

log = logging.getLogger("sweep_insider")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def parse_since(value: str) -> datetime:
    """Read the --since argument. A time with no zone is read as Eastern."""
    text = value.strip().replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                moment = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            raise argparse.ArgumentTypeError(
                f"Could not read {value!r} as a date and time. "
                "Try something like 2026-09-04T00:00"
            )
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=EASTERN)
    return moment.astimezone(EASTERN)


def weekdays_between(first: date, second: date) -> int:
    """Rough count of trading days between two dates.

    Weekends are excluded, market holidays are not, so this can read one or two
    days long across a holiday week. That only ever makes the cluster window
    slightly generous, which is the harmless direction.
    """
    start, end = sorted((first, second))
    days = 0
    cursor = start
    while cursor < end:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            days += 1
    return days


def to_float(text: str | None) -> float | None:
    if text is None:
        return None
    cleaned = text.strip().replace(",", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def child_value(node: ET.Element | None, *path: str) -> str | None:
    """Read <thing><value>text</value></thing>, which is how Form 4 nests things."""
    if node is None:
        return None
    cursor: ET.Element | None = node
    for tag in path:
        cursor = cursor.find(tag) if cursor is not None else None
    if cursor is None:
        return None
    value = cursor.find("value")
    text = value.text if value is not None else cursor.text
    return text.strip() if text else None


def is_true(text: str | None) -> bool:
    return (text or "").strip().lower() in {"1", "true", "y", "yes"}


def money(amount: float) -> str:
    """Write a dollar amount the way a person would say it."""
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f} million"
    return f"${amount:,.0f}"


# ---------------------------------------------------------------------------
# Talking to EDGAR
# ---------------------------------------------------------------------------


class EdgarClient:
    """Fetches pages from sec.gov, politely, with a small on-disk cache.

    Everything EDGAR hands back for a finished filing is permanent, so once a
    filing is on disk we never ask for it again. That is what makes a second run
    of the same day take seconds instead of minutes.
    """

    def __init__(self, cache_dir: Path, requests_per_second: float) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept-Encoding": "gzip, deflate",
                "Host": "www.sec.gov",
            }
        )
        self._min_gap = 1.0 / requests_per_second
        self._lock = threading.Lock()
        self._last_start = 0.0
        self.requests_made = 0
        self.cache_hits = 0
        self.failures = 0

    def _pace(self) -> None:
        with self._lock:
            wait = self._min_gap - (time.monotonic() - self._last_start)
            if wait > 0:
                time.sleep(wait)
            self._last_start = time.monotonic()
            self.requests_made += 1

    def get_text(self, url: str) -> str | None:
        """Fetch a URL. Returns None if EDGAR would not give it to us."""
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            self._pace()
            try:
                response = self.session.get(url, timeout=REQUEST_TIMEOUT)
            except requests.RequestException as exc:
                log.debug("Attempt %d for %s failed: %s", attempt, url, exc)
                if attempt == RETRY_ATTEMPTS:
                    self.failures += 1
                    return None
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue

            if response.status_code == 200:
                response.encoding = response.encoding or "latin-1"
                return response.text
            if response.status_code == 404:
                log.debug("Not published: %s", url)
                return None
            if response.status_code in (403, 429, 500, 502, 503, 504):
                log.debug(
                    "EDGAR said %s for %s, waiting before attempt %d",
                    response.status_code,
                    url,
                    attempt + 1,
                )
                if attempt == RETRY_ATTEMPTS:
                    self.failures += 1
                    return None
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue
            log.debug("Unexpected %s for %s", response.status_code, url)
            self.failures += 1
            return None
        return None

    def get_cached(self, url: str, cache_name: str) -> str | None:
        """Same as get_text, but keeps a copy on disk under output/edgar_cache/."""
        path = self.cache_dir / cache_name
        if path.exists():
            self.cache_hits += 1
            return path.read_text(encoding="utf-8", errors="replace")
        text = self.get_text(url)
        if text is None:
            return None
        try:
            path.write_text(text, encoding="utf-8", errors="replace")
        except OSError as exc:
            log.warning("Could not save %s to the cache: %s", cache_name, exc)
        return text


# ---------------------------------------------------------------------------
# Step one: which filings are there?
# ---------------------------------------------------------------------------


@dataclass
class FilingRef:
    accession: str
    cik: str
    source: str
    accepted_hint: datetime | None = None

    @property
    def submission_url(self) -> str:
        return f"{ARCHIVES}/edgar/data/{int(self.cik)}/{self.accession}.txt"

    @property
    def index_url(self) -> str:
        plain = self.accession.replace("-", "")
        return (
            f"{ARCHIVES}/edgar/data/{int(self.cik)}/{plain}/{self.accession}-index.htm"
        )


def daily_index_refs(
    client: EdgarClient, since: datetime, until: datetime, warnings: list[str]
) -> tuple[dict[str, FilingRef], int]:
    """List every Form 4 EDGAR published on each day in the window.

    One request per calendar day. Weekends and holidays simply have no file, and
    a missing file is normal rather than an error.
    """
    refs: dict[str, FilingRef] = {}
    days_found = 0
    today = datetime.now(EASTERN).date()
    day = since.date()
    while day <= until.date():
        if day.weekday() >= 5:
            day += timedelta(days=1)
            continue
        stamp = day.strftime("%Y%m%d")
        url = DAILY_INDEX.format(
            year=day.year, quarter=(day.month - 1) // 3 + 1, stamp=stamp
        )
        # Today's index is still being written, so it is never cached.
        if day < today:
            text = client.get_cached(url, f"form.{stamp}.idx")
        else:
            text = client.get_text(url)
        if text is None:
            log.info("No daily index for %s, which is normal for a market holiday", day)
            day += timedelta(days=1)
            continue
        days_found += 1
        added = 0
        for line in text.splitlines():
            parts = line.split()
            if len(parts) < 4 or parts[0] != "4":
                continue
            match = ACCESSION_PATTERN.search(parts[-1])
            if not match:
                continue
            accession = match.group(1)
            if accession in refs:
                continue
            cik_match = re.search(r"edgar/data/(\d+)/", parts[-1])
            if not cik_match:
                continue
            refs[accession] = FilingRef(accession, cik_match.group(1), "daily index")
            added += 1
        log.info("Daily index for %s listed %d Form 4 filings", day, added)
        day += timedelta(days=1)

    if days_found == 0:
        warnings.append(
            "EDGAR published no daily index files for the days asked for, so the "
            "sweep leaned entirely on the latest-filings feed"
        )
    return refs, days_found


def feed_refs(
    client: EdgarClient, since: datetime, warnings: list[str]
) -> dict[str, FilingRef]:
    """Walk the latest-filings feed back to --since.

    The feed is the fast lane: a filing shows up here within a minute or two of
    EDGAR accepting it, well before the daily index catches up. It is shallow
    though, holding only the last few thousand entries, so it is a top-up rather
    than the main source.
    """
    refs: dict[str, FilingRef] = {}
    reached_since = False
    for page in range(FEED_MAX_PAGES):
        start = page * FEED_PAGE_SIZE
        text = client.get_text(LATEST_FEED.format(start=start))
        if text is None:
            warnings.append(
                f"The latest-filings feed stopped answering at entry {start}, so "
                "anything more recent than the daily index may be missing"
            )
            break
        try:
            feed = ET.fromstring(text.encode("utf-8", errors="replace"))
        except ET.ParseError:
            log.info("Feed page starting at %d was not readable, stopping there", start)
            break
        entries = feed.findall("{http://www.w3.org/2005/Atom}entry")
        if not entries:
            log.info("Feed ran out of entries at %d", start)
            break

        oldest: datetime | None = None
        for entry in entries:
            link = entry.find("{http://www.w3.org/2005/Atom}link")
            href = link.get("href", "") if link is not None else ""
            title = entry.findtext("{http://www.w3.org/2005/Atom}title") or ""
            updated = entry.findtext("{http://www.w3.org/2005/Atom}updated") or ""
            # Amendments restate an earlier filing, so counting them would count
            # the same purchase twice.
            if title.split(" - ")[0].strip() != "4":
                continue
            match = ACCESSION_PATTERN.search(href)
            cik_match = re.search(r"edgar/data/(\d+)/", href)
            if not match or not cik_match:
                continue
            try:
                accepted = datetime.fromisoformat(updated).astimezone(EASTERN)
            except ValueError:
                accepted = None
            if accepted is not None and (oldest is None or accepted < oldest):
                oldest = accepted
            if accepted is not None and accepted < since:
                continue
            accession = match.group(1)
            existing = refs.get(accession)
            # The feed lists the same filing once for the company and once for
            # each insider named on it, so the same accession turns up several
            # times. Prefer the company's copy, purely so the URL we build reads
            # sensibly. Either CIK would fetch the same document.
            is_issuer = title.rstrip().endswith("(Issuer)")
            if existing is None:
                refs[accession] = FilingRef(
                    accession, cik_match.group(1), "latest-filings feed", accepted
                )
            else:
                if is_issuer:
                    existing.cik = cik_match.group(1)
                if existing.accepted_hint is None and accepted is not None:
                    existing.accepted_hint = accepted

        if oldest is not None and oldest < since:
            reached_since = True
            log.info(
                "Feed reached back to %s, which is past the start of the window",
                oldest.isoformat(timespec="minutes"),
            )
            break

    if not reached_since:
        log.info(
            "The feed did not reach all the way back to %s on its own, which is "
            "expected. The daily index files cover the rest.",
            since.isoformat(timespec="minutes"),
        )
    return refs


# ---------------------------------------------------------------------------
# Step two: read one filing
# ---------------------------------------------------------------------------


@dataclass
class Purchase:
    """One insider's open-market buying inside one Form 4."""

    accession: str
    url: str
    issuer_cik: str
    issuer_name: str
    ticker: str
    owner_cik: str
    owner_name: str
    title: str
    role_weight: float
    shares: float
    price: float
    value_usd: float
    transaction_date: date
    accepted_at: datetime
    shares_owned_before: float | None
    shares_owned_after: float | None
    security_title: str = ""
    ownership: str = "D"

    @property
    def is_common_stock(self) -> bool:
        title = self.security_title
        if not title:
            return True
        return bool(COMMON_STOCK_PATTERN.search(title)) and not NOT_COMMON_PATTERN.search(
            title
        )

    @property
    def pct_increase(self) -> float | None:
        if self.shares_owned_before is None or self.shares_owned_before <= 0:
            return None
        return self.shares / self.shares_owned_before * 100.0

    @property
    def is_new_position(self) -> bool:
        return self.shares_owned_before is not None and self.shares_owned_before <= 0


@dataclass
class FilingResult:
    purchases: list[Purchase] = field(default_factory=list)
    parsed: bool = False
    had_any_transaction: bool = False
    skipped_plan: int = 0
    skipped_no_price: int = 0
    problem: str | None = None


def role_weight_for(
    is_director: bool, is_officer: bool, is_ten_percent: bool, title: str
) -> float:
    """Turn the checkboxes and the job title into a single weight."""
    weights = []
    if is_officer:
        weights.append(
            ROLE_WEIGHT_CEO_CFO
            if CEO_CFO_PATTERN.search(title or "")
            else ROLE_WEIGHT_OTHER_OFFICER
        )
    if is_director:
        weights.append(ROLE_WEIGHT_DIRECTOR)
    if is_ten_percent:
        weights.append(ROLE_WEIGHT_TEN_PERCENT)
    if not weights:
        # No box ticked. Treat them like a director, the middle of the road.
        return ROLE_WEIGHT_DIRECTOR
    return max(weights)


def describe_role(
    is_director: bool, is_officer: bool, is_ten_percent: bool, title: str
) -> str:
    if title.strip():
        return title.strip()
    parts = []
    if is_officer:
        parts.append("officer")
    if is_director:
        parts.append("director")
    if is_ten_percent:
        parts.append("ten percent owner")
    return ", ".join(parts) if parts else "insider"


def collect_footnote_ids(node: ET.Element) -> set[str]:
    ids = set()
    for ref in node.iter("footnoteId"):
        value = ref.get("id")
        if value:
            ids.add(value)
    return ids


def parse_filing(ref: FilingRef, raw: str) -> FilingResult:
    """Pull the purchases out of one downloaded Form 4 submission."""
    result = FilingResult()

    match = OWNERSHIP_PATTERN.search(raw)
    if not match:
        result.problem = "no Form 4 ownership document inside the filing"
        return result
    try:
        doc = ET.fromstring(match.group(0))
    except ET.ParseError as exc:
        result.problem = f"the ownership XML would not parse ({exc})"
        return result
    result.parsed = True

    accepted_match = ACCEPTANCE_PATTERN.search(raw)
    if accepted_match:
        accepted_at = datetime.strptime(
            accepted_match.group(1), "%Y%m%d%H%M%S"
        ).replace(tzinfo=EASTERN)
    elif ref.accepted_hint is not None:
        accepted_at = ref.accepted_hint
    else:
        result.problem = "the filing carried no acceptance time"
        return result

    issuer = doc.find("issuer")
    issuer_cik = (child_value(doc, "issuer", "issuerCik") or "").strip()
    if not issuer_cik and issuer is not None:
        issuer_cik = (issuer.findtext("issuerCik") or "").strip()
    issuer_name = (
        issuer.findtext("issuerName", default="").strip() if issuer is not None else ""
    )
    ticker = (
        issuer.findtext("issuerTradingSymbol", default="").strip().upper()
        if issuer is not None
        else ""
    )
    if ticker in {"N/A", "NONE", "NA", "-"}:
        ticker = ""

    # Footnotes, so we can spot the words "10b5-1" wherever they hide.
    footnotes = {
        note.get("id", ""): "".join(note.itertext())
        for note in doc.iter("footnote")
    }
    planned_footnote_ids = {
        key for key, text in footnotes.items() if PLAN_TEXT_PATTERN.search(text)
    }
    document_says_planned = is_true(doc.findtext("aff10b5One"))
    remarks = doc.findtext("remarks") or ""
    remarks_say_planned = bool(PLAN_TEXT_PATTERN.search(remarks))

    owners = []
    for owner in doc.iter("reportingOwner"):
        relationship = owner.find("reportingOwnerRelationship")
        title = ""
        is_director = is_officer = is_ten_percent = False
        if relationship is not None:
            title = (relationship.findtext("officerTitle") or "").strip()
            is_director = is_true(relationship.findtext("isDirector"))
            is_officer = is_true(relationship.findtext("isOfficer"))
            is_ten_percent = is_true(relationship.findtext("isTenPercentOwner"))
        identity = owner.find("reportingOwnerId")
        owners.append(
            {
                "cik": (identity.findtext("rptOwnerCik") or "").strip()
                if identity is not None
                else "",
                "name": (identity.findtext("rptOwnerName") or "").strip()
                if identity is not None
                else "",
                "title": describe_role(is_director, is_officer, is_ten_percent, title),
                "weight": role_weight_for(
                    is_director, is_officer, is_ten_percent, title
                ),
            }
        )
    if not owners:
        result.problem = "the filing named no insider"
        return result

    # Some Form 4s are filed jointly, usually a fund and the person who runs it.
    # The purchase happened once, so it is credited to the first named insider
    # rather than once per name. Crediting each would inflate both the money
    # spent and the cluster count, and a fake cluster is exactly the mistake
    # this strategy cannot afford.
    lead = owners[0]
    owner_name = lead["name"]
    if len(owners) > 1:
        others = len(owners) - 1
        owner_name = f"{owner_name} (filed jointly with {others} other)" if others == 1 \
            else f"{owner_name} (filed jointly with {others} others)"
    owner_cik = lead["cik"]
    owner_title = lead["title"]
    owner_weight = max(owner["weight"] for owner in owners)

    for transaction in doc.iter("nonDerivativeTransaction"):
        result.had_any_transaction = True
        code = (child_value(transaction, "transactionCoding", "transactionCode") or "")
        code = code.strip().upper()
        if code != "P":
            continue
        direction = (
            child_value(transaction, "transactionAmounts", "transactionAcquiredDisposedCode")
            or ""
        ).strip().upper()
        if direction != "A":
            # A code P marked as a disposal is a data entry slip or a return of
            # shares. Either way it is not somebody buying.
            continue

        # A transaction is treated as pre-scheduled if the form's own checkbox
        # is ticked, or if any footnote attached to it, or the remarks, mention
        # a Rule 10b5-1 plan. Erring towards excluding is deliberate: a planned
        # buy carries no fresh opinion, so a wrongly kept one is worse than a
        # wrongly dropped one.
        linked_ids = collect_footnote_ids(transaction)
        planned = (
            document_says_planned
            or remarks_say_planned
            or bool(linked_ids & planned_footnote_ids)
            or bool(planned_footnote_ids and not linked_ids)
        )
        if planned:
            result.skipped_plan += 1
            continue

        shares = to_float(
            child_value(transaction, "transactionAmounts", "transactionShares")
        )
        price = to_float(
            child_value(transaction, "transactionAmounts", "transactionPricePerShare")
        )
        if not shares or shares <= 0 or price is None or price <= 0:
            # No price means we cannot say what it cost, so it cannot clear a
            # dollar threshold. Usually a gift or a plan purchase filed oddly.
            result.skipped_no_price += 1
            continue

        raw_date = child_value(transaction, "transactionDate") or ""
        try:
            transaction_date = datetime.strptime(raw_date[:10], "%Y-%m-%d").date()
        except ValueError:
            transaction_date = accepted_at.date()

        owned_after = to_float(
            child_value(
                transaction, "postTransactionAmounts", "sharesOwnedFollowingTransaction"
            )
        )
        owned_before = None if owned_after is None else owned_after - shares
        security_title = (child_value(transaction, "securityTitle") or "").strip()
        ownership = (
            child_value(transaction, "ownershipNature", "directOrIndirectOwnership")
            or "D"
        ).strip().upper()

        result.purchases.append(
            Purchase(
                accession=ref.accession,
                url=ref.index_url,
                issuer_cik=issuer_cik.lstrip("0") or issuer_cik,
                issuer_name=issuer_name,
                ticker=ticker,
                owner_cik=owner_cik,
                owner_name=owner_name,
                title=owner_title,
                role_weight=owner_weight,
                shares=shares,
                price=price,
                value_usd=shares * price,
                transaction_date=transaction_date,
                accepted_at=accepted_at,
                shares_owned_before=owned_before,
                shares_owned_after=owned_after,
                security_title=security_title,
                ownership=ownership,
            )
        )
    return result


# ---------------------------------------------------------------------------
# Step three: group, filter, score
# ---------------------------------------------------------------------------


@dataclass
class InsiderLine:
    """Everything one insider bought at one company, across their filings."""

    name: str
    title: str
    role_weight: float
    shares: float = 0.0
    value_usd: float = 0.0
    first_shares_owned_before: float | None = None
    is_new_position: bool = False
    transaction_dates: list[date] = field(default_factory=list)
    accessions: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    accepted_at: datetime | None = None
    security_title: str = ""
    is_common_stock: bool = True
    held_indirectly: bool = False

    @property
    def price(self) -> float:
        return self.value_usd / self.shares if self.shares else 0.0

    @property
    def pct_increase(self) -> float | None:
        if self.first_shares_owned_before is None or self.first_shares_owned_before <= 0:
            return None
        return self.shares / self.first_shares_owned_before * 100.0

    @property
    def latest_date(self) -> date:
        return max(self.transaction_dates)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "shares": round(self.shares, 4),
            "price": round(self.price, 4),
            "value_usd": round(self.value_usd, 2),
            "pct_increase_in_holding": (
                None if self.pct_increase is None else round(self.pct_increase, 2)
            ),
            "shares_owned_before": (
                None
                if self.first_shares_owned_before is None
                else round(self.first_shares_owned_before, 4)
            ),
            "is_new_position": self.is_new_position,
            "security_title": self.security_title,
            "is_common_stock": self.is_common_stock,
            "held_indirectly": self.held_indirectly,
            "role_weight": self.role_weight,
            "transaction_date": self.latest_date.isoformat(),
            "filing_accepted_at": (
                self.accepted_at.isoformat() if self.accepted_at else None
            ),
            "accession_number": self.accessions[0] if self.accessions else None,
            "url": self.urls[0] if self.urls else None,
        }


def build_insider_lines(purchases: list[Purchase]) -> list[InsiderLine]:
    """Fold a company's purchases down to one row per person."""
    by_person: dict[str, list[Purchase]] = {}
    for purchase in purchases:
        key = purchase.owner_cik or purchase.owner_name.upper()
        by_person.setdefault(key, []).append(purchase)

    lines = []
    for group in by_person.values():
        group.sort(key=lambda p: (p.transaction_date, p.accepted_at))
        first = group[0]
        biggest = max(group, key=lambda p: p.value_usd)
        line = InsiderLine(
            name=first.owner_name,
            title=first.title,
            role_weight=max(p.role_weight for p in group),
            first_shares_owned_before=first.shares_owned_before,
            is_new_position=first.is_new_position,
            security_title=biggest.security_title,
            is_common_stock=all(p.is_common_stock for p in group),
            held_indirectly=any(p.ownership == "I" for p in group),
        )
        for purchase in group:
            line.shares += purchase.shares
            line.value_usd += purchase.value_usd
            line.transaction_dates.append(purchase.transaction_date)
            if purchase.accession not in line.accessions:
                line.accessions.append(purchase.accession)
                line.urls.append(purchase.url)
            if line.accepted_at is None or purchase.accepted_at > line.accepted_at:
                line.accepted_at = purchase.accepted_at
        lines.append(line)

    lines.sort(key=lambda line: line.value_usd, reverse=True)
    return lines


def largest_cluster(lines: list[InsiderLine]) -> int:
    """How many different insiders bought inside one ten-trading-day stretch.

    Slide a window over the buy dates and count the distinct people caught in
    the widest one. Two people buying the same week is the pattern the strategy
    is looking for.
    """
    if not lines:
        return 0
    dated = sorted(
        ((line.latest_date, index) for index, line in enumerate(lines)),
        key=lambda pair: pair[0],
    )
    best = 1
    for anchor_date, _ in dated:
        inside = {
            index
            for day, index in dated
            if weekdays_between(anchor_date, day) <= CLUSTER_WINDOW_TRADING_DAYS
        }
        best = max(best, len(inside))
    return best


def build_reasons(
    lines: list[InsiderLine],
    cluster_count: int,
    total_value: float,
    role_weight_max: float,
    ticker: str,
) -> list[str]:
    reasons: list[str] = []
    people = "insider" if len(lines) == 1 else "insiders"
    reasons.append(
        f"{len(lines)} {people} bought {money(total_value)} of {ticker or 'the stock'} "
        f"on the open market with their own cash"
    )
    if cluster_count >= 2:
        reasons.append(
            f"This is a cluster: {cluster_count} different insiders bought within "
            f"{CLUSTER_WINDOW_TRADING_DAYS} trading days of each other, which is the "
            "pattern the strategy is built around"
        )
        # Six people paying an identical price on an identical day is a company
        # scheme running, not six people each deciding the stock is cheap. It
        # still counts, but Claude should see it before treating it as six
        # independent opinions.
        days = {line.latest_date for line in lines}
        prices = [line.price for line in lines if line.price]
        same_price = prices and (max(prices) - min(prices)) <= 0.005 * max(prices)
        if len(days) == 1 and same_price:
            reasons.append(
                "Careful: every one of them bought on the same day at the same "
                "price, which usually means a company share scheme rather than "
                f"{cluster_count} people separately deciding to buy"
            )
    for line in lines[:4]:
        piece = (
            f"{line.name} ({line.title}) bought {line.shares:,.0f} shares at about "
            f"${line.price:,.2f}, worth {money(line.value_usd)}, on "
            f"{line.latest_date.isoformat()}"
        )
        if line.is_new_position:
            piece += ", and the filing shows no holding of this security beforehand"
        elif line.pct_increase is not None:
            # Below one percent, rounding to whole numbers would print "0 percent"
            # for somebody who did in fact buy something.
            shown = (
                f"{line.pct_increase:.2f}"
                if line.pct_increase < 1
                else f"{line.pct_increase:.0f}"
            )
            piece += f", lifting their holding by {shown} percent"
        if line.held_indirectly:
            piece += ". The shares are held indirectly, through a trust or a company"
        reasons.append(piece)

    odd = [line for line in lines if not line.is_common_stock]
    if odd:
        titles = sorted({line.security_title for line in odd if line.security_title})
        reasons.append(
            "Careful: the buying was in "
            + ", ".join(titles)
            + f", not the ordinary shares that trade under {ticker or 'this ticker'}. "
            "Treat this as a weaker signal, or skip it."
        )
    if role_weight_max >= ROLE_WEIGHT_CEO_CFO:
        reasons.append(
            "The chief executive or finance chief is among the buyers, the two "
            "roles with the clearest view of the numbers"
        )
    elif role_weight_max >= ROLE_WEIGHT_OTHER_OFFICER:
        reasons.append("A serving officer of the company is among the buyers")
    reasons.append(
        "None of these buys were made under a pre-scheduled Rule 10b5-1 plan, so "
        "each was a decision taken on the day"
    )

    # Insiders are supposed to file within two business days. Some file months
    # late, and a buy from six weeks ago is old news the market has already had.
    lags = [
        weekdays_between(line.latest_date, line.accepted_at.date())
        for line in lines
        if line.accepted_at is not None
    ]
    if lags and min(lags) > CLUSTER_WINDOW_TRADING_DAYS:
        reasons.append(
            f"Careful: the buying happened about {min(lags)} trading days before "
            "the filing reached the SEC, so this is late news rather than fresh news"
        )
    return reasons


def compute_score(
    total_value: float, best_pct: float, cluster_count: int, role_weight_max: float
) -> float:
    """One number that ranks the shortlist.

    Four things multiplied together, all of them from the strategy document:
    who bought, how much, how big a change it made to what they already held,
    and whether anybody bought alongside them. Bigger is more interesting.
    """
    size_term = math.log10(1.0 + total_value / MIN_VALUE_ALONE)
    conviction_term = 1.0 + min(best_pct, PCT_INCREASE_CAP) / 100.0
    cluster_term = 1.0 + 0.5 * (max(cluster_count, 1) - 1)
    return 10.0 * role_weight_max * size_term * conviction_term * cluster_term


# ---------------------------------------------------------------------------
# The whole sweep
# ---------------------------------------------------------------------------


class InsiderSweep:
    def __init__(self, client: EdgarClient, since: datetime, limit: int | None) -> None:
        self.client = client
        self.since = since
        self.limit = limit
        self.counts: dict[str, int] = {}
        self.warnings: list[str] = []
        self.problems: dict[str, int] = {}
        self.sources_used: list[str] = []

    def note(self, message: str) -> None:
        log.warning(message)
        self.warnings.append(message)

    def gather_refs(self) -> list[FilingRef]:
        until = datetime.now(EASTERN)
        index_refs, index_days = daily_index_refs(
            self.client, self.since, until, self.warnings
        )
        self.counts["from_daily_index"] = len(index_refs)
        self.counts["daily_index_days"] = index_days
        if index_days:
            self.sources_used.append(
                f"daily index files for {index_days} trading day(s)"
            )

        latest = feed_refs(self.client, self.since, self.warnings)
        fresh = {
            accession: ref
            for accession, ref in latest.items()
            if accession not in index_refs
        }
        self.counts["from_feed_only"] = len(fresh)
        if latest:
            self.sources_used.append("the latest-filings feed as a top-up")
        merged = dict(index_refs)
        merged.update(fresh)

        if not merged:
            return []
        refs = list(merged.values())
        # Newest first, so a --limit keeps the freshest filings.
        refs.sort(key=lambda ref: (ref.accepted_hint or datetime.min.replace(
            tzinfo=EASTERN
        )), reverse=True)
        if self.limit and len(refs) > self.limit:
            self.note(
                f"There were {len(refs)} filings to read but --limit is "
                f"{self.limit}, so the older ones were skipped"
            )
            refs = refs[: self.limit]
        return refs

    def read_filings(self, refs: list[FilingRef]) -> list[Purchase]:
        purchases: list[Purchase] = []
        parsed = 0
        downloaded = 0
        skipped_before_since = 0
        plan_skips = 0
        no_price_skips = 0

        def fetch(ref: FilingRef) -> tuple[FilingRef, str | None]:
            return ref, self.client.get_cached(
                ref.submission_url, f"{ref.accession}.txt"
            )

        with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
            for ref, raw in pool.map(fetch, refs):
                if raw is None:
                    self.problems["could not download the filing"] = (
                        self.problems.get("could not download the filing", 0) + 1
                    )
                    continue
                downloaded += 1
                try:
                    result = parse_filing(ref, raw)
                except Exception as exc:  # one bad filing must not stop the sweep
                    log.debug("Filing %s blew up: %s", ref.accession, exc)
                    self.problems["the filing could not be read"] = (
                        self.problems.get("the filing could not be read", 0) + 1
                    )
                    continue
                if result.problem:
                    self.problems[result.problem] = (
                        self.problems.get(result.problem, 0) + 1
                    )
                if not result.parsed:
                    continue
                parsed += 1
                plan_skips += result.skipped_plan
                no_price_skips += result.skipped_no_price
                for purchase in result.purchases:
                    if purchase.accepted_at < self.since:
                        skipped_before_since += 1
                        continue
                    purchases.append(purchase)

        self.counts["filings_listed"] = len(refs)
        self.counts["filings_downloaded"] = downloaded
        self.counts["filings_parsed"] = parsed
        self.counts["purchase_rows_before_since"] = skipped_before_since
        self.counts["purchases_dropped_as_10b5_1_plan"] = plan_skips
        self.counts["purchases_dropped_with_no_price"] = no_price_skips
        return purchases

    def shortlist(self, purchases: list[Purchase]) -> list[dict[str, Any]]:
        self.counts["purchases_found"] = len(purchases)

        with_ticker = [p for p in purchases if p.ticker]
        self.counts["purchases_dropped_no_ticker"] = len(purchases) - len(with_ticker)

        by_issuer: dict[str, list[Purchase]] = {}
        for purchase in with_ticker:
            by_issuer.setdefault(purchase.issuer_cik or purchase.ticker, []).append(
                purchase
            )
        self.counts["issuers_with_buying"] = len(by_issuer)

        insider_rows = 0
        candidates: list[dict[str, Any]] = []
        for issuer_key, issuer_purchases in by_issuer.items():
            # One row per person, so somebody who bought in three goes over two
            # days is judged on what they spent in total, not on each slice.
            lines = build_insider_lines(issuer_purchases)
            insider_rows += len(lines)

            # The rule from the strategy document: a lone buy has to be worth
            # $25,000, but inside a cluster of two or more people $10,000 counts.
            # So try the generous floor first, see whether a real cluster forms,
            # and fall back to the strict floor if it does not.
            in_cluster = [line for line in lines if line.value_usd >= MIN_VALUE_IN_CLUSTER]
            cluster_count = largest_cluster(in_cluster)
            if cluster_count >= 2:
                kept = in_cluster
            else:
                kept = [line for line in lines if line.value_usd >= MIN_VALUE_ALONE]
                cluster_count = largest_cluster(kept)
            if not kept:
                continue

            # Take the ticker and name off the biggest buy, so a company that
            # spells itself two ways across filings is labelled by its main one.
            headline = max(issuer_purchases, key=lambda p: p.value_usd)
            total_value = sum(line.value_usd for line in kept)
            role_weight_max = max(line.role_weight for line in kept)
            pct_values = [
                PCT_INCREASE_CAP if line.is_new_position else (line.pct_increase or 0.0)
                for line in kept
            ]
            best_pct = max(pct_values) if pct_values else 0.0
            score = compute_score(total_value, best_pct, cluster_count, role_weight_max)

            candidates.append(
                {
                    "ticker": headline.ticker,
                    "cik": issuer_key,
                    "issuer_name": headline.issuer_name,
                    "insiders": [line.as_dict() for line in kept],
                    "cluster_count": cluster_count,
                    "role_weight_max": role_weight_max,
                    "total_value_usd": round(total_value, 2),
                    "score": round(score, 2),
                    "reasons": build_reasons(
                        kept, cluster_count, total_value, role_weight_max, headline.ticker
                    ),
                    # Filled in later by the trading loop from IBKR. This script
                    # has no market data of any kind.
                    "last_price": None,
                    "avg_volume_20d": None,
                    "dollar_volume_ratio": None,
                    "enrichment_note": (
                        "Price and volume are left empty on purpose. This sweep only "
                        "reads SEC filings. The trading loop fills these three fields "
                        "from IBKR before the price floor and liquidity floor are "
                        "applied."
                    ),
                }
            )

        self.counts["insider_rows"] = insider_rows
        self.counts["after_filters"] = len(candidates)
        candidates.sort(key=lambda row: row["score"], reverse=True)
        shortlist = candidates[:MAX_CANDIDATES]
        self.counts["shortlisted"] = len(shortlist)
        return shortlist

    def run(self) -> tuple[dict[str, Any], bool]:
        refs = self.gather_refs()
        if not refs:
            reachable = self.client.requests_made > self.client.failures
            if not reachable:
                return {}, False
            self.note(
                "EDGAR answered but listed no Form 4 filings in this window. That "
                "is normal over a weekend or a market holiday."
            )
            return self.build_output([]), True

        purchases = self.read_filings(refs)
        if self.counts.get("filings_downloaded", 0) == 0:
            return {}, False
        shortlist = self.shortlist(purchases)
        return self.build_output(shortlist), True

    def build_output(self, shortlist: list[dict[str, Any]]) -> dict[str, Any]:
        now = datetime.now(EASTERN)
        if self.problems:
            for problem, count in sorted(
                self.problems.items(), key=lambda pair: -pair[1]
            ):
                self.warnings.append(f"{count} filing(s) skipped because {problem}")
        return {
            "timestamp": now.isoformat(),
            "timestamp_utc": now.astimezone(UTC).isoformat(),
            "since": self.since.isoformat(),
            "source": ", plus ".join(self.sources_used) or "nothing reachable",
            "filings_scanned": self.counts.get("filings_downloaded", 0),
            "purchases_found": self.counts.get("purchases_found", 0),
            "after_filters": self.counts.get("after_filters", 0),
            "thresholds": {
                "min_value_alone_usd": MIN_VALUE_ALONE,
                "min_value_in_cluster_usd": MIN_VALUE_IN_CLUSTER,
                "cluster_window_trading_days": CLUSTER_WINDOW_TRADING_DAYS,
                "max_candidates": MAX_CANDIDATES,
                "role_weights": {
                    "ceo_or_cfo": ROLE_WEIGHT_CEO_CFO,
                    "other_officer": ROLE_WEIGHT_OTHER_OFFICER,
                    "director": ROLE_WEIGHT_DIRECTOR,
                    "ten_percent_owner": ROLE_WEIGHT_TEN_PERCENT,
                },
            },
            "counts": dict(self.counts),
            "edgar_requests_made": self.client.requests_made,
            "edgar_cache_hits": self.client.cache_hits,
            "edgar_request_failures": self.client.failures,
            "warnings": list(self.warnings),
            "candidates": shortlist,
        }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    today = datetime.now(EASTERN).date().isoformat()
    default_out = PROJECT_ROOT / "output" / f"insider_shortlist_{today}.json"
    parser = argparse.ArgumentParser(
        description=(
            "Find companies whose executives and directors have been buying their "
            "own stock on the open market, using SEC Form 4 filings."
        )
    )
    parser.add_argument(
        "--since",
        type=parse_since,
        default=None,
        help=(
            "Only look at filings EDGAR accepted at or after this moment, for "
            "example 2026-09-04T00:00. A time with no zone is read as US Eastern. "
            "Default: midnight Eastern this morning."
        ),
    )
    parser.add_argument(
        "--out",
        default=str(default_out),
        help="Where to write the shortlist JSON. Default: %(default)s",
    )
    parser.add_argument(
        "--cache-dir",
        default=str(CACHE_DIR),
        help="Where downloaded filings are kept so re-runs are cheap. Default: %(default)s",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Read at most this many filings, newest first. An escape hatch for a "
            "quick test, since a full three-day sweep is a few thousand filings."
        ),
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

    since = args.since or datetime.now(EASTERN).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    log.info(
        "Looking for Form 4 filings EDGAR accepted since %s Eastern",
        since.isoformat(timespec="minutes"),
    )
    log.info(
        "Keeping open-market purchases worth %s on their own, or %s each when two "
        "or more insiders bought within %d trading days",
        money(MIN_VALUE_ALONE),
        money(MIN_VALUE_IN_CLUSTER),
        CLUSTER_WINDOW_TRADING_DAYS,
    )

    client = EdgarClient(Path(args.cache_dir).expanduser(), MAX_REQUESTS_PER_SECOND)
    sweep = InsiderSweep(client, since, args.limit)

    try:
        result, reachable = sweep.run()
    except KeyboardInterrupt:
        log.warning("Interrupted")
        return 0
    except Exception as exc:
        log.exception("The sweep failed partway through: %s", exc)
        result = sweep.build_output([])
        result["warnings"].append(f"The sweep failed partway through: {exc}")
        reachable = client.requests_made > client.failures

    if not reachable:
        log.error(
            "Could not reach SEC EDGAR at www.sec.gov. %d request(s) tried, all "
            "failed. Nothing was written.",
            client.requests_made,
        )
        return 1

    out_path = Path(args.out).expanduser()
    if not out_path.is_absolute():
        out_path = (Path.cwd() / out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2) + "\n")

    log.info("Counts: %s", json.dumps(result.get("counts", {})))
    log.info(
        "Read %d filing(s) from %s using %d EDGAR request(s) and %d cached copies",
        result.get("filings_scanned", 0),
        result.get("source", "nowhere"),
        result.get("edgar_requests_made", 0),
        result.get("edgar_cache_hits", 0),
    )
    log.info(
        "Found %d qualifying purchase row(s), %d compan(ies) cleared the filters, "
        "wrote the top %d to %s",
        result.get("purchases_found", 0),
        result.get("after_filters", 0),
        len(result.get("candidates", [])),
        out_path,
    )
    for candidate in result.get("candidates", [])[:5]:
        log.info(
            "  %-6s score %6.1f  %2d insider(s)  %s  %s",
            candidate["ticker"],
            candidate["score"],
            candidate["cluster_count"],
            money(candidate["total_value_usd"]).rjust(12),
            candidate["issuer_name"][:44],
        )
    for warning in result.get("warnings", []):
        log.info("Note: %s", warning)
    return 0


if __name__ == "__main__":
    sys.exit(main())

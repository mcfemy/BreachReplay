import csv
import io
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup

from app.core.logging import get_logger

logger = get_logger(__name__)

_HEADERS = {"User-Agent": "BreachReplay/1.0 research@breachreplay.io"}

CISA_KEV_JSON = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
SEC_EFTS_API = (
    "https://efts.sec.gov/LATEST/search-index"
    "?q=%22cybersecurity+incident%22"
    "&forms=8-K"
    "&dateRange=custom"
    "&startdt={start}"
    "&enddt={end}"
)
HHS_BREACH_PORTAL_URL = "https://ocrportal.hhs.gov/ocr/breach/breach_report.jsf"
HHS_BREACH_CSV_URL = HHS_BREACH_PORTAL_URL  # used as the source URL reference in saved scenarios
RSS_FEEDS = {
    "krebs": "https://krebsonsecurity.com/feed/",
    "sans": "https://isc.sans.edu/rssfeed.xml",
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _get(url: str, timeout: int = 20, stream: bool = False) -> Optional[requests.Response]:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout, stream=stream)
        resp.raise_for_status()
        return resp
    except Exception:
        logger.exception("HTTP fetch failed", extra={"url": url})
        return None


def fetch_plain_text(url: str) -> Optional[str]:
    resp = _get(url)
    if not resp:
        return None
    if resp.headers.get("content-type", "").startswith("text/plain"):
        return resp.text
    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


# ---------------------------------------------------------------------------
# CISA — Known Exploited Vulnerabilities catalog
# ---------------------------------------------------------------------------

def search_cisa_advisories(limit: int = 10, days_back: int = 90) -> list[str]:
    """
    Return advisory URLs for recently-added KEV entries that are linked to known
    ransomware campaigns.  The CISA advisory listing page uses JavaScript rendering
    so we use the public KEV JSON feed instead, which is updated daily.

    Returns a list of advisory/vendor note URLs to pass to process_advisory_url.
    """
    resp = _get(CISA_KEV_JSON)
    if not resp:
        return []
    try:
        data = resp.json()
    except Exception:
        logger.exception("CISA KEV JSON parse failed")
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).date()
    urls: list[str] = []

    for vuln in data.get("vulnerabilities", []):
        try:
            added = datetime.strptime(vuln["dateAdded"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue

        if added < cutoff:
            continue

        # Prefer ransomware-linked entries — higher scenario quality
        is_ransomware = vuln.get("knownRansomwareCampaignUse", "") == "Known"

        notes = vuln.get("notes", "")
        # Extract the first http URL from the notes field
        note_urls = re.findall(r"https?://[^\s;]+", notes)
        if note_urls:
            urls.append(note_urls[0].rstrip(" ;"))
        elif is_ransomware:
            # No direct URL — synthesise a fake "URL" carrying the structured text
            urls.append(f"cisa-kev://{vuln['cveID']}")

        if len(urls) >= limit:
            break

    return urls


def fetch_cisa_kev_text(cve_id: str) -> Optional[str]:
    """Build a narrative text block from KEV catalog data for a given CVE."""
    resp = _get(CISA_KEV_JSON)
    if not resp:
        return None
    try:
        data = resp.json()
    except Exception:
        return None

    for vuln in data.get("vulnerabilities", []):
        if vuln.get("cveID") == cve_id:
            return (
                f"CISA Known Exploited Vulnerability: {vuln.get('vulnerabilityName', cve_id)}\n"
                f"CVE ID: {cve_id}\n"
                f"Affected Vendor/Product: {vuln.get('vendorProject', 'Unknown')} — {vuln.get('product', 'Unknown')}\n"
                f"Date Added to KEV: {vuln.get('dateAdded', 'Unknown')}\n"
                f"Known Ransomware Campaign Use: {vuln.get('knownRansomwareCampaignUse', 'Unknown')}\n"
                f"Description: {vuln.get('shortDescription', 'No description available.')}\n"
                f"Required Action: {vuln.get('requiredAction', 'See CISA advisory.')}\n"
                f"CWE: {', '.join(vuln.get('cwes', []))}\n"
                f"Notes: {vuln.get('notes', '')}\n"
            )
    return None


# ---------------------------------------------------------------------------
# SEC EDGAR 8-K
# ---------------------------------------------------------------------------

def search_sec_8k_filings(start_date: str, end_date: str, limit: int = 10) -> list[dict]:
    """Search SEC EDGAR EFTS for cybersecurity-related 8-K filings."""
    url = SEC_EFTS_API.format(start=start_date, end=end_date)
    resp = _get(url)
    if not resp:
        return []
    try:
        data = resp.json()
    except Exception:
        logger.exception("SEC EFTS JSON parse failed")
        return []

    results = []
    for hit in data.get("hits", {}).get("hits", [])[:limit]:
        src = hit.get("_source", {})

        # EFTS uses 'adsh' for accession number and 'ciks' (list) for entity IDs
        accession = src.get("adsh", "")
        ciks = src.get("ciks", [])
        entity_id = ciks[0].lstrip("0") if ciks else ""

        display_names = src.get("display_names", [])
        entity_name = display_names[0].split("(")[0].strip() if display_names else "Unknown"

        if not accession or not entity_id:
            continue

        results.append({
            "entity_name": entity_name,
            "file_date": src.get("file_date", ""),
            "accession_no": accession,
            "entity_id": entity_id,
        })
    return results


def fetch_sec_filing_text(entity_id: str, accession_no: str) -> Optional[str]:
    """
    Fetch readable text from an SEC EDGAR 8-K filing.

    Uses the data.sec.gov submissions API (designed for programmatic access,
    no rate-limiting concerns) to resolve the primary document filename,
    then fetches the actual filing HTML.
    """
    # Pad CIK to 10 digits as required by the submissions API
    cik_padded = str(entity_id).zfill(10)
    submissions_url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"

    resp = _get(submissions_url)
    if not resp:
        return None

    try:
        data = resp.json()
    except Exception:
        logger.exception("SEC submissions JSON parse failed", extra={"cik": entity_id})
        return None

    recent = data.get("filings", {}).get("recent", {})
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    # Find the primary document for our target accession
    primary_doc = None
    for i, acc in enumerate(accessions):
        if acc == accession_no:
            primary_doc = primary_docs[i] if i < len(primary_docs) else None
            break

    if not primary_doc:
        logger.warning("SEC: primary document not found for accession", extra={"accession_no": accession_no})
        return None

    accession_nodash = accession_no.replace("-", "")
    doc_url = (
        f"https://www.sec.gov/Archives/edgar/data/{entity_id}"
        f"/{accession_nodash}/{primary_doc}"
    )

    import time
    time.sleep(0.15)  # SEC rate limit: max 10 req/sec; 150ms keeps us safe
    return fetch_plain_text(doc_url)


# ---------------------------------------------------------------------------
# HHS Breach Portal
# ---------------------------------------------------------------------------

def fetch_hhs_breach_csv(min_individuals: int = 10000) -> list[dict]:
    """
    Scrape the HHS OCR Breach Portal HTML table for significant healthcare breaches.
    The portal is a Java Server Faces app — the table renders in HTML without JavaScript.
    Falls back gracefully if the portal is unreachable.
    """
    resp = _get(HHS_BREACH_PORTAL_URL, timeout=30)
    if not resp:
        logger.warning("HHS breach portal unreachable; skipping HHS source")
        return []

    try:
        soup = BeautifulSoup(resp.text, "lxml")

        # The OCR portal renders a <table> with breach rows
        table = soup.find("table", id=re.compile(r"breach", re.I)) or soup.find("table")
        if not table:
            logger.warning("HHS breach portal: no table found in HTML response")
            return []

        rows = table.find_all("tr")
        if len(rows) < 2:
            logger.warning("HHS breach portal: table has fewer than 2 rows")
            return []

        # Extract headers from first row
        headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]

        def col(cells, *names):
            for name in names:
                for i, h in enumerate(headers):
                    if name.lower() in h.lower() and i < len(cells):
                        return cells[i].get_text(strip=True)
            return ""

        breaches = []
        for row in rows[1:]:
            cells = row.find_all("td")
            if not cells:
                continue
            try:
                count_str = col(cells, "Individuals", "Affected").replace(",", "")
                count = int(count_str) if count_str.isdigit() else 0
            except (ValueError, AttributeError):
                count = 0

            if count < min_individuals:
                continue

            name = col(cells, "Name", "Entity", "Organization") or "Unknown Organization"
            state = col(cells, "State")
            breach_type = col(cells, "Type of Breach", "Breach Type")
            location = col(cells, "Location")
            date_str = col(cells, "Date", "Reported", "Submission")

            summary = (
                f"Healthcare data breach reported to HHS OCR. "
                f"Entity: {name} ({state}). "
                f"Type of breach: {breach_type}. "
                f"Location of breached information: {location}. "
                f"Individuals affected: {count:,}. "
                f"Breach reported on {date_str}."
            )

            breaches.append({
                "name": name,
                "state": state,
                "individuals": count,
                "date": date_str,
                "source_reference": f"hhs-{re.sub(r'[^a-z0-9]', '-', name.lower())[:60]}-{date_str[:10]}",
                "summary": summary,
            })

        return breaches
    except Exception:
        logger.exception("HHS breach portal parse failed")
        return []


# ---------------------------------------------------------------------------
# RSS Feeds (Krebs on Security / SANS ISC)
# ---------------------------------------------------------------------------

def fetch_rss_article_urls(feed_url: str, limit: int = 5) -> list[str]:
    """Parse an RSS or Atom feed and return article URLs."""
    resp = _get(feed_url)
    if not resp:
        return []
    try:
        root = ET.fromstring(resp.content)
        urls: list[str] = []

        # RSS 2.0: channel/item/link
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for item in root.iter("item"):
            link = item.find("link")
            if link is not None and link.text:
                urls.append(link.text.strip())
            if len(urls) >= limit:
                break

        # Atom: feed/entry/link[@rel="alternate"]
        if not urls:
            for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
                for link in entry.findall("{http://www.w3.org/2005/Atom}link"):
                    href = link.get("href", "")
                    if href and link.get("rel", "alternate") == "alternate":
                        urls.append(href)
                        break
                if len(urls) >= limit:
                    break

        return urls
    except Exception:
        logger.exception("RSS feed parse failed", extra={"feed_url": feed_url})
        return []


# ---------------------------------------------------------------------------
# Deduplication helper
# ---------------------------------------------------------------------------

def is_source_already_processed(source_reference: str) -> bool:
    """Return True if a scenario with this source_reference already exists in the DB."""
    from sqlalchemy import select
    from app.db.session import SyncSessionLocal
    from app.models.scenario import Scenario

    try:
        with SyncSessionLocal() as db:
            result = db.execute(
                select(Scenario.id).where(Scenario.source_reference == source_reference).limit(1)
            )
            return result.scalar_one_or_none() is not None
    except Exception:
        logger.exception("Deduplication check failed", extra={"source_reference": source_reference})
        return False

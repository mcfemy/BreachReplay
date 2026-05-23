import requests
from bs4 import BeautifulSoup
import re
from typing import Optional

from app.core.logging import get_logger


logger = get_logger(__name__)


CISA_ADVISORY_BASE = "https://www.cisa.gov/news-events/cybersecurity-advisories"
SEC_EFTS_API = "https://efts.sec.gov/LATEST/search-index?q=%22cybersecurity+incident%22&dateRange=custom&startdt={start}&enddt={end}&forms=8-K"
HHS_BREACH_PORTAL_CSV = "https://ocrportal.hhs.gov/ocr/breach/breach_report.jsf"


def fetch_cisa_advisory(advisory_url: str) -> Optional[str]:
    try:
        resp = requests.get(advisory_url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        content_div = soup.find("div", class_="c-wysiwyg") or soup.find("article") or soup.find("main")
        if content_div:
            return content_div.get_text(separator="\n", strip=True)
        return soup.get_text(separator="\n", strip=True)
    except Exception as e:
        logger.exception("Error fetching CISA advisory", extra={"advisory_url": advisory_url})
        return None


def search_cisa_advisories(limit: int = 10) -> list:
    try:
        resp = requests.get(CISA_ADVISORY_BASE, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/cybersecurity-advisories/aa" in href:
                full_url = href if href.startswith("http") else f"https://www.cisa.gov{href}"
                if full_url not in links:
                    links.append(full_url)
            if len(links) >= limit:
                break
        return links
    except Exception as e:
        logger.exception("Error searching CISA advisories")
        return []


def search_sec_8k_filings(start_date: str, end_date: str) -> list:
    try:
        url = SEC_EFTS_API.format(start=start_date, end=end_date)
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        hits = data.get("hits", {}).get("hits", [])
        results = []
        for hit in hits:
            source = hit.get("_source", {})
            results.append({
                "entity": source.get("entity_name", ""),
                "filing_date": source.get("file_date", ""),
                "url": f"https://www.sec.gov/Archives/edgar/data/{source.get('entity_id', '')}/{source.get('file_num', '')}",
                "accession": source.get("accession_no", ""),
            })
        return results
    except Exception as e:
        logger.exception("Error fetching SEC 8-K filings")
        return []


def fetch_plain_text(url: str) -> Optional[str]:
    try:
        resp = requests.get(url, timeout=20, headers={"User-Agent": "BreachReplay/1.0 research@breachreplay.io"})
        resp.raise_for_status()
        if resp.headers.get("content-type", "").startswith("text/plain"):
            return resp.text
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)
    except Exception as e:
        logger.exception("Error fetching plain text", extra={"url": url})
        return None

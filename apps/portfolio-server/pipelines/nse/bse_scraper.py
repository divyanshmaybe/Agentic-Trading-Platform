# -*- coding: utf-8 -*-
"""Low-latency BSE corporate-announcement poller."""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.parse import quote, urlparse

import requests

PORTFOLIO_SERVER_DIR = Path(__file__).resolve().parents[2]
if str(PORTFOLIO_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(PORTFOLIO_SERVER_DIR))


BSE_BASE_URL = "https://www.bseindia.com"
BSE_API_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
    "?pageno=1&strCat=-1&strPrevDate={date}&strScrip=&strSearch=P"
    "&strToDate={date}&strType=C&subcategory=-1"
)
BSE_PDF_BASE_URL = "https://www.bseindia.com/xml-data/corpfiling/AttachLive"
PROCESSED_ANNOUNCEMENTS_FILE = Path(__file__).with_name(
    "bse_processed_announcements.json"
)

BAGGING_KEYWORDS = [
    "bagging",
    "bag/receiv",
    "order receipt",
    "order win",
    "contract award",
    "letter of award",
    "loa ",
    "work order",
    "purchase order",
    "supply order",
    "project award",
    "order intake",
    "new order",
    "order book",
]

BSE_BAGGING_SUBCATEGORIES = {
    "award of order / receipt of order",
}

BSE_ADVERSE_ORDER_KEYWORDS = {
    "income tax",
    "tax authority",
    "tax demand",
    "demand order",
    "penalty",
    "adjudication",
    "regulatory order",
    "court order",
    "nclt",
    "nclat",
    "gst order",
    "show cause",
}

BSE_RELEVANT_SUBCATEGORIES = {
    "outcome of board meeting",
    "press release / media release",
    "change in management",
    "change in directorate",
    "acquisition",
    "investor presentation",
    "diversification / disinvestment",
    "award of order / receipt of order",
    "appointment of company secretary / compliance officer",
    "resignation of company secretary / compliance officer",
    "resignation of director",
    "resignation of managing director",
    "resignation of chief executive officer (ceo)",
    "resignation of chief financial officer (cfo)",
    "cessation",
    "financial results",
    "monthly business updates",
    "strikes /lockouts / disturbances",
    "updates - corporate insolvency resolution process  (cirp)",
    "outcome without intimation",
    "revision of outcome",
    "press release / media release (revised)",
    "restructuring",
    "sale of shares",
    "scheme of arrangement",
    "liquidation - corporate insolvency resolution process  (cirp)",
    "initiation of corporate insolvency resolution process (cirp) by financial creditors",
    "admission of application by tribunal",
    "appointment of interim resolution professional (irp)",
    "intimation of meeting of committee of creditors",
    "outcome of meeting of committee of creditors",
    "public announcement",
}

_celery_app = None


def _get_celery_app():
    global _celery_app
    if _celery_app is None:
        from celery_app import celery_app

        _celery_app = celery_app
    return _celery_app

RELEVANT_FILE_TYPES = {
    "Outcome of Board Meeting",
    "Press Release",
    "Appointment",
    "Acquisition",
    "Updates",
    "Action(s) initiated or orders passed",
    "Investor Presentation",
    "Sale or Disposal",
    "Bagging/Receiving of Orders/Contracts",
    "Change in Director(s)",
}


def get_session_headers() -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": BSE_BASE_URL + "/",
        "Origin": BSE_BASE_URL,
        "Connection": "keep-alive",
    }


def is_bagging_announcement(
    headline: str, category_name: str, subcategory_name: str = ""
) -> bool:
    text = f"{headline} {category_name} {subcategory_name}".lower()
    if any(keyword in text for keyword in BSE_ADVERSE_ORDER_KEYWORDS):
        return False
    if subcategory_name.strip().lower() in BSE_BAGGING_SUBCATEGORIES:
        return True
    return any(keyword in text for keyword in BAGGING_KEYWORDS)


def _matches_relevant_type(
    headline: str, category_name: str, subcategory_name: str = ""
) -> bool:
    normalized_subcategory = " ".join(
        subcategory_name.strip().lower().split()
    )
    normalized_relevant = {
        " ".join(value.split()) for value in BSE_RELEVANT_SUBCATEGORIES
    }
    if normalized_subcategory in normalized_relevant:
        return True
    if normalized_subcategory not in {"", "general"}:
        return False
    category = category_name.strip().lower()
    if any(category == filing_type.lower() for filing_type in RELEVANT_FILE_TYPES):
        return True

    text = headline.lower()
    relevant_keywords = (
        "board meeting", "press release", "appointment", "resignation",
        "acquisition", "merger", "update", "order", "contract",
        "investor presentation", "sale", "disposal", "director",
    )
    return any(keyword in text for keyword in relevant_keywords)


def normalize_api_announcement(item: Dict) -> Dict:
    scrip_cd = str(item.get("SCRIP_CD") or "").strip()
    nsurl = str(item.get("NSURL") or "").strip()
    if nsurl.lower().startswith(("http://", "https://")):
        path_parts = [
            part for part in urlparse(nsurl).path.split("/") if part
        ]
        symbol = (
            path_parts[-2].upper()
            if len(path_parts) >= 2 and path_parts[-1].isdigit()
            else ""
        )
    else:
        symbol = nsurl
    symbol = symbol or scrip_cd
    attachment_name = str(item.get("ATTACHMENTNAME") or "").strip()
    if attachment_name and not attachment_name.lower().startswith("http"):
        attachment_name = (
            f"{BSE_PDF_BASE_URL}/{quote(Path(attachment_name).name)}"
        )

    headline = str(item.get("HEADLINE") or "").strip()
    category_name = str(
        item.get("CategoryName")
        or item.get("CATEGORYNAME")
        or item.get("SUBCATNAME")
        or ""
    ).strip()
    subcategory_name = str(item.get("SUBCATNAME") or "").strip()
    slno = str(
        item.get("SLNO")
        or item.get("NEWSID")
        or item.get("BSENEWSID")
        or item.get("RECORDID")
        or ""
    ).strip()
    return {
        "slno": slno,
        "symbol": symbol,
        "scrip_cd": scrip_cd,
        "headline": headline,
        "category_name": category_name,
        "subcategory_name": subcategory_name,
        "attachment_name": attachment_name,
        "submission_dt": str(item.get("News_submission_dt") or "").strip(),
        "is_bagging": is_bagging_announcement(
            headline, category_name, subcategory_name
        ),
    }


def load_processed_announcements() -> Tuple[set, set]:
    try:
        with PROCESSED_ANNOUNCEMENTS_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return set(data.get("processed_ids", [])), set(
            data.get("processed_files", [])
        )
    except FileNotFoundError:
        return set(), set()
    except Exception as exc:
        print(f"[WARN] Could not load BSE processed announcements: {exc}")
        return set(), set()


def save_processed_announcements(processed_ids: set, processed_files: set) -> None:
    try:
        data = {
            "processed_ids": sorted(processed_ids),
            "processed_files": sorted(processed_files),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        with PROCESSED_ANNOUNCEMENTS_FILE.open(
            "w", encoding="utf-8"
        ) as file:
            json.dump(data, file, indent=2)
    except Exception as exc:
        print(f"[WARN] Could not save BSE processed announcements: {exc}")


def _dispatch_hot_path(announcement: Dict, detected_at: datetime) -> None:
    """Dispatch with the existing trade-execution payload contract."""
    dispatch_at = datetime.now(timezone.utc)
    payload = {
        "symbol": announcement["symbol"],
        "filing_time": announcement["submission_dt"],
        "signal": 1,
        "explanation": "Bagging order detected — instant execution",
        "confidence": 0.75,
        "generated_at": dispatch_at.isoformat().replace("+00:00", "Z"),
        "source": "bse_filings_pipeline",
        "subject_of_announcement": (
            announcement.get("subcategory_name")
            or announcement["category_name"]
        ),
        "attachment_url": announcement["attachment_name"],
        "date_time_of_submission": announcement["submission_dt"],
        "reference_price": None,
    }
    _get_celery_app().send_task(
        "pipeline.trade_execution.process_signal",
        args=[payload],
        queue="trading",
        priority=10,
    )
    latency_ms = int(
        (datetime.now(timezone.utc) - detected_at).total_seconds() * 1000
    )
    print(
        f"[HOT-PATH] {announcement['symbol']} | "
        f"detected_at={detected_at.isoformat()} | "
        f"dispatch_at={dispatch_at.isoformat()} | latency_ms={latency_ms}"
    )


class BSEScraper:
    def __init__(self, refresh_interval: int = 5) -> None:
        self._refresh_interval = refresh_interval
        self._seen_slnos, self._processed_files = load_processed_announcements()
        self._session = requests.Session()
        self._session.headers.update(get_session_headers())
        self._session_established = False
        self._session_fail_count = 0
        # Import and initialize Celery before the first announcement is
        # detected so framework startup never counts against hot-path latency.
        _get_celery_app()

    def _ensure_session(self) -> None:
        if not self._session_established:
            print("[BSE-POLL] Establishing persistent BSE session")
            response = self._session.get(BSE_BASE_URL, timeout=15)
            response.raise_for_status()
            self._session_established = True
            self._session_fail_count = 0

    def _on_request_error(self, status_code: int) -> None:
        if status_code in (401, 403) or self._session_fail_count > 3:
            self._session_established = False
            self._session_fail_count = 0
        else:
            self._session_fail_count += 1

    def _fetch_api_announcements(self) -> List[Dict]:
        try:
            self._ensure_session()
            date = datetime.now().strftime("%Y%m%d")
            response = self._session.get(BSE_API_URL.format(date=date), timeout=15)
            if response.status_code != 200:
                self._on_request_error(response.status_code)
                print(f"[BSE-POLL] API returned HTTP {response.status_code}")
                return []
            self._session_fail_count = 0
            data = response.json()
            table = data.get("Table", []) if isinstance(data, dict) else []
            return [
                normalize_api_announcement(item)
                for item in table
                if isinstance(item, dict)
            ]
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", 0)
            self._on_request_error(status)
            print(f"[BSE-POLL] Request failed: {exc}")
            return []
        except (ValueError, TypeError) as exc:
            print(f"[BSE-POLL] Invalid API response: {exc}")
            return []

    def run(self) -> None:
        print(
            f"[BSE-POLL] Starting BSE polling every {self._refresh_interval}s"
        )
        while True:
            poll_started = time.perf_counter()
            hot = cold = skipped = new = 0
            announcements = self._fetch_api_announcements()

            for announcement in announcements:
                slno = announcement["slno"]
                if not slno or slno in self._seen_slnos:
                    skipped += 1
                    continue

                detected_at = datetime.now(timezone.utc)
                new += 1

                if announcement["is_bagging"]:
                    try:
                        _dispatch_hot_path(announcement, detected_at)
                        self._seen_slnos.add(slno)
                        hot += 1
                    except Exception as exc:
                        print(
                            f"[HOT-PATH] {announcement['symbol']} | "
                            f"dispatch_error={exc}"
                        )
                    continue

                if not _matches_relevant_type(
                    announcement["headline"],
                    announcement["category_name"],
                    announcement["subcategory_name"],
                ):
                    self._seen_slnos.add(slno)
                    skipped += 1
                    continue

                _get_celery_app().send_task(
                    "pipeline.bse.process_filing",
                    args=[announcement],
                    queue="general",
                    priority=5,
                )
                self._seen_slnos.add(slno)
                if announcement["attachment_name"]:
                    self._processed_files.add(announcement["attachment_name"])
                cold += 1

            save_processed_announcements(
                self._seen_slnos, self._processed_files
            )
            poll_ms = int((time.perf_counter() - poll_started) * 1000)
            print(
                f"[BSE-POLL] total={len(announcements)} | new={new} | "
                f"hot={hot} | cold={cold} | skipped={skipped} | "
                f"poll_ms={poll_ms}"
            )
            time.sleep(self._refresh_interval)


def main() -> None:
    BSEScraper(
        refresh_interval=int(os.getenv("BSE_REFRESH_INTERVAL", "5"))
    ).run()


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
NSE Live Web Scraper - Pathway Implementation

This module scrapes NSE corporate filings announcements in real-time,
filters by relevance using XBRL parsing, and feeds into the sentiment pipeline.
"""

import os
import time
import json
import xml.etree.ElementTree as ET
from typing import Optional, Dict, List, Tuple
from datetime import datetime
import requests
import pathway as pw
from pathway.io.python import ConnectorSubject


# Relevant file types and their impact
RELEVANT_FILE_TYPES = {
    "Outcome of Board Meeting": {"positive": True, "negative": True},
    "Press Release": {"positive": True, "negative": False},
    "Appointment": {"positive": True, "negative": True},
    "Acquisition": {"positive": True, "negative": True},
    "Updates": {"positive": True, "negative": True},
    "Action(s) initiated or orders passed": {"positive": True, "negative": True},
    "Investor Presentation": {"positive": True, "negative": True},
    "Sale or Disposal": {"positive": True, "negative": True},
    "Bagging/Receiving of Orders/Contracts": {"positive": True, "negative": True},
    "Change in Director(s)": {"positive": True, "negative": True},
}

NSE_BASE_URL = "https://www.nseindia.com"
NSE_ANNOUNCEMENTS_URL = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
NSE_API_URL = "https://www.nseindia.com/api/corporate-announcements?index=equities"


class NSEAnnouncementSchema(pw.Schema):
    """Schema for NSE announcement data"""
    seq_id: str = pw.column_definition(primary_key=True)  # seq_id is unique per announcement
    symbol: str
    desc: str
    dt: str
    attchmntFile: str
    sm_name: str
    sm_isin: str
    an_dt: str
    sort_date: str
    attchmntText: str
    fileSize: str


def get_session_headers() -> Dict[str, str]:
    """Get session headers for NSE website"""
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
        "Origin": "https://www.nseindia.com",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Cache-Control": "no-cache",
    }
    
    # Note: requests library will automatically decompress Brotli if 'brotli' or 'brotlipy' package is installed


# Removed Selenium/browser code and HTML parsing - now using API endpoint only


def fetch_xbrl_content(xbrl_url: str) -> Optional[Dict[str, str]]:
    """Fetch and parse XBRL content"""
    try:
        if not xbrl_url:
            return None
        
        session = requests.Session()
        headers = get_session_headers()
        
        # Ensure full URL
        if not xbrl_url.startswith('http'):
            xbrl_url = NSE_BASE_URL + xbrl_url
        
        response = session.get(xbrl_url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # Parse XML
        root = ET.fromstring(response.content)
        
        # Define namespaces
        namespaces = {
            'xbrli': 'http://www.xbrl.org/2003/instance',
            'in-capmkt': 'http://www.sebi.gov.in/xbrl/2025-05-28/in-capmkt'
        }
        
        # Extract relevant fields
        xbrl_data = {}
        
        # Symbol
        symbol_elem = root.find('.//in-capmkt:NSESymbol', namespaces)
        if symbol_elem is not None:
            xbrl_data['symbol'] = symbol_elem.text or ""
        
        # Company name
        company_elem = root.find('.//in-capmkt:NameOfTheCompany', namespaces)
        if company_elem is not None:
            xbrl_data['company_name'] = company_elem.text or ""
        
        # Subject (file type)
        subject_elem = root.find('.//in-capmkt:SubjectOfAnnouncement', namespaces)
        if subject_elem is not None:
            xbrl_data['subject'] = subject_elem.text or ""
        
        # Description
        desc_elem = root.find('.//in-capmkt:DescriptionOfAnnouncement', namespaces)
        if desc_elem is not None:
            xbrl_data['description'] = desc_elem.text or ""
        
        # Attachment URL
        attachment_elem = root.find('.//in-capmkt:AttachmentURL', namespaces)
        if attachment_elem is not None:
            xbrl_data['attachment_url'] = attachment_elem.text or ""
        
        # Date and time
        datetime_elem = root.find('.//in-capmkt:DateAndTimeOfSubmission', namespaces)
        if datetime_elem is not None:
            xbrl_data['datetime'] = datetime_elem.text or ""
        
        # Category
        category_elem = root.find('.//in-capmkt:CategoryOfAnnouncement', namespaces)
        if category_elem is not None:
            xbrl_data['category'] = category_elem.text or ""
        
        return xbrl_data
        
    except Exception as e:
        print(f"[ERROR] Error fetching XBRL from {xbrl_url}: {e}")
        return None


def is_relevant_announcement(xbrl_data: Optional[Dict[str, str]]) -> bool:
    """Check if announcement is relevant based on XBRL subject"""
    if not xbrl_data:
        return False
    
    subject = xbrl_data.get('subject', '').strip()
    
    # Check if subject matches any relevant file type
    return subject in RELEVANT_FILE_TYPES


# File to store processed announcements and files
PROCESSED_ANNOUNCEMENTS_FILE = "processed_announcements.json"


def load_processed_announcements() -> Tuple[set, set]:
    """Load previously processed announcement IDs and PDF URLs from file"""
    try:
        if os.path.exists(PROCESSED_ANNOUNCEMENTS_FILE):
            with open(PROCESSED_ANNOUNCEMENTS_FILE, 'r') as f:
                data = json.load(f)
                processed_ids = set(data.get('processed_ids', []))
                processed_files = set(data.get('processed_files', []))
                print(f"[INFO] Loaded {len(processed_ids)} processed announcements, {len(processed_files)} processed files")
                return processed_ids, processed_files
    except Exception as e:
        print(f"[WARN] Could not load processed announcements: {e}")
    return set(), set()


def save_processed_announcements(processed_ids: set, processed_files: set = None):
    """Save processed announcement IDs and PDF URLs to file"""
    try:
        data = {
            'processed_ids': list(processed_ids),
            'processed_files': list(processed_files or set()),
            'last_updated': datetime.now().isoformat()
        }
        with open(PROCESSED_ANNOUNCEMENTS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"[INFO] Saved {len(processed_ids)} processed IDs, {len(processed_files or set())} processed files")
    except Exception as e:
        print(f"[WARN] Could not save processed announcements: {e}")


def cleanup_pdf_files(seq_id: str, pdf_url: str):
    """Clean up downloaded PDF file after processing"""
    try:
        if not pdf_url:
            return
        
        # Extract filename from URL
        filename = pdf_url.split("/")[-1]
        if not filename:
            return
        
        # Remove from docs directory
        pdf_path = os.path.join("docs", filename)
        if os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
                print(f"[INFO] Cleaned up PDF: {filename}")
            except Exception as e:
                print(f"[WARN] Could not delete PDF {filename}: {e}")
    except Exception as e:
        print(f"[WARN] Error cleaning up PDF: {e}")


# Removed old scrape_nse_announcements function - now using NSEScraperSubject class


def normalize_api_announcement(item: Dict) -> Dict[str, str]:
    """Normalize API response item to our format"""
    symbol = item.get('symbol', '')
    dt = item.get('dt', '') or item.get('an_dt', '')
    desc = item.get('desc', '')
    
    # Extract seq_id - use the seq_id from API response
    seq_id = item.get('seq_id', '')
    if not seq_id:
        # Generate unique ID if not provided
        seq_id = f"{symbol}_{dt}_{desc}".replace(' ', '_').replace(':', '_')
    else:
        seq_id = str(seq_id)
    
    # Extract XBRL URL from seq_id
    xbrl_url = ""
    if seq_id and seq_id.isdigit():
        xbrl_url = f"{NSE_BASE_URL}/api/xbrl/{seq_id}"
    
    # Extract PDF URL (already full URL in API response)
    pdf_url = item.get('attchmntFile', '')
    
    return {
        'symbol': symbol,
        'desc': desc,
        'dt': dt or item.get('an_dt', ''),
        'attchmntFile': pdf_url,
        'sm_name': item.get('sm_name', ''),
        'sm_isin': item.get('sm_isin', ''),
        'an_dt': item.get('an_dt', ''),
        'sort_date': item.get('sort_date', ''),
        'seq_id': seq_id,
        'attchmntText': item.get('attchmntText', ''),
        'fileSize': item.get('fileSize', ''),
        'xbrl_url': xbrl_url,
    }


class NSEScraperSubject(ConnectorSubject):
    """
    Pathway connector subject for NSE announcements scraper.
    Uses API endpoint and tracks seen announcements to emit only new ones.
    """
    
    _refresh_interval: int
    _seen_seq_ids: set
    _processed_files: set
    
    def __init__(self, refresh_interval: int = 60) -> None:
        super().__init__()
        self._refresh_interval = refresh_interval
        self._seen_seq_ids = set()
        self._processed_files = set()
        
        # Load previously processed announcements and files
        try:
            processed_ids, processed_files = load_processed_announcements()
            self._seen_seq_ids = processed_ids
            self._processed_files = processed_files
            print(f"[INFO] Loaded {len(processed_ids)} previously seen announcements, {len(processed_files)} processed files")
        except Exception as e:
            print(f"[WARN] Could not load processed announcements: {e}")
    
    def _fetch_api_announcements(self) -> List[Dict]:
        """Fetch announcements from API - simplified and robust"""
        session = requests.Session()
        headers = get_session_headers()
        
        try:
            # Establish session (required by NSE)
            session.get(NSE_BASE_URL, headers=headers, timeout=10)
            time.sleep(1)
            session.get(NSE_ANNOUNCEMENTS_URL, headers=headers, timeout=10)
            time.sleep(1)
            
            # Fetch from API
            response = session.get(NSE_API_URL, headers=headers, timeout=15)
            response.raise_for_status()
            
            # Handle Brotli compression if requests didn't auto-decompress
            if response.headers.get('Content-Encoding') == 'br':
                try:
                    # Try to parse as JSON first (requests may have auto-decompressed)
                    data = response.json()
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # Still compressed, decompress manually
                    try:
                        import brotli
                        decompressed = brotli.decompress(response.content)
                        data = json.loads(decompressed.decode('utf-8'))
                    except Exception:
                        return []
            else:
                # Parse JSON directly
                data = response.json()
            
            if not isinstance(data, list):
                return []
            
            # Convert to our format
            announcements = []
            for item in data:
                try:
                    announcements.append(normalize_api_announcement(item))
                except Exception:
                    continue  # Skip invalid items
            
            return announcements
            
        except Exception as e:
            print(f"[ERROR] API fetch failed: {e}")
            return []  # Return empty list, keep polling
    
    def run(self) -> None:
        """Run the scraper and emit only new announcements"""
        save_counter = 0
        SAVE_INTERVAL = 10
        
        while True:
            try:
                print(f"[INFO] Polling NSE API at {datetime.now()}")
                
                # Fetch all announcements from API
                announcements = self._fetch_api_announcements()
                
                if not announcements:
                    print("[WARN] No announcements fetched, waiting before retry...")
                    time.sleep(self._refresh_interval)
                    continue
                
                # Process only new announcements
                new_count = 0
                for ann in announcements:
                    try:
                        seq_id = ann.get('seq_id', '')
                        if not seq_id:
                            continue
                        
                        # Skip if already seen
                        if seq_id in self._seen_seq_ids:
                            continue
                        
                        # Mark as seen
                        self._seen_seq_ids.add(seq_id)
                        new_count += 1
                        
                        # Check if PDF file already processed
                        pdf_url = ann.get('attchmntFile', '')
                        if pdf_url and pdf_url in self._processed_files:
                            print(f"[DEBUG] PDF already processed, skipping: {pdf_url}")
                            continue
                        
                        # Check XBRL relevance before emitting
                        xbrl_url = ann.pop('xbrl_url', '')
                        if xbrl_url:
                            try:
                                xbrl_data = fetch_xbrl_content(xbrl_url)
                                if is_relevant_announcement(xbrl_data):
                                    print(f"[INFO] New relevant: {ann.get('symbol', '')} - {ann.get('desc', '')}")
                                    
                                    # Update PDF URL from XBRL if available
                                    if xbrl_data and 'attachment_url' in xbrl_data:
                                        ann['attchmntFile'] = xbrl_data['attachment_url']
                                        pdf_url = ann['attchmntFile']
                                    
                                    # Track processed file
                                    if pdf_url:
                                        self._processed_files.add(pdf_url)
                                    
                                    # Emit to Pathway table (seq_id must be first as it's the primary key)
                                    self.next(
                                        seq_id=seq_id,
                                        symbol=ann.get('symbol', ''),
                                        desc=ann.get('desc', ''),
                                        dt=ann.get('dt', ''),
                                        attchmntFile=pdf_url,
                                        sm_name=ann.get('sm_name', ''),
                                        sm_isin=ann.get('sm_isin', ''),
                                        an_dt=ann.get('an_dt', ''),
                                        sort_date=ann.get('sort_date', ''),
                                        attchmntText=ann.get('attchmntText', ''),
                                        fileSize=ann.get('fileSize', ''),
                                    )
                                    
                                    # Periodically save
                                    save_counter += 1
                                    if save_counter >= SAVE_INTERVAL:
                                        save_processed_announcements(self._seen_seq_ids, self._processed_files)
                                        save_counter = 0
                            except Exception as e:
                                print(f"[WARN] Error processing announcement {seq_id}: {e}")
                                # Continue with next announcement
                                continue
                    except Exception as e:
                        print(f"[WARN] Error processing announcement: {e}")
                        continue  # Continue with next announcement
                
                print(f"[INFO] Found {new_count} new announcements, {len(announcements) - new_count} already seen")
                
                # Save processed IDs and files after each poll
                save_processed_announcements(self._seen_seq_ids, self._processed_files)
                
                # Wait before next poll
                print(f"[INFO] Waiting {self._refresh_interval} seconds before next poll...")
                time.sleep(self._refresh_interval)
                
            except KeyboardInterrupt:
                print("[INFO] Scraping stopped by user")
                save_processed_announcements(self._seen_seq_ids, self._processed_files)
                break
            except Exception as e:
                print(f"[ERROR] Error in polling loop: {e}")
                import traceback
                traceback.print_exc()
                save_processed_announcements(self._seen_seq_ids, self._processed_files)
                time.sleep(self._refresh_interval)


def create_nse_scraper_input(refresh_interval: int = 60) -> pw.Table:
    """
    Create Pathway table from live NSE web scraper
    
    Args:
        refresh_interval: Seconds between scrapes (default: 60)
    
    Returns:
        Pathway table with NSE announcements
    """
    subject = NSEScraperSubject(refresh_interval=refresh_interval)
    
    return pw.io.python.read(
        subject,
        schema=NSEAnnouncementSchema
    )


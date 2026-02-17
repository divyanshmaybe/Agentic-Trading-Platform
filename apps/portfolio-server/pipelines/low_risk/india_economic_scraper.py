#!/usr/bin/env python3
"""
Indian Economic Indicators Scraper

Scrapes economic data from Trading Economics website and saves to CSV.
"""

from typing import List, Dict, Optional
from urllib.parse import urljoin
import pandas as pd
import requests
from bs4 import BeautifulSoup
import time
import sys


class IndiaEconomicScraper:
    """Scraper for Indian economic indicators from Trading Economics"""

    def __init__(
        self,
        base_url: str = "https://tradingeconomics.com",
        path: str = "/india/indicators",
        headers: Optional[Dict] = None,
        request_timeout: int = 10,
    ):
        self.base_url = base_url
        self.path = path
        self.url = urljoin(self.base_url, self.path)
        self.headers = headers or {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/91.0.4472.124 Safari/537.36"
            )
        }
        self.request_timeout = request_timeout

    def fetch_page(self) -> Optional[str]:
        """Fetch the webpage content"""
        try:
            print(f"Fetching data from {self.url}...")
            response = requests.get(
                self.url, headers=self.headers, timeout=self.request_timeout
            )
            response.raise_for_status()
            print("✓ Page fetched successfully")
            return response.text
        except requests.exceptions.RequestException as e:
            print(f"✗ Error fetching page: {e}", file=sys.stderr)
            return None

    def parse_indicators(self, html_content: str) -> List[Dict]:
        """Parse indicators from HTML content"""
        soup = BeautifulSoup(html_content, "html.parser")
        data: List[Dict] = []

        # Find all tables with class 'table table-hover' (common on TradingEconomics indicators page)
        tables = soup.find_all("table", class_="table table-hover")

        print(f"Found {len(tables)} table(s) on page")

        for table in tables:
            tbody = table.find("tbody")
            if not tbody:
                continue

            rows = tbody.find_all("tr")

            for row in rows:
                cols = row.find_all("td")

                # If the page structure is standard, we typically get columns like:
                # [Indicator, Last, Previous, Unit, Date, ...] but sometimes layout changes.
                if not cols:
                    continue

                # Extract anchor (indicator name + relative link) if present
                indicator_name = None
                indicator_link = None
                first_td = cols[0]
                a_tag = first_td.find("a")

                if a_tag:
                    indicator_name = a_tag.get_text(strip=True)
                    href = a_tag.get("href", "")
                    if href:
                        indicator_link = urljoin(self.base_url, href)
                else:
                    indicator_name = first_td.get_text(strip=True)

                # Extract textual content of remaining columns (safe fallback)
                col_texts = [c.get_text(" ", strip=True) for c in cols]

                # Try to map likely fields - use safe indexing with fallback to empty string
                def safe(i: int) -> str:
                    return col_texts[i] if i < len(col_texts) else ""

                entry = {
                    "indicator": indicator_name or "",
                    "indicator_link": indicator_link or "",
                    "col_0": safe(0),  # usually indicator name
                    "last": safe(1),
                    "previous": safe(2),
                    "unit": safe(3),
                    "date": safe(4),
                    # keep raw columns so if the layout differs you still have data
                    "raw_columns": col_texts,
                }

                data.append(entry)

        print(f"Parsed {len(data)} indicator rows")
        return data

    def to_dataframe(self, data: List[Dict]) -> pd.DataFrame:
        """Convert parsed data to a DataFrame and do light normalization"""
        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        # Normalize columns where possible
        # If last/prevoius contain non-numeric characters (commas, %), keep as string.
        # Convert empty strings to NaN for easier downstream processing
        df.replace({"": pd.NA}, inplace=True)

        return df

    def scrape(self) -> pd.DataFrame:
        """
        Main scrape method that returns DataFrame.
        This is the interface used by Celery tasks.
        """
        html = self.fetch_page()
        if html is None:
            print("Failed to fetch page. Returning empty DataFrame.", file=sys.stderr)
            return pd.DataFrame()

        data = self.parse_indicators(html)
        df = self.to_dataframe(data)

        return df

    def save_csv(self, df: pd.DataFrame, filename: str = "india_indicators.csv") -> None:
        """Save DataFrame to CSV"""
        if df.empty:
            print("No data to save.")
            return

        df.to_csv(filename, index=False)
        print(f"✓ Saved {len(df)} rows to {filename}")


def main():
    scraper = IndiaEconomicScraper()
    df = scraper.scrape()

    # Show a small sample in console
    if not df.empty:
        print(df.head(10).to_string(index=False))
    else:
        print("No indicator data found on the page.")

    # Save to CSV
    scraper.save_csv(df)


if __name__ == "__main__":
    main()


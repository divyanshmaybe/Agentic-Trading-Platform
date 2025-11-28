#!/usr/bin/env python3
"""
CPI Data Scraper - FIXED with proper session handling

======================================================
This version properly establishes ASP.NET session before accessing forms
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional
import urllib3

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class CPIScraperFixed:
    """Scraper for CPI data from MOSPI website - FIXED SESSION HANDLING"""

    BASE_URL = "https://cpi.mospi.gov.in"

    ALL_STATES = {
        "ALL India": "99",
        "Andaman and Nicobar Islands": "35",
        "Andhra Pradesh": "28",
        "Arunachal Pradesh": "12",
        "Assam": "18",
        "Bihar": "10",
        "Chandigarh": "04",
        "Chhattisgarh": "22",
        "Dadra and Nagar Haveli": "26",
        "Daman and Diu": "25",
        "Delhi": "07",
        "Goa": "30",
        "Gujarat": "24",
        "Haryana": "06",
        "Himachal Pradesh": "02",
        "Jammu and Kashmir": "01",
        "Jharkhand": "20",
        "Karnataka": "29",
        "Kerala": "32",
        "Lakshadweep": "31",
        "Madhya Pradesh": "23",
        "Maharashtra": "27",
        "Manipur": "14",
        "Meghalaya": "17",
        "Mizoram": "15",
        "Nagaland": "13",
        "Odisha": "21",
        "Puducherry": "34",
        "Punjab": "03",
        "Rajasthan": "08",
        "Sikkim": "11",
        "Tamil Nadu": "33",
        "Telangana": "36",
        "Tripura": "16",
        "Uttar Pradesh": "09",
        "Uttarakhand": "05",
        "West Bengal": "19",
    }

    def __init__(self):
        """Initialize the scraper with a session"""
        self.session = requests.Session()

        # Set browser-like headers
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0",
            }
        )

        self.timeseries_url = None

    def establish_session(self) -> bool:
        """
        Establish session by following redirects and getting ASP.NET_SessionId cookie
        This is the CRITICAL step your original code was missing!
        """
        try:
            print("\n[Step 1: Establishing session...]")

            # Make initial request to base URL - this will redirect and set session cookie
            response = self.session.get(
                self.BASE_URL, verify=False, timeout=30, allow_redirects=True  # Follow redirects to get session cookie
            )

            print(f"✓ Initial request: {response.status_code}")
            print(f"✓ Final URL: {response.url}")

            # Check if we got the session cookie
            session_cookie = self.session.cookies.get("ASP.NET_SessionId")
            if session_cookie:
                print(f"✓ Session cookie obtained: ASP.NET_SessionId={session_cookie}")
            else:
                print("⚠️  No session cookie found (might still work)")

            # Display all cookies for debugging
            if self.session.cookies:
                print(f"✓ Total cookies: {len(self.session.cookies)}")
                for cookie in self.session.cookies:
                    print(f"  - {cookie.name}={cookie.value[:20]}...")

            return True

        except Exception as e:
            print(f"✗ Error establishing session: {e}")
            return False

    def get_form_data(self) -> dict:
        """Get ASP.NET form data from TimeSeries page"""
        try:
            print("\n[Step 2: Getting form data...]")

            # Now access the TimeSeries page with our established session
            self.timeseries_url = f"{self.BASE_URL}/TimeSeries_2012.aspx"

            response = self.session.get(self.timeseries_url, verify=False, timeout=30)

            print(f"✓ TimeSeries page: {response.status_code}")

            if response.status_code != 200:
                print(f"✗ Unexpected status: {response.status_code}")
                return {}

            # Parse HTML to extract hidden form fields
            soup = BeautifulSoup(response.text, "html.parser")

            form_data = {}
            form_fields = [
                "__VIEWSTATE",
                "__VIEWSTATEGENERATOR",
                "__EVENTVALIDATION",
                "__VIEWSTATEENCRYPTED",
            ]

            for field in form_fields:
                element = soup.find("input", {"name": field})
                if element and element.get("value"):
                    form_data[field] = element["value"]
                    value_preview = (
                        element["value"][:50]
                        if len(element["value"]) > 50
                        else element["value"]
                    )
                    print(f"  ✓ {field}: {value_preview}...")
                else:
                    form_data[field] = ""
                    if field != "__VIEWSTATEENCRYPTED":  # This one is often empty
                        print(f"  ⚠️  {field}: empty")

            return form_data

        except Exception as e:
            print(f"✗ Error getting form data: {e}")
            return {}

    def scrape_all_states(
        self,
        from_year: str = None,
        from_month: str = None,
        to_year: str = None,
        to_month: str = None,
        group_code: str = "27",
    ) -> Optional[pd.DataFrame]:
        """Scrape CPI data for ALL Indian states"""

        # Calculate dates if not provided (1 year behind current date)
        if not all([from_year, from_month, to_year, to_month]):
            current_date = datetime.now()
            one_year_ago = current_date - timedelta(days=365)
            from_year = str(one_year_ago.year)
            from_month = str(one_year_ago.month).zfill(2)
            to_year = str(current_date.year)
            to_month = str(current_date.month).zfill(2)

        print("\n" + "=" * 80)
        print("CPI DATA SCRAPER - ALL INDIA ONLY (FIXED)")
        print("=" * 80)
        print(f"Period: {from_month}/{from_year} to {to_month}/{to_year}")
        print(f"State: ALL India only")
        print(f"Group Code: {group_code}")
        print("=" * 80)

        # CRITICAL: Establish session first!
        if not self.establish_session():
            print("\n✗ Failed to establish session")
            return None

        # Get form data
        form_data = self.get_form_data()
        if not form_data or not form_data.get("__VIEWSTATE"):
            print("\n✗ Failed to get form data")
            return None

        # Prepare POST data with ONLY "ALL India" selected
        print("\n[Step 3: Preparing POST data...]")

        post_data = {
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "__LASTFOCUS": "",
            "__VIEWSTATE": form_data.get("__VIEWSTATE", ""),
            "__VIEWSTATEGENERATOR": form_data.get("__VIEWSTATEGENERATOR", ""),
            "__VIEWSTATEENCRYPTED": form_data.get("__VIEWSTATEENCRYPTED", ""),
            "__EVENTVALIDATION": form_data.get("__EVENTVALIDATION", ""),
            "ctl00$Content1$DropDownList1": from_year,
            "ctl00$Content1$DropDownList3": from_month,
            "ctl00$Content1$DropDownList5": group_code,
            "ctl00$Content1$DropDownList8": "State",
            "ctl00$Content1$Button2": "View Indices",
            "ctl00$Content1$DropDownList2": to_year,
            "ctl00$Content1$DropDownList4": to_month,
        }

        # Add ONLY "ALL India" checkbox (first item, index 0, code "99")
        checkbox_name = "ctl00$Content1$CheckBoxList1$0"
        post_data[checkbox_name] = "99"  # ALL India code

        print(f"✓ Selected: ALL India only")
        print(f"✓ Date range: {from_month}/{from_year} to {to_month}/{to_year}")

        # Make POST request with proper headers
        print("\n[Step 4: Submitting form...]")

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": self.timeseries_url,
            "Origin": self.BASE_URL,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
        }

        try:
            response = self.session.post(
                self.timeseries_url,
                data=post_data,
                headers=headers,
                verify=False,
                timeout=60,
            )

            print(f"✓ POST response: {response.status_code}")
            print(f"✓ Response length: {len(response.text)} bytes")

            if response.status_code != 200:
                print(f"✗ Unexpected status code: {response.status_code}")
                return None

            # Parse the response
            print("\n[Step 5: Parsing table...]")
            df = self._parse_table(response.text)
            return df

        except requests.Timeout:
            print("✗ Request timeout (try again later)")
            return None
        except Exception as e:
            print(f"✗ Error during scraping: {e}")
            return None

    def _parse_table(self, html_content: str) -> Optional[pd.DataFrame]:
        """Parse HTML table from response"""
        soup = BeautifulSoup(html_content, "html.parser")

        # Look for the data table
        table = soup.find("table", {"id": "Content1_GridView1"})

        if not table:
            print("✗ Table not found in response")
            # Try to find any table
            all_tables = soup.find_all("table")
            print(f"  Found {len(all_tables)} tables total")
            return None

        print("✓ Data table found")

        rows = table.find_all("tr")

        if len(rows) < 2:
            print("✗ No data rows found")
            return None

        # Extract headers
        headers = [th.get_text(strip=True) for th in rows[0].find_all("th")]
        print(f"✓ Headers: {headers}")

        # Extract data rows
        data = []
        for row in rows[1:]:
            cols = row.find_all("td")
            if cols:
                row_data = [col.get_text(strip=True) for col in cols]
                data.append(row_data)

        if not data:
            print("✗ No data extracted")
            return None

        # Create DataFrame
        df = pd.DataFrame(data, columns=headers)

        # Convert numeric columns
        numeric_cols = ["Rural", "Urban", "Combined"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Filter to only "ALL India" rows (in case multiple states are returned)
        if "State" in df.columns:
            initial_count = len(df)
            df = df[df["State"] == "ALL India"].copy()
            filtered_count = len(df)
            if initial_count != filtered_count:
                print(f"✓ Filtered to ALL India only: {filtered_count} rows (from {initial_count} total)")

        print(f"✓ DataFrame created: {len(df)} rows × {len(df.columns)} columns")

        return df

    def scrape(self) -> pd.DataFrame:
        """
        Main scrape method that returns DataFrame.
        This is the interface used by Celery tasks.
        Wrapper around scrape_all_states().
        """
        df = self.scrape_all_states()
        if df is None:
            return pd.DataFrame()
        return df


def main():
    """Main function"""

    print("=" * 80)
    print("🚀 CPI SCRAPER - FIXED VERSION")
    print("=" * 80)
    print("This version properly establishes ASP.NET session before accessing forms")
    print("=" * 80)

    # Create scraper instance
    scraper = CPIScraperFixed()

    # Scrape data for all states (1 year behind to current)
    df = scraper.scrape()

    if df is not None and len(df) > 0:
        print("\n" + "=" * 100)
        print("✅ SUCCESS! CPI DATA RETRIEVED")
        print("=" * 100)

        # Show preview
        print("\n📊 DATA PREVIEW:")
        print(df.head(20).to_string(index=False))
        if len(df) > 20:
            print(f"\n... (showing first 20 of {len(df)} total rows)")

        # Show statistics
        print("\n" + "=" * 100)
        print("📈 STATISTICS:")
        print(f"  Total records: {len(df)}")
        if "State" in df.columns:
            print(f"  Unique states: {df['State'].nunique()}")
            print(f"  States: {', '.join(df['State'].unique()[:5])}...")
        if "Year" in df.columns:
            print(f"  Years: {df['Year'].unique()}")
        if "Month" in df.columns:
            print(f"  Months: {df['Month'].unique()}")

        # Save to CSV
        output_file = "cpi_all_states_data.csv"
        df.to_csv(output_file, index=False)
        print(f"\n✓ Data saved to: {output_file}")
        print("=" * 100)

    else:
        print("\n" + "=" * 80)
        print("✗ FAILED TO SCRAPE DATA")
        print("=" * 80)
        print("\n💡 TROUBLESHOOTING:")
        print("  1. Check internet connection")
        print("  2. Verify website is accessible: https://cpi.mospi.gov.in")
        print("  3. Try again in a few minutes (server might be busy)")
        print("  4. Check if website structure has changed")
        print("=" * 80)


if __name__ == "__main__":
    main()


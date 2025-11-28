"""
Economic Indicators Data Storage Manager

Handles reading and writing economic indicator data with file locking.
Uses write locks to block all access during updates.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

import pandas as pd

from .file_lock import FileWriteLock, FileReadLock

logger = logging.getLogger(__name__)


class EconomicIndicatorsStorage:
    """Manages storage of economic indicator data with file locking"""

    def __init__(self, data_dir: str | Path = "data/economic_indicators"):
        """
        Initialize storage manager.
        
        Args:
            data_dir: Directory to store indicator data files
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.data_dir / "metadata.json"

    def _get_data_file(self, scraper_name: str) -> Path:
        """Get path to data file for a scraper"""
        # Map scraper names to file names
        file_mapping = {
            "trading_economics": "trading_economics.json",
            "cpi": "cpi_data.json",
        }
        filename = file_mapping.get(scraper_name, f"{scraper_name}.json")
        return self.data_dir / filename

    def _load_metadata(self) -> Dict[str, Any]:
        """Load metadata file"""
        if not self.metadata_file.exists():
            return {}

        try:
            with open(self.metadata_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load metadata: {e}")
            return {}

    def _save_metadata(self, metadata: Dict[str, Any]):
        """Save metadata file"""
        try:
            with open(self.metadata_file, "w") as f:
                json.dump(metadata, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save metadata: {e}")

    def read_indicators(self, scraper_name: str) -> Optional[Dict[str, Any]]:
        """
        Read indicator data for a scraper as dictionary (JSON format).
        
        Will wait if write lock is active.
        
        Args:
            scraper_name: Name of the scraper (e.g., "trading_economics", "cpi")
            
        Returns:
            Dictionary with 'data' (list of records) and 'metadata', or None if file doesn't exist
        """
        data_file = self._get_data_file(scraper_name)

        if not data_file.exists():
            logger.debug(f"Data file does not exist: {data_file}")
            return None

        # Use read lock to wait for write lock to release
        # For small JSON files, this ensures we don't read during writes
        try:
            with FileReadLock(data_file):
                with open(data_file, "r") as f:
                    return json.load(f)
        except FileNotFoundError:
            return None
        except Exception as e:
            logger.error(f"Failed to read indicators for {scraper_name}: {e}")
            return None

    def read_indicators_df(self, scraper_name: str) -> Optional[pd.DataFrame]:
        """
        Read indicator data for a scraper as pandas DataFrame.
        
        Will wait if write lock is active.
        
        Args:
            scraper_name: Name of the scraper (e.g., "trading_economics", "cpi")
            
        Returns:
            DataFrame with indicator data, or None if file doesn't exist
        """
        data_dict = self.read_indicators(scraper_name)
        
        if data_dict is None:
            return None
        
        # Extract data records from dictionary
        records = data_dict.get("data", [])
        
        if not records:
            return pd.DataFrame()
        
        # Convert to DataFrame
        df = pd.DataFrame(records)
        
        return df

    def write_indicators(
        self, scraper_name: str, data: pd.DataFrame, metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Write indicator data for a scraper.
        
        Uses write lock to block all access during update.
        
        Args:
            scraper_name: Name of the scraper (e.g., "trading_economics", "cpi")
            data: DataFrame containing the indicator data
            metadata: Optional additional metadata to store
        """
        data_file = self._get_data_file(scraper_name)

        # Convert DataFrame to JSON-serializable format
        if data.empty:
            records = []
        else:
            # Replace NaN with None for JSON serialization
            records = data.replace({pd.NA: None}).to_dict("records")

        # Prepare data structure
        output_data = {
            "scraper": scraper_name,
            "last_updated": datetime.utcnow().isoformat() + "Z",
            "row_count": len(records),
            "data": records,
        }

        # Add custom metadata if provided
        if metadata:
            output_data["custom_metadata"] = metadata

        # Write with exclusive lock (blocks all access)
        try:
            with FileWriteLock(data_file):
                # Write data file
                with open(data_file, "w") as f:
                    json.dump(output_data, f, indent=2)

                # Update metadata file
                all_metadata = self._load_metadata()
                all_metadata[scraper_name] = {
                    "last_updated": output_data["last_updated"],
                    "row_count": output_data["row_count"],
                    "data_file": str(data_file),
                }
                self._save_metadata(all_metadata)

                logger.info(
                    f"✓ Updated {scraper_name} indicators: {len(records)} rows"
                )

        except Exception as e:
            logger.error(f"Failed to write indicators for {scraper_name}: {e}")
            raise

    def check_if_update_needed(
        self, scraper_name: str, max_age_days: int = 30
    ) -> bool:
        """
        Check if data needs updating based on last update time.
        
        Args:
            scraper_name: Name of the scraper
            max_age_days: Maximum age in days before update is needed
            
        Returns:
            True if update is needed, False otherwise
        """
        data_file = self._get_data_file(scraper_name)

        # If file doesn't exist, update is needed
        if not data_file.exists():
            logger.info(f"Data file missing for {scraper_name}, update needed")
            return True

        # Check metadata
        metadata = self._load_metadata()
        scraper_meta = metadata.get(scraper_name, {})

        if not scraper_meta or "last_updated" not in scraper_meta:
            logger.info(f"No metadata for {scraper_name}, update needed")
            return True

        # Check age
        try:
            last_updated_str = scraper_meta["last_updated"]
            last_updated = datetime.fromisoformat(
                last_updated_str.replace("Z", "+00:00")
            )
            age = datetime.utcnow() - last_updated.replace(tzinfo=None)

            if age > timedelta(days=max_age_days):
                logger.info(
                    f"Data for {scraper_name} is {age.days} days old, update needed"
                )
                return True

            logger.debug(
                f"Data for {scraper_name} is {age.days} days old, no update needed"
            )
            return False

        except Exception as e:
            logger.warning(f"Failed to check update status for {scraper_name}: {e}")
            return True  # Err on the side of updating

    def get_last_update_time(self, scraper_name: str) -> Optional[datetime]:
        """Get last update time for a scraper"""
        metadata = self._load_metadata()
        scraper_meta = metadata.get(scraper_name, {})

        if not scraper_meta or "last_updated" not in scraper_meta:
            return None

        try:
            last_updated_str = scraper_meta["last_updated"]
            return datetime.fromisoformat(last_updated_str.replace("Z", "+00:00"))
        except Exception:
            return None


# Global instance
_storage_instance: Optional[EconomicIndicatorsStorage] = None


def get_storage() -> EconomicIndicatorsStorage:
    """Get global storage instance"""
    global _storage_instance
    if _storage_instance is None:
        import os

        data_dir = os.getenv(
            "ECONOMIC_INDICATORS_DATA_DIR", "data/economic_indicators"
        )
        _storage_instance = EconomicIndicatorsStorage(data_dir)
    return _storage_instance


"""
Market Hours Utility Module

Production-ready market hours enforcement for NSE trading.
NO FALLBACKS - Fail fast if outside trading hours in production mode.

Market Hours: 9:15 AM - 3:30 PM IST (Monday-Friday)
Pre-market: 9:00 AM - 9:15 AM IST (orders accepted but not executed)
Post-market: 3:30 PM - 4:00 PM IST (closing auctions only)
"""

import logging
import os
from datetime import datetime, time
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Indian Standard Time
IST = ZoneInfo("Asia/Kolkata")

# Market hours configuration (IST)
MARKET_OPEN = time(9, 15)  # 9:15 AM
MARKET_CLOSE = time(15, 30)  # 3:30 PM
PRE_MARKET_OPEN = time(9, 0)  # 9:00 AM
POST_MARKET_CLOSE = time(16, 0)  # 4:00 PM

# Market days (Monday=0, Friday=4)
MARKET_DAYS = {0, 1, 2, 3, 4}  # Mon-Fri

# Market holidays (NSE) - Update this list annually
# Format: (month, day)
NSE_HOLIDAYS_2024 = [
    (1, 26),   # Republic Day
    (3, 8),    # Maha Shivaratri
    (3, 25),   # Holi
    (3, 29),   # Good Friday
    (4, 11),   # Id-Ul-Fitr
    (4, 17),   # Ram Navami
    (4, 21),   # Mahavir Jayanti
    (5, 1),    # May Day
    (6, 17),   # Bakri Id
    (7, 17),   # Muharram
    (8, 15),   # Independence Day
    (8, 26),   # Janmashtami
    (9, 16),   # Milad-un-Nabi
    (10, 2),   # Gandhi Jayanti
    (10, 12),  # Dussehra
    (10, 31),  # Diwali
    (11, 1),   # Diwali (Balipratipada)
    (11, 15),  # Gurunanak Jayanti
    (12, 25),  # Christmas
]

NSE_HOLIDAYS_2025 = [
    (1, 26),   # Republic Day
    (2, 26),   # Maha Shivaratri
    (3, 14),   # Holi
    (3, 31),   # Id-Ul-Fitr
    (4, 10),   # Mahavir Jayanti
    (4, 14),   # Dr. Ambedkar Jayanti
    (4, 18),   # Good Friday
    (5, 1),    # Maharashtra Day
    (6, 6),    # Bakri Id
    (8, 15),   # Independence Day
    (8, 27),   # Ganesh Chaturthi
    (10, 2),   # Gandhi Jayanti
    (10, 20),  # Dussehra
    (10, 21),  # Diwali (Laxmi Pujan)
    (10, 22),  # Diwali (Balipratipada)
    (11, 5),   # Gurunanak Jayanti
    (12, 25),  # Christmas
]


def is_market_holiday(dt: datetime) -> bool:
    """Check if given datetime is a market holiday."""
    # Use appropriate year's holiday list
    holidays = NSE_HOLIDAYS_2025 if dt.year >= 2025 else NSE_HOLIDAYS_2024
    return (dt.month, dt.day) in holidays


def is_market_hours(
    dt: Optional[datetime] = None,
    *,
    allow_pre_market: bool = False,
    allow_post_market: bool = False,
) -> bool:
    """
    Check if given datetime is within market trading hours.
    
    Args:
        dt: Datetime to check (default: current time in IST)
        allow_pre_market: If True, allow pre-market hours (9:00-9:15 AM)
        allow_post_market: If True, allow post-market hours (3:30-4:00 PM)
    
    Returns:
        True if within market hours, False otherwise
    
    Production behavior:
    - Returns False for weekends
    - Returns False for market holidays
    - Returns False for times outside 9:15 AM - 3:30 PM IST
    - NO FALLBACKS - strict enforcement
    """
    if dt is None:
        dt = datetime.now(IST)
    elif dt.tzinfo is None:
        # Assume UTC if naive, convert to IST
        dt = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(IST)
    else:
        dt = dt.astimezone(IST)
    
    # Check if weekend
    if dt.weekday() not in MARKET_DAYS:
        return False
    
    # Check if market holiday
    if is_market_holiday(dt):
        return False
    
    current_time = dt.time()
    
    # Standard market hours
    if MARKET_OPEN <= current_time <= MARKET_CLOSE:
        return True
    
    # Pre-market hours (if allowed)
    if allow_pre_market and PRE_MARKET_OPEN <= current_time < MARKET_OPEN:
        return True
    
    # Post-market hours (if allowed)
    if allow_post_market and MARKET_CLOSE < current_time <= POST_MARKET_CLOSE:
        return True
    
    return False


def get_market_status(dt: Optional[datetime] = None) -> Tuple[str, str]:
    """
    Get detailed market status for given datetime.
    
    Returns:
        (status, message) tuple where status is one of:
        - "open": Market is open for trading
        - "closed": Market is closed
        - "pre_market": Pre-market session
        - "post_market": Post-market session
        - "weekend": Weekend
        - "holiday": Market holiday
    """
    if dt is None:
        dt = datetime.now(IST)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(IST)
    else:
        dt = dt.astimezone(IST)
    
    # Check weekend
    if dt.weekday() not in MARKET_DAYS:
        return "weekend", f"Market closed (Weekend: {dt.strftime('%A')})"
    
    # Check holiday
    if is_market_holiday(dt):
        return "holiday", f"Market closed (Holiday: {dt.strftime('%B %d, %Y')})"
    
    current_time = dt.time()
    
    # Check market hours
    if MARKET_OPEN <= current_time <= MARKET_CLOSE:
        return "open", f"Market open (9:15 AM - 3:30 PM IST)"
    
    if PRE_MARKET_OPEN <= current_time < MARKET_OPEN:
        return "pre_market", f"Pre-market session (9:00 AM - 9:15 AM IST)"
    
    if MARKET_CLOSE < current_time <= POST_MARKET_CLOSE:
        return "post_market", f"Post-market session (3:30 PM - 4:00 PM IST)"
    
    return "closed", f"Market closed (Hours: 9:15 AM - 3:30 PM IST)"


def enforce_market_hours(
    dt: Optional[datetime] = None,
    *,
    demo_mode: Optional[bool] = None,
    allow_pre_market: bool = False,
    allow_post_market: bool = False,
) -> None:
    """
    Enforce market hours check - raises ValueError if outside market hours.
    
    Args:
        dt: Datetime to check (default: current time)
        demo_mode: If True, skip enforcement (default: from DEMO_MODE env var)
        allow_pre_market: Allow pre-market hours
        allow_post_market: Allow post-market hours
    
    Raises:
        ValueError: If outside market hours and not in demo mode
    
    Production behavior:
    - In production (demo_mode=False), ALWAYS enforces market hours
    - Rejects trades outside 9:15 AM - 3:30 PM IST
    - Rejects trades on weekends and holidays
    - NO EXCEPTIONS, NO FALLBACKS
    """
    if demo_mode is None:
        demo_mode = os.getenv("DEMO_MODE", "false").lower() in {"1", "true", "yes"}
    
    if demo_mode:
        logger.debug("Market hours enforcement skipped (DEMO_MODE=true)")
        return
    
    if dt is None:
        dt = datetime.now(IST)
    
    if not is_market_hours(dt, allow_pre_market=allow_pre_market, allow_post_market=allow_post_market):
        status, message = get_market_status(dt)
        error_msg = (
            f"Trading not allowed outside market hours. "
            f"Status: {status}. {message}. "
            f"Requested time: {dt.strftime('%Y-%m-%d %H:%M:%S %Z')}"
        )
        logger.error("❌ Market hours violation: %s", error_msg)
        raise ValueError(error_msg)
    
    logger.debug("✅ Market hours check passed: %s", dt.strftime('%Y-%m-%d %H:%M:%S %Z'))


def get_next_market_open(dt: Optional[datetime] = None) -> datetime:
    """
    Get the next market opening time from given datetime.
    
    Returns:
        Datetime of next market open (9:15 AM IST)
    """
    if dt is None:
        dt = datetime.now(IST)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(IST)
    else:
        dt = dt.astimezone(IST)
    
    # Start with next day
    next_day = dt.replace(hour=9, minute=15, second=0, microsecond=0)
    
    # If current time is before market open today, use today
    if dt.time() < MARKET_OPEN and dt.weekday() in MARKET_DAYS and not is_market_holiday(dt):
        return next_day
    
    # Otherwise find next market day
    from datetime import timedelta
    next_day = next_day + timedelta(days=1)
    
    while next_day.weekday() not in MARKET_DAYS or is_market_holiday(next_day):
        next_day = next_day + timedelta(days=1)
    
    return next_day


def get_next_market_close(dt: Optional[datetime] = None) -> datetime:
    """
    Get the next market closing time from given datetime.
    
    Returns:
        Datetime of next market close (3:30 PM IST)
    """
    if dt is None:
        dt = datetime.now(IST)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(IST)
    else:
        dt = dt.astimezone(IST)
    
    # If market is open today, return today's close
    if is_market_hours(dt):
        return dt.replace(hour=15, minute=30, second=0, microsecond=0)
    
    # Otherwise get next market open, then add close time
    next_open = get_next_market_open(dt)
    return next_open.replace(hour=15, minute=30, second=0, microsecond=0)


def seconds_until_market_close(dt: Optional[datetime] = None) -> int:
    """
    Get seconds until next market close.
    
    Returns:
        Seconds until market close (negative if market is closed)
    """
    if dt is None:
        dt = datetime.now(IST)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(IST)
    else:
        dt = dt.astimezone(IST)
    
    next_close = get_next_market_close(dt)
    delta = (next_close - dt).total_seconds()
    return int(delta)


__all__ = [
    "is_market_hours",
    "get_market_status",
    "enforce_market_hours",
    "get_next_market_open",
    "get_next_market_close",
    "seconds_until_market_close",
    "is_market_holiday",
    "IST",
]

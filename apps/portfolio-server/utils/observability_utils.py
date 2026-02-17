"""
Observability Utilities

Helper functions for parsing and transforming observability data.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def parse_json_field(value: Optional[str]) -> Optional[Any]:
    """
    Parse JSON string field, return None if invalid.
    
    Args:
        value: JSON string to parse
        
    Returns:
        Parsed JSON object or original value if parsing fails
    """
    if not value:
        return None
    try:
        if isinstance(value, (dict, list)):
            return value
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def build_where_clause(
    analysis_type: Optional[str] = None,
    symbol: Optional[str] = None,
    status: Optional[str] = None,
    sentiment: Optional[str] = None,
    triggered_by: Optional[str] = None,
    model_name: Optional[str] = None,
    start_date: Optional[Any] = None,
    end_date: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Build Prisma where clause from filter parameters.
    
    Args:
        analysis_type: Filter by analysis type (mapped to filing_type)
        symbol: Filter by stock symbol (case-insensitive contains)
        status: Filter by status (ignored as not in DB)
        sentiment: Filter by sentiment (ignored as not in DB)
        triggered_by: Filter by trigger type
        model_name: Filter by LLM model name (ignored as not in DB)
        start_date: Filter logs after this date
        end_date: Filter logs before this date
        
    Returns:
        Prisma where clause dictionary
    """
    where_clause: Dict[str, Any] = {}
    
    if analysis_type:
        where_clause["filing_type"] = analysis_type
    
    if symbol:
        where_clause["symbol"] = {"contains": symbol.upper(), "mode": "insensitive"}
    
    # Status and sentiment are not directly in the DB schema for NseObservabilityLog
    # We could potentially map them to trading_decision but it's inexact
    
    if triggered_by:
        where_clause["triggered_by"] = triggered_by
    
    # Date filters
    if start_date or end_date:
        date_filter: Dict[str, Any] = {}
        if start_date:
            date_filter["gte"] = start_date
        if end_date:
            date_filter["lte"] = end_date
        where_clause["created_at"] = date_filter
    
    return where_clause


def build_order_clause(sort_by: str, sort_order: str) -> Dict[str, str]:
    """
    Build Prisma order clause from sort parameters.
    
    Args:
        sort_by: Field to sort by (API field name)
        sort_order: Sort direction ('asc' or 'desc')
        
    Returns:
        Prisma order clause dictionary
    """
    # Map API field names to Prisma field names
    field_mapping = {
        "created_at": "created_at",
        "latency_ms": "created_at", # Fallback
        "confidence_score": "confidence_score",
        "analysis_type": "filing_type",
        "symbol": "symbol",
        "status": "created_at", # Fallback
        "sentiment": "trading_decision",
    }
    
    sort_field = field_mapping.get(sort_by, "created_at")
    order = sort_order if sort_order in ["asc", "desc"] else "desc"
    
    return {sort_field: order}

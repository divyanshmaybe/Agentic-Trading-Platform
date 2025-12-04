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
        analysis_type: Filter by analysis type
        symbol: Filter by stock symbol (case-insensitive contains)
        status: Filter by status
        sentiment: Filter by sentiment
        triggered_by: Filter by trigger type
        model_name: Filter by LLM model name
        start_date: Filter logs after this date
        end_date: Filter logs before this date
        
    Returns:
        Prisma where clause dictionary
    """
    where_clause: Dict[str, Any] = {}
    
    if analysis_type:
        where_clause["analysisType"] = analysis_type
    
    if symbol:
        where_clause["symbol"] = {"contains": symbol.upper(), "mode": "insensitive"}
    
    if status:
        where_clause["status"] = status
    
    if sentiment:
        where_clause["sentiment"] = sentiment
    
    if triggered_by:
        where_clause["triggeredBy"] = triggered_by
    
    if model_name:
        where_clause["modelName"] = model_name
    
    # Date filters
    if start_date or end_date:
        date_filter: Dict[str, Any] = {}
        if start_date:
            date_filter["gte"] = start_date
        if end_date:
            date_filter["lte"] = end_date
        where_clause["createdAt"] = date_filter
    
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
        "created_at": "createdAt",
        "latency_ms": "latencyMs",
        "confidence_score": "confidenceScore",
        "analysis_type": "analysisType",
        "symbol": "symbol",
        "status": "status",
        "sentiment": "sentiment",
    }
    
    sort_field = field_mapping.get(sort_by, sort_by)
    order = sort_order if sort_order in ["asc", "desc"] else "desc"
    
    return {sort_field: order}

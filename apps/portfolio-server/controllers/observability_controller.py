"""
Observability Controller

Handles business logic for NSE observability analysis logs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from prisma import Prisma

from utils.observability_utils import (
    parse_json_field,
    build_where_clause,
    build_order_clause,
)
from schemas.observability_schemas import (
    ObservabilityLogResponse,
    ObservabilityLogListResponse,
    ObservabilityStatsResponse,
)


class ObservabilityController:
    """Controller for observability log operations."""
    
    def __init__(self, prisma: Prisma):
        self.prisma = prisma
    
    def _log_to_response(self, log) -> ObservabilityLogResponse:
        """Convert Prisma model to response model."""
        # Map sentiment from trading decision
        sentiment = "neutral"
        if log.trading_decision:
            decision = log.trading_decision.upper()
            if "BUY" in decision:
                sentiment = "positive"
            elif "SELL" in decision:
                sentiment = "negative"
                
        metadata = parse_json_field(log.metadata) or {}
                
        return ObservabilityLogResponse(
            id=log.id,
            analysis_type=log.filing_type or "unknown",
            symbol=log.symbol,
            analysis_period=None,
            prompt=metadata.get("prompt"),
            response=log.feedback_on_agent_performance,
            model_name=metadata.get("model_name"),
            model_provider=metadata.get("model_provider"),
            token_count=metadata.get("tokens"),
            latency_ms=metadata.get("latency_ms"),
            cost_estimate=metadata.get("cost_estimate"),
            summary=log.reasoning_of_nse_agent,
            key_findings=metadata.get("key_findings"),
            sentiment=sentiment,
            risk_factors=metadata.get("risk_factors"),
            recommendations=None,
            confidence_score=log.confidence_score,
            triggered_by=log.triggered_by,
            worker_id=None,
            status="completed", # Default to completed as these are post-analysis logs
            error_message=None,
            created_at=log.created_at,
            context_data=None,
            metadata=metadata,
        )
    
    async def list_logs(
        self,
        limit: int,
        offset: int,
        sort_by: str,
        sort_order: str,
        analysis_type: Optional[str] = None,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
        sentiment: Optional[str] = None,
        triggered_by: Optional[str] = None,
        model_name: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> ObservabilityLogListResponse:
        """
        List observability logs with filtering and pagination.
        
        Returns:
            Paginated list of observability logs
        """
        where_clause = build_where_clause(
            analysis_type=analysis_type,
            symbol=symbol,
            status=status,
            sentiment=sentiment,
            triggered_by=triggered_by,
            model_name=model_name,
            start_date=start_date,
            end_date=end_date,
        )
        
        order_clause = build_order_clause(sort_by, sort_order)
        
        # Get total count
        total = await self.prisma.nseobservabilitylog.count(where=where_clause)
        
        # Query logs
        logs = await self.prisma.nseobservabilitylog.find_many(
            where=where_clause,
            order=order_clause,
            skip=offset,
            take=limit,
        )
        
        return ObservabilityLogListResponse(
            logs=[self._log_to_response(log) for log in logs],
            total=total,
            limit=limit,
            offset=offset,
            has_more=(offset + len(logs)) < total,
        )
    
    async def get_log(self, log_id: str) -> Optional[ObservabilityLogResponse]:
        """
        Get a single observability log by ID.
        
        Args:
            log_id: The unique log identifier
            
        Returns:
            Log response or None if not found
        """
        log = await self.prisma.nseobservabilitylog.find_unique(where={"id": log_id})
        
        if not log:
            return None
        
        return self._log_to_response(log)
    
    async def get_stats(self, days: int) -> ObservabilityStatsResponse:
        """
        Get aggregate statistics for observability logs.
        
        Args:
            days: Number of days to include in stats
            
        Returns:
            Statistics response
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        # Get counts
        total = await self.prisma.nseobservabilitylog.count(
            where={"created_at": {"gte": cutoff_date}}
        )
        
        # All logs in this table are effectively "completed" analyses
        completed = total
        failed = 0
        
        # Get sentiment breakdown (approximation based on trading decision)
        positive = await self.prisma.nseobservabilitylog.count(
            where={
                "created_at": {"gte": cutoff_date},
                "trading_decision": {"contains": "BUY", "mode": "insensitive"}
            }
        )
        negative = await self.prisma.nseobservabilitylog.count(
            where={
                "created_at": {"gte": cutoff_date},
                "trading_decision": {"contains": "SELL", "mode": "insensitive"}
            }
        )
        neutral = total - (positive + negative)
        if neutral < 0: neutral = 0
        
        # Get unique symbols count
        logs_with_symbols = await self.prisma.nseobservabilitylog.find_many(
            where={"created_at": {"gte": cutoff_date}},
            distinct=["symbol"],
        )
        symbols_analyzed = len(logs_with_symbols)
        
        # Get recent activity (last 24 hours)
        recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        recent_count = await self.prisma.nseobservabilitylog.count(
            where={"created_at": {"gte": recent_cutoff}}
        )
        
        return ObservabilityStatsResponse(
            total_analyses=total,
            completed=completed,
            failed=failed,
            avg_latency_ms=None,
            sentiment_breakdown={
                "positive": positive,
                "negative": negative,
                "neutral": neutral,
            },
            symbols_analyzed=symbols_analyzed,
            recent_activity_count=recent_count,
        )
    
    async def list_symbols(self) -> List[str]:
        """
        Get list of unique symbols that have been analyzed.
        
        Returns:
            Sorted list of unique symbols
        """
        logs = await self.prisma.nseobservabilitylog.find_many(
            distinct=["symbol"]
        )
        
        symbols = [log.symbol for log in logs if log.symbol]
        return sorted(set(symbols))
    
    async def list_triggers(self) -> List[str]:
        """
        Get list of unique trigger types.
        
        Returns:
            Sorted list of unique trigger types
        """
        logs = await self.prisma.nseobservabilitylog.find_many(
            distinct=["triggered_by"]
        )
        
        triggers = [log.triggered_by for log in logs if log.triggered_by]
        return sorted(set(triggers))

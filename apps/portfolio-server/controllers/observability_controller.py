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
        return ObservabilityLogResponse(
            id=log.id,
            analysis_type=log.analysisType,
            symbol=log.symbol,
            analysis_period=log.analysisPeriod,
            prompt=log.prompt,
            response=log.response,
            model_name=log.modelName,
            model_provider=log.modelProvider,
            token_count=log.tokenCount,
            latency_ms=log.latencyMs,
            cost_estimate=float(log.costEstimate) if log.costEstimate else None,
            summary=log.summary,
            key_findings=parse_json_field(log.keyFindings),
            sentiment=log.sentiment,
            risk_factors=parse_json_field(log.riskFactors),
            recommendations=parse_json_field(log.recommendations),
            confidence_score=log.confidenceScore,
            triggered_by=log.triggeredBy,
            worker_id=log.workerId,
            status=log.status,
            error_message=log.errorMessage,
            created_at=log.createdAt,
            context_data=parse_json_field(log.contextData),
            metadata=parse_json_field(log.metadata),
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
            where={"createdAt": {"gte": cutoff_date}}
        )
        
        completed = await self.prisma.nseobservabilitylog.count(
            where={"createdAt": {"gte": cutoff_date}, "status": "completed"}
        )
        
        failed = await self.prisma.nseobservabilitylog.count(
            where={"createdAt": {"gte": cutoff_date}, "status": "failed"}
        )
        
        # Get sentiment breakdown
        positive = await self.prisma.nseobservabilitylog.count(
            where={"createdAt": {"gte": cutoff_date}, "sentiment": "positive"}
        )
        negative = await self.prisma.nseobservabilitylog.count(
            where={"createdAt": {"gte": cutoff_date}, "sentiment": "negative"}
        )
        neutral = await self.prisma.nseobservabilitylog.count(
            where={"createdAt": {"gte": cutoff_date}, "sentiment": "neutral"}
        )
        
        # Get unique symbols count
        logs_with_symbols = await self.prisma.nseobservabilitylog.find_many(
            where={"createdAt": {"gte": cutoff_date}, "symbol": {"not": None}},
            distinct=["symbol"],
        )
        symbols_analyzed = len(logs_with_symbols)
        
        # Get recent activity (last 24 hours)
        recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        recent_count = await self.prisma.nseobservabilitylog.count(
            where={"createdAt": {"gte": recent_cutoff}}
        )
        
        # Calculate average latency
        avg_latency = await self._calculate_avg_latency(cutoff_date)
        
        return ObservabilityStatsResponse(
            total_analyses=total,
            completed=completed,
            failed=failed,
            avg_latency_ms=avg_latency,
            sentiment_breakdown={
                "positive": positive,
                "negative": negative,
                "neutral": neutral,
            },
            symbols_analyzed=symbols_analyzed,
            recent_activity_count=recent_count,
        )
    
    async def _calculate_avg_latency(self, cutoff_date: datetime) -> Optional[float]:
        """Calculate average latency for completed logs."""
        logs_with_latency = await self.prisma.nseobservabilitylog.find_many(
            where={
                "createdAt": {"gte": cutoff_date},
                "status": "completed",
                "latencyMs": {"not": None}
            },
            select={"latencyMs": True}
        )
        
        if not logs_with_latency:
            return None
        
        latencies = [log.latencyMs for log in logs_with_latency if log.latencyMs]
        if not latencies:
            return None
        
        return sum(latencies) / len(latencies)
    
    async def list_symbols(self) -> List[str]:
        """
        Get list of unique symbols that have been analyzed.
        
        Returns:
            Sorted list of unique symbols
        """
        logs = await self.prisma.nseobservabilitylog.find_many(
            where={"symbol": {"not": None}},
            distinct=["symbol"],
            select={"symbol": True}
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
            where={"triggeredBy": {"not": None}},
            distinct=["triggeredBy"],
            select={"triggeredBy": True}
        )
        
        triggers = [log.triggeredBy for log in logs if log.triggeredBy]
        return sorted(set(triggers))

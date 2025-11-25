"""
Order Monitor Worker - Wrapper for streaming order monitor functionality.

This module provides the OrderMonitorWorker class that was previously
in a separate file but is now implemented in streaming_order_monitor_pipeline.py.
"""

from pipelines.orders.streaming_order_monitor_pipeline import PathwayOrderMonitor

# Alias for backwards compatibility
OrderMonitorWorker = PathwayOrderMonitor
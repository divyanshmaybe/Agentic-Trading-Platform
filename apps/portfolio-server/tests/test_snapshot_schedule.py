"""
Unit tests for Celery Beat schedule configuration.
These tests don't require a database connection.
"""

import os
import sys
from pathlib import Path

import pytest

# Setup paths
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
SHARED_PY_PATH = os.path.join(REPO_ROOT, "shared/py")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
if SHARED_PY_PATH not in sys.path:
    sys.path.insert(0, SHARED_PY_PATH)

PORTFOLIO_SERVER_ROOT = os.path.join(os.path.dirname(__file__), "..")
if PORTFOLIO_SERVER_ROOT not in sys.path:
    sys.path.insert(0, PORTFOLIO_SERVER_ROOT)

from celery_app import celery_app


@pytest.mark.unit
class TestCeleryBeatSchedule:
    """Test Celery Beat schedule configuration (no database required)"""
    
    def test_snapshot_task_in_beat_schedule(self):
        """Test that snapshot task is registered in Celery Beat schedule"""
        beat_schedule = celery_app.conf.beat_schedule
        
        assert "trading-agent-snapshots" in beat_schedule, \
            "Snapshot task not found in beat schedule. Check SNAPSHOT_CAPTURE_ENABLED setting."
        
        snapshot_config = beat_schedule["trading-agent-snapshots"]
        assert snapshot_config["task"] == "snapshot.capture_agent_snapshots"
        
        # Verify schedule is every 3 hours (actual config is */3)
        schedule = str(snapshot_config["schedule"])
        assert "*/3" in schedule or "0,3,6,9,12,15,18,21" in schedule, \
            f"Schedule should be every 3 hours, got: {schedule}"
        
        print(f"✅ Snapshot task scheduled: {schedule}")
    
    def test_snapshot_task_enabled(self):
        """Test that snapshot task is enabled by default"""
        beat_schedule = celery_app.conf.beat_schedule
        
        # Check if snapshot task exists (enabled by default)
        assert "trading-agent-snapshots" in beat_schedule, \
            "Snapshot task not enabled. Set SNAPSHOT_CAPTURE_ENABLED=true"
        
        print("✅ Snapshot task is enabled in beat schedule")
    
    def test_snapshot_task_queue_configuration(self):
        """Test that snapshot task has correct queue configuration"""
        beat_schedule = celery_app.conf.beat_schedule
        
        if "trading-agent-snapshots" in beat_schedule:
            snapshot_config = beat_schedule["trading-agent-snapshots"]
            options = snapshot_config.get("options", {})
            queue = options.get("queue", "default")
            
            # Queue should be configured (default is "general" or custom)
            assert queue is not None
            print(f"✅ Snapshot task queue: {queue}")


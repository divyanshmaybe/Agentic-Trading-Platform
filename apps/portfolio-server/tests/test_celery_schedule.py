"""
Test suite for Celery Beat schedule configuration.

These tests do not require a database connection.
"""

import os
import sys
from unittest.mock import MagicMock

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


class TestCeleryBeatSchedule:
    """Test Celery Beat schedule configuration (no database required)"""

    def test_snapshot_task_in_beat_schedule(self):
        """Test that snapshot task is registered in Celery Beat schedule"""
        beat_schedule = celery_app.conf.beat_schedule

        assert "trading-agent-snapshots" in beat_schedule, \
            "Snapshot task not found in beat schedule. Check SNAPSHOT_CAPTURE_ENABLED setting."

        snapshot_config = beat_schedule["trading-agent-snapshots"]
        assert snapshot_config["task"] == "snapshot.capture_agent_snapshots"

        # Verify schedule is every 3 hours
        schedule = str(snapshot_config["schedule"])
        assert "*/3" in schedule, \
            f"Schedule should be every 3 hours, got: {schedule}"

        print(f"✅ Snapshot task scheduled: {schedule}")

    def test_snapshot_task_enabled(self):
        """Test that snapshot task is enabled by default"""
        beat_schedule = celery_app.conf.beat_schedule

        # Check if snapshot task exists (enabled by default)
        assert "trading-agent-snapshots" in beat_schedule, \
            "Snapshot task not enabled. Set SNAPSHOT_CAPTURE_ENABLED=true"

        print("✅ Snapshot task is enabled in beat schedule")

    def test_portfolio_snapshot_task_in_beat_schedule(self):
        """Test that portfolio snapshot task is registered in Celery Beat schedule"""
        beat_schedule = celery_app.conf.beat_schedule

        assert "portfolio-snapshots" in beat_schedule, \
            "Portfolio snapshot task not found in beat schedule."

        snapshot_config = beat_schedule["portfolio-snapshots"]
        assert snapshot_config["task"] == "snapshot.capture_portfolio_snapshots"

        # Verify schedule is every 3 hours (5 minutes after agent snapshots)
        schedule = str(snapshot_config["schedule"])
        assert "*/3" in schedule, \
            f"Schedule should be every 3 hours, got: {schedule}"

        print(f"✅ Portfolio snapshot task scheduled: {schedule}")

    def test_all_snapshot_tasks_scheduled(self):
        """Test that all snapshot tasks are properly scheduled"""
        beat_schedule = celery_app.conf.beat_schedule

        expected_tasks = [
            "trading-agent-snapshots",
            "portfolio-snapshots",
        ]

        for task_name in expected_tasks:
            assert task_name in beat_schedule, f"Task {task_name} not found in beat schedule"
            task_config = beat_schedule[task_name]
            assert "task" in task_config
            assert "schedule" in task_config
            assert "options" in task_config

        print(f"✅ All {len(expected_tasks)} snapshot tasks are scheduled")
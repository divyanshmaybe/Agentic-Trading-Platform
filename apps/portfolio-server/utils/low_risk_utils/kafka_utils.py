"""
Kafka utilities for low_risk pipelines.

Provides reusable Kafka publisher setup and helper for
publishing agent logs and events to Kafka topics.
"""

import logging
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

# Add shared directory to path for kafka_service import
shared_dir = Path(__file__).resolve().parent.parent.parent.parent / "shared" / "py"
if str(shared_dir) not in sys.path:
    sys.path.insert(0, str(shared_dir))

from kafka_service import default_kafka_bus, KafkaPublisher

logger = logging.getLogger(__name__)


class LowRiskKafkaPublisher:
    """
    Singleton Kafka publisher for low_risk pipelines.

    Production-ready design:
    - Single publisher instance (expensive resource, shared)
    - Thread-safe initialization
    - User context passed per-message (not stored in singleton)
    - Suitable for multi-user concurrent environments
    - Monotonic sequence numbers for message ordering
    """

    _instance: Optional['LowRiskKafkaPublisher'] = None
    _publisher: Optional[KafkaPublisher] = None
    _lock = None  # Will be initialized as threading.Lock
    _sequence_counter: int = 0
    _sequence_lock: Optional[threading.Lock] = None

    def __new__(cls):
        """Thread-safe singleton pattern."""
        if cls._lock is None:
            cls._lock = threading.Lock()
        if cls._sequence_lock is None:
            cls._sequence_lock = threading.Lock()

        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize publisher if not already initialized (thread-safe)."""
        if self._publisher is None:
            with self._lock:
                # Double-check locking pattern
                if self._publisher is None:
                    self._initialize_publisher()

    def _initialize_publisher(
        self,
        topic: str = "low_risk_agent_logs",
        source: str = "low_risk_pipeline"
    ) -> None:
        """
        Initialize the Kafka publisher (called once, thread-safe).

        Args:
            topic: Kafka topic name
            source: Source identifier for default headers
        """
        try:
            # Check if publisher already registered
            if topic in default_kafka_bus._publishers:
                self._publisher = default_kafka_bus._publishers[topic]
                logger.debug(f"✓ Using existing Kafka publisher for {topic}")
            else:
                self._publisher = default_kafka_bus.register_publisher(
                    name=topic,
                    topic=topic,
                    partition_key_factory=None,
                    default_headers={"source": source},
                    auto_start=True,
                )
                logger.info(f"✅ Kafka publisher initialized for {topic}")
        except Exception as e:
            logger.warning(f"Failed to initialize Kafka publisher: {e}. Logs will not be published.")
            self._publisher = None

    def get_publisher(self) -> Optional[KafkaPublisher]:
        """
        Get the underlying KafkaPublisher instance.

        Returns:
            KafkaPublisher instance or None if not initialized
        """
        return self._publisher

    def _get_next_sequence(self) -> int:
        """
        Get the next sequence number in a thread-safe manner.

        Returns:
            Monotonically increasing sequence number
        """
        with self._sequence_lock:
            LowRiskKafkaPublisher._sequence_counter += 1
            return LowRiskKafkaPublisher._sequence_counter

    def publish(
        self,
        data: Dict[str, Any],
        user_id: str,
        message_type: str = "info",
        task_id: Optional[str] = None,
    ) -> None:
        """
        Publish data to Kafka with consistent structure.

        Thread-safe, production-ready design:
        - user_id MUST be passed per message (not stored globally)
        - task_id allows frontend to track specific pipeline executions
        - Supports concurrent requests from different users
        - Each message is independent

        Message structure:
        {
            "user_id": str,
            "task_id": str | None,
            "type": str,
            ...additional data from 'data' dict
        }

        Args:
            data: Dictionary containing the message data
            user_id: User identifier (REQUIRED for proper multi-user support)
            message_type: Message type identifier (default: "info")
            task_id: Celery task ID for tracking pipeline execution (optional)
        """
        if not self._publisher:
            return

        if not user_id:
            logger.warning("user_id not provided for Kafka message - message will be published without user context")

        try:
            # Get sequence number for ordering
            seq = self._get_next_sequence()
            timestamp_ms = int(time.time() * 1000)

            # Build message with consistent structure including sequence for ordering
            message = {
                "user_id": user_id,
                "type": message_type,
                "seq": seq,  # Sequence number for frontend ordering
                "ts": timestamp_ms,  # Timestamp in milliseconds
                **data
            }
            # Pass task_id as Kafka message key for frontend filtering/routing
            # Use block=True to ensure sequential message ordering
            self._publisher.publish(message, key=task_id, block=True)
        except Exception as e:
            logger.warning(f"Failed to publish to Kafka: {e}")


def publish_to_kafka(
    data: Dict[str, Any],
    user_id: Optional[str] = None,
    message_type: str = "info",
    task_id: Optional[str] = None,
) -> None:
    """
    Publish data to Kafka with consistent structure.

    Helper function that uses the singleton publisher and formats messages.

    Args:
        data: Dictionary containing the message data
        user_id: User identifier (REQUIRED for production)
        message_type: Message type identifier (default: "info")
        task_id: Celery task ID for tracking pipeline execution (optional)
    """
    instance = LowRiskKafkaPublisher()
    instance.publish(data, user_id=user_id or "", message_type=message_type, task_id=task_id)
    time.sleep(0.2)

__all__ = [
    "LowRiskKafkaPublisher",
    "publish_to_kafka",
]

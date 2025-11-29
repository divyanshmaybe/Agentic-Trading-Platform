"""
Kafka utilities for low_risk pipelines.

Provides reusable Kafka publisher setup and logging helpers for
publishing agent logs and notifications to Kafka topics.
"""

import logging
import sys
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

# Add shared directory to path for kafka_service import
shared_dir = Path(__file__).resolve().parent.parent.parent.parent / "shared" / "py"
if str(shared_dir) not in sys.path:
    sys.path.insert(0, str(shared_dir))

from kafka_service import default_kafka_bus, KafkaPublisher

logger = logging.getLogger(__name__)


# Module-level publisher for standalone functions
_module_publisher: Optional[KafkaPublisher] = None
_module_user_id: Optional[str] = None


def setup_kafka_publisher(topic: str = "low_risk_agent_logs", source: str = "low_risk_pipeline") -> Optional[KafkaPublisher]:
    """
    Set up Kafka publisher for low_risk agent logs topic.
    
    Args:
        topic: Kafka topic name (default: "low_risk_agent_logs")
        source: Source identifier for default headers (default: "low_risk_pipeline")
    
    Returns:
        KafkaPublisher instance for publishing agent logs, or None if setup fails
    """
    try:
        publisher = default_kafka_bus.register_publisher(
            name=topic,
            topic=topic,
            partition_key_factory=None,
            default_headers={"source": source},
            auto_start=True,
        )
        logger.info(f"✅ Kafka publisher initialized for {topic}")
        return publisher
    except Exception as e:
        logger.warning(f"Failed to initialize Kafka publisher: {e}. Logs will not be published.")
        return None


def get_module_publisher() -> Optional[KafkaPublisher]:
    """
    Get the module-level publisher singleton.
    
    Returns:
        Shared KafkaPublisher instance, or None if not initialized
    """
    global _module_publisher
    if _module_publisher is None:
        _module_publisher = setup_kafka_publisher()
    return _module_publisher


def set_module_user_id(user_id: str) -> None:
    """
    Set the module-level user_id for standalone function logging.
    
    Args:
        user_id: User identifier to include in all logs
    """
    global _module_user_id
    _module_user_id = user_id


def get_module_user_id() -> Optional[str]:
    """
    Get the current module-level user_id.
    
    Returns:
        Current user_id or None
    """
    return _module_user_id


def publish_log(
    message: str,
    publisher: Optional[KafkaPublisher] = None,
    user_id: Optional[str] = None,
    level: str = "info",
    **extra_data
) -> None:
    """
    Publish log message to Kafka with user_id and metadata.
    
    Args:
        message: Log message to publish
        publisher: KafkaPublisher instance (uses module publisher if None)
        user_id: User identifier (uses module user_id if None)
        level: Log level (default: "info")
        **extra_data: Additional data to include in the log payload
    """
    pub = publisher or get_module_publisher()
    uid = user_id or _module_user_id
    
    if pub:
        try:
            log_data = {
                "user_id": uid,
                "timestamp": datetime.utcnow().isoformat(),
                "level": level,
                "message": message,
                **extra_data
            }
            pub.publish(log_data, block=False)
        except Exception as e:
            logger.warning(f"Failed to publish log to Kafka: {e}")


def publish_notification(
    notification_data: Dict[str, Any],
    publisher: Optional[KafkaPublisher] = None,
    user_id: Optional[str] = None,
) -> None:
    """
    Publish notification/event data to Kafka.
    
    Args:
        notification_data: Dictionary containing notification data
        publisher: KafkaPublisher instance (uses module publisher if None)
        user_id: User identifier to add to notification (uses module user_id if None)
    """
    pub = publisher or get_module_publisher()
    uid = user_id or _module_user_id
    
    if pub:
        try:
            # Add user_id if not already present
            if "user_id" not in notification_data and uid:
                notification_data = {"user_id": uid, **notification_data}
            
            pub.publish(notification_data, block=False)
        except Exception as e:
            logger.warning(f"Failed to publish notification to Kafka: {e}")


__all__ = [
    "setup_kafka_publisher",
    "get_module_publisher",
    "set_module_user_id",
    "get_module_user_id",
    "publish_log",
    "publish_notification",
]

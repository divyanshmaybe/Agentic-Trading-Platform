"""
Kafka utilities for low_risk pipelines.

Provides reusable Kafka publisher setup and helper for
publishing agent logs and events to Kafka topics.
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


def publish_to_kafka(
    data: Dict[str, Any],
    publisher: Optional[KafkaPublisher] = None,
    user_id: Optional[str] = None,
    message_type: str = "info",
) -> None:
    """
    Publish data to Kafka with consistent structure.
    
    All messages follow this structure:
    {
        "user_id": str,
        "timestamp": str (ISO format),
        "type": str,
        ...additional data from 'data' dict
    }
    
    Args:
        data: Dictionary containing the message data
        publisher: KafkaPublisher instance (uses module publisher if None)
        user_id: User identifier (uses module user_id if None)
        message_type: Message type identifier (default: "info")
    """
    pub = publisher or get_module_publisher()
    uid = user_id or _module_user_id
    
    if pub:
        try:
            # Build message with consistent structure
            message = {
                "user_id": uid,
                "timestamp": datetime.utcnow().isoformat(),
                "type": message_type,
                **data
            }
            pub.publish(message, block=False)
        except Exception as e:
            logger.warning(f"Failed to publish to Kafka: {e}")


__all__ = [
    "setup_kafka_publisher",
    "get_module_publisher",
    "set_module_user_id",
    "get_module_user_id",
    "publish_to_kafka",
]

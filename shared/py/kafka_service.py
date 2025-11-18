"""Centralised Kafka event bus using Pathway pipelines.

This module provides a shared Kafka service that all Python apps in the
monorepo can import. Publishers register themselves once, then stream their
events through a Pathway pipeline that serialises and forwards records to
Kafka. The bus is responsible for normalising payloads, enforcing schemas,
and keeping the Pathway runtime hidden behind a simple async API.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Type, Union

import pathway as pw
from pydantic import BaseModel, ValidationError
from confluent_kafka.admin import AdminClient, NewTopic  # type: ignore


LOGGER = logging.getLogger("shared.kafka")


def _ensure_pathway_silent() -> None:
    """Disable noisy Pathway dashboards unless explicitly requested."""

    os.environ.setdefault("PATHWAY_DISABLE_PROGRESS", "1")
    os.environ.setdefault("PATHWAY_MONITORING_LEVEL", "none")
    # Suppress verbose Pathway sink logging
    os.environ.setdefault("PATHWAY_LOG_LEVEL", "WARNING")
    logging.getLogger("pathway").setLevel(logging.WARNING)
    logging.getLogger("pathway.io").setLevel(logging.WARNING)
    logging.getLogger("pathway.io.kafka").setLevel(logging.WARNING)


_ensure_pathway_silent()


class KafkaServiceError(RuntimeError):
    """Base exception for Kafka service errors."""


class PublisherAlreadyRegistered(KafkaServiceError):
    """Raised when attempting to register a duplicate publisher name."""


class PublisherNotStarted(KafkaServiceError):
    """Raised when publish is attempted before the pipeline is running."""


class SchemaValidationError(KafkaServiceError):
    """Raised when a payload does not match the configured schema."""


class KafkaPublishError(KafkaServiceError):
    """Raised when enqueueing a record for publication fails."""


@dataclass(slots=True)
class KafkaSettings:
    """Runtime configuration for the Kafka service."""

    bootstrap_servers: str = field(default_factory=lambda: os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"))
    security_protocol: Optional[str] = field(default_factory=lambda: os.getenv("KAFKA_SECURITY_PROTOCOL"))
    sasl_mechanism: Optional[str] = field(default_factory=lambda: os.getenv("KAFKA_SASL_MECHANISM"))
    sasl_username: Optional[str] = field(default_factory=lambda: os.getenv("KAFKA_SASL_USERNAME"))
    sasl_password: Optional[str] = field(default_factory=lambda: os.getenv("KAFKA_SASL_PASSWORD"))
    ssl_cafile: Optional[str] = field(default_factory=lambda: os.getenv("KAFKA_SSL_CAFILE"))

    num_partitions: int = field(default_factory=lambda: int(os.getenv("KAFKA_TOPIC_PARTITIONS", "1")))
    replication_factor: int = field(default_factory=lambda: int(os.getenv("KAFKA_TOPIC_REPLICATION", "1")))

    def client_config(self) -> Dict[str, Any]:
        config: Dict[str, Any] = {
            "bootstrap.servers": self.bootstrap_servers,
        }
        if self.security_protocol:
            config["security.protocol"] = self.security_protocol
        if self.sasl_mechanism:
            config["sasl.mechanism"] = self.sasl_mechanism
        if self.sasl_username:
            config["sasl.username"] = self.sasl_username
        if self.sasl_password:
            config["sasl.password"] = self.sasl_password
        if self.ssl_cafile:
            config["ssl.ca.location"] = self.ssl_cafile
        return config

    def admin_client(self) -> AdminClient:
        return AdminClient(self.client_config())


class _KafkaEventSchema(pw.Schema):
    """Schema for normalised Kafka records."""

    key: Optional[str]
    value: str
    headers: Optional[Dict[str, str]]


def _default_serializer(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"), default=str)


class _KafkaQueueSubject(pw.io.python.ConnectorSubject):
    """Pathway subject that drains a Queue[dict] and emits rows."""

    deletions_enabled = False

    def __init__(
        self,
        name: str,
        event_queue: "queue.Queue[Optional[Dict[str, Any]]]",
        stop_event: threading.Event,
    ) -> None:
        super().__init__(datasource_name=f"kafka_publisher:{name}")
        self._name = name
        self._queue = event_queue
        self._stop_event = stop_event

    def run(self) -> None:  # pragma: no cover - exercised via integration
        LOGGER.debug("Kafka subject %s loop started", self._name)
        while True:
            if self._stop_event.is_set():
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    LOGGER.debug(
                        "Kafka subject %s stop event set and queue drained", self._name
                    )
                    break
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if item is None:
                LOGGER.debug("Kafka subject %s received sentinel", self._name)
                break

            try:
                self.next(**item)
            except Exception as exc:  # pragma: no cover - guard rail
                LOGGER.exception(
                    "Kafka subject %s failed to forward message %s: %s",
                    self._name,
                    item,
                    exc,
                )

        LOGGER.debug("Kafka subject %s loop exited", self._name)


class KafkaPublisher:
    """Publisher handle that streams records to a dedicated Pathway pipeline."""

    def __init__(
        self,
        name: str,
        topic: str,
        settings: KafkaSettings,
        *,
        value_model: Optional[Type[BaseModel]] = None,
        serializer: Optional[Callable[[Dict[str, Any]], str]] = None,
        default_headers: Optional[Dict[str, str]] = None,
        partition_key_factory: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
    ) -> None:
        self.name = name
        self.topic = topic
        self.settings = settings
        self._value_model = value_model
        self._serializer = serializer or _default_serializer
        self._default_headers = default_headers or {}
        self._partition_key_factory = partition_key_factory
        self._queue: "queue.Queue[Optional[Dict[str, Any]]]" = queue.Queue(maxsize=10_000)
        self._started = threading.Event()
        self._stop_event = threading.Event()
        self._runtime_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def publish(
        self,
        payload: Union[BaseModel, Dict[str, Any]],
        *,
        key: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        block: bool = True,
        timeout: Optional[float] = None,
    ) -> None:
        """Validate and enqueue an event for publication.

        Parameters
        ----------
        payload:
            Either a dictionary or a pydantic model instance matching the
            publisher schema.
        key:
            Optional partition key; if omitted we fall back to the registered
            key factory (if any).
        headers:
            Optional Kafka headers to attach to the record.
        block:
            Whether to block if the internal queue is full (defaults to True).
        timeout:
            Optional timeout (in seconds) for the enqueue operation when
            ``block`` is True.
        """

        if not self._started.is_set():
            raise PublisherNotStarted(
                f"Publisher {self.name} is not started yet; call start() on KafkaEventBus."
            )

        record_dict = self._normalise_payload(payload)
        record_key = key or self._resolve_partition_key(record_dict)
        record_headers = {**self._default_headers, **(headers or {})}

        serialised_value: str
        try:
            serialised_value = self._serializer(record_dict)
        except Exception as exc:  # pragma: no cover - defensive path
            raise KafkaPublishError(f"Failed serialising payload for {self.topic}") from exc

        envelope = {
            "key": record_key,
            "value": serialised_value,
            "headers": record_headers or None,
        }

        try:
            self._queue.put(envelope, block=block, timeout=timeout)
        except queue.Full as exc:  # pragma: no cover - guard rail
            raise KafkaPublishError(
                f"Publisher {self.name} queue is full; consider increasing capacity."
            ) from exc

    async def publish_async(
        self,
        payload: Union[BaseModel, Dict[str, Any]],
        *,
        key: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> None:
        """Async-compatible helper that defers to :meth:`publish`."""

        await asyncio.to_thread(
            self.publish,
            payload,
            key=key,
            headers=headers,
            block=True,
            timeout=timeout,
        )

    def start(self) -> None:
        """Start the background Pathway pipeline for this publisher."""

        if self._started.is_set():  # idempotent
            return

        self._stop_event.clear()
        self._runtime_thread = threading.Thread(
            target=self._run_pipeline,
            name=f"KafkaPublisher[{self.name}]-runtime",
            daemon=True,
        )
        self._runtime_thread.start()
        self._started.set()
        LOGGER.info("Kafka publisher %s -> topic %s started", self.name, self.topic)

    def stop(self, *, timeout: float = 10.0) -> None:
        """Stop the Pathway pipeline and wait for cleanup."""

        if not self._started.is_set():
            return

        self._stop_event.set()
        self._queue.put(None)
        if self._runtime_thread and self._runtime_thread.is_alive():
            self._runtime_thread.join(timeout=timeout)
        self._started.clear()
        LOGGER.info("Kafka publisher %s stopped", self.name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _normalise_payload(self, payload: Union[BaseModel, Dict[str, Any]]) -> Dict[str, Any]:
        if isinstance(payload, BaseModel):
            return payload.model_dump(mode="json")

        if self._value_model is None:
            if not isinstance(payload, dict):
                raise SchemaValidationError(
                    f"Publisher {self.name} expects dict payloads; received {type(payload).__name__}."
                )
            return payload

        try:
            model = self._value_model.model_validate(payload)
        except ValidationError as exc:  # pragma: no cover - defensive path
            raise SchemaValidationError(str(exc)) from exc
        return model.model_dump(mode="json")

    def _resolve_partition_key(self, payload: Dict[str, Any]) -> Optional[str]:
        if self._partition_key_factory:
            try:
                return self._partition_key_factory(payload)
            except Exception as exc:  # pragma: no cover - guard rails
                LOGGER.warning("Partition key factory raised for %s: %s", self.name, exc)
        return None

    # ------------------------------------------------------------------
    # Pathway runtime
    # ------------------------------------------------------------------
    def _run_pipeline(self) -> None:
        LOGGER.debug("Launching Pathway pipeline for publisher %s", self.name)

        subject = _KafkaQueueSubject(self.name, self._queue, self._stop_event)
        source = pw.io.python.read(
            subject,
            schema=_KafkaEventSchema,
            autocommit_duration_ms=500,
            max_backlog_size=self._queue.maxsize,
            name=f"{self.name}_subject",
        )
    # Pathway requires Kafka keys to be either bytes or strings (BYTES, STR, ANY types).
    # We enforce type safety by normalising keys to pure str, replacing None with empty string.
        # This prevents Pathway rejection errors while maintaining partition semantics.
        table = source.select(
            key=pw.apply(lambda maybe_key: "" if maybe_key is None else str(maybe_key), pw.this.key),
            value=pw.this.value,
            headers=pw.this.headers,
        )
        sink = pw.io.kafka.write(
            table,
            self.settings.client_config(),
            self.topic,
            format="json",
            key=table.key,
            name=f"{self.name}_sink",
        )

        try:
            # Suppress Pathway sink logging by setting log level before run
            import logging
            pathway_logger = logging.getLogger("pathway")
            original_level = pathway_logger.level
            pathway_logger.setLevel(logging.WARNING)
            try:
                pw.run(monitoring_level=pw.MonitoringLevel.NONE)
            finally:
                pathway_logger.setLevel(original_level)
        finally:  # pragma: no cover - Pathway cleanup best effort
            LOGGER.debug("Pathway pipeline for %s exited", self.name)


class KafkaEventBus:
    """Singleton facade aggregating all publishers in the workspace."""

    _instance: Optional["KafkaEventBus"] = None

    def __init__(self, settings: Optional[KafkaSettings] = None) -> None:
        self.settings = settings or KafkaSettings()
        self._publishers: Dict[str, KafkaPublisher] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Singleton helpers
    # ------------------------------------------------------------------
    @classmethod
    def instance(cls) -> "KafkaEventBus":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def register_publisher(
        self,
        name: str,
        *,
        topic: str,
        value_model: Optional[Type[BaseModel]] = None,
        serializer: Optional[Callable[[Dict[str, Any]], str]] = None,
        default_headers: Optional[Dict[str, str]] = None,
        partition_key_factory: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
        auto_start: bool = True,
    ) -> KafkaPublisher:
        """Register a new publisher with the central bus."""

        with self._lock:
            if name in self._publishers:
                raise PublisherAlreadyRegistered(f"Publisher {name} already registered")

            publisher = KafkaPublisher(
                name,
                topic,
                self.settings,
                value_model=value_model,
                serializer=serializer,
                default_headers=default_headers,
                partition_key_factory=partition_key_factory,
            )
            self._publishers[name] = publisher

        self._ensure_topic(topic)

        if auto_start:
            publisher.start()

        return publisher

    def get_publisher(self, name: str) -> KafkaPublisher:
        try:
            return self._publishers[name]
        except KeyError as exc:  # pragma: no cover - defensive path
            raise KafkaServiceError(f"Publisher {name} is not registered") from exc

    def start_all(self) -> None:
        with self._lock:
            for publisher in self._publishers.values():
                publisher.start()

    def stop_all(self) -> None:
        with self._lock:
            for publisher in self._publishers.values():
                publisher.stop()

    # ------------------------------------------------------------------
    # Topic helpers
    # ------------------------------------------------------------------
    def _ensure_topic(self, topic: str) -> None:
        admin = self.settings.admin_client()
        LOGGER.info("Connecting to Kafka at %s", self.settings.bootstrap_servers)
        metadata = admin.list_topics(timeout=5)
        if topic in metadata.topics and metadata.topics[topic].error is None:
            LOGGER.info("✓ Kafka topic %s already exists", topic)
            return

        LOGGER.info(
            "Creating Kafka topic %s (partitions=%s, replication=%s)",
            topic,
            self.settings.num_partitions,
            self.settings.replication_factor,
        )
        new_topic = NewTopic(
            topic,
            num_partitions=self.settings.num_partitions,
            replication_factor=self.settings.replication_factor,
        )
        futures = admin.create_topics([new_topic])

        try:
            futures[topic].result(timeout=10)
            LOGGER.info("✓ Kafka topic %s created", topic)
        except Exception as exc:  # pragma: no cover - topic may already exist or race condition
            # If topic already exists, ignore error, otherwise log
            if "Topic already exists" not in str(exc):
                LOGGER.warning("Failed to create topic %s: %s", topic, exc)
            else:
                LOGGER.info("ℹ︎ Kafka topic %s already existed", topic)
                return


# Default bus exposed for convenience -------------------------------------------------

default_kafka_bus = KafkaEventBus.instance()


__all__ = [
    "KafkaEventBus",
    "KafkaPublisher",
    "KafkaServiceError",
    "KafkaPublishError",
    "PublisherAlreadyRegistered",
    "PublisherNotStarted",
    "SchemaValidationError",
    "KafkaSettings",
    "default_kafka_bus",
]

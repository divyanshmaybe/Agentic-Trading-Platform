# Shared Python Utilities

This directory contains reusable building blocks for the backend services. The
latest addition is a centralised Kafka event bus that all applications can use
to publish high-frequency signals without re-implementing transport logic.

## Kafka Event Bus

`kafka_service.py` exposes a singleton `KafkaEventBus` that is backed by a
Pathway pipeline. Publishers register once, then stream validated payloads into
Kafka with a single async call.

```python
from pydantic import BaseModel
from shared.py.kafka_service import default_kafka_bus


class TradeSignal(BaseModel):
    symbol: str
    signal: str
    confidence: float


# Register a publisher (typically at startup)
signals_publisher = default_kafka_bus.register_publisher(
    "portfolio.trade-signals",
    topic="signals.trade",
    value_model=TradeSignal,
    default_headers={"source": "portfolio-server"},
)


async def dispatch_trade_signal(signal: TradeSignal) -> None:
    await signals_publisher.publish(signal)
```

### Environment variables

| Variable | Description | Default |
| --- | --- | --- |
| `KAFKA_BOOTSTRAP_SERVERS` | Comma-separated broker list | `localhost:9092` |
| `KAFKA_SECURITY_PROTOCOL` | (Optional) `PLAINTEXT`, `SASL_SSL`, etc. | unset |
| `KAFKA_SASL_MECHANISM` | SASL mechanism when security protocol requires it | unset |
| `KAFKA_SASL_USERNAME` | SASL username | unset |
| `KAFKA_SASL_PASSWORD` | SASL password | unset |
| `KAFKA_SSL_CAFILE` | CA bundle path for TLS | unset |

### Key capabilities

- **Schema enforcement** – optional Pydantic models guarantee consistent event
  shapes before they leave the service.
- **Pathway everywhere** – Pathway orchestrates the stream, so we benefit from
  its monitoring, reproducibility, and ability to extend to consumers in the
  future.
- **Thread-safe publishers** – each publisher runs in its own daemon thread and
  can be awaited from asyncio code without blocking.
- **Automatic headers & partition keys** – supply defaults at registration and
  override them per publish when needed.

### Lifecycle management

- `KafkaEventBus.start_all()` – explicitly start all registered publishers
  (registration auto-starts by default).
- `KafkaEventBus.stop_all()` – graceful shutdown when the host application is
  exiting.

See the inline documentation in `kafka_service.py` for more advanced
configuration options.

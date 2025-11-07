from __future__ import annotations

import os

# Disable Pathway progress dashboard before importing pathway
os.environ.setdefault("PATHWAY_DISABLE_PROGRESS", "1")
os.environ.setdefault("PATHWAY_LOG_LEVEL", "warning")

import asyncio
import contextlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

import pathway as pw
from pathway.io.python import ConnectorSubject
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

logger = logging.getLogger(__name__)

DEFAULT_WS_URL = os.getenv("MARKET_DATA_WS_URL", "wss://example.com/stream")
DEFAULT_PROVIDER = "generic"
DEFAULT_RETRY_SECONDS = 5


class MarketTickSchema(pw.Schema):
    """Pathway schema for streaming market ticks."""

    symbol: str = pw.column_definition(primary_key=True)
    price: str
    provider: str
    raw: str
    received_at: float


@dataclass
class WebsocketMessage:
    symbol: str
    price: Decimal
    raw: Dict[str, Any]


class WebsocketAdapter:
    """Adapter interface for websocket market data providers."""

    name: str

    def __init__(self, name: str) -> None:
        self.name = name

    async def on_connect(self, ws, symbols: Iterable[str]) -> None:  # pragma: no cover - template
        raise NotImplementedError

    async def handle_message(self, message: str) -> Sequence[WebsocketMessage]:  # pragma: no cover - template
        raise NotImplementedError

    async def subscribe_symbol(self, ws, symbol: str) -> None:  # pragma: no cover - template
        raise NotImplementedError

    async def unsubscribe_symbol(self, ws, symbol: str) -> None:  # pragma: no cover - template
        raise NotImplementedError


class GenericJSONAdapter(WebsocketAdapter):
    """Adapter for generic JSON websocket feeds with {"symbol": ..., "price": ...}."""

    def __init__(self) -> None:
        super().__init__("generic-json")
        self.ws_url = os.getenv("MARKET_DATA_WS_URL", DEFAULT_WS_URL)
        self.subscribe_key = os.getenv("MARKET_DATA_SUBSCRIBE_KEY", "subscribe")
        self.channel_key = os.getenv("MARKET_DATA_CHANNEL_KEY", "symbol")
        self.price_key = os.getenv("MARKET_DATA_PRICE_KEY", "price")
        self.symbol_key = os.getenv("MARKET_DATA_SYMBOL_KEY", "symbol")
        self.payload_template = os.getenv("MARKET_DATA_SUBSCRIBE_TEMPLATE")
        self.unsubscribe_template = os.getenv("MARKET_DATA_UNSUBSCRIBE_TEMPLATE")

    async def on_connect(self, ws, symbols: Iterable[str]) -> None:
        for symbol in symbols:
            await self.subscribe_symbol(ws, symbol)

    async def subscribe_symbol(self, ws, symbol: str) -> None:
        payload = self._build_payload(symbol, subscribe=True)
        if payload:
            await ws.send(payload)

    async def unsubscribe_symbol(self, ws, symbol: str) -> None:
        payload = self._build_payload(symbol, subscribe=False)
        if payload:
            await ws.send(payload)

    def _build_payload(self, symbol: str, subscribe: bool) -> Optional[str]:
        if self.payload_template:
            payload = self.payload_template.format(symbol=symbol, action=self.subscribe_key)
            if not subscribe and self.unsubscribe_template:
                payload = self.unsubscribe_template.format(symbol=symbol, action="unsubscribe")
            return payload

        message = {
            self.subscribe_key: subscribe,
            self.channel_key: symbol,
        }
        return json.dumps(message)

    async def handle_message(self, message: str) -> Sequence[WebsocketMessage]:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            logger.debug("Market stream discarded non-JSON payload: %s", message)
            return []

        if isinstance(payload, dict):
            symbol = payload.get(self.symbol_key)
            price = payload.get(self.price_key)
        else:
            return []

        if not symbol or price is None:
            return []

        try:
            price_decimal = Decimal(str(price))
        except Exception:  # pragma: no cover - defensive
            logger.debug("Market stream received invalid price payload: %s", payload)
            return []

        return [WebsocketMessage(symbol=symbol.upper(), price=price_decimal, raw=payload)]


class FinnhubAdapter(WebsocketAdapter):
    """Adapter for the Finnhub trade websocket."""

    def __init__(self) -> None:
        super().__init__("finnhub")
        base_url = os.getenv("MARKET_DATA_WS_URL") or os.getenv("FINNHUB_WS_URL") or "wss://ws.finnhub.io"
        token = (
            os.getenv("FINNHUB_API_TOKEN")
            or os.getenv("FINNHUB_TOKEN")
            or os.getenv("FINNHUB_API_KEY")
        )

        parsed = urlparse(base_url)
        query = parse_qs(parsed.query, keep_blank_values=True)

        existing_token = None
        if "token" in query and query["token"]:
            existing_token = query["token"][0]

        if not existing_token and token:
            query["token"] = [token]
        elif existing_token:
            query["token"] = [existing_token]

        if query:
            query_string = urlencode({key: value[0] for key, value in query.items()})
            self.ws_url = urlunparse(parsed._replace(query=query_string))
        else:
            self.ws_url = base_url
            if not token:
                logger.warning(
                    "Finnhub websocket URL has no token. Ensure your URL already includes ?token=..."
                )

    async def on_connect(self, ws, symbols: Iterable[str]) -> None:
        for symbol in symbols:
            await self.subscribe_symbol(ws, symbol)

    async def subscribe_symbol(self, ws, symbol: str) -> None:
        await ws.send(json.dumps({"type": "subscribe", "symbol": symbol}))

    async def unsubscribe_symbol(self, ws, symbol: str) -> None:
        await ws.send(json.dumps({"type": "unsubscribe", "symbol": symbol}))

    async def handle_message(self, message: str) -> Sequence[WebsocketMessage]:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            logger.debug("Finnhub stream discarded non-JSON payload: %s", message)
            return []

        msg_type = payload.get("type")
        if msg_type == "ping":
            return []
        if msg_type != "trade":
            return []

        data = payload.get("data") or []
        messages: List[WebsocketMessage] = []
        for entry in data:
            symbol = entry.get("s")
            price = entry.get("p")
            if not symbol or price is None:
                continue
            try:
                price_decimal = Decimal(str(price))
            except Exception:
                continue
            messages.append(
                WebsocketMessage(
                    symbol=symbol.upper(),
                    price=price_decimal,
                    raw=entry,
                )
            )
        return messages


class FivePaisaAdapter(WebsocketAdapter):
    """Adapter for 5paisa websocket price streams with configurable payloads."""

    def __init__(self) -> None:
        super().__init__("5paisa")
        ws_url = os.getenv("MARKET_DATA_WS_URL") or os.getenv("FIVEPAISA_WS_URL")
        if not ws_url:
            raise RuntimeError("FIVEPAISA_WS_URL environment variable is required for 5paisa market data")
        self.ws_url = ws_url
        self.auth_message = os.getenv("FIVEPAISA_AUTH_MESSAGE")
        self.subscribe_template = os.getenv("FIVEPAISA_SUBSCRIBE_TEMPLATE")
        self.unsubscribe_template = os.getenv("FIVEPAISA_UNSUBSCRIBE_TEMPLATE")
        self.symbol_key = os.getenv("FIVEPAISA_SYMBOL_KEY", "Symbol")
        self.price_keys = [
            key.strip()
            for key in os.getenv("FIVEPAISA_PRICE_KEYS", "LastTradedPrice,LastRate,LTP,Price").split(",")
            if key.strip()
        ]
        self.batch_key = os.getenv("FIVEPAISA_BATCH_KEY", "Data")

    async def on_connect(self, ws, symbols: Iterable[str]) -> None:
        if self.auth_message:
            await ws.send(self.auth_message)
        for symbol in symbols:
            await self.subscribe_symbol(ws, symbol)

    async def subscribe_symbol(self, ws, symbol: str) -> None:
        payload = self._build_subscription(symbol, subscribe=True)
        if payload:
            await ws.send(payload)

    async def unsubscribe_symbol(self, ws, symbol: str) -> None:
        payload = self._build_subscription(symbol, subscribe=False)
        if payload:
            await ws.send(payload)

    def _build_subscription(self, symbol: str, subscribe: bool) -> Optional[str]:
        template = self.subscribe_template if subscribe else self.unsubscribe_template
        if template:
            try:
                return template.format(symbol=symbol)
            except Exception:
                logger.warning("5paisa subscription template formatting failed for symbol %s", symbol)
                return None
        default_payload = {
            "Method": "SUBSCRIBE_L2" if subscribe else "UNSUBSCRIBE_L2",
            "Instrument": [symbol],
        }
        return json.dumps(default_payload)

    async def handle_message(self, message: str) -> Sequence[WebsocketMessage]:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            logger.debug("5paisa stream discarded non-JSON payload: %s", message)
            return []

        entries: List[Dict[str, Any]] = []
        batch = payload.get(self.batch_key) or payload.get(self.batch_key.lower())
        if isinstance(batch, list):
            entries.extend(batch)
        elif isinstance(payload, dict):
            entries.append(payload)

        messages: List[WebsocketMessage] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            symbol = entry.get(self.symbol_key) or entry.get(self.symbol_key.lower()) or entry.get("Token")
            price = self._extract_price(entry)
            if not symbol or price is None:
                continue
            messages.append(
                WebsocketMessage(
                    symbol=str(symbol).upper(),
                    price=price,
                    raw=entry,
                )
            )
        return messages

    def _extract_price(self, entry: Dict[str, Any]) -> Optional[Decimal]:
        for key in self.price_keys:
            value = entry.get(key) or entry.get(key.lower())
            if value is None:
                continue
            try:
                return Decimal(str(value))
            except Exception:
                continue
        return None


class MarketPriceSubject(ConnectorSubject):
    """Pathway connector subject managing a single websocket connection."""

    def __init__(self, adapter: WebsocketAdapter, retry_seconds: int = DEFAULT_RETRY_SECONDS) -> None:
        super().__init__()
        self._adapter = adapter
        self._retry_seconds = retry_seconds
        self._symbols: Set[str] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._symbol_queue: Optional[asyncio.Queue[str]] = None
        self._pending: Set[str] = set()
        self._lock = threading.Lock()

    @property
    def adapter(self) -> WebsocketAdapter:
        return self._adapter

    def add_symbol(self, symbol: str) -> None:
        normalized = symbol.upper()
        with self._lock:
            if normalized in self._symbols:
                return
            self._symbols.add(normalized)
            if self._loop and self._loop.is_running() and self._symbol_queue is not None:
                asyncio.run_coroutine_threadsafe(self._symbol_queue.put(normalized), self._loop)
            else:
                self._pending.add(normalized)

    def run(self) -> None:
        asyncio.run(self._run_forever())

    async def _run_forever(self) -> None:
        while True:
            try:
                await self._run_single_connection()
            except asyncio.CancelledError:  # pragma: no cover - shutdown path
                raise
            except Exception as exc:  # pragma: no cover - logging only
                logger.exception("MarketPriceSubject reconnect triggered: %s", exc)
                await asyncio.sleep(self._retry_seconds)

    async def _run_single_connection(self) -> None:
        import websockets

        url = getattr(self._adapter, "ws_url", DEFAULT_WS_URL)
        logger.info("Connecting to market data stream: %s", url)
        async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
            self._loop = asyncio.get_running_loop()
            self._symbol_queue = asyncio.Queue()

            for symbol in list(self._pending):
                await self._symbol_queue.put(symbol)
            self._pending.clear()

            await self._adapter.on_connect(ws, list(self._symbols))

            consumer = asyncio.create_task(self._consume_messages(ws))
            subscriber = asyncio.create_task(self._dispatch_subscriptions(ws, self._symbol_queue))

            done, pending = await asyncio.wait(
                {consumer, subscriber},
                return_when=asyncio.FIRST_EXCEPTION,
            )

            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

            for task in done:
                if task.exception():
                    raise task.exception()
        self._symbol_queue = None
        self._loop = None

    async def _consume_messages(self, ws) -> None:
        async for message in ws:
            parsed_messages = await self._adapter.handle_message(message)
            if not parsed_messages:
                continue
            for parsed in parsed_messages:
                self.next(
                    symbol=parsed.symbol,
                    price=str(parsed.price),
                    provider=self._adapter.name,
                    raw=json.dumps(parsed.raw, default=str),
                    received_at=asyncio.get_running_loop().time(),
                )

    async def _dispatch_subscriptions(self, ws, queue: asyncio.Queue[str]) -> None:
        while True:
            symbol = await queue.get()
            try:
                await self._adapter.subscribe_symbol(ws, symbol)
                logger.info("Subscribed to %s", symbol)
            except Exception as exc:
                logger.error("Failed to subscribe %s: %s", symbol, exc)
                self._pending.add(symbol)
                await asyncio.sleep(self._retry_seconds)


class MarketDataService:
    """Singleton service exposing cached market prices sourced via Pathway stream."""

    _instance: Optional["MarketDataService"] = None
    _instance_lock = threading.Lock()

    def __init__(self, adapter: Optional[WebsocketAdapter] = None) -> None:
        os.environ.setdefault("PATHWAY_DISABLE_PROGRESS", "1")
        os.environ.setdefault("PATHWAY_LOG_LEVEL", "warning")
        self.adapter = adapter or self._select_adapter()
        self.subject = MarketPriceSubject(self.adapter)
        self._latest: Dict[str, Decimal] = {}
        self._lock = threading.Lock()
        self._started = threading.Event()
        self._runner_thread = threading.Thread(target=self._run_pathway_runtime, daemon=True)
        self._runner_thread.start()
        self._started.wait(timeout=10)

    @classmethod
    def get_instance(cls) -> "MarketDataService":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def register_symbol(self, symbol: str) -> None:
        normalized = symbol.upper()
        self.subject.add_symbol(normalized)

    def get_latest_price(self, symbol: str) -> Optional[Decimal]:
        normalized = symbol.upper()
        with self._lock:
            return self._latest.get(normalized)

    def get_or_fetch_price(self, symbol: str) -> Decimal:
        normalized = symbol.upper()
        price = self.get_latest_price(normalized)
        if price is not None:
            return price

        logger.info("Waiting for first tick for %s", normalized)
        self.register_symbol(normalized)

        for _ in range(20):
            price = self.get_latest_price(normalized)
            if price is not None:
                return price
            time.sleep(0.5)

        raise RuntimeError(f"Live price for {normalized} unavailable from provider {self.adapter.name}")

    async def await_price(self, symbol: str, timeout: float = 10.0) -> Decimal:
        normalized = symbol.upper()
        self.register_symbol(normalized)
        deadline = time.time() + timeout

        price = self.get_latest_price(normalized)
        if price is not None:
            return price

        while time.time() < deadline:
            price = self.get_latest_price(normalized)
            if price is not None:
                return price
            await asyncio.sleep(0.3)

        raise RuntimeError(f"Timed out waiting for live price for {normalized}")

    def _run_pathway_runtime(self) -> None:
        table = pw.io.python.read(self.subject, schema=MarketTickSchema)

        def on_tick(_key: pw.Pointer, row: Dict[str, Any], _time: float, is_addition: bool) -> None:
            if not is_addition:
                return
            try:
                price = Decimal(row["price"])
            except Exception:
                logger.debug("Skipping tick with invalid price: %s", row)
                return
            symbol = row["symbol"].upper()
            with self._lock:
                self._latest[symbol] = price

        pw.io.subscribe(table, on_tick)
        self._started.set()
        try:
            monitoring_level = getattr(pw, "MonitoringLevel", None)
            if monitoring_level is not None and hasattr(monitoring_level, "ERRORS_ONLY"):
                pw.run(monitoring_level=monitoring_level.ERRORS_ONLY)
            else:
                pw.run()
        except AttributeError:
            pw.run()

    def _select_adapter(self) -> WebsocketAdapter:
        provider = os.getenv("MARKET_DATA_PROVIDER", DEFAULT_PROVIDER).lower()
        if provider == "finnhub":
            return FinnhubAdapter()
        if provider in {"5paisa", "fivepaisa"}:
            return FivePaisaAdapter()
        return GenericJSONAdapter()


def get_market_data_service() -> MarketDataService:
    return MarketDataService.get_instance()


def get_live_price(symbol: str) -> Decimal:
    service = get_market_data_service()
    return service.get_or_fetch_price(symbol)


async def await_live_price(symbol: str, timeout: float = 10.0) -> Decimal:
    service = get_market_data_service()
    return await service.await_price(symbol, timeout=timeout)

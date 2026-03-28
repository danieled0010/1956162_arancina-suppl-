from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import signal
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
import numpy as np
import websockets
from fastapi import FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from common.models import Base, DetectedEvent
from common.schemas import BrokerMeasurement

LOGGER = logging.getLogger("processor")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [processor] %(message)s")


class Settings(BaseSettings):
    processor_id: str = "processor-1"
    broker_ws_url: str = "ws://broker:8090/api/stream/ws"
    simulator_control_url: str = "http://simulator:8080/api/control"
    database_url: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/seismic"

    window_seconds: float = 4.0
    minimum_samples_per_window: int = 64
    analysis_stride_samples: int = 5
    reconnect_backoff_seconds: float = 2.0
    startup_retry_attempts: int = 15
    startup_retry_delay_seconds: float = 2.0
    min_peak_to_peak_amplitude: float = 1.2
    duplicate_emit_cooldown_seconds: float = 1.0

    model_config = SettingsConfigDict(env_prefix="PROCESSOR_", extra="ignore")


settings = Settings()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def classify_frequency(frequency_hz: float) -> str | None:
    if 0.5 <= frequency_hz < 3.0:
        return "earthquake"
    if 3.0 <= frequency_hz < 8.0:
        return "conventional_explosion"
    if frequency_hz >= 8.0:
        return "nuclear_like"
    return None


@dataclass
class SensorBuffer:
    samples: deque[tuple[datetime, float]] = field(default_factory=deque)
    processed_count: int = 0
    last_event_signature: str | None = None
    last_event_emitted_at: datetime | None = None


class EventStore:
    def __init__(self, database_url: str):
        self.engine = create_async_engine(database_url, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(bind=self.engine, class_=AsyncSession, expire_on_commit=False)

    async def start(self) -> None:
        # Protect DDL from concurrent replica startup race conditions.
        # Multiple processors may boot together and attempt metadata creation at the same time.
        async with self.engine.begin() as connection:
            await connection.execute(text("SELECT pg_advisory_lock(982341761)"))
            try:
                await connection.run_sync(Base.metadata.create_all)
            finally:
                await connection.execute(text("SELECT pg_advisory_unlock(982341761)"))

    async def stop(self) -> None:
        await self.engine.dispose()

    async def insert_event(self, payload: dict[str, Any]) -> bool:
        statement = pg_insert(DetectedEvent).values(**payload)
        statement = statement.on_conflict_do_nothing(index_elements=["event_signature"])

        async with self.session_factory() as session:
            result = await session.execute(statement)
            await session.commit()
            return bool(result.rowcount and result.rowcount > 0)


@dataclass
class ProcessorRuntime:
    event_store: EventStore
    buffers: dict[str, SensorBuffer] = field(default_factory=lambda: defaultdict(SensorBuffer))
    started_at: datetime = field(default_factory=utcnow)

    broker_task: asyncio.Task | None = None
    control_task: asyncio.Task | None = None
    broker_connected: bool = False
    control_connected: bool = False

    total_measurements: int = 0
    total_events_detected: int = 0
    total_events_persisted: int = 0
    total_duplicate_events_skipped: int = 0
    last_measurement_at: datetime | None = None

    async def start(self) -> None:
        await self._start_event_store_with_retry()
        self.broker_task = asyncio.create_task(self._broker_consumer_loop(), name="broker-consumer")
        self.control_task = asyncio.create_task(self._control_listener_loop(), name="control-listener")

    async def stop(self) -> None:
        for task in (self.broker_task, self.control_task):
            if task is None:
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self.event_store.stop()

    async def _broker_consumer_loop(self) -> None:
        while True:
            try:
                async with websockets.connect(settings.broker_ws_url, max_size=2_000_000) as websocket:
                    self.broker_connected = True
                    LOGGER.info("Connected to broker stream: %s", settings.broker_ws_url)
                    while True:
                        raw = await websocket.recv()
                        measurement = BrokerMeasurement.model_validate_json(raw)
                        await self._process_measurement(measurement)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.broker_connected = False
                LOGGER.warning("Broker stream disconnected (%s). Reconnecting...", exc)
                await asyncio.sleep(settings.reconnect_backoff_seconds)

    async def _start_event_store_with_retry(self) -> None:
        last_error: Exception | None = None
        for attempt in range(1, settings.startup_retry_attempts + 1):
            try:
                await self.event_store.start()
                if attempt > 1:
                    LOGGER.info("Event store initialized after %s attempts", attempt)
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                LOGGER.warning(
                    "Event store startup attempt %s/%s failed (%s). Retrying in %.1fs...",
                    attempt,
                    settings.startup_retry_attempts,
                    exc,
                    settings.startup_retry_delay_seconds,
                )
                await asyncio.sleep(settings.startup_retry_delay_seconds)

        raise RuntimeError("Failed to initialize event store after retries") from last_error

    async def _control_listener_loop(self) -> None:
        timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_read=None)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                try:
                    async with session.get(
                        settings.simulator_control_url,
                        headers={"Accept": "text/event-stream"},
                    ) as response:
                        response.raise_for_status()
                        self.control_connected = True
                        LOGGER.info("Connected to control stream: %s", settings.simulator_control_url)
                        event_name: str | None = None
                        data_lines: list[str] = []

                        async for chunk in response.content:
                            line = chunk.decode("utf-8").strip()
                            if not line:
                                if data_lines:
                                    payload = json.loads("\n".join(data_lines))
                                    if event_name == "command" and payload.get("command") == "SHUTDOWN":
                                        await self._terminate_for_shutdown()
                                        return
                                event_name = None
                                data_lines = []
                                continue

                            if line.startswith("event:"):
                                event_name = line.split(":", 1)[1].strip()
                            elif line.startswith("data:"):
                                data_lines.append(line.split(":", 1)[1].strip())
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    self.control_connected = False
                    LOGGER.warning("Control stream disconnected (%s). Reconnecting...", exc)
                    await asyncio.sleep(settings.reconnect_backoff_seconds)

    async def _process_measurement(self, measurement: BrokerMeasurement) -> None:
        sensor_id = measurement.sensor_id
        buffer = self.buffers[sensor_id]
        buffer.samples.append((measurement.timestamp, measurement.value))
        self.total_measurements += 1
        self.last_measurement_at = measurement.timestamp

        cutoff = measurement.timestamp - timedelta(seconds=settings.window_seconds)
        while buffer.samples and buffer.samples[0][0] < cutoff:
            buffer.samples.popleft()

        buffer.processed_count += 1
        if buffer.processed_count % settings.analysis_stride_samples != 0:
            return
        if len(buffer.samples) < settings.minimum_samples_per_window:
            return

        dominant_frequency_hz, peak_to_peak = self._analyze_window(buffer.samples, measurement.sampling_rate_hz)
        if dominant_frequency_hz is None:
            return

        event_type = classify_frequency(dominant_frequency_hz)
        if event_type is None:
            return

        if peak_to_peak < settings.min_peak_to_peak_amplitude:
            return

        window_start = buffer.samples[0][0]
        window_end = buffer.samples[-1][0]
        signature = self._build_signature(sensor_id, event_type, window_start, window_end)

        if signature == buffer.last_event_signature:
            return

        if (
            buffer.last_event_emitted_at is not None
            and (measurement.timestamp - buffer.last_event_emitted_at).total_seconds()
            < settings.duplicate_emit_cooldown_seconds
        ):
            return

        self.total_events_detected += 1
        payload = {
            "event_signature": signature,
            "sensor_id": sensor_id,
            "event_type": event_type,
            "dominant_frequency_hz": float(round(dominant_frequency_hz, 6)),
            "peak_to_peak_amplitude": float(round(peak_to_peak, 6)),
            "window_start": window_start,
            "window_end": window_end,
            "detected_by_replica": settings.processor_id,
            "metadata_json": {
                "sampleCount": len(buffer.samples),
                "windowSeconds": settings.window_seconds,
                "analysisStrideSamples": settings.analysis_stride_samples,
                "source": "fft",
            },
        }

        inserted = await self.event_store.insert_event(payload)
        if inserted:
            self.total_events_persisted += 1
            LOGGER.info(
                "Persisted event sensor=%s type=%s freq=%.3fHz p2p=%.3f",
                sensor_id,
                event_type,
                dominant_frequency_hz,
                peak_to_peak,
            )
        else:
            self.total_duplicate_events_skipped += 1

        buffer.last_event_signature = signature
        buffer.last_event_emitted_at = measurement.timestamp

    @staticmethod
    def _analyze_window(samples: deque[tuple[datetime, float]], sampling_rate_hz: float) -> tuple[float | None, float]:
        values = np.array([value for _, value in samples], dtype=np.float64)
        if values.size < 2:
            return None, 0.0

        peak_to_peak = float(np.max(values) - np.min(values))
        demeaned = values - np.mean(values)

        fft = np.fft.rfft(demeaned)
        frequencies = np.fft.rfftfreq(values.size, d=1.0 / sampling_rate_hz)
        magnitudes = np.abs(fft)
        if magnitudes.size <= 1:
            return None, peak_to_peak

        magnitudes[0] = 0.0
        dominant_idx = int(np.argmax(magnitudes))
        dominant_frequency_hz = float(frequencies[dominant_idx])
        return dominant_frequency_hz, peak_to_peak

    @staticmethod
    def _build_signature(sensor_id: str, event_type: str, window_start: datetime, window_end: datetime) -> str:
        raw = f"{sensor_id}|{event_type}|{window_start.isoformat()}|{window_end.isoformat()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def _terminate_for_shutdown(self) -> None:
        LOGGER.warning("Received SHUTDOWN command. Terminating replica %s", settings.processor_id)
        await asyncio.sleep(0.25)
        os.kill(os.getpid(), signal.SIGTERM)


store = EventStore(settings.database_url)
runtime = ProcessorRuntime(event_store=store)
app = FastAPI(title="Seismic Processor", version="1.0.0")


@app.on_event("startup")
async def on_startup() -> None:
    await runtime.start()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await runtime.stop()


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "processorId": settings.processor_id,
        "brokerConnected": runtime.broker_connected,
        "controlConnected": runtime.control_connected,
        "trackedSensors": len(runtime.buffers),
        "totalMeasurements": runtime.total_measurements,
        "totalEventsPersisted": runtime.total_events_persisted,
        "lastMeasurementAt": runtime.last_measurement_at.isoformat() if runtime.last_measurement_at else None,
        "startedAt": runtime.started_at.isoformat(),
    }


@app.get("/internal/summary")
async def summary() -> dict[str, Any]:
    return {
        "processorId": settings.processor_id,
        "trackedSensors": len(runtime.buffers),
        "totalMeasurements": runtime.total_measurements,
        "totalEventsDetected": runtime.total_events_detected,
        "totalEventsPersisted": runtime.total_events_persisted,
        "totalDuplicateEventsSkipped": runtime.total_duplicate_events_skipped,
        "brokerConnected": runtime.broker_connected,
        "controlConnected": runtime.control_connected,
    }


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "processor",
        "health": "/health",
        "summary": "/internal/summary",
    }

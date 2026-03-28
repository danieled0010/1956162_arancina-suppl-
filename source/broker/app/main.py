from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic_settings import BaseSettings, SettingsConfigDict

LOGGER = logging.getLogger("broker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [broker] %(message)s")


class Settings(BaseSettings):
    simulator_base_url: str = "http://simulator:8080"
    sensor_discovery_interval_seconds: float = 20.0
    reconnect_backoff_seconds: float = 2.0
    subscriber_queue_size: int = 1024

    model_config = SettingsConfigDict(env_prefix="BROKER_", extra="ignore")


settings = Settings()


@dataclass
class BrokerRuntime:
    sensors: dict[str, dict[str, Any]] = field(default_factory=dict)
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    sensor_tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    discovery_task: asyncio.Task | None = None
    total_messages: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_measurement_at: str | None = None

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=settings.subscriber_queue_size)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.subscribers.discard(queue)

    async def broadcast(self, message: dict[str, Any]) -> None:
        if not self.subscribers:
            return

        for queue in tuple(self.subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                continue

    async def start(self) -> None:
        if self.discovery_task is None:
            self.discovery_task = asyncio.create_task(self._discovery_loop(), name="sensor-discovery")

    async def stop(self) -> None:
        if self.discovery_task is not None:
            self.discovery_task.cancel()
            await _suppress_cancelled(self.discovery_task)
            self.discovery_task = None

        for sensor_id, task in list(self.sensor_tasks.items()):
            task.cancel()
            await _suppress_cancelled(task)
            self.sensor_tasks.pop(sensor_id, None)

    async def _discovery_loop(self) -> None:
        while True:
            try:
                await self._refresh_sensors()
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Sensor discovery failed: %s", exc)
            await asyncio.sleep(settings.sensor_discovery_interval_seconds)

    async def _refresh_sensors(self) -> None:
        endpoint = urljoin(settings.simulator_base_url.rstrip("/") + "/", "api/devices/")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(endpoint)
            response.raise_for_status()
            payload = response.json()

        new_sensors: dict[str, dict[str, Any]] = {}
        for sensor in payload:
            sensor_id = sensor["id"]
            new_sensors[sensor_id] = sensor
            if sensor_id not in self.sensor_tasks:
                self.sensor_tasks[sensor_id] = asyncio.create_task(
                    self._sensor_ingest_loop(sensor_id),
                    name=f"sensor-{sensor_id}",
                )
                LOGGER.info("Started ingest task for %s", sensor_id)

        removed_ids = set(self.sensor_tasks) - set(new_sensors)
        for sensor_id in removed_ids:
            task = self.sensor_tasks.pop(sensor_id)
            task.cancel()
            await _suppress_cancelled(task)
            LOGGER.info("Stopped ingest task for removed sensor %s", sensor_id)

        self.sensors = new_sensors

    async def _sensor_ingest_loop(self, sensor_id: str) -> None:
        while True:
            sensor = self.sensors.get(sensor_id)
            if sensor is None:
                await asyncio.sleep(settings.reconnect_backoff_seconds)
                continue

            ws_endpoint = _build_ws_endpoint(settings.simulator_base_url, sensor["websocket_url"])
            try:
                async with websockets.connect(ws_endpoint, max_size=2_000_000) as websocket:
                    LOGGER.info("Connected to simulator stream for %s", sensor_id)
                    while True:
                        raw = await websocket.recv()
                        sample = json.loads(raw)
                        envelope = {
                            "sensorId": sensor_id,
                            "timestamp": sample["timestamp"],
                            "value": sample["value"],
                            "samplingRateHz": sensor.get("sampling_rate_hz", 20.0),
                        }
                        self.total_messages += 1
                        self.last_measurement_at = envelope["timestamp"]
                        await self.broadcast(envelope)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Sensor stream %s disconnected (%s). Reconnecting...", sensor_id, exc)
                await asyncio.sleep(settings.reconnect_backoff_seconds)


async def _suppress_cancelled(task: asyncio.Task) -> None:
    try:
        await task
    except asyncio.CancelledError:
        pass


def _build_ws_endpoint(base_http_url: str, ws_path: str) -> str:
    parsed = urlparse(base_http_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = ws_path if ws_path.startswith("/") else f"/{ws_path}"
    return urlunparse((scheme, parsed.netloc, path, "", "", ""))


runtime = BrokerRuntime()
app = FastAPI(title="Seismic Broker", version="1.0.0")


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
        "sensorsDiscovered": len(runtime.sensors),
        "subscribers": len(runtime.subscribers),
        "totalMessages": runtime.total_messages,
        "lastMeasurementAt": runtime.last_measurement_at,
        "startedAt": runtime.started_at.isoformat(),
    }


@app.get("/api/sensors")
async def list_sensors() -> list[dict[str, Any]]:
    return list(runtime.sensors.values())


@app.websocket("/api/stream/ws")
async def stream_to_processors(websocket: WebSocket) -> None:
    await websocket.accept()
    queue = runtime.subscribe()
    try:
        while True:
            message = await queue.get()
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    finally:
        runtime.unsubscribe(queue)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "broker",
        "health": "/health",
        "stream": "/api/stream/ws",
        "sensors": "/api/sensors",
    }

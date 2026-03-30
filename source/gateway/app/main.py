from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
from datetime import datetime
from itertools import cycle
from typing import Any, Literal

import httpx
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Select, asc, desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from common.models import DetectedEvent
from common.schemas import EventOut

LOGGER = logging.getLogger("gateway")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [gateway] %(message)s")


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/seismic"
    processor_urls: str = "http://processor-a:8091,http://processor-b:8091,http://processor-c:8091"
    broker_base_url: str = "http://broker:8090"
    simulator_base_url: str = "http://simulator:8080"
    processor_health_timeout_seconds: float = 2.0
    live_poll_interval_seconds: float = 1.0
    upstream_timeout_seconds: float = 8.0

    model_config = SettingsConfigDict(env_prefix="GATEWAY_", extra="ignore")


settings = Settings()


class GatewayRuntime:
    def __init__(self) -> None:
        self.engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(bind=self.engine, class_=AsyncSession, expire_on_commit=False)
        urls = [item.strip() for item in settings.processor_urls.split(",") if item.strip()]
        self.processor_urls = urls
        self._round_robin_cycle = cycle(urls) if urls else cycle([])

    async def close(self) -> None:
        await self.engine.dispose()

    async def db_healthy(self) -> bool:
        try:
            async with self.session_factory() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception:  # noqa: BLE001
            return False

    async def list_replica_statuses(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=settings.processor_health_timeout_seconds) as client:
            tasks = [self._fetch_replica_status(client, url) for url in self.processor_urls]
            return await asyncio.gather(*tasks)

    async def _fetch_replica_status(self, client: httpx.AsyncClient, base_url: str) -> dict[str, Any]:
        try:
            response = await client.get(f"{base_url}/health")
            response.raise_for_status()
            payload = response.json()
            return {
                "url": base_url,
                "healthy": True,
                "processorId": payload.get("processorId"),
                "details": payload,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "url": base_url,
                "healthy": False,
                "processorId": None,
                "details": {"error": str(exc)},
            }

    async def proxy_summary_to_healthy_replica(self) -> dict[str, Any]:
        statuses = await self.list_replica_statuses()
        healthy_urls = [status["url"] for status in statuses if status["healthy"]]
        if not healthy_urls:
            raise HTTPException(status_code=503, detail="No healthy processing replicas available.")

        async with httpx.AsyncClient(timeout=settings.processor_health_timeout_seconds) as client:
            for _ in range(len(healthy_urls)):
                candidate = next(self._round_robin_cycle)
                if candidate not in healthy_urls:
                    continue
                try:
                    response = await client.get(f"{candidate}/internal/summary")
                    response.raise_for_status()
                    return {
                        "routedTo": candidate,
                        "summary": response.json(),
                        "healthyReplicaCount": len(healthy_urls),
                    }
                except Exception:  # noqa: BLE001
                    continue

        raise HTTPException(status_code=503, detail="All healthy replicas failed to answer summary request.")

    async def fetch_sensors(self) -> list[dict[str, Any]]:
        endpoint = f"{settings.broker_base_url.rstrip('/')}/api/sensors"
        try:
            async with httpx.AsyncClient(timeout=settings.upstream_timeout_seconds) as client:
                response = await client.get(endpoint)
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, list):
                    return payload
                return []
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Failed to fetch sensors from broker (%s): %s", endpoint, exc)
            return []

    async def check_upstream_health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=settings.upstream_timeout_seconds) as client:
            broker_url = f"{settings.broker_base_url.rstrip('/')}/health"
            simulator_url = f"{settings.simulator_base_url.rstrip('/')}/health"
            broker_result = await self._probe_health_endpoint(client, broker_url, "broker")
            simulator_result = await self._probe_health_endpoint(client, simulator_url, "simulator")
        return {"broker": broker_result, "simulator": simulator_result}

    async def _probe_health_endpoint(
        self,
        client: httpx.AsyncClient,
        url: str,
        name: str,
    ) -> dict[str, Any]:
        try:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
            return {"service": name, "healthy": True, "url": url, "details": payload}
        except Exception as exc:  # noqa: BLE001
            return {"service": name, "healthy": False, "url": url, "details": {"error": str(exc)}}


class SensorEventTriggerRequest(BaseModel):
    event_type: Literal[
        "earthquake",
        "conventional_explosion",
        "nuclear_like",
    ]


def _apply_event_filters(
    statement: Select[Any],
    *,
    sensor_id: str | None,
    event_type: str | None,
    since: datetime | None,
    until: datetime | None,
) -> Select[Any]:
    if sensor_id:
        statement = statement.where(DetectedEvent.sensor_id == sensor_id)
    if event_type:
        statement = statement.where(DetectedEvent.event_type == event_type)
    if since:
        statement = statement.where(DetectedEvent.created_at >= since)
    if until:
        statement = statement.where(DetectedEvent.created_at <= until)
    return statement


runtime = GatewayRuntime()
app = FastAPI(title="Seismic Gateway", version="1.0.0")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await runtime.close()


@app.get("/health")
async def health() -> dict[str, Any]:
    db_ok = await runtime.db_healthy()
    replicas = await runtime.list_replica_statuses()
    healthy_count = sum(1 for replica in replicas if replica["healthy"])

    return {
        "status": "ok" if db_ok else "degraded",
        "databaseHealthy": db_ok,
        "totalReplicas": len(replicas),
        "healthyReplicas": healthy_count,
    }


@app.get("/health/full")
async def health_full() -> dict[str, Any]:
    db_ok = await runtime.db_healthy()
    replica_statuses = await runtime.list_replica_statuses()
    upstreams = await runtime.check_upstream_health()
    all_replicas_healthy = all(item["healthy"] for item in replica_statuses) if replica_statuses else False
    upstream_ok = all(item["healthy"] for item in upstreams.values())
    overall_ok = db_ok and all_replicas_healthy and upstream_ok

    return {
        "status": "ok" if overall_ok else "degraded",
        "databaseHealthy": db_ok,
        "replicas": {
            "total": len(replica_statuses),
            "healthy": sum(1 for item in replica_statuses if item["healthy"]),
            "items": replica_statuses,
        },
        "upstreams": upstreams,
    }


@app.get("/api/replicas")
async def replicas() -> dict[str, Any]:
    statuses = await runtime.list_replica_statuses()
    return {
        "total": len(statuses),
        "healthy": sum(1 for status in statuses if status["healthy"]),
        "replicas": statuses,
    }


@app.get("/api/processing/summary")
async def processing_summary() -> dict[str, Any]:
    return await runtime.proxy_summary_to_healthy_replica()


@app.get("/api/sensors")
async def sensors() -> dict[str, Any]:
    rows = await runtime.fetch_sensors()
    field_count = sum(1 for item in rows if item.get("category") == "field")
    datacenter_count = sum(1 for item in rows if item.get("category") == "datacenter")
    return {
        "total": len(rows),
        "field": field_count,
        "datacenter": datacenter_count,
        "items": rows,
    }


@app.get("/api/system/overview")
async def system_overview() -> dict[str, Any]:
    db_ok = await runtime.db_healthy()
    replica_statuses = await runtime.list_replica_statuses()
    sensor_payload = await runtime.fetch_sensors()

    async with runtime.session_factory() as session:
        total_events = (await session.execute(select(func.count(DetectedEvent.id)))).scalar_one()
        latest_event_at = (await session.execute(select(func.max(DetectedEvent.created_at)))).scalar_one()
        type_rows = (
            await session.execute(
                select(DetectedEvent.event_type, func.count(DetectedEvent.id))
                .group_by(DetectedEvent.event_type)
                .order_by(desc(func.count(DetectedEvent.id)))
            )
        ).all()

    counts_by_type = {event_type: count for event_type, count in type_rows}
    return {
        "generatedAt": datetime.utcnow().isoformat() + "Z",
        "gateway": {
            "status": "ok" if db_ok else "degraded",
            "databaseHealthy": db_ok,
        },
        "replicas": {
            "total": len(replica_statuses),
            "healthy": sum(1 for item in replica_statuses if item["healthy"]),
            "items": replica_statuses,
        },
        "sensors": {
            "total": len(sensor_payload),
            "field": sum(1 for item in sensor_payload if item.get("category") == "field"),
            "datacenter": sum(1 for item in sensor_payload if item.get("category") == "datacenter"),
        },
        "events": {
            "totalPersisted": total_events,
            "countsByType": counts_by_type,
            "lastDetectedAt": latest_event_at.isoformat() if latest_event_at else None,
        },
    }


@app.get("/api/events", response_model=list[EventOut])
async def list_events(
    limit: int = Query(default=100, ge=1, le=1000),
    sensor_id: str | None = None,
    event_type: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> list[EventOut]:
    statement: Select[tuple[DetectedEvent]] = select(DetectedEvent)
    statement = _apply_event_filters(
        statement,
        sensor_id=sensor_id,
        event_type=event_type,
        since=since,
        until=until,
    )

    statement = statement.order_by(asc(DetectedEvent.created_at) if order == "asc" else desc(DetectedEvent.created_at))
    statement = statement.limit(limit)

    async with runtime.session_factory() as session:
        rows = (await session.execute(statement)).scalars().all()

    return [_to_event_out(row) for row in rows]


@app.get("/api/events/export.csv")
async def export_events_csv(
    limit: int = Query(default=2000, ge=1, le=10000),
    sensor_id: str | None = None,
    event_type: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Response:
    statement: Select[tuple[DetectedEvent]] = select(DetectedEvent)
    statement = _apply_event_filters(
        statement,
        sensor_id=sensor_id,
        event_type=event_type,
        since=since,
        until=until,
    )
    statement = statement.order_by(desc(DetectedEvent.created_at)).limit(limit)

    async with runtime.session_factory() as session:
        rows = (await session.execute(statement)).scalars().all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "id",
            "event_signature",
            "sensor_id",
            "event_type",
            "dominant_frequency_hz",
            "peak_to_peak_amplitude",
            "window_start",
            "window_end",
            "detected_by_replica",
            "created_at",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.id,
                row.event_signature,
                row.sensor_id,
                row.event_type,
                row.dominant_frequency_hz,
                row.peak_to_peak_amplitude,
                row.window_start.isoformat(),
                row.window_end.isoformat(),
                row.detected_by_replica,
                row.created_at.isoformat(),
            ]
        )

    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=detected-events.csv"},
    )


@app.get("/api/events/by-id/{event_id}", response_model=EventOut)
async def get_event(event_id: int) -> EventOut:
    async with runtime.session_factory() as session:
        row = await session.get(DetectedEvent, event_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found.")
    return _to_event_out(row)


@app.get("/api/analytics/overview")
async def analytics_overview(
    sensor_id: str | None = None,
    event_type: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    async with runtime.session_factory() as session:
        total_stmt = _apply_event_filters(
            select(func.count(DetectedEvent.id)),
            sensor_id=sensor_id,
            event_type=event_type,
            since=since,
            until=until,
        )
        total_events = (await session.execute(total_stmt)).scalar_one()

        band_stmt = _apply_event_filters(
            select(DetectedEvent.event_type, func.count(DetectedEvent.id)).group_by(DetectedEvent.event_type),
            sensor_id=sensor_id,
            event_type=event_type,
            since=since,
            until=until,
        )
        band_rows = (await session.execute(band_stmt)).all()

        sensor_stmt = _apply_event_filters(
            select(DetectedEvent.sensor_id, func.count(DetectedEvent.id))
            .group_by(DetectedEvent.sensor_id)
            .order_by(desc(func.count(DetectedEvent.id)))
            .limit(10),
            sensor_id=sensor_id,
            event_type=event_type,
            since=since,
            until=until,
        )
        sensor_rows = (await session.execute(sensor_stmt)).all()

        stats_stmt = _apply_event_filters(
            select(
                func.avg(DetectedEvent.dominant_frequency_hz),
                func.avg(DetectedEvent.peak_to_peak_amplitude),
                func.min(DetectedEvent.created_at),
                func.max(DetectedEvent.created_at),
            ),
            sensor_id=sensor_id,
            event_type=event_type,
            since=since,
            until=until,
        )
        avg_freq, avg_amp, first_seen, last_seen = (await session.execute(stats_stmt)).one()

    counts_by_type = {kind: count for kind, count in band_rows}
    top_sensors = [{"sensorId": sid, "count": count} for sid, count in sensor_rows]
    dominant_type = max(counts_by_type.items(), key=lambda item: item[1])[0] if counts_by_type else None

    return {
        "filters": {
            "sensorId": sensor_id,
            "eventType": event_type,
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
        },
        "totalEvents": total_events,
        "dominantType": dominant_type,
        "countsByType": counts_by_type,
        "topSensors": top_sensors,
        "avgDominantFrequencyHz": float(avg_freq) if avg_freq is not None else None,
        "avgPeakToPeakAmplitude": float(avg_amp) if avg_amp is not None else None,
        "firstDetectedAt": first_seen.isoformat() if first_seen else None,
        "lastDetectedAt": last_seen.isoformat() if last_seen else None,
    }


@app.get("/api/events/live")
async def live_events(last_event_id: int = Query(default=0, ge=0)) -> StreamingResponse:
    async def event_stream() -> Any:
        current_last_id = last_event_id
        while True:
            statement = (
                select(DetectedEvent)
                .where(DetectedEvent.id > current_last_id)
                .order_by(asc(DetectedEvent.id))
                .limit(200)
            )
            async with runtime.session_factory() as session:
                rows = (await session.execute(statement)).scalars().all()

            if rows:
                for row in rows:
                    current_last_id = max(current_last_id, row.id)
                    payload = _to_event_out(row).model_dump(mode="json")
                    yield f"event: detected_event\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"
            else:
                yield "event: heartbeat\ndata: {\"status\":\"alive\"}\n\n"

            await asyncio.sleep(settings.live_poll_interval_seconds)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.get("/api/events/stream-status")
async def stream_status() -> dict[str, Any]:
    async with runtime.session_factory() as session:
        total_events = (await session.execute(select(func.count(DetectedEvent.id)))).scalar_one()
        latest_id = (await session.execute(select(func.max(DetectedEvent.id)))).scalar_one()
        latest_at = (await session.execute(select(func.max(DetectedEvent.created_at)))).scalar_one()

    now = datetime.utcnow()
    age_seconds = None
    if latest_at is not None:
        age_seconds = max((now - latest_at.replace(tzinfo=None)).total_seconds(), 0.0)

    return {
        "totalPersistedEvents": total_events,
        "latestEventId": latest_id,
        "latestEventAt": latest_at.isoformat() if latest_at else None,
        "secondsSinceLatestEvent": age_seconds,
        "liveFeedLikelyIdle": bool(total_events == 0 or (age_seconds is not None and age_seconds > 30)),
    }


@app.post("/api/admin/sensors/{sensor_id}/events")
async def trigger_sensor_event(sensor_id: str, request: SensorEventTriggerRequest = Body(...)) -> dict[str, Any]:
    endpoint = f"{settings.simulator_base_url.rstrip('/')}/api/admin/sensors/{sensor_id}/events"
    async with httpx.AsyncClient(timeout=settings.upstream_timeout_seconds) as client:
        response = await client.post(endpoint, json=request.model_dump())
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()


@app.post("/api/admin/shutdown")
async def trigger_shutdown() -> dict[str, Any]:
    endpoint = f"{settings.simulator_base_url.rstrip('/')}/api/admin/shutdown"
    async with httpx.AsyncClient(timeout=settings.upstream_timeout_seconds) as client:
        response = await client.post(endpoint)
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "gateway",
        "health": "/health",
        "healthFull": "/health/full",
        "events": "/api/events",
        "liveEvents": "/api/events/live",
        "streamStatus": "/api/events/stream-status",
        "replicas": "/api/replicas",
        "sensors": "/api/sensors",
        "systemOverview": "/api/system/overview",
        "analyticsOverview": "/api/analytics/overview",
        "eventsCsvExport": "/api/events/export.csv",
    }


def _to_event_out(row: DetectedEvent) -> EventOut:
    return EventOut(
        id=row.id,
        event_signature=row.event_signature,
        sensor_id=row.sensor_id,
        event_type=row.event_type,
        dominant_frequency_hz=row.dominant_frequency_hz,
        peak_to_peak_amplitude=row.peak_to_peak_amplitude,
        window_start=row.window_start,
        window_end=row.window_end,
        detected_by_replica=row.detected_by_replica,
        metadata_json=row.metadata_json,
        created_at=row.created_at,
    )

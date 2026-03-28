from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SensorMeasurement(BaseModel):
    timestamp: datetime
    value: float


class BrokerMeasurement(BaseModel):
    sensor_id: str = Field(..., alias="sensorId")
    timestamp: datetime
    value: float
    sampling_rate_hz: float = Field(..., alias="samplingRateHz")

    model_config = {"populate_by_name": True}


class EventOut(BaseModel):
    id: int
    event_signature: str
    sensor_id: str
    event_type: str
    dominant_frequency_hz: float
    peak_to_peak_amplitude: float
    window_start: datetime
    window_end: datetime
    detected_by_replica: str
    metadata_json: dict[str, Any]
    created_at: datetime

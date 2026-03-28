from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class DetectedEvent(Base):
    __tablename__ = "detected_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_signature: Mapped[str] = mapped_column(String(128), nullable=False)
    sensor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    dominant_frequency_hz: Mapped[float] = mapped_column(Float, nullable=False)
    peak_to_peak_amplitude: Mapped[float] = mapped_column(Float, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detected_by_replica: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("event_signature", name="uq_detected_events_event_signature"),
        Index("ix_detected_events_sensor_id", "sensor_id"),
        Index("ix_detected_events_event_type", "event_type"),
        Index("ix_detected_events_created_at", "created_at"),
    )

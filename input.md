# Seismic Platform User Stories (30 Total)

This list is based on the current implementation in this repository.

Legend:
- `Done (existing)` = already available before this story pass
- `Done (implemented now)` = added in this story pass

| ID | User Story | Status | Evidence |
|---|---|---|---|
| US-01 | As an operator, I want to start the full distributed stack with one command so that the platform is reproducible. | Done (existing) | `docker-compose.yml` |
| US-02 | As an operator, I want automatic sensor discovery from the simulator so that newly available sensors can be ingested without manual wiring. | Done (existing) | `broker` discovery loop in `source/broker/app/main.py` |
| US-03 | As an operator, I want ingestion of each sensor WebSocket stream so that real-time measurements enter the platform. | Done (existing) | `broker` `_sensor_ingest_loop` |
| US-04 | As an operator, I want the broker to fan-out raw measurements to replicas so that processing is distributed and fault tolerant. | Done (existing) | `broker` `/api/stream/ws` |
| US-05 | As an operator, I want each processor replica to keep an in-memory sliding window per sensor so FFT/DFT analysis is possible. | Done (existing) | `processor` `SensorBuffer` + window trimming |
| US-06 | As an operator, I want FFT-based dominant frequency extraction so that detections can be classified by spectrum. | Done (existing) | `processor` `_analyze_window` |
| US-07 | As an operator, I want events in `0.5 <= f < 3.0` classified as earthquakes so alerts reflect seismic signatures. | Done (existing) | `processor` `classify_frequency` |
| US-08 | As an operator, I want events in `3.0 <= f < 8.0` classified as conventional explosions so alerts reflect blast signatures. | Done (existing) | `processor` `classify_frequency` |
| US-09 | As an operator, I want events in `f >= 8.0` classified as nuclear-like so high-risk signatures are flagged immediately. | Done (existing) | `processor` `classify_frequency` |
| US-10 | As an operator, I want detected events persisted to shared Postgres so that all replicas write to a common durable store. | Done (existing) | `processor` `EventStore` + Postgres config |
| US-11 | As an operator, I want duplicate-safe persistence so that replica overlap does not create duplicate event records. | Done (existing) | unique `event_signature` + `ON CONFLICT DO NOTHING` |
| US-12 | As an operator, I want processing replicas to terminate on simulator `SHUTDOWN` command so failure scenarios are testable. | Done (existing) | `processor` control SSE listener + SIGTERM |
| US-13 | As an operator, I want a single gateway entrypoint so frontend clients do not depend on individual replicas. | Done (existing) | `gateway` service and API |
| US-14 | As an operator, I want health-aware routing to healthy replicas so partial failures do not break summary queries. | Done (existing) | `gateway` `/api/processing/summary` |
| US-15 | As an operator, I want filterable historical event queries so I can inspect detections by sensor/type/time. | Done (existing) | `gateway` `/api/events` |
| US-16 | As an operator, I want live event delivery via SSE so I can monitor detections in real time. | Done (existing) | `gateway` `/api/events/live` + frontend live list |
| US-17 | As an operator, I want dashboard health and replica visibility so I can monitor runtime stability. | Done (existing) | frontend status cards + replicas panel |
| US-18 | As an operator, I want to pause/resume live stream updates so I can temporarily inspect static state. | Done (existing) | frontend stream toggle |
| US-19 | As an operator, I want a canonical sensor catalog so filters and controls are based on real discovered devices. | Done (implemented now) | `gateway` `/api/sensors` + frontend sensor map |
| US-20 | As an operator, I want to export filtered historical events to CSV so I can share and analyze data offline. | Done (implemented now) | `gateway` `/api/events/export.csv` + frontend export button |
| US-21 | As an operator, I want to open a detailed view of a specific event so I can inspect full metadata and timing. | Done (implemented now) | `gateway` `/api/events/by-id/{event_id}` + frontend modal |
| US-22 | As an operator, I want analytics overview (counts, top sensors, average frequency/amplitude) so I can understand trend and intensity quickly. | Done (implemented now) | `gateway` `/api/analytics/overview` + frontend analytics panel |
| US-23 | As an operator, I want to trigger manual sensor events from the dashboard so I can run deterministic test scenarios. | Done (implemented now) | `gateway` `/api/admin/sensors/{sensor_id}/events` + frontend controls |
| US-24 | As an operator, I want to trigger manual shutdown from the dashboard so I can validate fault tolerance behavior quickly. | Done (implemented now) | `gateway` `/api/admin/shutdown` + frontend controls |
| US-25 | As an operator, I want a consolidated system overview endpoint so status, sensor inventory, and event totals are available in one call. | Done (implemented now) | `gateway` `/api/system/overview` |
| US-26 | As an operator, I want schema initialization guarded against concurrent replica startup so processors do not crash on boot races. | Done (implemented now) | `processor` advisory lock around metadata creation |
| US-27 | As an operator, I want processor startup retries for datastore initialization so temporary Postgres unavailability does not kill replicas. | Done (implemented now) | `processor` `_start_event_store_with_retry` |
| US-28 | As an operator, I want processors to auto-restart when they terminate so replica health recovers automatically after failures. | Done (implemented now) | `docker-compose.yml` `restart: unless-stopped` on processors |
| US-29 | As an operator, I want full health diagnostics including broker and simulator upstreams so I can quickly identify availability bottlenecks. | Done (implemented now) | `gateway` `/health/full` |
| US-30 | As an operator, I want live-feed status diagnostics so I can distinguish "no detections yet" from pipeline failures. | Done (implemented now) | `gateway` `/api/events/stream-status` |

## Notes

- Stories US-19 to US-30 were implemented in this pass.
- Stories US-01 to US-18 were already present in the current codebase.

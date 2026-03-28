# SYSTEM DESCRIPTION:

Seismic Intelligence Platform is a distributed monitoring system for seismic threat detection in a fragile geopolitical scenario. It continuously acquires vibration streams from a provided simulator, distributes measurements to processing replicas, detects suspicious frequency patterns with FFT analysis, and persists classified events in a shared datastore with duplicate-safe guarantees.

A neutral-region command center accesses the platform through a single gateway and a real-time dashboard. The system is designed to stay operational during partial failures by using health-aware routing, multiple processor replicas, startup retry logic, and automatic container restarts.

# USER STORIES:

1. As an operator, I want to start the full distributed stack with one command so that the platform is reproducible.
2. As an operator, I want automatic sensor discovery from the simulator so that newly available sensors can be ingested without manual wiring.
3. As an operator, I want ingestion of each sensor WebSocket stream so that real-time measurements enter the platform.
4. As an operator, I want the broker to fan-out raw measurements to replicas so that processing is distributed and fault tolerant.
5. As an operator, I want each processor replica to keep an in-memory sliding window per sensor so FFT/DFT analysis is possible.
6. As an operator, I want FFT-based dominant frequency extraction so that detections can be classified by spectrum.
7. As an operator, I want events in `0.5 <= f < 3.0` classified as earthquakes so alerts reflect seismic signatures.
8. As an operator, I want events in `3.0 <= f < 8.0` classified as conventional explosions so alerts reflect blast signatures.
9. As an operator, I want events in `f >= 8.0` classified as nuclear-like so high-risk signatures are flagged immediately.
10. As an operator, I want detected events persisted to shared Postgres so that all replicas write to a common durable store.
11. As an operator, I want duplicate-safe persistence so that replica overlap does not create duplicate event records.
12. As an operator, I want processing replicas to terminate on simulator `SHUTDOWN` command so failure scenarios are testable.
13. As an operator, I want a single gateway entrypoint so frontend clients do not depend on individual replicas.
14. As an operator, I want health-aware routing to healthy replicas so partial failures do not break summary queries.
15. As an operator, I want filterable historical event queries so I can inspect detections by sensor/type/time.
16. As an operator, I want live event delivery via SSE so I can monitor detections in real time.
17. As an operator, I want dashboard health and replica visibility so I can monitor runtime stability.
18. As an operator, I want to pause/resume live stream updates so I can temporarily inspect static state.
19. As an operator, I want a canonical sensor catalog so filters and controls are based on real discovered devices.
20. As an operator, I want to export filtered historical events to CSV so I can share and analyze data offline.
21. As an operator, I want to open a detailed view of a specific event so I can inspect full metadata and timing.
22. As an operator, I want analytics overview (counts, top sensors, average frequency/amplitude) so I can understand trend and intensity quickly.
23. As an operator, I want to trigger manual sensor events from the dashboard so I can run deterministic test scenarios.
24. As an operator, I want to trigger manual shutdown from the dashboard so I can validate fault tolerance behavior quickly.
25. As an operator, I want a consolidated system overview endpoint so status, sensor inventory, and event totals are available in one call.
26. As an operator, I want schema initialization guarded against concurrent replica startup so processors do not crash on boot races.
27. As an operator, I want processor startup retries for datastore initialization so temporary Postgres unavailability does not kill replicas.
28. As an operator, I want processors to auto-restart when they terminate so replica health recovers automatically after failures.
29. As an operator, I want full health diagnostics including broker and simulator upstreams so I can quickly identify availability bottlenecks.
30. As an operator, I want live-feed status diagnostics so I can distinguish "no detections yet" from pipeline failures.

# CONTAINERS:

## CONTAINER_NAME: simulator

### DESCRIPTION:
Provided seismic signal simulator container exposing sensor discovery, per-sensor WebSocket streams, control SSE, and instructor triggers.

### USER STORIES:
2, 3, 12, 23, 24, 29

### PORTS:
8080:8080

### DESCRIPTION:
External black-box service used as seismic data source and control-command source. It also exposes manual testing endpoints for deterministic disturbances and shutdown commands.

### PERSISTENCE EVALUATION
Not applicable (external dependency).

### EXTERNAL SERVICES CONNECTIONS
None.

### MICROSERVICES:

#### MICROSERVICE: seismic-signal-simulator
- TYPE: external
- DESCRIPTION: Seismic measurement and control simulator provided by instructors.
- PORTS: 8080
- TECHNOLOGICAL SPECIFICATION: Provided Docker image (`seismic-signal-simulator:multiarch_v1`).
- SERVICE ARCHITECTURE: External REST + SSE + WebSocket service.

## CONTAINER_NAME: postgres

### DESCRIPTION:
Shared relational datastore for persisted detected events across all processor replicas.

### USER STORIES:
10, 11, 15, 20, 21, 22, 25, 26, 27, 30

### PORTS:
5432:5432

### DESCRIPTION:
Stores deduplicated event records in a single database used by processors (writes) and gateway (reads/analytics/export/live feed polling status).

### PERSISTENCE EVALUATION
Persistent volume `postgres_data:/var/lib/postgresql/data`.

### EXTERNAL SERVICES CONNECTIONS
Used by processor replicas and gateway through PostgreSQL connections.

### MICROSERVICES:

#### MICROSERVICE: postgres
- TYPE: database
- DESCRIPTION: PostgreSQL instance for `detected_events`.
- PORTS: 5432
- TECHNOLOGICAL SPECIFICATION: `postgres:16-alpine`.
- SERVICE ARCHITECTURE: Centralized stateful SQL datastore.

- DB STRUCTURE:

  **detected_events** : | id | event_signature | sensor_id | event_type | dominant_frequency_hz | peak_to_peak_amplitude | window_start | window_end | detected_by_replica | metadata_json | created_at |

  Constraints and indexes:
  - Unique constraint on `event_signature`
  - Indexes on `sensor_id`, `event_type`, `created_at`

## CONTAINER_NAME: broker

### DESCRIPTION:
Discovery and ingestion service that subscribes to simulator sensor streams and redistributes measurements to all processor replicas.

### USER STORIES:
2, 3, 4, 19, 25, 29

### PORTS:
8090:8090

### DESCRIPTION:
Discovers sensors via simulator discovery endpoint, opens one ingestion loop per sensor, and publishes envelopes to subscribed processor replicas through a WebSocket fan-out stream.

### PERSISTENCE EVALUATION
No persistent storage; in-memory runtime state (sensors/subscribers/counters).

### EXTERNAL SERVICES CONNECTIONS
Simulator (REST + WebSocket), processor replicas (WebSocket clients).

### MICROSERVICES:

#### MICROSERVICE: broker
- TYPE: backend
- DESCRIPTION: Sensor discovery + ingest + fan-out distribution service.
- PORTS: 8090
- TECHNOLOGICAL SPECIFICATION: Python 3.11, FastAPI, httpx, websockets.
- SERVICE ARCHITECTURE: Async FastAPI service with discovery loop and per-sensor ingest tasks.

- ENDPOINTS:

  | HTTP METHOD | URL | Description | User Stories |
  | ----------- | --- | ----------- | ------------ |
  | GET | /health | Broker health and ingestion counters | 29 |
  | GET | /api/sensors | Currently discovered sensors | 2, 19 |
  | WS | /api/stream/ws | Fan-out stream consumed by processors | 4 |
  | GET | / | Service index | 13 |

## CONTAINER_NAME: processor replicas (processor-a, processor-b, processor-c)

### DESCRIPTION:
Three equivalent processing replicas that consume broker data, detect events with FFT analysis, and persist deduplicated detections.

### USER STORIES:
5, 6, 7, 8, 9, 10, 11, 12, 14, 26, 27, 28

### PORTS:
Internal service port 8091 (not published to host).

### DESCRIPTION:
Each replica:
- consumes `/api/stream/ws` from broker
- keeps per-sensor sliding windows
- computes dominant frequency and peak-to-peak amplitude
- classifies events by frequency bands
- writes events to shared Postgres with conflict-safe insert
- listens to simulator `/api/control` and self-terminates on `SHUTDOWN`
- exposes health and summary APIs used by gateway routing

### PERSISTENCE EVALUATION
No local persistence. Writes durable data to shared Postgres.

### EXTERNAL SERVICES CONNECTIONS
Broker (WebSocket), simulator control stream (SSE via HTTP), Postgres (async SQLAlchemy + asyncpg).

### MICROSERVICES:

#### MICROSERVICE: processor
- TYPE: backend worker/API
- DESCRIPTION: FFT detection and event persistence replica.
- PORTS: 8091 (internal)
- TECHNOLOGICAL SPECIFICATION: Python 3.11, FastAPI, numpy, websockets, aiohttp, SQLAlchemy, asyncpg.
- SERVICE ARCHITECTURE: Async consumer loops (broker/control) plus in-memory buffers and DB writer.

- ENDPOINTS:

  | HTTP METHOD | URL | Description | User Stories |
  | ----------- | --- | ----------- | ------------ |
  | GET | /health | Replica health and counters | 14, 17, 28, 29 |
  | GET | /internal/summary | Processing summary used by gateway routing | 14, 17 |
  | GET | / | Service index | 13 |

## CONTAINER_NAME: gateway

### DESCRIPTION:
Unified API entrypoint for dashboard and clients; aggregates health, exposes historical/live data, analytics, and simulator trigger proxies.

### USER STORIES:
13, 14, 15, 16, 19, 20, 21, 22, 23, 24, 25, 29, 30

### PORTS:
8088:8088

### DESCRIPTION:
Gateway centralizes all client-facing APIs:
- routes processing summary only to healthy replicas
- reads persisted events from Postgres for history/live/export/analytics
- fetches sensor catalog from broker
- exposes full health diagnostics (DB, replicas, upstream broker/simulator)
- proxies instructor manual triggers to simulator

### PERSISTENCE EVALUATION
No local persistence. Uses Postgres for event reads and analytics.

### EXTERNAL SERVICES CONNECTIONS
Postgres, broker, simulator, processor replicas.

### MICROSERVICES:

#### MICROSERVICE: gateway
- TYPE: backend API
- DESCRIPTION: Public API façade and orchestration layer.
- PORTS: 8088
- TECHNOLOGICAL SPECIFICATION: Python 3.11, FastAPI, SQLAlchemy, asyncpg, httpx.
- SERVICE ARCHITECTURE: FastAPI API gateway with DB access and upstream proxy/aggregation logic.

- ENDPOINTS:

  | HTTP METHOD | URL | Description | User Stories |
  | ----------- | --- | ----------- | ------------ |
  | GET | /health | Gateway health (DB + replica summary) | 17 |
  | GET | /health/full | Full diagnostics including upstreams | 29 |
  | GET | /api/replicas | Replica health list | 17 |
  | GET | /api/processing/summary | Health-aware routed summary to healthy replica | 14 |
  | GET | /api/sensors | Canonical sensor catalog | 19, 25 |
  | GET | /api/system/overview | Consolidated system overview payload | 25 |
  | GET | /api/events | Filterable historical events | 15 |
  | GET | /api/events/export.csv | CSV export for filtered events | 20 |
  | GET | /api/events/by-id/{event_id} | Single event detail | 21 |
  | GET | /api/analytics/overview | Counts, top sensors, aggregate metrics | 22 |
  | GET | /api/events/live | Live SSE detected events stream | 16 |
  | GET | /api/events/stream-status | Live-feed status diagnostics | 30 |
  | POST | /api/admin/sensors/{sensor_id}/events | Manual sensor disturbance trigger proxy | 23 |
  | POST | /api/admin/shutdown | Manual shutdown trigger proxy | 24 |
  | GET | / | Service index | 13 |

## CONTAINER_NAME: frontend

### DESCRIPTION:
React + Vite dashboard served by Nginx for command-center monitoring and operational controls.

### USER STORIES:
16, 17, 18, 19, 20, 21, 22, 23, 24, 30

### PORTS:
5173:80

### DESCRIPTION:
Single-page dashboard that:
- shows live detected events and stream heartbeat status
- shows replica health and routed summary
- provides filters, historical table, and event detail modal
- provides analytics overview and classification mix
- supports CSV export and live stream pause/resume
- exposes instructor control actions (manual sensor event, manual shutdown)

### PERSISTENCE EVALUATION
None.

### EXTERNAL SERVICES CONNECTIONS
Gateway API (HTTP/SSE).

### MICROSERVICES:

#### MICROSERVICE: frontend
- TYPE: frontend
- DESCRIPTION: Web dashboard for operational monitoring and control.
- PORTS: 80 (container), mapped to host 5173.
- TECHNOLOGICAL SPECIFICATION: React 18, Vite 6, Nginx 1.27.
- SERVICE ARCHITECTURE: SPA consuming gateway APIs and SSE.

- PAGES:

  | Name | Description | Related Microservice | User Stories |
  | ---- | ----------- | -------------------- | ------------ |
  | / (Dashboard) | Unified real-time operations dashboard with live events, health, analytics, history, event details, and instructor controls | gateway | 16, 17, 18, 19, 20, 21, 22, 23, 24, 30 |

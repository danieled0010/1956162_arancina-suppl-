# Seismic Analysis Backend (FastAPI)

Distributed backend implementation for the Lab of Advanced Programming assignment.

User stories (25 total) are documented in `input.md`.

## Architecture

- `simulator` (provided image): seismic measurement source + control SSE stream
- `broker` (FastAPI): receives simulator sensor streams and fan-outs measurements to processors
- `processor-a/b/c` (FastAPI replicas):
  - consumes broker stream
  - keeps per-sensor sliding windows
  - computes FFT dominant frequency
  - classifies events (`earthquake`, `conventional_explosion`, `nuclear_like`)
  - persists events idempotently into Postgres
  - listens to simulator `/api/control` and self-terminates on `SHUTDOWN`
- `postgres`: shared persistence for deduplicated events
- `gateway` (FastAPI): single entry point for clients/dashboard
  - replica health and summary routing
  - historical event query API
  - live event SSE endpoint
  - analytics and system overview APIs
  - instructor manual trigger proxy APIs
- `frontend` (React + Vite, served by Nginx): real-time command dashboard
  - gateway/replica status overview
  - live detected-event ticker (SSE)
  - filterable historical table and classification mix
  - event detail modal
  - CSV export
  - instructor trigger controls

## Run

1. Load provided simulator image:

```bash
docker load -i seismic-signal-simulator-oci.tar
```

2. Start backend stack:

```bash
docker compose up --build
```

3. Main endpoints:

- Frontend dashboard: `http://localhost:5173`
- Gateway API: `http://localhost:8088`
- Gateway health: `GET /health`
- Full health diagnostics: `GET /health/full`
- System overview: `GET /api/system/overview`
- Sensor catalog: `GET /api/sensors`
- Historical events: `GET /api/events`
- Event detail: `GET /api/events/by-id/{event_id}`
- Live events SSE: `GET /api/events/live`
- Live stream diagnostics: `GET /api/events/stream-status`
- Analytics: `GET /api/analytics/overview`
- CSV export: `GET /api/events/export.csv`
- Replica health: `GET /api/replicas`
- Routed replica summary: `GET /api/processing/summary`
- Manual event trigger: `POST /api/admin/sensors/{sensor_id}/events`
- Manual shutdown trigger: `POST /api/admin/shutdown`

## Notes

- The DB table has a unique constraint on `event_signature` to guarantee duplicate-safe persistence across replicas.
- Broker does no frequency analysis/classification (distribution-only responsibility).
- You can manually trigger simulator events/shutdown via simulator admin endpoints:
  - `POST http://localhost:8080/api/admin/sensors/{sensor_id}/events`
  - `POST http://localhost:8080/api/admin/shutdown`

# Seismic Intelligence Platform

Distributed seismic monitoring platform built for the Laboratory of Advanced Programming assignment.

The system ingests real-time sensor signals from the provided simulator, distributes measurements across processing replicas, classifies seismic signatures with FFT-based analysis, stores deduplicated events in PostgreSQL, and exposes a live operator dashboard.

## Quick Start (Docker)

1. Load the provided simulator image:

```bash
docker load -i seismic-signal-simulator-oci.tar
```

2. Start the stack:

```bash
docker compose up --build
```

## Main URLs

- Frontend dashboard: `http://localhost:5173`
- Gateway API root: `http://localhost:8088`
- Gateway health: `http://localhost:8088/health`
- Broker health: `http://localhost:8090/health`
- Simulator health: `http://localhost:8080/health`
- Simulator docs: `http://localhost:8080/docs`

## Repository Structure

```text
.
├── Student_doc.md
├── input.md
├── booklets/                      # diagrams and presentation assets
└── source/
```

## Additional Notes

- Sensor measurement distribution is handled by the custom `broker` service.
- Heavy signal processing runs only in `processor` replicas; the `gateway` remains a lightweight access/routing layer.
- Event persistence is duplicate-safe thanks to unique `event_signature` constraints in PostgreSQL.
- Processor replicas listen to simulator control SSE (`/api/control`) and terminate on `SHUTDOWN` for failure testing.
- User stories and deliverable details are documented in `Student_doc.md` and `input.md`.

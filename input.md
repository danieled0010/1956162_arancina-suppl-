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

## Notes

- User stories 1–18 were already present in the current codebase; stories 19–30 were added in the story pass. Mapping to containers, endpoints, and evidence: see `Student_doc.md`.


import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { CircleMarker, MapContainer, Popup, TileLayer, Tooltip, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import {
  apiUrl,
  buildSinceIso,
  eventTypeLabel,
  formatFixed,
  formatTimestamp,
} from './lib/formatters';

const DEFAULT_LIMIT = 200;
const MAX_LIVE_ITEMS = 80;
const MAX_TABLE_ITEMS = 600;
const LIVE_WINDOW_MINUTES = 5;

const TIME_WINDOW_OPTIONS = [
  { value: '5m', label: 'Last 5 minutes' },
  { value: '15m', label: 'Last 15 minutes' },
  { value: '1h', label: 'Last 1 hour' },
  { value: '6h', label: 'Last 6 hours' },
  { value: '24h', label: 'Last 24 hours' },
  { value: 'all', label: 'All' },
];

const EVENT_TYPE_OPTIONS = [
  { value: 'earthquake', label: 'Earthquake' },
  { value: 'conventional_explosion', label: 'Conventional Explosion' },
  { value: 'nuclear_like', label: 'Nuclear-like' },
];

const MANUAL_TRIGGER_EVENT_TYPES = [
  { value: 'earthquake', label: 'Earthquake' },
  { value: 'conventional_explosion', label: 'Conventional Explosion' },
  { value: 'nuclear_like', label: 'Nuclear-like' },
];

const eventTypeClass = {
  earthquake: 'badge-earthquake',
  conventional_explosion: 'badge-explosion',
  nuclear_like: 'badge-nuclear',
};

const eventTypeMapColor = {
  earthquake: '#0f9d92',
  conventional_explosion: '#f05a28',
  nuclear_like: '#2463eb',
};

function MapBoundsUpdater({ points }) {
  const map = useMap();

  useEffect(() => {
    if (!points.length) {
      return;
    }

    const bounds = points.map((point) => [point.latitude, point.longitude]);
    if (bounds.length === 1) {
      map.setView(bounds[0], 7, { animate: false });
      return;
    }

    map.fitBounds(bounds, { padding: [30, 30] });
  }, [map, points]);

  return null;
}

function App() {
  const [events, setEvents] = useState([]);
  const [liveEvents, setLiveEvents] = useState([]);
  const [systemOverview, setSystemOverview] = useState(null);
  const [summary, setSummary] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [sensors, setSensors] = useState([]);
  const [streamStatus, setStreamStatus] = useState(null);

  const [loadingEvents, setLoadingEvents] = useState(true);
  const [eventsError, setEventsError] = useState('');
  const [streamConnected, setStreamConnected] = useState(false);
  const [streamPaused, setStreamPaused] = useState(false);
  const [lastHeartbeatAt, setLastHeartbeatAt] = useState(null);
  const [lastRefreshAt, setLastRefreshAt] = useState(null);

  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [sensorFilter, setSensorFilter] = useState('');
  const [eventTypeFilter, setEventTypeFilter] = useState('');
  const [timeWindow, setTimeWindow] = useState('1h');
  const [autoRefresh, setAutoRefresh] = useState(true);

  const [selectedEvent, setSelectedEvent] = useState(null);
  const [loadingEventDetail, setLoadingEventDetail] = useState(false);

  const [manualSensorId, setManualSensorId] = useState('');
  const [manualEventType, setManualEventType] = useState('earthquake');
  const [actionMessage, setActionMessage] = useState('');
  const [actionError, setActionError] = useState('');
  const [manualActionBusy, setManualActionBusy] = useState(false);

  const streamRef = useRef(null);
  const maxEventIdRef = useRef(0);

  const currentSinceIso = useMemo(() => (timeWindow === 'all' ? null : buildSinceIso(timeWindow)), [timeWindow]);

  const matchesFilters = useCallback(
    (event) => {
      if (sensorFilter && event.sensor_id !== sensorFilter) {
        return false;
      }
      if (eventTypeFilter && event.event_type !== eventTypeFilter) {
        return false;
      }
      if (currentSinceIso && new Date(event.created_at) < new Date(currentSinceIso)) {
        return false;
      }
      return true;
    },
    [sensorFilter, eventTypeFilter, currentSinceIso]
  );

  const buildFilterParams = useCallback(() => {
    return {
      sensor_id: sensorFilter || null,
      event_type: eventTypeFilter || null,
      since: currentSinceIso,
    };
  }, [sensorFilter, eventTypeFilter, currentSinceIso]);

  const fetchSystemOverview = useCallback(async () => {
    const response = await fetch(apiUrl('/api/system/overview'));
    if (!response.ok) {
      throw new Error(`Failed to fetch system overview (${response.status})`);
    }
    const payload = await response.json();
    setSystemOverview(payload);
  }, []);

  const fetchProcessingSummary = useCallback(async () => {
    const response = await fetch(apiUrl('/api/processing/summary'));
    if (!response.ok) {
      setSummary(null);
      return;
    }
    const payload = await response.json();
    setSummary(payload);
  }, []);

  const fetchSensorCatalog = useCallback(async () => {
    const response = await fetch(apiUrl('/api/sensors'));
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    if (Array.isArray(payload.items)) {
      setSensors(payload.items);
      if (!manualSensorId && payload.items.length > 0) {
        setManualSensorId(payload.items[0].id);
      }
    }
  }, [manualSensorId]);

  const fetchStreamStatus = useCallback(async () => {
    const response = await fetch(apiUrl('/api/events/stream-status'));
    if (!response.ok) {
      setStreamStatus(null);
      return;
    }
    const payload = await response.json();
    if (typeof payload.latestEventId === 'number') {
      maxEventIdRef.current = Math.max(maxEventIdRef.current, payload.latestEventId);
    }
    setStreamStatus(payload);
  }, []);

  const fetchAnalytics = useCallback(async () => {
    const params = buildFilterParams();
    const response = await fetch(apiUrl('/api/analytics/overview', params));
    if (!response.ok) {
      setAnalytics(null);
      return;
    }
    const payload = await response.json();
    setAnalytics(payload);
  }, [buildFilterParams]);

  const fetchLiveSnapshot = useCallback(async () => {
    const response = await fetch(
      apiUrl('/api/events', {
        limit: MAX_LIVE_ITEMS,
        order: 'desc',
        since: buildSinceIso('5m'),
      })
    );
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    setLiveEvents(payload);
    const maxId = payload.reduce((max, item) => Math.max(max, item.id), maxEventIdRef.current);
    maxEventIdRef.current = maxId;
  }, []);

  const fetchEvents = useCallback(async () => {
    setLoadingEvents(true);
    setEventsError('');

    const params = {
      limit,
      order: 'desc',
      ...buildFilterParams(),
    };

    try {
      const response = await fetch(apiUrl('/api/events', params));
      if (!response.ok) {
        throw new Error(`Failed to fetch events (${response.status})`);
      }
      const payload = await response.json();
      setEvents(payload);
      const maxId = payload.reduce((max, item) => Math.max(max, item.id), maxEventIdRef.current);
      maxEventIdRef.current = maxId;
      setLastRefreshAt(new Date().toISOString());
    } catch (error) {
      setEventsError(error instanceof Error ? error.message : 'Failed to fetch events');
    } finally {
      setLoadingEvents(false);
    }
  }, [limit, buildFilterParams]);

  useEffect(() => {
    fetchSystemOverview().catch(() => null);
    fetchProcessingSummary().catch(() => null);
    fetchSensorCatalog().catch(() => null);
    fetchStreamStatus().catch(() => null);
    fetchLiveSnapshot().catch(() => null);
    const interval = window.setInterval(() => {
      fetchSystemOverview().catch(() => null);
      fetchProcessingSummary().catch(() => null);
      fetchSensorCatalog().catch(() => null);
      fetchStreamStatus().catch(() => null);
    }, 5000);
    return () => window.clearInterval(interval);
  }, [fetchLiveSnapshot, fetchProcessingSummary, fetchSensorCatalog, fetchSystemOverview, fetchStreamStatus]);

  useEffect(() => {
    fetchEvents();
    fetchAnalytics().catch(() => null);
  }, [fetchEvents, fetchAnalytics]);

  useEffect(() => {
    if (!autoRefresh) {
      return undefined;
    }
    const interval = window.setInterval(() => {
      fetchEvents();
      fetchAnalytics().catch(() => null);
    }, 7000);
    return () => window.clearInterval(interval);
  }, [autoRefresh, fetchEvents, fetchAnalytics]);

  useEffect(() => {
    if (streamPaused) {
      if (streamRef.current) {
        streamRef.current.close();
        streamRef.current = null;
      }
      setStreamConnected(false);
      return undefined;
    }

    // Strict live mode: start from the latest known event id and only show
    // events produced after the dashboard session is connected.
    const streamStartId = Math.max(maxEventIdRef.current, 0);
    const streamUrl = apiUrl('/api/events/live', {
      last_event_id: streamStartId,
    });
    const stream = new EventSource(streamUrl);
    streamRef.current = stream;

    stream.onopen = () => {
      setStreamConnected(true);
    };

    stream.onerror = () => {
      setStreamConnected(false);
    };

    stream.addEventListener('heartbeat', () => {
      setLastHeartbeatAt(new Date().toISOString());
    });

    stream.addEventListener('detected_event', (event) => {
      try {
        const data = JSON.parse(event.data);
        maxEventIdRef.current = Math.max(maxEventIdRef.current, data.id);

        setLiveEvents((current) => [data, ...current.filter((item) => item.id !== data.id)].slice(0, MAX_LIVE_ITEMS));
        if (matchesFilters(data)) {
          setEvents((current) => [data, ...current.filter((item) => item.id !== data.id)].slice(0, MAX_TABLE_ITEMS));
        }
      } catch (error) {
        console.error('Invalid SSE payload', error);
      }
    });

    return () => {
      stream.close();
      if (streamRef.current === stream) {
        streamRef.current = null;
      }
      setStreamConnected(false);
    };
  }, [matchesFilters, streamPaused]);

  const recentLiveEvents = useMemo(() => {
    const cutoffMs = Date.now() - LIVE_WINDOW_MINUTES * 60 * 1000;
    return liveEvents.filter((event) => {
      const createdAtMs = Date.parse(event.created_at);
      return Number.isFinite(createdAtMs) && createdAtMs >= cutoffMs;
    });
  }, [liveEvents, lastHeartbeatAt]);

  const sensorNameMap = useMemo(() => {
    const map = {};
    sensors.forEach((sensor) => {
      map[sensor.id] = sensor.name ? `${sensor.id} - ${sensor.name}` : sensor.id;
    });
    return map;
  }, [sensors]);

  const sensorOptions = useMemo(() => {
    if (sensors.length > 0) {
      return sensors.map((sensor) => sensor.id);
    }
    const fromEvents = new Set();
    events.forEach((event) => fromEvents.add(event.sensor_id));
    liveEvents.forEach((event) => fromEvents.add(event.sensor_id));
    return Array.from(fromEvents).sort();
  }, [events, liveEvents, sensors]);

  const geoPoints = useMemo(() => {
    const sensorsWithCoordinates = sensors
      .map((sensor) => ({
        id: sensor.id,
        name: sensor.name || sensor.id,
        latitude: Number(sensor.coordinates?.latitude),
        longitude: Number(sensor.coordinates?.longitude),
      }))
      .filter((sensor) => Number.isFinite(sensor.latitude) && Number.isFinite(sensor.longitude));

    if (!sensorsWithCoordinates.length) {
      return [];
    }

    const perSensorStats = new Map();
    events.forEach((event) => {
      const current = perSensorStats.get(event.sensor_id) || {
        count: 0,
        latestType: null,
        latestCreatedAt: null,
      };

      current.count += 1;
      if (!current.latestCreatedAt || new Date(event.created_at) > new Date(current.latestCreatedAt)) {
        current.latestCreatedAt = event.created_at;
        current.latestType = event.event_type;
      }
      perSensorStats.set(event.sensor_id, current);
    });

    return sensorsWithCoordinates.map((sensor) => {
      const stats = perSensorStats.get(sensor.id);
      return {
        ...sensor,
        detections: stats?.count || 0,
        latestType: stats?.latestType || null,
      };
    });
  }, [events, sensors]);

  const countsByType = useMemo(() => {
    if (analytics?.countsByType) {
      return analytics.countsByType;
    }
    return events.reduce((acc, item) => {
      const key = item.event_type || 'unknown';
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, {});
  }, [analytics, events]);

  const dominantType = useMemo(() => {
    if (analytics?.dominantType) {
      return eventTypeLabel(analytics.dominantType);
    }
    const entries = Object.entries(countsByType);
    if (!entries.length) {
      return '-';
    }
    const [type] = entries.sort((a, b) => b[1] - a[1])[0];
    return eventTypeLabel(type);
  }, [analytics, countsByType]);

  const handleCsvExport = useCallback(() => {
    const params = { limit: 5000, ...buildFilterParams() };
    window.open(apiUrl('/api/events/export.csv', params), '_blank', 'noopener,noreferrer');
  }, [buildFilterParams]);

  const openEventDetail = useCallback(async (eventId) => {
    setLoadingEventDetail(true);
    setActionError('');
    try {
      const response = await fetch(apiUrl(`/api/events/by-id/${eventId}`));
      if (!response.ok) {
        throw new Error(`Failed to load event detail (${response.status})`);
      }
      const payload = await response.json();
      setSelectedEvent(payload);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Failed to load event detail');
    } finally {
      setLoadingEventDetail(false);
    }
  }, []);

  const handleManualSensorEvent = useCallback(async () => {
    if (!manualSensorId) {
      setActionError('Select a sensor before triggering an event.');
      return;
    }
    setManualActionBusy(true);
    setActionMessage('');
    setActionError('');
    try {
      const response = await fetch(apiUrl(`/api/admin/sensors/${manualSensorId}/events`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_type: manualEventType }),
      });
      if (!response.ok) {
        throw new Error(`Manual event trigger failed (${response.status})`);
      }
      const payload = await response.json();
      setActionMessage(
        `Triggered ${eventTypeLabel(manualEventType)} on ${payload.sensorId} (eventId: ${payload.event?.eventId || 'n/a'}).`
      );
      fetchEvents();
      fetchAnalytics().catch(() => null);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Failed to trigger sensor event');
    } finally {
      setManualActionBusy(false);
    }
  }, [manualSensorId, manualEventType, fetchAnalytics, fetchEvents]);

  const handleManualShutdown = useCallback(async () => {
    setManualActionBusy(true);
    setActionMessage('');
    setActionError('');
    try {
      const response = await fetch(apiUrl('/api/admin/shutdown'), { method: 'POST' });
      if (!response.ok) {
        throw new Error(`Manual shutdown failed (${response.status})`);
      }
      const payload = await response.json();
      setActionMessage(
        `Shutdown command issued. Listener count: ${payload.controlStreamConnections}. A processor replica should terminate.`
      );
      fetchSystemOverview().catch(() => null);
      fetchProcessingSummary().catch(() => null);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Failed to trigger shutdown');
    } finally {
      setManualActionBusy(false);
    }
  }, [fetchProcessingSummary, fetchSystemOverview]);

  const totalReplicas = systemOverview?.replicas?.total ?? 0;
  const healthyReplicas = systemOverview?.replicas?.healthy ?? 0;
  const dbHealthy = systemOverview?.gateway?.databaseHealthy;
  const processingSummary = summary?.summary;
  const totalPersisted = systemOverview?.events?.totalPersisted ?? events.length;
  const liveStatusLabel = streamStatus?.liveFeedLikelyIdle ? 'idle' : 'active';

  return (
    <div className="app-shell">
      <div className="ambient ambient-a" />
      <div className="ambient ambient-b" />
      <div className="ambient ambient-c" />

      <header className="hero">
        <div>
          <p className="kicker">Neutral-Region Command View</p>
          <h1>Seismic Intelligence Dashboard</h1>
          <p className="subtitle">
            Live monitoring for distributed processing replicas with duplicate-safe event persistence.
          </p>
        </div>
        <div className="hero-actions">
          <button className="btn btn-secondary" onClick={() => setStreamPaused((current) => !current)}>
            {streamPaused ? 'Resume Live Stream' : 'Pause Live Stream'}
          </button>
          <button className="btn btn-secondary" onClick={handleCsvExport}>
            Export CSV
          </button>
          <button className="btn btn-primary" onClick={fetchEvents}>
            Refresh Events
          </button>
        </div>
      </header>

      <section className="stats-grid">
        <MetricCard
          title="Gateway Status"
          value={systemOverview?.gateway?.status || 'loading'}
          helper={`Last refresh: ${formatTimestamp(lastRefreshAt)}`}
          tone={systemOverview?.gateway?.status === 'ok' ? 'good' : 'warn'}
        />
        <MetricCard
          title="Database"
          value={dbHealthy === undefined ? 'loading' : dbHealthy ? 'healthy' : 'degraded'}
          helper={`Total persisted events: ${totalPersisted}`}
          tone={dbHealthy ? 'good' : 'warn'}
        />
        <MetricCard
          title="Replicas"
          value={`${healthyReplicas}/${totalReplicas}`}
          helper="Healthy processing replicas"
          tone={healthyReplicas > 0 ? 'good' : 'warn'}
        />
        <MetricCard
          title="Dominant Classification"
          value={dominantType}
          helper={`Live feed: ${liveStatusLabel}`}
          tone="neutral"
        />
      </section>

      <section className="panel admin-panel">
        <div className="panel-head">
          <h2>Instructor Controls</h2>
          <span className="muted">Manual simulator triggers through gateway</span>
        </div>
        <div className="admin-grid">
          <label>
            Target Sensor
            <select value={manualSensorId} onChange={(event) => setManualSensorId(event.target.value)}>
              <option value="">Select sensor</option>
              {sensorOptions.map((sensorId) => (
                <option key={sensorId} value={sensorId}>
                  {sensorNameMap[sensorId] || sensorId}
                </option>
              ))}
            </select>
          </label>
          <label>
            Event Type
            <select value={manualEventType} onChange={(event) => setManualEventType(event.target.value)}>
              {MANUAL_TRIGGER_EVENT_TYPES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <button className="btn btn-primary" disabled={manualActionBusy} onClick={handleManualSensorEvent}>
            Trigger Sensor Event
          </button>
          <button className="btn btn-secondary" disabled={manualActionBusy} onClick={handleManualShutdown}>
            Trigger Shutdown
          </button>
        </div>
        {actionMessage && <p className="success-banner">{actionMessage}</p>}
        {actionError && <p className="error-banner">{actionError}</p>}
      </section>

      <section className="panel map-panel">
        <div className="panel-head">
          <h2>Detection Map</h2>
          <span className="muted">Dot size = detections in current history view</span>
        </div>

        {!geoPoints.length ? (
          <p className="empty-state">No sensor coordinates available yet.</p>
        ) : (
          <>
            <div className="geo-map-wrap">
              <MapContainer
                center={[geoPoints[0].latitude, geoPoints[0].longitude]}
                zoom={6}
                scrollWheelZoom={true}
                className="leaflet-map"
              >
                <TileLayer
                  attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                  url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                />
                <MapBoundsUpdater points={geoPoints} />
                {geoPoints.map((point) => {
                  const radius = Math.min(18, 6 + point.detections * 1.2);
                  const fill = eventTypeMapColor[point.latestType] || '#64748b';

                  return (
                    <CircleMarker
                      key={point.id}
                      center={[point.latitude, point.longitude]}
                      radius={radius}
                      pathOptions={{
                        color: '#10253f',
                        weight: 1.2,
                        fillColor: fill,
                        fillOpacity: 0.78,
                      }}
                    >
                      <Tooltip direction="top" offset={[0, -8]} opacity={0.95}>
                        {sensorNameMap[point.id] || point.id}
                      </Tooltip>
                      <Popup>
                        <strong>{sensorNameMap[point.id] || point.id}</strong>
                        <br />
                        Detections: {point.detections}
                        <br />
                        Latest type: {eventTypeLabel(point.latestType) || 'n/a'}
                        <br />
                        Coordinates: {point.latitude.toFixed(4)}, {point.longitude.toFixed(4)}
                      </Popup>
                    </CircleMarker>
                  );
                })}
              </MapContainer>
            </div>
            <div className="map-legend">
              <span className="map-legend-title">Legend</span>
              <span className="map-legend-item">
                <i style={{ backgroundColor: eventTypeMapColor.earthquake }} />
                Earthquake
              </span>
              <span className="map-legend-item">
                <i style={{ backgroundColor: eventTypeMapColor.conventional_explosion }} />
                Conventional Explosion
              </span>
              <span className="map-legend-item">
                <i style={{ backgroundColor: eventTypeMapColor.nuclear_like }} />
                Nuclear-like
              </span>
              <span className="map-legend-item">
                <i style={{ backgroundColor: '#64748b' }} />
                No detections yet
              </span>
            </div>
            <p className="muted geo-map-note">
              OpenStreetMap + Leaflet. Color follows latest event type per sensor, while circle size reflects detection volume.
            </p>
          </>
        )}
      </section>

      <main className="dashboard-grid">
        <section className="panel live-panel">
          <div className="panel-head">
            <h2>Live Detected Events</h2>
            <span className="muted">{recentLiveEvents.length} shown</span>
          </div>

          {!recentLiveEvents.length && (
            <p className="empty-state">No events detected in the last 5 minutes. Trigger simulator disturbances to test.</p>
          )}

          <ul className="live-list">
            {recentLiveEvents.slice(0, 20).map((event) => (
              <li key={event.id} className="live-item">
                <div className="live-item-primary">
                  <div className="live-item-title">
                    <strong>{sensorNameMap[event.sensor_id] || event.sensor_id}</strong>
                    <span className={`badge ${eventTypeClass[event.event_type] || 'badge-default'}`}>
                      {eventTypeLabel(event.event_type)}
                    </span>
                  </div>
                </div>
                <div className="live-meta">
                  <span>{formatFixed(event.dominant_frequency_hz, 2)} Hz</span>
                  <span>{formatTimestamp(event.created_at)}</span>
                </div>
              </li>
            ))}
          </ul>
        </section>

        <section className="panel replicas-panel">
          <div className="panel-head">
            <h2>Replica Health</h2>
            <span className="muted">Gateway route check</span>
          </div>

          <div className="replica-list">
            {systemOverview?.replicas?.items?.map((replica) => (
              <article key={replica.url} className={`replica-card ${replica.healthy ? 'healthy' : 'unhealthy'}`}>
                <h3>{replica.processorId || 'Unavailable'}</h3>
                <p>{replica.url}</p>
                <p>{replica.healthy ? 'Healthy' : 'Unavailable'}</p>
              </article>
            )) || <p className="empty-state">Loading replica status...</p>}
          </div>

          <div className="summary-box">
            <h3>Routed Summary</h3>
            {processingSummary ? (
              <ul>
                <li>Replica: {processingSummary.processorId}</li>
                <li>Tracked sensors: {processingSummary.trackedSensors}</li>
                <li>Total measurements: {processingSummary.totalMeasurements}</li>
                <li>Total persisted events: {processingSummary.totalEventsPersisted}</li>
              </ul>
            ) : (
              <p className="empty-state">No routed summary available right now.</p>
            )}
          </div>
        </section>

        <section className="panel control-panel filters-panel">
          <div className="panel-head">
            <h2>Filters</h2>
            <span className={`status-pill ${streamConnected ? 'online' : 'offline'}`}>
              Stream: {streamPaused ? 'paused' : streamConnected ? 'online' : 'reconnecting'}
            </span>
          </div>

          <div className="control-grid">
            <label>
              Sensor
              <select value={sensorFilter} onChange={(event) => setSensorFilter(event.target.value)}>
                <option value="">All sensors</option>
                {sensorOptions.map((sensorId) => (
                  <option key={sensorId} value={sensorId}>
                    {sensorNameMap[sensorId] || sensorId}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Event Type
              <select value={eventTypeFilter} onChange={(event) => setEventTypeFilter(event.target.value)}>
                <option value="">All types</option>
                {EVENT_TYPE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Time Window
              <select value={timeWindow} onChange={(event) => setTimeWindow(event.target.value)}>
                {TIME_WINDOW_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Max Rows
              <input
                type="number"
                min="20"
                max="1000"
                step="20"
                value={limit}
                onChange={(event) => {
                  const next = Number(event.target.value);
                  if (Number.isNaN(next)) {
                    return;
                  }
                  setLimit(Math.min(1000, Math.max(20, next)));
                }}
              />
            </label>
          </div>

          <div className="toggles">
            <label className="toggle">
              <input type="checkbox" checked={autoRefresh} onChange={(event) => setAutoRefresh(event.target.checked)} />
              <span>Auto-refresh historical events</span>
            </label>
            <div className="heartbeat-wrap">
              <p className="heartbeat">Last stream heartbeat: {formatTimestamp(lastHeartbeatAt)}</p>
              <p className="heartbeat">
                Last detected event: {formatTimestamp(streamStatus?.latestEventAt)} ({formatFixed(streamStatus?.secondsSinceLatestEvent, 1)}s ago)
              </p>
            </div>
          </div>
        </section>

        <section className="panel bands-panel">
          <div className="panel-head">
            <h2>Analytics Overview</h2>
            <span className="muted">Filtered current view</span>
          </div>

          <div className="bands">
            {EVENT_TYPE_OPTIONS.map((option) => {
              const count = countsByType[option.value] || 0;
              const ratio = events.length ? Math.max((count / events.length) * 100, 4) : 0;
              return (
                <div key={option.value} className="band-row">
                  <div className="band-label">{option.label}</div>
                  <div className="band-track">
                    <div className={`band-fill ${eventTypeClass[option.value] || 'badge-default'}`} style={{ width: `${ratio}%` }} />
                  </div>
                  <div className="band-value">{count}</div>
                </div>
              );
            })}
          </div>
          <div className="analytics-stats">
            <p>Total events in filter: {analytics?.totalEvents ?? events.length}</p>
            <p>Avg dominant frequency: {formatFixed(analytics?.avgDominantFrequencyHz, 2)} Hz</p>
            <p>Avg peak-to-peak amplitude: {formatFixed(analytics?.avgPeakToPeakAmplitude, 2)}</p>
          </div>
        </section>

        <section className="panel history-panel">
          <div className="panel-head">
            <h2>Historical Events</h2>
            <span className="muted">{loadingEvents ? 'Refreshing...' : `${events.length} rows`}</span>
          </div>

          {eventsError && <p className="error-banner">{eventsError}</p>}

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Sensor</th>
                  <th>Type</th>
                  <th>Frequency</th>
                  <th>Amplitude</th>
                  <th>Replica</th>
                  <th>Window</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr key={event.id} onClick={() => openEventDetail(event.id)} className="clickable-row">
                    <td data-label="Time">{formatTimestamp(event.created_at)}</td>
                    <td data-label="Sensor">{sensorNameMap[event.sensor_id] || event.sensor_id}</td>
                    <td data-label="Type">
                      <span className={`badge ${eventTypeClass[event.event_type] || 'badge-default'}`}>
                        {eventTypeLabel(event.event_type)}
                      </span>
                    </td>
                    <td data-label="Frequency">{formatFixed(event.dominant_frequency_hz, 3)} Hz</td>
                    <td data-label="Amplitude">{formatFixed(event.peak_to_peak_amplitude, 3)}</td>
                    <td data-label="Replica">{event.detected_by_replica}</td>
                    <td data-label="Window">
                      {formatTimestamp(event.window_start)} — {formatTimestamp(event.window_end)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!events.length && !loadingEvents && <p className="empty-state">No events found for current filters.</p>}
          </div>
        </section>
      </main>

      {(selectedEvent || loadingEventDetail) && (
        <div className="modal-backdrop" onClick={() => setSelectedEvent(null)}>
          <div className="modal-card" onClick={(event) => event.stopPropagation()}>
            <div className="panel-head">
              <h2>Event Detail</h2>
              <button className="btn btn-secondary" onClick={() => setSelectedEvent(null)}>
                Close
              </button>
            </div>
            {loadingEventDetail && <p className="empty-state">Loading event details...</p>}
            {selectedEvent && (
              <dl className="detail-grid">
                <DetailRow label="Event ID" value={String(selectedEvent.id)} />
                <DetailRow label="Signature" value={selectedEvent.event_signature} />
                <DetailRow label="Sensor" value={sensorNameMap[selectedEvent.sensor_id] || selectedEvent.sensor_id} />
                <DetailRow label="Type" value={eventTypeLabel(selectedEvent.event_type)} />
                <DetailRow label="Dominant Frequency" value={`${formatFixed(selectedEvent.dominant_frequency_hz, 3)} Hz`} />
                <DetailRow label="Peak-to-peak Amplitude" value={formatFixed(selectedEvent.peak_to_peak_amplitude, 3)} />
                <DetailRow label="Detected By" value={selectedEvent.detected_by_replica} />
                <DetailRow label="Window Start" value={formatTimestamp(selectedEvent.window_start)} />
                <DetailRow label="Window End" value={formatTimestamp(selectedEvent.window_end)} />
                <DetailRow label="Persisted At" value={formatTimestamp(selectedEvent.created_at)} />
              </dl>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function MetricCard({ title, value, helper, tone }) {
  return (
    <article className={`metric-card metric-${tone}`}>
      <p>{title}</p>
      <h3>{value}</h3>
      <span>{helper}</span>
    </article>
  );
}

function DetailRow({ label, value }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

export default App;

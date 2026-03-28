export function formatTimestamp(value) {
  if (!value) {
    return '-';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '-';
  }
  return new Intl.DateTimeFormat('en-GB', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date);
}

export function formatFixed(value, digits = 2) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) {
    return '-';
  }
  return Number(value).toFixed(digits);
}

export function eventTypeLabel(eventType) {
  if (!eventType) {
    return 'Unknown';
  }
  return eventType
    .split('_')
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(' ');
}

export function buildSinceIso(windowKey) {
  const now = Date.now();
  const windowToMinutes = {
    '5m': 5,
    '15m': 15,
    '1h': 60,
    '6h': 360,
    '24h': 1440,
  };

  const minutes = windowToMinutes[windowKey];
  if (!minutes) {
    return null;
  }
  return new Date(now - minutes * 60 * 1000).toISOString();
}

export function buildUrl(baseUrl, path, params) {
  const base = (baseUrl || '').replace(/\/$/, '');
  const url = new URL(`${base}${path}`, window.location.origin);
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, String(value));
      }
    });
  }
  if (/^https?:\/\//i.test(base)) {
    return `${url.origin}${url.pathname}${url.search}`;
  }
  return `${url.pathname}${url.search}`;
}

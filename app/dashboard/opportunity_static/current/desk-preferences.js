export function readPreference(key, fallback = '') {
  try { return localStorage.getItem(`predict-desk-${key}`) ?? fallback; }
  catch { return fallback; }
}

export function savePreference(key, value) {
  try { localStorage.setItem(`predict-desk-${key}`, value); }
  catch { /* The current page still works when browser storage is disabled. */ }
}

export function timezone() {
  return readPreference('timezone') || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
}

export function clock(at) {
  if (!at) return 'Time unavailable';
  return new Intl.DateTimeFormat('en-US', {
    timeZone: timezone(), month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short'
  }).format(new Date(at));
}

export function applyTheme() {
  const theme = readPreference('theme');
  if (theme) document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}

applyTheme();

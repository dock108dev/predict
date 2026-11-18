/* Start the default public read while the desk modules are still loading. */
(() => {
  const path = location.pathname;
  if (path !== '/arbs' || location.search
      || window.history.state?.predictDesk || window.PredictDeskStarted) return;
  const browse = path === '/browse-odds';
  const arb = path === '/arbs';
  const fields = {
    basis: browse || arb ? 'sportsbooks' : 'after_fees', family: 'winner,spread,total', group: 'outcome',
    layout: 'desk', league: 'NBA,NFL,MLB,NHL,NCAAB,NCAAF', limit: arb ? '25' : '12',
    offset: '0', phase: 'pregame', summary: '1', venue: 'kalshi,polymarket_us,novig,prophetx',
    view: arb ? 'arbs' : 'ev',
  };
  if (browse) fields.browse_odds = '1';
  if (!arb) fields.lines = 'main';
  try {
    const saved = JSON.parse(localStorage.getItem(`predict-desk-${browse ? 'browse' : arb ? 'arb' : 'ev'}-filters`) || '{}') || {};
    const returnState = JSON.parse(sessionStorage.getItem('predict-desk-return') || 'null');
    if (returnState?.url === location.href && returnState.restoreOnArrival) return;
    const ev = browse && JSON.parse(localStorage.getItem('predict-desk-ev-filters') || '{}');
    const basis = browse || arb ? saved.basis || ev?.basis || fields.basis : fields.basis;
    if (!['after_fees', 'sportsbooks', 'reviewed', 'conservative', 'before'].includes(basis)) return;
    fields.basis = arb ? basis : 'after_fees';
    for (const key of ['league', 'venue', 'family']) {
      if (!browse && !arb) continue;
      if (!saved[key]) continue;
      if (typeof saved[key] !== 'string') return;
      const selected = new Set(saved[key].split(','));
      fields[key] = fields[key].split(',').filter(value => selected.has(value)).join(',') || 'none';
    }
    if (!arb && saved.lines === 'all') fields.lines = 'all';
    if (!browse && saved.positive === 'on') fields.positive = 'on';
    if (['search', 'day', 'time_from', 'time_to', 'minimum', 'profit'].some(key => saved[key])) return;
  } catch { return; }
  const query = new URLSearchParams(fields);
  query.sort();
  const url = '/api/comparison-current?' + query;
  const controller = new AbortController();
  const promise = fetch(url, {signal:controller.signal})
    .then(response => response.ok ? response.json() : null)
    .catch(() => null);
  window.PredictDeskLanding = {url, controller, promise};
})();

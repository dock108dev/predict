import {applyTheme, clock} from './desk-preferences.js';

export const workspaceNavigation = Object.freeze([
  {href:'/', label:'Dashboard'},
  {href:'/data', label:'Data'},
  {href:'/experiments', label:'Experiments'},
]);

function renderNavigation(nav) {
  nav.replaceChildren(...workspaceNavigation.map(({href, label}) => {
    const link = document.createElement('a');
    link.href = href;
    link.textContent = label;
    if (location.pathname === href) link.setAttribute('aria-current', 'page');
    return link;
  }));
}

function formattedTime(value) {
  return value && Number.isFinite(Date.parse(value)) ? clock(value) : 'Unavailable';
}

function mountCollectionStatus(nav) {
  const panel = document.createElement('details');
  panel.className = 'workspace-collection';
  const summary = document.createElement('summary');
  summary.textContent = 'Collection';
  const tooltip = document.createElement('div');
  const state = document.createElement('strong');
  state.setAttribute('role', 'status');
  state.textContent = 'Reading collection status…';
  const times = document.createElement('dl');
  const last = document.createElement('dd');
  const next = document.createElement('dd');
  for (const [label, value] of [['Last pull', last], ['Next pull', next]]) {
    const name = document.createElement('dt');
    name.textContent = label;
    value.textContent = 'Loading…';
    times.append(name, value);
  }
  const problem = document.createElement('p');
  problem.hidden = true;
  const controls = document.createElement('a');
  controls.href = '/settings#collection';
  controls.textContent = 'Collection controls';
  tooltip.append(state, times, problem, controls);
  panel.append(summary, tooltip);
  nav.after(panel);

  let reading = false;
  async function update() {
    if (reading || document.hidden) return;
    reading = true;
    try {
      const response = await fetch('/api/workspace/collection', {
        cache:'no-store', signal:AbortSignal.timeout(8000),
      });
      if (!response.ok) throw new Error();
      const value = await response.json();
      state.textContent = value.state;
      summary.textContent = value.problem ? 'Collection issue' : value.state;
      last.textContent = formattedTime(value.last_pull_at);
      next.textContent = formattedTime(value.next_pull_at);
      problem.hidden = !value.problem;
      problem.textContent = value.problem || '';
    } catch {
      state.textContent = 'Collection status unavailable';
      summary.textContent = 'Collection status unavailable';
      last.textContent = next.textContent = 'Unavailable';
      problem.hidden = true;
    } finally {
      reading = false;
    }
  }
  panel.addEventListener('toggle', () => { if (panel.open) void update(); });
  document.addEventListener('visibilitychange', update);
  window.setInterval(update, 60000);
  void update();
}

export function renderWorkspaceNavigation() {
  for (const nav of document.querySelectorAll('[data-workspace-nav]')) {
    renderNavigation(nav);
    if (!nav.nextElementSibling?.classList.contains('workspace-collection')) {
      mountCollectionStatus(nav);
    }
  }
}

renderWorkspaceNavigation();
applyTheme();

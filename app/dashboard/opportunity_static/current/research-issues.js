import {count, link, node, stack, table, time} from './workspace-ui.js';

const statuses = {
  open:'Open', resolved_by_evidence:'Resolved by evidence', accepted_historical_gap:'Accepted historical gap',
  accepted_source_limitation:'Accepted source limitation', excluded_by_scope:'Excluded by scope',
  assigned_another_date:'Assigned another date',
};
function evidenceLinks(items = []) {
  const root = node('ul');
  for (const item of items) {
    const row = node('li', item.label);
    try {
      const url = new URL(item.url, location.origin);
      if (item.url && ['http:', 'https:'].includes(url.protocol)) row.replaceChildren(link(item.label, url.href));
    } catch { /* Keep the source label when its link cannot be opened. */ }
    root.append(row);
  }
  return root;
}

function historyView(issue) {
  const panel = node('details');
  panel.append(node('summary', `Decision history · ${count(issue.history?.length || 0)}`));
  if (!issue.history?.length) panel.append(node('p', 'No recorded decisions.'));
  else panel.append(table(['Decision', 'Reason and evidence', 'Actor and decision time', 'Evidence revision'],
    issue.history.map(decision => {
      const reason = node('div', decision.reason);
      if (decision.evidence?.length) reason.append(evidenceLinks(decision.evidence));
      return [statuses[decision.status], reason, stack(decision.actor, time(decision.decided_at)), decision.evidence_revision];
    })));
  return panel;
}

export function issueLedger(value, query, coverageURL, gameId) {
  const panel = node('section', undefined, 'workspace-panel workspace-card');
  panel.id = 'mens-d1-issues';
  const navigation = node('div', undefined, 'workspace-variant');
  const open = node('button', 'Open issues'), history = node('button', 'Accepted and resolved');
  const contents = node('div');
  panel.append(node('h3', 'Evidence issues'), navigation, contents);
  navigation.append(open, history);
  contents.tabIndex = -1;
  const issues = [...value.issues];
  let browsingHistory = false;
  const selectedGame = gameId || query.get('coverage_game');
  function render() {
    const scoped = selectedGame ? issues.filter(issue => issue.game_id === selectedGame || issue.game_id == null) : issues;
    const active = scoped.filter(issue => issue.status === 'open' && issue.active !== false);
    const closed = scoped.filter(issue => !active.includes(issue));
    open.textContent = `Open issues (${count(active.length)})`;
    history.textContent = `Accepted and resolved (${count(closed.length)})`;
    open.setAttribute('aria-pressed', String(!browsingHistory));
    history.setAttribute('aria-pressed', String(browsingHistory));
    const visible = browsingHistory ? closed : active;
    if (!visible.length) {
      contents.replaceChildren(node('p', browsingHistory ? 'No accepted or resolved issues.' : 'No open issues for this evidence view.'));
      return;
    }
    contents.replaceChildren(...visible.map(issue => {
      const row = node('details', undefined, 'workspace-panel issue-entry');
      const title = issue.game_title ? `${issue.game_title} · ${issue.title}` : issue.title;
      row.append(node('summary', title), node('p', statuses[issue.status], 'workspace-caption'), node('p', issue.reason));
      if (issue.evidence_changed) row.append(node('p', 'New evidence is available for this issue.', 'workspace-notice'));
      if (issue.game_id) row.append(link('Open game and original evidence', coverageURL(query, {coverage_game:issue.game_id})));
      if (issue.evidence?.length) row.append(evidenceLinks(issue.evidence));
      const currentDecision = issue.history?.find(decision => decision.id === issue.latest_decision_id);
      if (currentDecision && currentDecision.reason !== issue.reason) row.append(node('p', currentDecision.reason));
      row.append(historyView(issue));
      return row;
    }));
  }
  open.onclick = () => { browsingHistory = false; render(); };
  history.onclick = () => { browsingHistory = true; render(); };
  render();
  return panel;
}

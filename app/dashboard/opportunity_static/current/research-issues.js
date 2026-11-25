import {count, link, node, readJSON, stack, table, time} from './workspace-ui.js';

const statuses = {
  open:'Open', resolved_by_evidence:'Resolved by evidence', accepted_historical_gap:'Accepted historical gap',
  accepted_source_limitation:'Accepted source limitation', excluded_by_scope:'Excluded by scope',
  assigned_another_date:'Assigned another date',
};
const actions = {
  open:'Reopen issue', resolved_by_evidence:'Resolve with evidence', accepted_historical_gap:'Accept historical gap',
  accepted_source_limitation:'Accept source limitation', excluded_by_scope:'Exclude with scope evidence',
  assigned_another_date:'Assign another date with evidence',
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

function decisionForm(issue, context, save) {
  const panel = node('details', undefined, 'workspace-panel');
  panel.append(node('summary', 'Record a decision'));
  const form = node('form', undefined, 'workspace-form issue-decision-form');
  const choice = node('label', 'Decision'), select = node('select');
  const offered = (issue.allowed_statuses || []).filter(status => status !== issue.status && actions[status]);
  if (!offered.length) return null;
  select.append(new Option('Choose a decision', ''), ...offered.map(status => new Option(actions[status], status)));
  select.setAttribute('aria-label', 'Decision');
  select.required = true;
  choice.append(select);
  const reasonLabel = node('label', 'Reason'), reason = node('textarea');
  reason.required = true;
  reason.rows = 3;
  reasonLabel.append(reason);
  const evidenceLabel = node('label', 'Evidence URL'), evidence = node('input');
  evidence.inputMode = 'url';
  evidenceLabel.append(evidence);
  const help = node('p', 'Use a retained evidence path or an HTTPS citation. Scope and date decisions require supporting evidence.', 'workspace-caption');
  select.onchange = () => {
    evidence.required = (select.value === 'resolved_by_evidence' && issue.verified_evidence === false) ||
      (['excluded_by_scope', 'assigned_another_date'].includes(select.value) && (issue.evidence?.length || 0) < 2);
  };
  const submit = node('button', 'Save issue decision');
  submit.type = 'submit';
  const status = node('p');
  status.setAttribute('role', 'status');
  form.onsubmit = async event => {
    event.preventDefault();
    submit.disabled = true;
    status.textContent = 'Saving decision…';
    try {
      const payload = {...context, id:issue.id, evidence_revision:issue.evidence_revision,
        latest_decision_id:issue.latest_decision_id ?? null, status:select.value, reason:reason.value.trim()};
      if (evidence.value.trim()) {
        const url = new URL(evidence.value.trim(), location.origin);
        payload.evidence_url = url.origin === location.origin ? url.pathname + url.search + url.hash : url.href;
      }
      const changed = await readJSON('/api/workspace/mens-d1/issues', {
        method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload),
      });
      save(changed.issue || changed);
    } catch (error) {
      status.textContent = error.message;
      submit.disabled = false;
    }
  };
  form.append(choice, reasonLabel, evidenceLabel, help, submit, status);
  panel.append(form);
  return panel;
}

export function issueLedger(value, query, coverageURL, gameId) {
  const panel = node('section', undefined, 'workspace-panel workspace-card');
  panel.id = 'mens-d1-issues';
  const navigation = node('div', undefined, 'workspace-variant');
  const open = node('button', 'Open issues'), history = node('button', 'Accepted and resolved');
  const status = node('p');
  status.setAttribute('role', 'status');
  const contents = node('div');
  panel.append(node('h3', 'Evidence issues'), node('p', 'Decisions are recorded against the evidence revision and leave saved runs and capture tasks intact.'),
    navigation, status, contents);
  navigation.append(open, history);
  contents.tabIndex = -1;
  const issues = [...value.issues];
  let browsingHistory = false;
  const context = {date:value.date, ...(query.has('run') ? {run:query.get('run')} : {})};
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
      if (issue.evidence_changed) row.append(node('p', 'New evidence is available. Review it before recording a decision.', 'workspace-notice'));
      if (issue.game_id) row.append(link('Open game and original evidence', coverageURL(query, {coverage_game:issue.game_id})));
      if (issue.evidence?.length) row.append(evidenceLinks(issue.evidence));
      const currentDecision = issue.history?.find(decision => decision.id === issue.latest_decision_id);
      if (currentDecision && currentDecision.reason !== issue.reason) row.append(node('p', currentDecision.reason));
      row.append(historyView(issue));
      const form = decisionForm(issue, context, changed => {
        const index = issues.findIndex(item => item.id === changed.id);
        if (index >= 0) issues[index] = changed;
        browsingHistory = changed.status !== 'open';
        render();
        contents.focus({preventScroll:true});
        status.textContent = `Saved · ${statuses[changed.status]} · ${title}`;
      });
      if (form) row.append(form);
      return row;
    }));
  }
  open.onclick = () => { browsingHistory = false; render(); };
  history.onclick = () => { browsingHistory = true; render(); };
  render();
  return panel;
}

import {byId, card, count, details, label, link, list, node, pairs, pct, readJSON, table, time, usd} from './workspace-ui.js';
import {renderRun, renderSavedEvidence} from './research-run.js';
import {renderResults} from './research-results.js';
import {campaignDays,campaignForm,campaignHref,campaignList,configuredModes,configuredPortfolio,readCampaign,renderCampaign,renderScheduledDay,sizingTitle} from './research-campaigns.js';
import {coverageContext, coverageURL, experimentCoverage, ledgerKeys, readDailyCoverage, reconciliationSummary, workbenchContext} from './mens-d1-coverage.js';
import {renderWorkspaceNavigation} from './workspace-nav.js';

const endpoint = '/api/research/workspace';
const sections = new Set(['theories', 'experiments', 'results']);
const root = byId('research-view'), status = byId('research-status');
const dialogs = byId('research-evidence');
let workspace, readiness, version = 0, loadedRun, busy = false, stopResultRefresh = () => {}, updateResultRoute;

const resultKeys = ['result', ...ledgerKeys];
const present = values => Object.fromEntries(Object.entries(values).filter(([, value]) => value != null));
const resultContext = query => workbenchContext(query, resultKeys);
const portfolioVariant = query => query.get('variant') === 'all_venues' ? 'all_venues' : 'best_venue';

const locationState = () => new URLSearchParams(location.search);
const sectionName = query => sections.has(query.get('section')) ? query.get('section') : 'overview';
const runById = id => (workspace.runs || []).find(run => run.id === id);
const claimById = id => (workspace.claims || []).find(claim => claim.id === id);
const definitionById = version => (workspace.definitions || []).find(definition => definition.version === version);
function url(section, params = {}) {
  const query = new URLSearchParams({...(section === 'overview' ? {} : {section}), ...present(params)});
  return '/research' + (query.size ? '?' + query : '');
}
function navigate(href, {inspect = false, replace = false} = {}) {
  if (href !== location.pathname + location.search) {
    if (replace) history.replaceState(null, '', href);
    else history.pushState(null, '', href);
  }
  render({inspect});
}
function dailyContext(context, date, run) {
  const next = {...context, view:'daily', date, run, scope:context.campaign ? 'mens-d1' : context.scope};
  if (date !== context.date || (context.run && context.run !== run)) {
    for (const key of ['result', 'game', 'trade', 'sizing_quote', 'sizing_bet', 'trade_page', 'coverage_game']) delete next[key];
  }
  if (!next.campaign) delete next.view;
  return present(next);
}
const runLink = (run, title = run.title || run.date) => link(title, url('experiments', {run:run.id}));
const claimLink = id => link(claimById(id)?.title || id, url('theories', {claim:id}));
const findingLink = finding => link(finding.title, url('results', {finding:finding.id}));
const runAPI = id => endpoint + '/runs/' + encodeURIComponent(id);
const dailyJobAPI = id => endpoint + '/mens-d1-jobs/' + id;
const jobIdentity = /^[a-f0-9]{32}$/;
const safeLocal = href => typeof href === 'string' && /^\/(?!\/)[^\\]*$/.test(href);
function claims(root, ids) {
  if (ids?.length) root.append(list(ids, id => {
    const li = node('li');
    li.append(claimLink(id));
    return li;
  }));
}
function evidenceLink(item, runId) {
  if (safeLocal(item.href)) return link(item.label, item.href);
  const id = item.run_id || runId;
  if (!id) return node('span', item.label || 'Evidence not recorded');
  const params = {run:id};
  if (item.ticket_id) params.ticket = item.ticket_id;
  else if (item.game_id) params.evidence = item.game_id;
  return link(item.label || 'Open saved evidence', url('experiments', params));
}
function links(root, title, values, render) {
  if (!values?.length) return;
  root.append(node('h3', title), list(values, value => {
    const item = node('li');
    item.append(render(value));
    return item;
  }));
}
function lines(root, title, values) {
  if (values?.length) root.append(node('h3', title), list(values));
}
function badge(value, state) {
  const element = node('span', value, 'workspace-tag');
  if (state) element.dataset.state = state;
  return element;
}
function readinessCard() {
  const panel = card('Capture readiness');
  const value = readiness?.readiness;
  if (!value) panel.append(node('p', 'Capture readiness is unavailable.'));
  else {
    const warnings = value.blockers || [];
    panel.append(badge(({ready:'Ready to capture', blocked:'Capture blocked', unknown:'Readiness unknown', limited:'Capture limited'})[value.state] || label(value.state), value.state));
    if (warnings.length) panel.append(list(warnings, warning => {
      const item = node('li', warning.message);
      if (safeLocal(warning.settings_url)) item.append(document.createTextNode(' '), link('Open Settings', warning.settings_url));
      return item;
    }));
    const storage = value.retention || {};
    const countKnown = ['checkpoint_refusals','observation_refusals','capture_refusals'].some(key => storage[key] != null);
    if (countKnown) panel.append(node('p', `Recorded refusals: ${count(storage.checkpoint_refusals)} scheduled checkpoints, ${count(storage.observation_refusals)} research observations, ${count(storage.capture_refusals)} cohort captures.`));
    if (storage.historical_gap_started_at) panel.append(node('p', `Earlier retention gaps date to ${time(storage.historical_gap_started_at)}. Refusal count: ${count(storage.historical_gap_attempts)}.`));
    if (readiness.next_capture?.target_at) panel.append(node('p', `Next scheduled ${readiness.next_capture.checkpoint === 'late' ? 'T−10' : 'early'} checkpoint: ${time(readiness.next_capture.target_at)}.`));
  }
  const actions = node('div', undefined, 'workspace-links');
  actions.append(link('Collection settings', '/settings#collection'), link('Storage settings', '/settings#storage'), link('Latest odds pull', '/data?evidence=pulls'));
  panel.append(actions);
  return panel;
}
function overview() {
  const layout = node('div', undefined, 'workspace-grid');
  for (const theory of workspace.theories || []) {
    const panel = card('Active research question');
    panel.append(node('h3', theory.title), node('p', theory.statement));
    links(panel, 'Open claims', (theory.claim_ids || []).filter(id => !['established', 'verified'].includes(claimById(id)?.status)), claimLink);
    panel.append(link('Open theory and risk objective', url('theories', {theory:theory.id}), 'research-button'));
    layout.append(panel);
  }
  const pilot = workspace.pilot;
  if (pilot) {
    const run = (workspace.runs || []).find(run => run.date === pilot.date && run.definition_version === pilot.definition_version);
    const panel = card('Experiment progress');
    panel.append(node('h3', pilot.title), node('p', `${pilot.date} · Retrospective pipeline pilot`));
    if (run) {
      panel.append(node('p', `${count(run.coverage?.captured_games)} valid T−10 captures from ${count(run.coverage?.tracked_games)} tracked games. Expected slate: ${count(run.coverage?.expected_games)}.`), runLink(run, 'Open pilot run'));
    } else panel.append(node('p', 'A replay has yet to be saved from retained evidence.'), link('Open pilot experiment', url('experiments', {definition:pilot.definition_version}), 'research-button'));
    layout.append(panel);
  }
  const recent = card('Recent findings');
  if (workspace.findings?.length) {
    recent.append(list(workspace.findings.slice(0, 4), finding => {
      const item = node('li');
      item.append(findingLink(finding), node('p', finding.statement, 'workspace-caption'));
      return item;
    }));
  } else recent.append(node('p', 'Findings will appear when a saved run has been evaluated.'));
  layout.append(recent, readinessCard());
  const next = card('Next useful work');
  next.append(list([
    link('Inspect tracked games with missing T−10 captures', '/data?evidence=checkpoints'),
    link('Check the newest acquisition attempt', '/data?evidence=pulls'),
    link('Replay a retained game date', url('experiments')),
  ], action => {
    const item = node('li');
    item.append(action);
    return item;
  }));
  root.replaceChildren(campaignList(workspace.campaigns),layout, next);
}
function theories(query) {
  const theoryId = query.get('theory'), claimId = query.get('claim');
  const selectedTheory = theoryId && (workspace.theories || []).find(theory => theory.id === theoryId);
  const selectedClaim = claimId && claimById(claimId);
  const theoryList = selectedTheory ? [selectedTheory] : workspace.theories || [];
  const claimList = selectedClaim ? [selectedClaim] : (workspace.claims || []).filter(claim => !selectedTheory || selectedTheory.claim_ids.includes(claim.id));
  const output = document.createDocumentFragment();
  if (theoryId || claimId) output.append(link('All theories and laws', url('theories')));
  if ((theoryId && !selectedTheory) || (claimId && !selectedClaim)) output.append(node('p', 'The requested research record could not be found.', 'workspace-notice'));
  if (!selectedClaim) for (const theory of theoryList) {
    const panel = card(theory.title);
    panel.classList.add('workspace-panel');
    panel.append(node('p', theory.statement), pairs({Scope:theory.scope, Version:theory.version}));
    links(panel, 'Supporting claims and laws', theory.claim_ids, claimLink);
    for (const objective of theory.risk_objectives || []) {
      panel.append(node('h3', 'Risk objective'), node('p', objective.statement));
      panel.append(pairs({'Current estimate':objective.estimate ?? 'Not established', Status:label(objective.status)}));
      lines(panel, 'Assumptions still needed', objective.missing_assumptions);
    }
    output.append(panel);
  }
  const collection = node('div', undefined, 'workspace-grid');
  for (const claim of claimList) {
    const panel = card(claim.title, claimId ? null : claimLink(claim.id));
    panel.append(badge(label(claim.type)), node('p', claim.statement));
    panel.append(pairs({Status:label(claim.status), Scope:claim.scope, Version:claim.version}));
    if (claim.challenge) panel.append(node('h3', 'What would challenge it'), node('p', claim.challenge));
    lines(panel, 'Assumptions', claim.assumptions);
    links(panel, 'Dependencies', claim.dependencies, claimLink);
    const parents = (workspace.theories || []).filter(theory => theory.claim_ids.includes(claim.id));
    links(panel, 'Theories using this claim', parents, theory => link(theory.title, url('theories', {theory:theory.id})));
    links(panel, 'Supporting evidence', claim.supporting_evidence, evidence => evidenceLink(evidence));
    links(panel, 'Contrary evidence', claim.contrary_evidence, evidence => evidenceLink(evidence));
    const definitions = (workspace.definitions || []).filter(definition => definition.claim_ids.includes(claim.id));
    links(panel, 'Experiments examining this claim', definitions, definition => link(definition.title + ' · ' + definition.version, url('experiments', {definition:definition.version})));
    links(panel, 'Findings', (workspace.findings || []).filter(finding => finding.claim_ids.includes(claim.id)), findingLink);
    collection.append(panel);
  }
  output.append(collection);
  root.replaceChildren(output);
}
function findings(root, values, selected) {
  if (!values.length) {
    root.append(node('p', 'No findings have been recorded for this selection.'));
    return;
  }
  for (const finding of values) {
    const panel = card(finding.title, selected ? null : findingLink(finding));
    panel.classList.add('workspace-panel');
    panel.append(badge(label(finding.disposition)), node('p', finding.statement));
    const run = runById(finding.run_id);
    const definition = definitionById(finding.definition_version);
    if (definition?.question) panel.append(node('h3', 'Experiment question'), node('p', definition.question));
    if (run) panel.append(runLink(run, `Open run · ${run.date}`));
    links(panel, 'Claims examined', finding.claim_ids, claimLink);
    lines(panel, 'Limitations', Array.isArray(finding.limitations) ? finding.limitations : finding.limitations ? [finding.limitations] : []);
    links(panel, 'Source evidence', finding.evidence, evidence => evidenceLink(evidence, finding.run_id));
    root.append(panel);
  }
}
function results(query) {
  const selected = query.get('finding');
  const values = (workspace.findings || []).filter(row => !selected || row.id === selected);
  root.replaceChildren(node('h2', 'Findings across saved runs'));
  if (selected) root.append(link('All findings', url('results')));
  findings(root, values, selected);
}
function field(title, control) {
  const element = node('label');
  element.append(node('span', title), control);
  return element;
}
function replayForm(definition, query) {
  const panel = card('Replay a game date');
  panel.classList.add('workspace-panel');
  const form = node('form', undefined, 'workspace-form');
  const date = node('input');
  date.id = 'research-replay-date';
  date.type = 'date';
  date.required = true;
  date.value = query.get('date') || workspace.pilot?.date || '';
  const dateChoice = node('select');
  dateChoice.id = 'research-available-dates';
  dateChoice.append(new Option('Choose a retained date', ''), ...(workspace.available_dates || []).map(item => new Option(`${item.date} · ${count(item.captured_games)} valid captures`, item.date)));
  dateChoice.onchange = () => { if (dateChoice.value) date.value = dateChoice.value; };
  const settings = node('details');
  settings.append(node('summary', 'Change assumptions for a new analysis version'));
  const settingFields = node('div', undefined, 'workspace-form');
  const inputs = {};
  for (const [key, title, example] of [
    ['minimum_ev', 'Minimum unrounded EV (decimal or fraction)', '0.04'],
    ['reference_bankroll_usd', 'Fixed sizing reference (USD)', '10000'],
    ['kelly_multiplier', 'Kelly fraction', '1/4'],
  ]) {
    const input = node('input');
    input.name = key;
    input.placeholder = definition.policy?.[key] ?? example;
    input.maxLength = 32;
    inputs[key] = input;
    settingFields.append(field(title, input));
  }
  settings.append(settingFields);
  const register = node('details');
  register.append(node('summary', 'Register a related exploratory experiment'));
  const registration = node('div', undefined, 'workspace-form');
  const title = node('input'), question = node('input');
  title.maxLength = 120;
  question.maxLength = 500;
  const claimControls = node('fieldset', undefined, 'workspace-claims');
  claimControls.append(node('legend', 'Claims to examine'));
  const availableClaims = (workspace.claims || []).map(claim => {
    const checkbox = node('input');
    checkbox.type = 'checkbox';
    checkbox.value = claim.id;
    checkbox.checked = (definition.claim_ids || []).includes(claim.id);
    claimControls.append(field(claim.title, checkbox));
    return checkbox;
  });
  registration.append(field('New experiment title', title), field('Research question', question), claimControls);
  register.append(registration, node('p', 'This creates a separate retrospective experiment using the selected definition as its starting policy.', 'workspace-caption'));
  register.addEventListener('toggle', () => {
    title.required = question.required = register.open;
    submit.textContent = register.open ? 'Register experiment and save replay' : 'Save replay';
  });
  const submit = node('button', 'Save replay');
  submit.type = 'submit';
  form.append(field('Game date (Eastern)', date), field('Available evidence', dateChoice), submit, settings, register);
  const feedback = node('p');
  feedback.id = 'research-replay-status';
  feedback.setAttribute('role','status');
  form.onsubmit = async event => {
    event.preventDefault();
    if (busy) return;
    const source = location.href;
    const assumptions = Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, input.value.trim()]).filter(([, value]) => value));
    const payload = {date:date.value, definition_version:definition.version};
    if (Object.keys(assumptions).length) payload.assumptions = assumptions;
    if (register.open) {
      const ids = availableClaims.filter(control => control.checked).map(control => control.value);
      if (!title.value.trim() || !question.value.trim() || !ids.length) {
        feedback.textContent = 'Enter a title and question and select at least one claim.';
        return;
      }
      payload.experiment = {title:title.value.trim(), question:question.value.trim(), claim_ids:ids};
    }
    busy = submit.disabled = true;
    feedback.textContent = 'Saving replay from retained checkpoint evidence…';
    try {
      const value = await readJSON(endpoint + '/runs', {
        method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload),
      });
      loadedRun = value;
      workspace = await readJSON(endpoint);
      if (location.href === source) {
        const context = query.get('scope') === 'mens-d1' ? coverageContext(query) : {};
        history.pushState(null, '', url('experiments', {...context, date:value.run.date, run:value.run.id}));
        await render();
      }
    } catch (error) {
      feedback.textContent = error.message;
    } finally {
      busy = submit.disabled = false;
    }
  };
  panel.append(form, feedback, node('p', 'Each saved replay keeps its definition and source revision. Replaying the same evidence uses the existing run.', 'workspace-caption'));
  return panel;
}
function definitionCard(definition) {
  const panel = card(definition.title);
  panel.classList.add('workspace-panel');
  panel.append(badge(label(definition.designation)), node('p', definition.question));
  if (definition.registration) panel.append(node('p', definition.registration, 'workspace-caption'));
  if (definition.recorded_at) panel.append(node('p', 'Registered ' + time(definition.recorded_at), 'workspace-caption'));
  panel.append(pairs({
    Version:definition.version,
    'Minimum screening EV':pct(definition.policy?.minimum_ev),
    ...(definition.policy?.sizing_mode==='fixed_profit' ? {'Sizing':sizingTitle(definition.policy)} : {
      'Sizing reference':usd(definition.policy?.reference_bankroll_usd),
      'Kelly multiplier':pct(definition.policy?.kelly_multiplier),
    }),
  }));
  for (const [earlier, caption] of [[definition.supersedes, 'Earlier version'], [definition.template_version, 'Template version']]) {
    if (earlier) panel.append(node('p', caption), link(earlier, url('experiments', {definition:earlier})));
  }
  links(panel, 'Claims examined', definition.claim_ids, claimLink);
  lines(panel, 'Assumptions', definition.assumptions);
  lines(panel, 'Evaluation criteria', definition.evaluation_criteria);
  if (definition.policy) panel.append(details('Exact definition and policy', definition));
  return panel;
}
function dailyRunForm(template, query, requestVersion, summaryRead) {
  const context = coverageContext(query, workspace.pilot?.date);
  const panel = card('Save a men’s D1 paper run');
  const feedback = node('p', 'Checking retained game evidence…', 'workspace-caption');
  feedback.setAttribute('role', 'status');
  const submit = node('button', 'Save run from retained schedule');
  submit.type = 'button';
  submit.disabled = true;
  panel.append(feedback, submit);
  const current = () => version === requestVersion;
  const updateURL = (extra = {}) => history.replaceState(null, '', url('experiments', {...context, ...extra}));
  const jobError = message => {
    updateURL();
    feedback.textContent = message;
    submit.disabled = false;
  };
  const watch = async id => {
    if (!current()) return;
    try {
      const job = await readJSON(dailyJobAPI(id));
      if (!current()) return;
      if (job.state === 'succeeded' && job.run_id) {
        updateURL({run:job.run_id});
        render();
      } else if (job.state === 'failed') {
        jobError(label(job.reason || 'The run could not be saved.'));
      } else {
        feedback.textContent = 'Saving from retained evidence. This job can continue while you leave the page.';
        setTimeout(() => watch(id), 1200);
      }
    } catch (error) {
      if (current()) jobError(error.message);
    }
  };
  submit.onclick = async () => {
    submit.disabled = true;
    feedback.textContent = 'Starting a run from retained evidence…';
    try {
      const job = await readJSON(endpoint + '/runs', {method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({date:context.date, definition_version:template.version})});
      if (!current()) return;
      if (!jobIdentity.test(job.job_id)) throw Error('The saved run job identity could not be verified.');
      history.pushState(null, '', url('experiments', {...context, coverage_job:job.job_id}));
      watch(job.job_id);
    } catch (error) {
      if (current()) jobError(error.message);
    }
  };
  const jobId = query.get('coverage_job');
  if (jobIdentity.test(jobId)) watch(jobId);
  else summaryRead.then(value => {
    if (!current()) return;
    const population = value.coverage_summary.population;
    submit.disabled = !(population.revision || population.occurrence_games);
    if (submit.disabled) {
      feedback.textContent = `No men’s D1 occurrence evidence is retained for ${context.date}.`;
      return;
    }
    const expected = population.expected_games;
    const evidence = population.source_eligible_games == null ? `${count(population.provider_known_games)} eligible provider-known games`
      : `${count(population.source_eligible_games)} eligible source games`;
    feedback.textContent = `${context.date} · ${evidence}.`
      + (expected == null ? ' The full expected slate is unknown.' : '') + ' Paper results use the frozen 4% EV and quarter Kelly policy.';
  }).catch(error => { if (current()) feedback.textContent = error.message; });
  return panel;
}

function definitionRuns(definition) {
  if (!definition) return [];
  return (workspace.runs || []).filter(run => run.definition_version === definition.version
    || (definition.id && definitionById(run.definition_version)?.id === definition.id));
}

function watchResults(read, publish, current, initial, pinned) {
  let started = true, reading = false, fingerprint = resultFingerprint(initial);
  async function check() {
    if (!started || reading || document.hidden || !current()) return;
    reading = true;
    try {
      const state = await read(true);
      if (resultFingerprint(state) === fingerprint || !started || !current()) return;
      if (!pinned && state.status?.stale) publish(state, {statusOnly:true});
      const latest = await read();
      if (started && current()) {
        fingerprint = resultFingerprint(latest);
        publish(latest);
      }
    } catch (error) {
      if (!started || !current()) return;
      fingerprint = '';
      publish({error:error.message}, {connectionLost:true});
    } finally {
      reading = false;
    }
  }
  const timer = setInterval(check, 15000);
  document.addEventListener('visibilitychange', check);
  return () => {
    started = false;
    clearInterval(timer);
    document.removeEventListener('visibilitychange', check);
  };
}

function resultFingerprint(analysis) {
  const {state, reason, stale, latest_version} = analysis.status || {};
  return JSON.stringify([state, reason, stale, latest_version, analysis.version?.id]);
}

async function openResults(mount, selected, query, context, variant, requestVersion) {
  const id = selected.run.id;
  const campaign = selected.definition.campaign_id;
  const policy=selected.report?.policy || selected.definition.policy || {};
  const config=workspace.campaigns?.find(entry => entry.id === campaign) || policy;
  const mode=selected.definition.sizing_mode || policy.sizing_mode || 'kelly';
  const base = {...context, ...(campaign ? {campaign, mode} : {}), run:id, date:selected.run.date, variant};
  const initialRoute = resultRouteKey(query);
  let params = {...base, ...resultContext(query)};
  const href = overrides => url('experiments', present({...params, ...overrides}));
  const runs = definitionRuns(selected.definition);
  const scheduled = config.start_date ? campaignDays(config) : [];
  const navigation = {
    variant, mode, config, href, go:overrides => navigate(href(overrides)), pinned:Boolean(params.result),
    editHref:campaign ? href({view:'revise',run:null}) : null,
    sizingModes:campaign ? configuredModes({...config,kelly_comparison:config.kelly_comparison ?? selected.definition.kelly_comparison}) : [],
    modeHref:(target,trade)=>target===mode ? href({view:null}) : href({
      mode:target, run:selected.sizing_runs?.[target], view:'daily', result:null, trade:null, trade_page:null,
      sizing_quote:trade?.frozen_quote_id || params.sizing_quote,
      sizing_bet:trade?.equivalent_bet_id || params.sizing_bet,
    }),
    coverageHref:context.scope ? game => coverageURL(new URLSearchParams(params),
      {coverage_game:game.occurrence_id || game.game_id}) + '#mens-d1-issues' : null,
    dates:[...new Set([selected.run.date, ...scheduled, ...runs.map(run => run.date)])].sort().reverse(),
    changeDate:day => {
      const run = campaign ? null : runs.find(candidate => candidate.date === day);
      if (day !== selected.run.date) navigate(url('experiments', dailyContext(params, day, run?.id)));
    },
  };
  function setNavigation() {
    Object.assign(navigation, {
      params, game:params.game, trade:params.trade,
      weeklyHref:campaign ? href({view:'weekly'}) : null,
      filter:['traded', 'zero', 'missing', 'unresolved', 'frozen', 'reconstructed'].includes(params.filter) ? params.filter : 'all',
      tradeFilter:['win', 'loss', 'push', 'void', 'unresolved'].includes(params.trade_filter) ? params.trade_filter : 'all',
    });
  }
  setNavigation();
  const current = () => requestVersion === version && mount.isConnected;
  let lastAnalysis = {};
  let displayedAnalysis;
  const ticketReads = new Map();
  const inspectTrade = (container, trade, onLoaded) => {
    container.append(node('p', 'Reading frozen quote and sizing calculation…'));
    if (!ticketReads.has(trade.id)) {
      ticketReads.set(trade.id, readJSON(runAPI(id) + '/tickets/' + encodeURIComponent(trade.id)).catch(error => {
        ticketReads.delete(trade.id);
        throw error;
      }));
    }
    ticketReads.get(trade.id).then(value => {
      if (!current() || !container.isConnected) return;
      onLoaded?.(value);
      renderSavedEvidence(container, value, {
        ticket:true, resultReview:true, exportLink:runAPI(id) + '?export=1',
        gameLink:gameId => href({evidence:gameId}),
      });
    }).catch(error => { if (current() && container.isConnected) container.replaceChildren(node('p', error.message)); });
  };
  function renderReport({inspect = false} = {}) {
    const focus = document.activeElement?.dataset.workbenchFocus;
    const disclosureKey = summary => JSON.stringify([
      summary.closest('.paper-result-trade')?.dataset.tradeId, summary.textContent,
    ]);
    const disclosures = new Set([...mount.querySelectorAll('details[open] > summary:first-child')].map(disclosureKey));
    renderResults(mount, selected, displayedAnalysis, navigation, inspectTrade);
    for (const summary of mount.querySelectorAll('details > summary:first-child')) {
      if (disclosures.has(disclosureKey(summary))) summary.parentElement.open = true;
    }
    if (inspect) {
      mount.querySelector('.paper-result-trade h3, .paper-result-trade h4')
        ?.focus({preventScroll:matchMedia('(min-width: 1061px)').matches});
    } else if (focus) {
      mount.querySelector(`[data-workbench-focus="${CSS.escape(focus)}"]`)?.focus({preventScroll:true});
    }
  }
  const publish = (analysis, {connectionLost = false, statusOnly = false} = {}) => {
    if (!current()) return;
    if (connectionLost && lastAnalysis.report) {
      analysis = {...lastAnalysis, error:analysis.error, status:{...lastAnalysis.status, stale:true}};
    } else if (statusOnly) analysis = {...lastAnalysis, status:analysis.status};
    else lastAnalysis = analysis;
    displayedAnalysis = analysis;
    renderReport();
  };
  updateResultRoute = (next, options) => {
    if (!current() || resultRouteKey(next) !== initialRoute) return false;
    params = {...base, ...resultContext(next)};
    setNavigation();
    renderReport(options);
    return true;
  };
  const read = (status = false) => readJSON(`${runAPI(id)}/results?` + new URLSearchParams({variant,
    ...(params.result ? {version:params.result} : {}), ...(status ? {status:'1'} : {})}));
  publish({});
  try {
    const analysis = await read();
    if (!current()) return;
    publish(analysis);
    if (!dialogs.open && params.game) mount.querySelector(params.trade ? '.paper-result-trade h4' : '.paper-result-game h3')?.focus();
    stopResultRefresh = watchResults(read, publish, current, analysis, navigation.pinned);
  } catch (error) {
    if (!current()) return;
    const analysis = {error:error.message};
    publish(analysis);
    if (!params.result) stopResultRefresh = watchResults(read, publish, current, analysis);
  }
}

function resultRouteKey(query) {
  const route = new URLSearchParams(query);
  for (const key of ledgerKeys) route.delete(key);
  if (route.get('view') === 'daily') route.delete('view');
  // The run identifies the campaign and date on both older and canonical links.
  if (route.has('run')) {
    for (const key of ['campaign', 'date', 'scope', 'definition']) route.delete(key);
  }
  route.set('variant', portfolioVariant(query));
  route.sort();
  return route.toString();
}

async function experiments(query, requestVersion) {
  if (query.get('campaign') && (!query.get('run') || query.get('view') === 'weekly')) {
    root.replaceChildren(node('p','Reading daily and weekly results…'));
    const campaign = query.get('campaign');
    const config = workspace.campaigns?.find(entry => entry.id === campaign);
    const variant = configuredPortfolio(config,portfolioVariant(query));
    const mode = query.get('mode');
    const edit = query.get('view') === 'revise', daily = query.get('view') === 'daily';
    const context = {...Object.fromEntries(query), campaign, variant};
    const current = () => !stopped && version === requestVersion;
    const weekHref = overrides => campaignHref(campaign, context.variant, {...context, view:'weekly', ...overrides});
    const dayHref = (day, run) => url('experiments', dailyContext(context, day, run));
    let timer, stopped = false;
    const refresh = async () => {
      try {
        const data = await readCampaign(campaign, variant, mode);
        if (!current() || root.querySelector('form')) return;
        context.mode = data.mode;
        context.variant = data.variant;
        root.querySelector('.campaign-read-status')?.remove();
        const day = data.days.find(item => item.date === context.date)
          || data.days.findLast(item => item.run_id) || data.days[0];
        if (daily && day?.run_id) {
          navigate(dayHref(day.date, day.run_id), {replace:true});
          return;
        }
        const options = {
          edit, context, weekly:weekHref(),
          daily:day ? dayHref(day.date, context.run || day.run_id) : null,
          dayHref,
          portfolioHref:key => daily
            ? url('experiments', {...dailyContext(context, day.date, null), variant:key})
            : weekHref({variant:key}),
          modeHref:key=> key===data.mode
            ? daily ? dayHref(day.date,day.run_id) : weekHref()
            : campaignHref(campaign,data.variant,{
              ...context, mode:key, view:daily ? 'daily' : 'weekly',
              date:context.date || day?.date, run:null, result:null, trade:null, trade_page:null,
            }),
          editHref:weekHref({view:'revise',run:null}),
        };
        if (daily && day) {
          renderScheduledDay(root, data, day, {...options, dayHref:date => navigate(dayHref(date, data.days.find(item => item.date === date)?.run_id))});
        } else renderCampaign(root, data, options);
      } catch (error) {
        if (!current()) return;
        if (edit) throw error;
        const previous = root.querySelector('.paper-workbench-header');
        const notice = node('p', previous ? 'Showing the last loaded experiment reports. Refresh failed.' : error.message,
          'campaign-read-status workspace-notice');
        notice.setAttribute('role','status');
        const existing = root.querySelector('.campaign-read-status');
        if (existing) existing.replaceWith(notice);
        else if (previous) root.prepend(notice);
        else root.replaceChildren(notice);
      } finally {
        if (!edit && current()) timer = setTimeout(() => refresh().catch(() => {}), 20000);
      }
    };
    stopResultRefresh = () => { stopped = true; clearTimeout(timer); };
    await refresh();
    return;
  }
  if (query.get('view')==='schedule') {root.replaceChildren();campaignForm(root);return;}
  const requestedDefinition = query.get('definition');
  const matchingRuns = requestedDefinition && query.get('view') !== 'definition' ? definitionRuns(definitionById(requestedDefinition)) : [];
  const definitionRun = matchingRuns.find(run => !query.has('date') || run.date === query.get('date'));
  const id = query.get('run') || definitionRun?.id;
  if (id) {
    if (!query.has('run')) {
      query.set('run', id);
      query.set('date', definitionRun.date);
      history.replaceState(null, '', '/research?' + query);
    }
    const selected = loadedRun?.run.id === id ? loadedRun : await readJSON(runAPI(id));
    if (requestVersion !== version) return;
    loadedRun = selected;
    const context = query.get('scope') === 'mens-d1' || selected.definition?.policy?.scope === 'mens-d1'
      ? {...coverageContext(query, selected.run.date), date:selected.run.date} : {};
    const dateContext = {...context};
    delete dateContext.run;
    const campaignConfig = workspace.campaigns?.find(entry=>entry.id===selected.definition.campaign_id);
    const mode = selected.definition.sizing_mode || selected.report?.policy?.sizing_mode;
    const variant = configuredPortfolio(campaignConfig,portfolioVariant(query));
    const nav = node('div', undefined, 'workspace-links');
    const resultReview = resultContext(query);
    if (selected.definition.campaign_id) nav.append(link('Back to daily & weekly results',url('experiments',{
      ...context, ...resultReview, campaign:selected.definition.campaign_id, date:selected.run.date, run:id, variant, mode, view:'weekly',
    })));
    if (Object.keys(context).length) {
      const dataContext = new URLSearchParams(present({...context, ...resultReview, run:id, variant, mode,
        campaign:selected.definition.campaign_id, view:'daily'}));
      nav.append(link('Daily coverage and issue decisions', coverageURL(dataContext) + '#mens-d1-issues'));
    }
    nav.append(link(Object.keys(context).length ? 'Current evidence and saved runs' : 'Experiments and runs', url('experiments', dateContext)),
      link('Open research findings', url('results')), link('Browse checkpoint evidence in Data', '/data?evidence=checkpoints'));
    root.replaceChildren(nav);
    const hasPortfolios = selected.report?.portfolios?.best_venue && selected.report?.portfolios?.all_venues;
    const paper = hasPortfolios && String(selected.report.policy?.execution || '').startsWith('paper_only');
    const reviewContext = present({...context, run:id, date:selected.run.date, variant, mode, ...resultReview});
    const evidenceHref = (key, value) => url('experiments', {...reviewContext, [key]:value});
    let audit = root;
    if (paper) {
      const mount = node('div');
      const reconciliation = node('div');
      audit = node('details', undefined, 'workspace-panel result-audit');
      audit.append(node('summary', 'Original selection and coverage audit'));
      root.prepend(mount);
      root.append(reconciliation, audit);
      if (Object.keys(context).length && !query.has('game')) {
        const selectedContext = new URLSearchParams({...context, run:id, variant});
        readDailyCoverage(selectedContext, {summary:true}).then(value => {
          if (requestVersion === version) reconciliation.replaceChildren(...reconciliationSummary(value.coverage_summary?.reconciliation, selectedContext));
        }).catch(() => { /* The coverage link above can be used independently. */ });
      }
      openResults(mount, selected, query, context, variant, requestVersion);
    }
    const showAudit = () => {
      if (Object.keys(context).length) audit.append(experimentCoverage(new URLSearchParams({...context, variant}),
        selected.run.date, selected.run, () => requestVersion === version));
      const original = hasPortfolios && !paper ? {...selected, report:{...selected.report, portfolios:null}} : selected;
      renderRun(audit, original, {
        variant, variantLink:name => url('experiments', {...reviewContext, variant:name}),
        ticketLink:ticket => evidenceHref('ticket', ticket.id),
        gameLink:game => evidenceHref('evidence', game.game_id),
        exportLink:runAPI(id) + '?export=1',
        offerExportLink:Object.keys(context).length ? runAPI(id) + '/offers' : null,
        priorRunLink:prior => url('experiments', {...dateContext, run:prior, variant}),
        definitionLink:link('Open frozen definition', url('experiments', {...dateContext, definition:selected.run.definition_version, view:'definition'})),
      });
    };
    if (paper) audit.addEventListener('toggle', () => { if (audit.open && audit.childElementCount === 1) showAudit(); });
    else showAudit();
    if (selected.findings?.length) {
      const resultPanel = node('section', undefined, 'workspace-panel');
      resultPanel.append(node('h2', 'Research findings for this run'));
      findings(resultPanel, selected.findings);
      root.append(resultPanel);
    }
    const ticket = query.get('ticket'), evidence = query.get('evidence');
    if (ticket || evidence) {
      const title = byId('research-evidence-title'), content = byId('research-evidence-content');
      title.textContent = ticket ? 'Saved paper ticket' : 'Frozen game evidence';
      content.replaceChildren(node('p', 'Reading saved source evidence…'));
      if (!dialogs.open) dialogs.showModal();
      const path = ticket ? '/tickets/' + encodeURIComponent(ticket) : '/evidence/' + encodeURIComponent(evidence);
      try {
        const value = await readJSON(runAPI(id) + path);
        if (requestVersion === version) renderSavedEvidence(content, value, {
          ticket:Boolean(ticket), exportLink:runAPI(id) + '?export=1',
          gameLink:gameId => evidenceHref('evidence', gameId),
        });
      } catch (error) {
        if (requestVersion === version) content.replaceChildren(node('p', error.message));
      }
    }
    return;
  }
  const definitions = workspace.definitions || [];
  const scoped = query.get('scope') === 'mens-d1';
  const date = coverageContext(query, workspace.pilot?.date).date;
  const availableRuns = (workspace.runs || []).filter(run => !scoped || run.date === date);
  const template = scoped && workspace.mens_d1_template;
  const summaryRead = scoped ? readDailyCoverage(new URLSearchParams({date}), {summary:true}) : null;
  const selected = query.get('definition') ? definitionById(query.get('definition'))
    : (scoped && definitions.find(definition => definition.policy?.scope === 'mens-d1'
        && availableRuns.some(run => run.definition_version === definition.version)))
      || template || definitionById(workspace.pilot?.definition_version) || definitions[0];
  root.replaceChildren(campaignList(workspace.campaigns),node('h2', 'Experiment definitions and dated runs'));
  root.append(experimentCoverage(query, workspace.pilot?.date, null, () => requestVersion === version, summaryRead));
  if (template) root.append(dailyRunForm(template, query, requestVersion, summaryRead));
  if (selected) {
    root.append(definitionCard(selected));
    if (selected !== template && selected.policy?.scope !== 'mens-d1') root.append(replayForm(selected, query));
    const versions = definitions.filter(definition => definition.id === selected.id && definition.version !== selected.version);
    if (versions.length) links(root, 'Other frozen versions', versions, definition => link(definition.version, url('experiments', {definition:definition.version, view:'definition'})));
  } else root.append(node('p', 'No matching experiment definition is available.'));
  const experiments = new Map();
  for (const definition of definitions) {
    const key = definition.id || definition.version;
    if ((selected?.id || selected?.version) !== key && !experiments.has(key)) experiments.set(key, definition);
  }
  links(root, 'Other experiment definitions', [...experiments.values()], definition => link(definition.title, url('experiments', {definition:definition.version})));
  const runs = availableRuns;
  if (!scoped && runs.length) root.append(table(['Saved run', 'Definition', 'Validity', 'Tracked / captured'], runs.map(run => [
    runLink(run, `${run.date} · ${run.title}`), run.definition_version,
    label(run.validity), `${count(run.coverage?.tracked_games)} / ${count(run.coverage?.captured_games)}` + (run.coverage?.reconstructed_games ? ` + ${count(run.coverage.reconstructed_games)} reconstructed` : ''),
  ])));
  else if (!scoped) root.append(node('p', 'No replay has been saved. Choose a date to read its retained checkpoint evidence.'));
  const data = node('div', undefined, 'workspace-links');
  data.append(link('Frozen checkpoint comparisons', '/data?evidence=checkpoints'), link('Declared populations and evaluations', '/data?evidence=populations'));
  root.append(data);
}
async function render(options) {
  if (!workspace) return;
  const query = locationState();
  if (updateResultRoute?.(query, options)) {
    renderWorkspaceNavigation();
    return;
  }
  updateResultRoute = null;
  stopResultRefresh();
  const section = sectionName(query), requestVersion = ++version;
  renderWorkspaceNavigation();
  for (const anchor of document.querySelectorAll('[data-section]')) {
    if (anchor.dataset.section === section) anchor.setAttribute('aria-current', 'page');
    else anchor.removeAttribute('aria-current');
    if (anchor.dataset.section === 'experiments') anchor.href = url('experiments');
  }
  status.textContent = '';
  if (dialogs.open && (section !== 'experiments' || (!query.has('ticket') && !query.has('evidence')))) dialogs.close();
  if (section === 'overview') overview();
  else if (section === 'theories') theories(query);
  else if (section === 'results') results(query);
  else {
    if (query.get('run') && loadedRun?.run.id !== query.get('run')) root.replaceChildren(node('p', 'Reading saved run…'));
    try {
      await experiments(query, requestVersion);
    } catch (error) {
      if (version === requestVersion) root.replaceChildren(link('Back to experiments', url('experiments')), node('p', error.message));
    }
  }
}
document.addEventListener('click', event => {
  const anchor = event.target.closest('a');
  if (!anchor || event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const target = new URL(anchor.href, location.href);
  if (target.origin !== location.origin || target.pathname !== '/research' || target.hash) return;
  event.preventDefault();
  navigate(target.pathname + target.search, {
    inspect:target.searchParams.has('trade') && target.searchParams.get('trade') !== locationState().get('trade'),
  });
});
window.addEventListener('popstate', render);
byId('research-evidence-close').onclick = () => dialogs.close();
dialogs.addEventListener('close', () => {
  const query = locationState();
  if (!query.has('ticket') && !query.has('evidence')) return;
  query.delete('ticket');
  query.delete('evidence');
  history.replaceState(null, '', '/research?' + query);
  render();
});
async function init() {
  const query = locationState();
  if (['#evidence', '#experiment'].includes(location.hash)) {
    query.delete('section');
    query.set('evidence', 'checkpoints');
    location.replace('/data?' + query);
    return;
  }
  // Show saved research independently of the slower operational status read.
  readJSON('/api/workspace/status').then(value => { readiness = value; }, () => { readiness = null; }).finally(() => {
    if (workspace && sectionName(locationState()) === 'overview') overview();
  });
  try {
    workspace = await readJSON(endpoint);
    render();
  } catch (error) {
    status.textContent = error.message;
    const retry = node('button', 'Retry research read');
    retry.onclick = init;
    root.replaceChildren(retry);
  }
}
init();

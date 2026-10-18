import {coverageNames, coverageFamilies, coverageWords, coverageSport, coverageSource, coverageFamily, coveragePeriod} from './coverage-model.js';
import {coverageElement, coverageTime, renderCoverageTotals, renderFilteredCoverage, renderCoverageMatrix, renderCoverageDetails, cellTitle} from './coverage-view.js';
const get = id => document.getElementById(id), keys = ['league', 'venue', 'market', 'period', 'attention', 'sort'];
let data = null, paused = false, timer = null, controller = null, failures = 0, active = true, opener = null, initialDataset = true;
const filters = () => Object.fromEntries(keys.map(key => [key, get(key).value]));
function options() {
  const dimensions = {league:[...new Set(data.cells.map(coverageSport))], venue:[...new Set(data.cells.map(coverageSource))], market:[...new Set(data.cells.map(coverageFamily))], period:[...new Set(data.cells.map(coveragePeriod))]};
  const all = {league:'All sports', venue:'All sources', market:'All families', period:'All periods'};
  for (const [key, values] of Object.entries(dimensions)) {
    const select = get(key), before = select.value, signature = JSON.stringify(values.sort());
    if (select.dataset.signature === signature) continue;
    select.dataset.signature = signature;
    select.replaceChildren(...['', ...values].map(value => {const label = key === 'venue' ? coverageNames[value] : key === 'market' ? coverageFamilies[value] : coverageWords(value); const option = coverageElement('option', value ? label || coverageWords(value) : all[key]); option.value = value; return option;}));
    select.value = values.includes(before) ? before : '';
  }
  if (initialDataset) {
    if (dimensions.period.includes('full_game')) get('period').value = 'full_game';
    initialDataset = false;
  }
}
function draw() {
  if (!data) return;
  const selected = filters(), focused = document.activeElement?.dataset.cellId;
  renderCoverageTotals(get('global-totals'), data.global_totals || {});
  const cells = renderCoverageMatrix(get('coverage'), data, selected, (cell, button) => {
    opener = button; get('cell-title').textContent = cellTitle(cell); renderCoverageDetails(get('cell-content'), cell, data);
    get('coverage-details').showModal(); get('close-coverage-details').focus();
  });
  renderFilteredCoverage(get('filtered-totals'), data, cells);
  if (focused && !get('coverage-details').open) [...get('coverage').querySelectorAll('button')].find(button => button.dataset.cellId === focused)?.focus({preventScroll:true});
  get('test-notice').hidden = !['synthetic', 'fixture', 'authored'].includes(data.mode);
  get('flow').dataset.state = 'ready';
  get('flow').textContent = (paused ? 'View updates paused. ' : '') + 'Captured ' + coverageTime(data.captured_at) + ' · Published ' + coverageTime(data.publication_at) + ' · ' + coverageWords(data.publication_state || 'published') + '. Measurements are as of capture; source clocks and explicit book confirmations determine freshness.' + (data.capture_age_seconds == null ? '' : ' Capture age: ' + Math.round(data.capture_age_seconds) + 's · Publication age: ' + Math.round(data.publication_age_seconds) + 's · Processing delay: ' + Number(data.capture_to_publication_seconds).toFixed(2) + 's.') + (data.publication_reasons?.length ? ' Summary warning: ' + data.publication_reasons.map(coverageWords).join(', ') + '.' : '');
}
function schedule() {
  clearTimeout(timer); if (active && !paused && failures < 4) timer = setTimeout(pull, 10000);
}
async function pull() {
  if (controller || !active || paused) return;
  controller = new AbortController(); const owned = controller, deadline = setTimeout(() => owned.abort(), 5000);
  try {
    const response = await fetch('/api/coverage', {signal:owned.signal, cache:'no-store'}), value = await response.json();
    if (!response.ok) throw Error(value.reason || value.error || 'Coverage publication is unavailable');
    if (value.schema !== 'predict-broad-coverage-1' || !Array.isArray(value.cells) || !value.global_totals) throw Error('Coverage publication does not have the expected captured contract');
    if (!active || paused) return;
    data = value; failures = 0; get('retry-coverage').hidden = true; options(); draw();
  } catch (error) {
    if (!active || paused) return;
    failures++; get('flow').dataset.state = 'error';
    get('flow').textContent = 'Coverage read unavailable. ' + (data ? 'Prior captured measurements remain visible; freshness is unverified. ' : '') + (failures >= 4 ? 'Choose Retry to read the local publication.' : 'Waiting for the next local publication read.');
    get('retry-coverage').hidden = false;
    if (!data) get('coverage').replaceChildren(coverageElement('p', 'Coverage is not available yet. Source status is in Admin. This read does not start collection.', 'empty'));
  } finally {clearTimeout(deadline); if (controller === owned) controller = null; schedule();}
}
get('filters').onsubmit = event => event.preventDefault();
for (const key of keys) get(key).addEventListener('change', draw);
get('clear-filters').onclick = () => {for (const key of keys) get(key).value = key === 'sort' ? 'scope' : ''; draw();};
get('close-coverage-details').onclick = () => get('coverage-details').close();
get('coverage-details').addEventListener('close', () => {const id = opener?.dataset.cellId; [...get('coverage').querySelectorAll('button')].find(button => button.dataset.cellId === id)?.focus({preventScroll:true}); opener = null;});
get('pause-coverage').onclick = () => {paused = !paused; get('pause-coverage').textContent = paused ? 'Resume view updates' : 'Pause view updates'; clearTimeout(timer); if (paused) {controller?.abort(); draw();} else {failures = 0; pull();}};
get('retry-coverage').onclick = () => {failures = 0; if (paused) {paused = false; get('pause-coverage').textContent = 'Pause view updates';} pull();};
window.addEventListener('pagehide', () => {active = false; clearTimeout(timer); controller?.abort();});
pull();

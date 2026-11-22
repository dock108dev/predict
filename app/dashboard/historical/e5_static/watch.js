'use strict';
const $=id=>document.getElementById(id);
const esc=v=>String(v??'Unknown').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pretty=v=>esc(JSON.stringify(v,null,2));
const human=v=>String(v).replaceAll('_',' ');
const usd=v=>v==null?'Unavailable':`${esc(v)} USD`;
const signed=v=>v==null?'Unavailable':`${v.startsWith('-')?'':v==='0'?'':'+'}${esc(v)} USD`;
const cls=v=>v==null?'':v.startsWith('-')?'negative':'positive';
const reasons=rs=>rs.length?`<ul class="reasons">${rs.map(r=>`<li>${esc(human(r))}</li>`).join('')}</ul>`:'';
const raw=(title,value)=>`<details><summary>${esc(title)}</summary><pre>${pretty(value)}</pre></details>`;
let pkg,active,signal='mispricing',selectedBook=null,selectedReceipt=null,referenceId=null,banner={degraded:false,dismissed:false};
const storageKey='predict-e5-saved-audit-v1';
function openPanels(){return [...document.querySelectorAll('details[open]')].map(d=>d.querySelector('summary').textContent);}
function restorePanels(titles){document.querySelectorAll('details').forEach(d=>{d.open=titles.includes(d.querySelector('summary').textContent);});}
function auditStatus(message){$('audit-status').textContent=message;}
function render(){
  const opened=openPanels();
  $('scenario').value=active.key;
  $('cutoff').textContent=`Scenario evaluation cutoff: ${active.cutoff} · alternatives at this cutoff are not observed market movement.`;
  $('scenario-note').textContent=active.invented?'Invented scenario · probabilities, target value and returns are synthetic assumptions and arithmetic. They do not replace E3’s conditional estimate.':'Saved E3 basis · unconditional target value and expected profit remain unavailable.';
  const degraded=active.signals.some(s=>s.status==='unavailable');
  banner=E5State.banner(banner,degraded);
  $('degraded').hidden=!degraded||banner.dismissed;
  $('degraded').querySelector('span').textContent='Some modeled results are unavailable. The reasons remain visible in their rows and details.';
  if(selectedBook===null)selectedBook=active.books[0].selection_key;
  $('books').innerHTML=active.books.map(b=>{
    const q=b.ask;const quantity=q?.quantity?.value;
    return `<article class="book ${b.selection_key===selectedBook?'selected':''}"><h3>${b.venue==='kalshi'?'Kalshi · ATL wins':'Polymarket US · PIT wins'}</h3><div class="quote">${usd(q?.price?.value)} <small>acquisition ask per contract</small></div><p>Bid: ${usd(b.bid?.price?.value)} / contract<br>Top ask quantity: ${esc(quantity)} contracts<br>Usable for this model: ${b.stale?'Unavailable · stale receipt':active.signals[0].sizing_basis.quantity===null?'Unavailable · declared quantity unknown':b.levels===null?'Unavailable · unknown depth':quantity==null?'Unavailable · quantity unknown':esc(quantity)+' contracts at top ask'}</p><small>Saved receipt ${esc(b.received_at)}<br>Age at cutoff: ${esc(b.age_seconds)} s · ${b.stale?'Stale':'within 30 s receipt threshold'}<br>Snapshot time ${esc(b.source_at)} · partial depth</small><button data-book="${esc(b.selection_key)}" aria-pressed="${b.selection_key===selectedBook}">Inspect ${b.venue==='kalshi'?'Kalshi':'Polymarket US'}</button></article>`;
  }).join('');
  $('books').querySelectorAll('[data-book]').forEach(b=>b.onclick=()=>{selectedBook=b.dataset.book;render();$('economics').open=true;});
  for(const s of ['arb','mispricing']){$(s).classList.toggle('active',s===signal);$(s).setAttribute('aria-pressed',String(s===signal));}
  const s=active.signals.find(s=>s.signal_class===signal),d=s.display;
  $('signal').innerHTML=`<p class="condition">${active.invented?'Invented scenario · synthetic assumptions and arithmetic':'E3 conditional estimate · exceptional probabilities unknown'}</p><h2>${signal==='arb'?'Modeled worst-case net':'Modeled expected net'}</h2><p>${signal==='arb'?'Across all material settlement states, conditional on both specified fills.':'Probability-weighted target-leg cashflows, conditional on the stated model and fill.'}</p><div class="numbers"><div><span>Total net</span><strong class="${cls(d.net)}">${signed(d.net)}</strong></div><div><span>${signal==='arb'?'Per equal-quantity two-leg unit':'Per target contract'}</span><strong>${signed(d.per_contract)}</strong></div><div><span>Return on stated capital</span><strong>${d.return_percent===null?'Unavailable':esc(d.return_percent)+'%'}</strong></div></div><p>Declared size: <b>${esc(s.sizing_basis.quantity)} contracts ${signal==='arb'?'on each of two legs':'on the target leg'}</b>. Capital / return denominator: <b>${usd(d.capital)}</b> (${signal==='arb'?'both legs’ entry cash plus consumed execution reserve':'single target entry cash requirement'}).</p>${signal==='mispricing'?`<p>${active.invented?'Invented scenario target value':'E3 unconditional target value'}: <b>${usd(s.unconditional_fair_value_usd)} / contract</b>.</p>`:''}${reasons(s.reasons)}<p class="subtle">Per-contract amounts rounded to 6 decimal places; returns to 4 percentage decimals. Exact values are retained in details.</p><p class="subtle">${esc(s.status)} · synthetic only · no current production opportunity. Shared liquidity is never added into an aggregate profit.</p>`;
  renderRanking();renderDetails();renderReferences();
  $('identity-content').innerHTML=`<p>${esc(active.replay)}</p><p>Audit ID</p><div class="identity-value">${esc(active.id)}</div><p>Exact export SHA-256</p><div class="identity-value">${esc(active.export_sha256)}</div><p>E3 estimate ID</p><div class="identity-value">${esc(active.estimate_id)}</div>${raw('Dependency identities',active.dependencies)}${raw('Assumptions & shared liquidity',{assumptions:active.assumptions,liquidity:active.liquidity_families})}${raw('Invented model and exceptional probability mass',active.model)}`;
  restorePanels(opened);
}
function renderRanking(){
 const groups=pkg.ranking.groups.filter(g=>g.basis[0]===signal);
 $('ranking-content').innerHTML=groups.map((g,i)=>`<h3>Comparable group ${i+1}</h3><p class="group-title">${esc(g.basis[1].quantity)} contracts · cutoff ${esc(g.basis[1].as_of)} · model ${esc(g.basis[1].model)}</p><ol>${g.rows.map(r=>{const c=pkg.cases.find(c=>c.id===r.audit_id);return `<li><button data-case="${c.key}">${esc(c.label)}</button> · ${signed(r.net_total_usd)}</li>`;}).join('')}</ol>`).join('')+`<h3>Unavailable · retained with reasons</h3>`+pkg.ranking.unavailable.filter(r=>r.signal_class===signal).map(r=>{const c=pkg.cases.find(c=>c.id===r.audit_id);return `<p><button data-case="${c.key}">${esc(c.label)}</button></p>${reasons(r.reasons)}`;}).join('');
 $('ranking-content').querySelectorAll('[data-case]').forEach(b=>b.onclick=()=>choose(b.dataset.case));
}
function renderDetails(){
 const b=E5State.select(active.books,selectedBook,'selection_key');
 if(!b){$('economic-details').innerHTML=`<p>Selected book ${esc(selectedBook)} is unavailable in this audit. Identity retained; no replacement selected.</p>`;return;}
 const leg=b.leg;
 $('economic-details').innerHTML=`<h3>${esc(b.venue==='kalshi'?'Kalshi · ATL':'Polymarket US · PIT')} · selected book</h3><p class="identity-value">${esc(selectedBook)}</p>${b.stale?'<p class="reasons">Stale book: modeled results unavailable. Retained cashflows below are conditional diagnostics only.</p>':''}<p>Consumed depth: ${leg?leg.consumed_levels.map(l=>`${esc(l.quantity)} contracts at ${usd(l.price)} / contract (available ${esc(l.available)})`).join('; '):'Unavailable — declared quantity or usable depth missing.'}</p><p>Entry cost ${usd(leg?.entry_cost)} · fees ${usd(leg?.entry_fees)} · required cash ${usd(leg?.required_cash)}. Depth impact is included in consumed prices.</p>${leg?`<div class="table-wrap"><table class="outcomes"><thead><tr><th>Settlement outcome</th><th>Gross payout USD</th><th>Settlement fee USD</th><th>Net cashflow USD</th></tr></thead><tbody>${Object.entries(leg.outcomes).map(([name,o])=>`<tr><td>${esc(human(name))}</td><td>${esc(o.gross_payout)}</td><td>${esc(o.settlement_fee)}</td><td>${esc(o.net_cashflow)}</td></tr>`).join('')}</tbody></table></div>`:''}${reasons(leg?.reasons||[])}${raw('Fee schedule, exact rounding & refunds',leg?.fee_audit??{reason:'No allocation available',contexts:active.signals[0].reasons})}${raw('Credits / rounding refunds',leg?.credits)}${raw('All retained depth, source times & book identity',b.details)}${raw('Signal cashflows, qualification and execution assumptions',active.signals)}`;
}
function renderReferences(){
 const referenceOpened=openPanels();
 const e=E5State.select(pkg.estimates,referenceId);
 if(!e){$('reference-status').textContent='Selected estimate unavailable; identity retained.';return;}
 $('receipt-cutoff').value=e.id;
 $('reference-status').textContent=`At ${e.cutoff}: ${e.percent===null?'conditional probability unavailable':e.percent+'% conditional on a normal team-winner result'} · ${e.status}. Scenario books are unchanged.`;
 if(selectedReceipt===null) selectedReceipt=(e.references.find(r=>r.included)||e.references[0])?.receipt_id??null;
 $('references').innerHTML=`<table><thead><tr><th>Receipt / source</th><th>Retained times UTC</th><th>Paired decimal odds ATL / PIT</th><th>Use at this cutoff</th></tr></thead><tbody>${e.references.map(r=>`<tr class="${selectedReceipt===r.receipt_id?'selected-row':''}"><td><button data-receipt="${esc(r.receipt_id)}">${esc(r.receipt_id)}</button><p>${esc(r.family||'Unknown lineage')}<br>The Odds API-shaped fixture</p></td><td>Received ${esc(r.received_at)}<br>Age ${esc(r.receipt_age_seconds)} s<br>Provider read ${esc(r.provider_last_read)}<br>Read age ${esc(r.read_age_seconds)} s</td><td>${r.original_odds?r.original_odds.map(esc).join(' / '):'Unavailable'}<p>${esc(r.observed_change)}</p></td><td>${r.included?'Included · one family':'Excluded'}${reasons(r.reasons)}</td></tr>`).join('')}</tbody></table>`;
 $('references').querySelectorAll('[data-receipt]').forEach(b=>b.onclick=()=>{selectedReceipt=b.dataset.receipt;renderReferences();});
 const row=E5State.select(e.references,selectedReceipt,'receipt_id');
 $('reference-detail').innerHTML=row?`<h3>Selected receipt · ${esc(selectedReceipt)}</h3><p>Receipt freshness limit ${esc(e.policy.max_receipt_age_seconds)} s; provider-read limit ${esc(e.policy.max_provider_read_age_seconds)} s. Bookmaker change time: Unknown.</p>${reasons(row.reasons)}${raw('Exact receipt, exclusion & source identities',row)}`:`<p class="reasons">Selected receipt ${esc(selectedReceipt)} was not available at this cutoff. Its identity is retained; no other receipt was selected.</p>`;
 restorePanels(referenceOpened);
}
function choose(key){const row=E5State.select(pkg.cases,key,'key');if(!row){auditStatus('Selected scenario unavailable; no replacement opened.');return;}active=row;render();}
async function reloadPackage(){
 $('load-status').hidden=false;$('content').hidden=true;$('error').hidden=true;$('retry').hidden=true;
 try{
  const response=await fetch('/api/package',{cache:'no-store'});const data=await response.json();
  if(!response.ok)throw new Error(`${data.error}: ${data.reason}`);
  if(data.mode!=='Synthetic'||!Array.isArray(data.cases)||!Array.isArray(data.estimates))throw new Error('Invalid preview package');
  if(!data.cases.length){$('load-status').textContent='No saved audits available. Nothing has been substituted.';$('retry').hidden=false;return;}
  pkg=data;active=pkg.cases[0];referenceId=active.estimate_id;
  $('scenario').innerHTML=pkg.cases.map(c=>`<option value="${c.key}">${esc(c.label)}</option>`).join('');
  $('receipt-cutoff').innerHTML=pkg.estimates.map(e=>`<option value="${e.id}">${esc(e.cutoff)} · ${esc(e.status)}</option>`).join('');
  $('baseline-percent').textContent=pkg.estimates.find(e=>e.id===pkg.cases[0].estimate_id).percent;
  const saved=localStorage.getItem(storageKey);
  if(saved){try{const record=JSON.parse(saved);active=E5State.verifySaved(record,pkg.cases);selectedBook=record.selectedBook;signal=record.signal==='arb'?'arb':'mispricing';referenceId=record.referenceId||active.estimate_id;selectedReceipt=record.selectedReceipt||null;auditStatus(`Reopened saved audit after reload · ${active.replay} · ${active.id}`);}catch(error){throw new Error(error.message);}}
  render();if(saved)restorePanels(JSON.parse(saved).panels||[]);$('content').hidden=false;$('load-status').hidden=true;
 }catch(error){$('load-status').hidden=true;$('error').textContent=error.message;$('error').hidden=false;$('retry').hidden=false;$('reset-bookmark').hidden=!localStorage.getItem(storageKey);}
}
$('scenario').onchange=()=>choose($('scenario').value);
$('receipt-cutoff').onchange=()=>{referenceId=$('receipt-cutoff').value;renderReferences();};
for(const s of ['arb','mispricing'])$(s).onclick=()=>{signal=s;render();};
$('dismiss').onclick=()=>{banner.dismissed=true;$('degraded').hidden=true;};
$('save-audit').onclick=()=>{try{localStorage.setItem(storageKey,JSON.stringify({...E5State.saved(active,selectedBook,signal),referenceId,selectedReceipt,panels:openPanels()}));auditStatus(`Saved exact audit for reopening · ${active.id}`);}catch(error){auditStatus(`Could not save: ${error.message}`);}};
$('reopen-audit').onclick=async()=>{if(!localStorage.getItem(storageKey)){auditStatus('No saved audit yet. Choose a scenario and save it first.');return;}await reloadPackage();};
$('reset-bookmark').onclick=()=>{localStorage.removeItem(storageKey);selectedBook=null;selectedReceipt=null;signal='mispricing';$('reset-bookmark').hidden=true;reloadPackage();};
$('retry').onclick=reloadPackage;
reloadPackage();

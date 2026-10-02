function nativeBookDetails(m,escape){
 const reviews=m.native_review_assessments||[];
 const reviewDetails=reviews.length?'<details data-detail-key="native-review-'+escape(m.source_id)+'-'+escape(m.market_id)+'"><summary>Details · reviewed native correspondence</summary><p>Identity and outcomes reviewed at the saved cutoff. Missing books do not supply prices; settlement, fees and timing remain separate.</p><pre>'+escape(JSON.stringify(reviews,null,2))+'</pre></details>':'';
 if(!m.book_evidence)return reviewDetails;
 const b=m.book_evidence,c=b.counts,last=b.latest||{};
 return reviewDetails+'<details data-detail-key="native-book-'+escape(m.source_id)+'-'+escape(m.market_id)+'"><summary>Details · native book observations</summary><p>'+escape(c.initial_snapshot||0)+' initial snapshots · '+escape(c.repeated_identical_observation||0)+' identical repeats · '+escape(c.price_or_quantity_change||0)+' price or quantity changes · '+escape(c.recovery_snapshot||0)+' recovery snapshots</p><p>Latest source time: '+escape(last.exchange_at||'unavailable')+' · received '+escape(last.received_at||'unavailable')+'. A repeated observation does not establish fresh prices.</p><p>Raw observations; settlement, fees and cross-source equivalence remain unverified.</p><details data-detail-key="native-input-'+escape(m.source_id)+'-'+escape(m.market_id)+'"><summary>Original inputs and identity</summary><pre>'+escape(JSON.stringify({observations:b,metadata:m.native,book:m.native_book},null,2))+'</pre></details></details>';
}
'use strict';
const $=id=>document.getElementById(id),esc=x=>String(x??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let query=new URLSearchParams(location.search),view=query.get('view')||'feed',busy=false,pendingRefresh=false,last=null,pollTimer=null,followSession=null;
const fields=['quantity','scenario','sort','venue','freshness','search','positive','period','family','competition','season'];
for(const key of fields)if(query.has(key)){if(key==='positive')$(key).checked=query.get(key)==='true';else $(key).value=query.get(key);}
function inputs(){const q=new URLSearchParams({view});for(const key of fields)q.set(key,key==='positive'?String($(key).checked):$(key).value);if($('capture').value)q.set('capture',$('capture').value);if(query.has('rule_version'))q.set('rule_version',query.get('rule_version'));return q;}
function comparisonSources(sources){return sources.filter(x=>['prediction','aggregate_comparison'].includes(x.role));}
function fmt(n,suffix=''){return n===null||n===undefined?'Unavailable':Number(n).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})+suffix;}
function link(r){const q=new URLSearchParams({session:r.session,hash:r.hash,cutoff:r.cutoff,quantity:$('quantity').value,scenario:$('scenario').value,candidate:r.candidate,view:r.calculation_view||(view==='ev'?'ev':'arb')});q.set('contract',r.contract||r.legs[0].id);if(r.rule_analysis)q.set('rule_version',r.rule_analysis.version);else if(query.has('rule_version'))q.set('rule_version',query.get('rule_version'));if(r.reference_id)q.set('reference',r.reference_id);if(view==='research')q.set('research','true');if((r.calculation_view==='ev'||view==='ev')&&r.probability!=null&&typeof r.probability!=='object'){q.set('probability',r.probability);q.set('basis',r.assumption);}return '/game?'+q;}
function rememberDetails(root){return new Set([...root.querySelectorAll('details[data-detail-key][open]')].map(d=>d.dataset.detailKey));}
function restoreDetails(root,keys){for(const d of root.querySelectorAll('details[data-detail-key]'))d.open=keys.has(d.dataset.detailKey);}
// Snapshot focus immediately before replacing markup, not before the request.
// Match retained identities rather than row position; never select a different row.
function rememberFocus(){
 const element=document.activeElement;
 const owner=element?.closest('#rows tr[data-id], #product-coverage details[data-detail-key]');
 if(!owner)return null;
 const key=element.dataset.focusKey||(element.tagName==='SUMMARY'?'summary':null);
 const href=element.tagName==='A'?element.getAttribute('href'):null;
 if(!key&&!href)return null;
 return {root:owner.dataset.id!==undefined?'rows':'product-coverage',id:owner.dataset.id??owner.dataset.detailKey,key,href};
}
function restoreFocus(focus){
 if(!focus||document.activeElement!==document.body)return;
 const selector=focus.root==='rows'?'tr[data-id]':'details[data-detail-key]';
 const owner=[...$(focus.root).querySelectorAll(selector)].find(e=>(e.dataset.id??e.dataset.detailKey)===focus.id);
 if(!owner)return;
 const target=[...owner.querySelectorAll('summary, a[href]')].find(e=>focus.key?(e.dataset.focusKey||(e.tagName==='SUMMARY'?'summary':null))===focus.key:e.getAttribute('href')===focus.href);
 if(target&&target.getClientRects().length)target.focus({preventScroll:true});
}

// Keep existing card nodes, open disclosures and scroll position through ticks.
function patchNode(old,node){
 if(old.nodeType!==node.nodeType||old.nodeName!==node.nodeName){old.replaceWith(node.cloneNode(true));return;}
 if(old.nodeType===3){if(old.nodeValue!==node.nodeValue)old.nodeValue=node.nodeValue;return;}
 if(old.nodeType!==1)return;
 if(old.tagName==='DETAILS'&&old.open)return;
 for(const a of [...old.attributes])if(!node.hasAttribute(a.name))old.removeAttribute(a.name);
 for(const a of [...node.attributes])if(old.getAttribute(a.name)!==a.value)old.setAttribute(a.name,a.value);
 const a=[...old.childNodes],b=[...node.childNodes];
 for(let i=0;i<Math.max(a.length,b.length);i++){
  if(!b[i])a[i].remove();else if(!a[i])old.appendChild(b[i].cloneNode(true));else patchNode(a[i],b[i]);
 }
}
function reconcileRows(markup){
 const root=$('rows'),table=document.createElement('table');table.innerHTML='<tbody>'+markup+'</tbody>';
 const old=[...root.children],incoming=[...table.tBodies[0].children];
 const key=n=>n.dataset.id||'heading:'+n.textContent;
 const byKey=new Map(old.map(n=>[key(n),n]));
 const anchor=old.find(n=>n.dataset.id&&n.getBoundingClientRect().bottom>0&&n.getBoundingClientRect().top<innerHeight);
 const y=anchor?.getBoundingClientRect().top;
 // Hold ranking while a disclosure is open; prices and health still update.
 if(old.some(n=>n.querySelector('details[open]'))){const order=new Map(old.map((n,i)=>[key(n),i]));incoming.sort((a,b)=>(order.get(key(a))??1e9)-(order.get(key(b))??1e9));}
 const retained=new Set();
 for(const n of incoming){const existing=byKey.get(key(n));if(existing){patchNode(existing,n);retained.add(existing);root.appendChild(existing);}else root.appendChild(n);}
 for(const n of old)if(!retained.has(n))n.remove();
 if(anchor?.isConnected&&y!==undefined)window.scrollBy(0,anchor.getBoundingClientRect().top-y);
}

function render(r,stable=false){
 const focus=last?.capture===r.capture?rememberFocus():null;
 const openRows=new Set([...document.querySelectorAll('#rows tr')].filter(x=>x.querySelector('details[open]')).map(x=>x.dataset.id));
 renderContent(r,stable);
 for(const row of document.querySelectorAll('#rows tr'))if(openRows.has(row.dataset.id)){const detail=row.querySelector('details');if(detail)detail.open=true;}
 restoreFocus(focus);
}
function renderContent(r,stable=false){const openCoverage=rememberDetails($('product-coverage'));r.rows=r.rows.filter(x=>view!=='arb'||BoardView.crossVenue(x));last=r;$('scenario').disabled=!!r.fee_scenario_locked;if(r.fee_scenario_locked)$('scenario').value='unknown';$('sort').disabled=view!=='research';const s=r.status;globalThis.PredictSources?.render(s,r.capture,r.state);if(s.active&&!pollTimer)pollTimer=setTimeout(poll,1500);$('max-games').disabled=s.active;$('max-games').parentElement.hidden=!s.start_controls.includes('max_games');$('start').textContent=s.operating_mode==='d2-bounded-inventory'?'Start coverage scan':'Start scan';if(s.fixed_duration)$('duration').value=s.fixed_duration;$('duration').disabled=s.active||!!s.fixed_duration;$('start').disabled=!s.start_available;$('stop').disabled=!s.active;$('mode').textContent=!r.capture?'No scan selected':BoardView.mode(r.data_mode,r.live,r.state);$('scan-state').textContent=BoardView.scanStatus(s);if(s.fixed_duration)$('scan-state').textContent+=' Duration is fixed at '+s.fixed_duration+' seconds.';if(s.error)$('scan-state').textContent+=' · '+s.error;
 r.sources=r.sources||[...new Set(r.rows.flatMap(x=>x.venues||[]))].map(v=>({source_id:v,label:v,role:'prediction'}));const sourceChoice=$('venue').value;if(r.sources.length){$('venue').innerHTML='<option value="">All sources</option>'+comparisonSources(r.sources).map(x=>`<option value="${esc(x.source_id)}">${esc(x.label)}</option>`).join('');$('venue').value=sourceChoice;}
 const chosen=r.capture;$('capture').innerHTML=r.captures.map(c=>`<option value="${esc(c.id)}">${esc(BoardView.captureLabel(c.label))}</option>`).join('');$('capture').value=chosen||'';
 const c=r.coverage;$('coverage').textContent=c?`${c.selected} games · ${c.excluded.length} excluded · ${c.truncated_by_limit} beyond limit`:'Discovery pending';$('coverage-detail').textContent=JSON.stringify(c,null,2);$('product-coverage').innerHTML=r.market_catalog?'<p class="source-summary">'+r.sources.filter(x=>x.coverage?.reason||['failed','unavailable','disconnected','resynchronization_required'].includes(x.coverage?.state||x.state)).map(x=>'<span>'+esc(x.label)+': '+esc(BoardView.sourceState(x.coverage?.state||x.state))+(x.coverage?.reason?' — '+esc(x.coverage.reason):'')+'</span>').join('')+'</p><details data-detail-key="markets"><summary>Sources and market coverage</summary><p>'+r.sources.map(x=>esc(x.label)+': '+esc(BoardView.sourceState(x.coverage?.state||x.state))+(x.selected?' · selected':'')+' · '+esc(x.environment||'environment unknown')+' · '+esc(x.update_path||'update method unknown')).join('<br>')+'</p>'+(Object.keys(r.native_comparison_review?.records||{}).length?'<p><a href="/api/native-reviews?capture='+encodeURIComponent(r.capture)+'&amp;cutoff='+encodeURIComponent(r.durable_cursor)+'&amp;download=true">Download selected native reviews</a></p>':'')+r.market_catalog.map(m=>'<div class="retained-native-market">'+esc(m.title)+' · '+esc(m.source_id)+' · '+esc(m.identity?.family)+' / '+esc(m.identity?.period)+' / '+esc(m.identity?.line??'no line')+' · '+esc(m.reason||(m.usable?(r.state==='saved'?'retained at cutoff':'receiving'):'awaiting usable book'))+(m.received_at?' · '+esc(m.update_path)+' · received '+esc(m.received_at):'')+(m.native?.display_prices||[]).map(p=>' · '+esc(p.label)+': displayed '+esc(p.available??'unavailable')+' / last trade '+esc(p.last??'unknown')+' (size unknown)').join('')+nativeBookDetails(m,esc)+(m.quotes||[]).map(q=>' · '+esc(q.side)+': '+(q.ask==null?'ask unavailable':'$'+esc(q.ask))+' / '+(q.ask_size==null?'size unknown':esc(q.ask_size)+' '+esc(q.unit))).join('')+'</div>').join('')+'</details>':'';if(r.references?.length)$('product-coverage').innerHTML+='<details data-detail-key="references"><summary>Saved references · '+r.references.length+'</summary>'+r.references.map(ref=>'<div class="retained-reference">'+esc(ref.provider_id)+' / '+esc(ref.origin_id)+' · '+esc(ref.market_identity?.competition)+' · '+esc(ref.participant)+' · '+esc(ref.value_kind)+' '+esc(ref.value)+'<br>'+esc(ref.market_identity?.family)+' / '+esc(ref.market_identity?.period)+' · '+esc(ref.reason||'Dated input; EV requires an exactly matching supported market')+'<br>As of '+esc(ref.source_at||'unknown')+' · received '+esc(ref.received_at)+'<br>'+esc(ref.dependency)+'<br>Scheduled '+esc(ref.market_identity?.scheduled_start)+' · delay '+esc(ref.delay_seconds??'unknown')+'<br>'+esc(ref.delay_basis)+'<details data-detail-key="reference-'+esc(ref.id)+'"><summary>Original input and calculation basis</summary><p>'+esc(ref.conversion_method||'No probability conversion')+'</p><pre>'+esc(JSON.stringify(ref.original_value,null,2))+'</pre><p>Event '+esc(ref.source_event_id)+' · '+esc(ref.evidence_mode)+'<br>'+esc(ref.provenance)+'<br>Cutoff '+esc(r.durable_cursor)+'</p></details></div>').join('')+'</details>';restoreDetails($('product-coverage'),openCoverage);$('updated').textContent=r.capture_time?'Captured '+new Date(r.capture_time).toLocaleString(undefined,{timeZoneName:'short'}):'';$('last-observation').textContent='Last observation: '+(r.last_update||'—');
 $('feed').setAttribute('aria-pressed',view==='feed');$('arb').setAttribute('aria-pressed',view==='arb');$('ev').setAttribute('aria-pressed',view==='ev');$('research').setAttribute('aria-pressed',view==='research');for(const id of ['positive','venue','freshness'])$(id).disabled=view==='research';$('empty').textContent=['competition','season','period','family','search','venue','freshness'].some(k=>$(k).value)||$('positive').checked?'No matches. Change the search or filters, or turn off Positive results only.':!r.capture?'No results yet. Choose a saved scan or use Start scan when available.':r.live&&!r.rows.length&&!r.market_catalog?.some(m=>m.usable)?'Looking for comparable prices. Results will appear here; Stop saves what has been collected.':r.references?.length&&!r.market_catalog?.length?'References saved. EV unavailable: no compatible prediction observations in this session.':'No comparable results in this scan. Check market coverage or choose another saved scan.';$('explanation').textContent=r.fee_scenario_locked?'Net profit is unavailable because fee applicability and settlement charges are unresolved.':view==='research'?'Retrospective, time-mismatched research · saved DraftKings probabilities and Kalshi YES asks. Conditional ordinary winners only; unconditional EV unavailable.':view==='arb'?(r.rows.some(x=>x.score_partitions)?(r.rows.some(x=>x.market_identity?.period==='first_half')?'Conditional net: reviewed scoring periods, including first-half tie / equality states. Later scoring excluded from first-half markets. Exceptional payouts unresolved.':'Net profit covers the reviewed scoring outcomes with modeled fees. Exceptional settlement and account fees remain unknown.'):'Net profit assumes normal winners and modeled fees. Exceptional settlement and account fees remain unknown.'):'Estimate profit with a dated reference, or open a game to enter your probability and basis.';
 if(view==='research'){renderResearch(r);return;}
 $('rows').classList.add('card-feed');$('head').innerHTML='';
 $('count').textContent=`${new Set((r.comparisons||[]).map(x=>x.event_key||x.game_id)).size} games · ${(r.comparisons||[]).length} price comparisons · ${r.rows.length} return calculations`;
 $('empty').hidden=r.rows.length>0||(r.comparisons||[]).length>0;
 $('explanation').textContent='Conditional estimates at the displayed time. EV needs probability and known costs. Arbitrage return is separate; alternatives share liquidity.';
 const selected=sessionStorage.getItem('predict-selected-row');
 let group=null;
 const comparisonMarkup=view==='feed'&&typeof PriceComparisons!=='undefined'?(r.comparisons?.length?'<tr class="group-heading"><td colspan="5"><h2>Compare prices</h2><p>Largest raw price gaps first. A gap does not establish positive EV.</p></td></tr>':'')+PriceComparisons.render(r,esc,link):'';
 let comparisonAdded=false;
 const nextRows=r.rows.map(x=>{
 const comparisonPrefix=!comparisonAdded&&(x.group==='EV unavailable'||x.group==='Arbitrage return %')?comparisonMarkup:'';
 if(comparisonPrefix)comparisonAdded=true;
 const label=x.group||(view==='arb'?'Arbitrage return %':x.reference_id?'Reference estimate %':'Manual What-if EV%');
 const heading=group!==label?`<tr class="group-heading"><td colspan="5"><h2>${esc(label)}</h2></td></tr>`:'';group=label;
 const reasons=x.unavailable_reason||BoardView.reasons(x).join(' · ')||(x.probability==null&&view!=='arb'?'Probability input unavailable':'Material costs or payout unavailable');
 const cash=x.cash??x.legs[0]?.cash;
 return comparisonPrefix+heading+`<tr class="opportunity-card ${selected===x.id?'selected':''}" data-id="${esc(x.id)}"><td><span class="metric-label">${esc(label)}</span><strong class="card-percent ${Number(x.return_pct)<0?'negative':Number(x.return_pct)>0?'positive':''}">${esc(fmt(x.return_pct,'%'))}</strong><small>${x.return_pct==null?esc(reasons):esc('Conditional · '+(x.usable?'usable at cutoff':'unavailable at cutoff')+(BoardView.reasons(x).length?' · '+BoardView.reasons(x).join(' · '):''))}</small></td><td><a data-focus-key="game" href="${esc(link(x))}">${esc(BoardView.title(x.game_title).name)}</a><small>${esc(BoardView.title(x.game_title).context)}</small><small>${esc(BoardView.mode(r.data_mode,r.live,r.state))} · ${esc(x.at)}</small></td><td>${x.legs.map(l=>`<div>${esc(BoardView.words(l.contract))}<small>${esc(l.label)} · ${l.ask==null?'Ask unavailable':'$'+esc(l.ask)}</small></div>`).join('')}</td><td><details><summary>Details</summary>${typeof PredictDecision==='undefined'?'':PredictDecision.summary(x.decision,esc)+PredictDecision.controls(x,esc)}<p>Evaluated size: ${esc(x.modeled_quantity)} contracts per leg${x.depth_limited?' · limited by depth':''}. Requested: ${esc($('quantity').value)}.</p><p>${x.calculation_view==='arb'||view==='arb'?'Conditional minimum net profit':'Expected net profit'}: $${esc(x.profit??'unavailable')}. Money committed including entry costs: $${esc(cash??'unavailable')}.</p><p>Return % = net profit ÷ money committed × 100. Fees and rounding can change with size; top prices are not average fills. These alternatives share liquidity.</p><p>${esc(x.assumption)} · probability ${esc(x.probability==null?'unavailable':JSON.stringify(x.probability))}</p><p>Cutoff ${esc(x.cutoff)} · ${esc(x.at)}</p><pre>${esc(JSON.stringify({legs:x.legs,settlement:x.settlement,normal_cashflows:x.normal_cashflows,references:x.references},null,2))}</pre><a data-focus-key="game-details" href="${esc(link(x))}">Game details →</a></details></td></tr>`;
 }).join('')+(comparisonAdded?'':comparisonMarkup);
 reconcileRows(nextRows);
 if(typeof PriceComparisons!=='undefined')PriceComparisons.measure(r);
}

function researchDetails(e){if(!e)return '';return `<p>Source retrieved ${esc(e.reference_retrieved_at)}<br>Target received ${esc(e.target_received_at)}<br>Original target cutoff ${esc(e.target_cutoff)}</p><p>DraftKings via ${BoardView.externalLink(e.source_url,'VegasInsider',esc)} · bookmaker update time and delay unknown.</p><p>${e.sides.map(s=>esc(s.team)+' '+esc(s.odds)).join(' / ')}</p><p>${esc(e.fee_basis)}</p><p>${esc(e.assessment.conclusion)}</p><p>${e.assessment.exceptional_differences.map(x=>esc(x.outcome)+': '+esc(x.draftkings)+' '+esc(x.kalshi)).join('<br>')}</p><pre>${esc(JSON.stringify({probability:e.probability,arithmetic:e.arithmetic,expected_payout:e.expected_payout,expected_profit:e.expected_profit,return_pct:e.return_pct,entry_cash:e.leg.cash,fee:e.leg.fee,binding:e.assessment.binding,limitations:e.limitations},null,2))}</pre>`;}
function renderResearch(r){
 $('rows').classList.remove('card-feed');
 $('head').innerHTML='<tr><th>Game / purchase</th><th>Page probability</th><th>Ask / size</th><th>Conditional net / ROI</th><th>Assumptions</th></tr>';
 $('count').textContent=`${r.rows.filter(x=>x.probability!=null).length} page-covered games · ${r.rows.length} shown`; $('empty').hidden=r.rows.length>0;
 const selected=sessionStorage.getItem('predict-selected-row');
 $('rows').innerHTML=r.rows.map(x=>`<tr class="${selected===x.id?'selected':''}" data-id="${esc(x.id)}"><td data-label="Game / purchase"><a data-focus-key="game" href="${esc(link(x))}">${esc(BoardView.title(x.game_title).name)}</a>${BoardView.title(x.game_title).context?'<small>'+esc(BoardView.title(x.game_title).context)+'</small>':''}<small>Buy ${esc(x.target_team)} YES · Kalshi</small></td><td data-label="Page probability">${esc(x.research?x.research.sides.find(s=>s.team===x.target_team).percent+'%':x.probability??'Unavailable')}</td><td data-label="Ask / size">${x.legs[0]?.ask==null?'Unavailable':'$'+esc(x.legs[0].ask)}<small>${esc(x.requested_quantity)} requested / ${esc(x.available_size??'unknown')} available</small></td><td data-label="Conditional net / ROI" class="number ${x.profit?.startsWith('-')?'negative':x.profit==null||/^0(?:\.0+)?$/.test(x.profit)?'':'positive'}">${esc(x.profit==null?'Unavailable':'$'+x.research.display.expected_profit)}<small>${esc(x.return_pct==null?'ROI unavailable':x.research.display.return_pct+'% ROI')}</small></td><td data-label="Assumptions">${esc(x.assumption)}<details><summary>Details</summary>${researchDetails(x.research)}${x.source?`<pre>${esc(JSON.stringify(x.source,null,2))}</pre>`:''}${(x.references||[]).map(r=>`<p>${esc(r.role)} · ${esc(r.provider_id)} / ${esc(r.origin_id)} · ${esc(r.value_kind)} ${esc(typeof r.value==='object'?JSON.stringify(r.value):r.value)}<br>As of ${esc(r.model_as_of||r.source_at)} · Received ${esc(r.received_at)} · Delay ${esc(r.delay_seconds??'unknown')}<br>${esc(r.dependency||'Independence unknown')} · ${esc(r.freshness||'dated')}<br>${esc(r.reason||r.delay_basis||'')}<br>${esc(r.provenance)}</p>`).join('')}<a data-focus-key="game-details" href="${esc(link(x))}">Game details →</a></details></td></tr>`).join('');
}

async function refresh(stable=false){if(busy){pendingRefresh=true;return;}busy=true;try{const q=inputs();if(followSession)q.set('capture',followSession);if(!q.has('capture')&&query.has('capture'))q.set('capture',query.get('capture'));if(view!=='research')q.set('sort','roi');q.set('assumptions',localStorage.getItem('predict-ev-assumptions')||'{}');const response=await fetch('/api/dashboard?'+q);const r=await response.json();if(!response.ok){const error=Error(r.error);error.inputRejected=response.status===422;throw error;}r.browser_received_at=performance.timeOrigin+performance.now();render(r,stable===true);globalThis.PredictWatch?.refresh(r);query=inputs();history.replaceState(null,'','?'+query);sessionStorage.setItem('predict-dashboard-query','?'+query);$('error').textContent=r.error||'';}catch(e){globalThis.PredictWatch?.expire('Dashboard unavailable; signals expired');$('error').textContent=(e.inputRejected?'Check your filters or Saved scans and settings, then use Refresh. ':'Could not load results. Use Refresh to try again. ')+e.message;$('scan-state').textContent=e.inputRejected?'The calculation inputs need attention.':'Scan status is unavailable. Use Refresh to reconnect.';$('updated').textContent='';$('empty').hidden=true;$('product-coverage').replaceChildren();$('rows').replaceChildren();$('count').textContent='Results unavailable';$('mode').textContent=e.inputRejected?'Inputs need attention':'Connection or data unavailable';$('start').disabled=true;}finally{busy=false;if(pendingRefresh){pendingRefresh=false;refresh(true);}}}
for(const key of fields)$(key).onchange=refresh;
$('capture').onchange=()=>{followSession=null;refresh();};$('refresh').onclick=refresh;for(const v of ['feed','arb','ev','research'])$(v).onclick=()=>{view=v;refresh();};
$('rows').onclick=e=>{const row=e.target.closest('tr');if(!row?.dataset.id)return;sessionStorage.setItem('predict-selected-row',row.dataset.id);sessionStorage.setItem('predict-dashboard-query','?'+inputs());if(!e.target.closest('a,details'))location.href=row.querySelector('a').href;};
function startOptions(){
 if(!last?.status?.start_controls)throw Error('Refresh to load scan controls.');
 const values={duration:Number($('duration').value),max_games:Number($('max-games').value),source_settings:globalThis.PredictSources?.settings(last.status)??null};
 return Object.fromEntries(last.status.start_controls.map(key=>{if(!Object.hasOwn(values,key))throw Error('Unsupported scan control.');return [key,values[key]];}));
}
async function command(path){$('scan-state').textContent=path==='stop'?'Stopping feeds and saving observations…':'Starting scan…';if(path==='stop'){$('mode').textContent='Stopping · observations frozen';globalThis.PredictWatch?.expire('Stop requested; signals expired');}$('start').disabled=true;$('stop').disabled=true;try{const response=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(path==='start'?startOptions():{})});const r=await response.json();if(!response.ok)throw Error(r.error);if(path==='start'){followSession=r.session;}await refresh();}catch(e){$('error').textContent='Could not '+path+' the scan. Use Refresh to check its status. '+e.message;}}
$('start').onclick=()=>command('start');$('stop').onclick=()=>command('stop');
// Status polling exists only while an explicitly started scan is active.
async function poll(){pollTimer=null;try{const s=await(await fetch('/api/status')).json();

 await refresh(true);
 if(s.active&&!pollTimer)pollTimer=setTimeout(poll,1500);else if(!s.active)followSession=null;
 }catch(e){$('error').textContent='Application unavailable. Use Refresh to reconnect.';}}
refresh();
// Server notices acknowledged changes, independently of either venue's cadence.
if(typeof EventSource!=='undefined'){
 const updates=new EventSource('/api/updates');
 updates.onopen=()=>{if(typeof PriceComparisons!=='undefined')Object.assign(PriceComparisons.observer,{stream_state:'connected',stream_connected_at:performance.timeOrigin+performance.now()});};
 updates.onerror=()=>{if(typeof PriceComparisons!=='undefined')PriceComparisons.observer.stream_state='disconnected';};
 updates.onmessage=()=>{if(typeof PriceComparisons!=='undefined')PriceComparisons.observer.last_notification_at=performance.timeOrigin+performance.now();refresh(true);};
 window.addEventListener('pagehide',()=>updates.close(),{once:true});
}

if($('import-references'))$('import-references').onclick=async()=>{try{const file=$('reference-file').files[0];if(!file||file.size>1024*1024)throw Error('Choose a prepared reference JSON file under 1 MB');const response=await fetch('/api/references',{method:'POST',headers:{'Content-Type':'application/json'},body:await file.text()});const result=await response.json();if(!response.ok)throw Error(result.error);$('reference-import-status').textContent=result.imported+' references added to this scan.';await refresh();}catch(e){$('reference-import-status').textContent=e.message;}};

if($('import-resolutions'))$('import-resolutions').onclick=async()=>{try{const file=$('resolution-file').files[0];if(!file||file.size>1024*1024)throw Error('Choose a prepared resolution JSON file under 1 MB');const response=await fetch('/api/resolutions',{method:'POST',headers:{'Content-Type':'application/json'},body:await file.text()});const result=await response.json();if(!response.ok)throw Error(result.error);$('resolution-import-status').textContent=result.imported+' retained resolution records appended. Stop to inspect saved resolution history.';await refresh();}catch(e){$('resolution-import-status').textContent=e.message;}};

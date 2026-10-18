import { SCANNER_BOUNDS, scannerDefaults, scannerPreferenceKey, safeScannerPreferences, scannerSelection, ScannerReader } from './scanner-client.js';

import { bootTicket } from './ticket-view.js';
import { bootArrivals } from './scanner-arrivals.js';
import { bootSummaries } from './scanner-summaries.js';

function bootScanner() {
  const ticket=bootTicket(),arrivals=bootArrivals(),summaries=bootSummaries();
  const byId=id=>document.getElementById('scanner-'+id);
  const make=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  const label=value=>({football:'Football',winner:'Winner',full_game:'Full game',kalshi:'Kalshi',polymarket_us:'Polymarket US',novig:'Novig',prophetx:'ProphetX'})[value]||value;
  const nodes=new Map();let page=null,filters=scannerDefaults(),selected=null,hover=null,held=false,verified=false,stopped=false,incompatible=false;
  let shown=[],searchDraft='',optionsSignature='',lastGeneration=0,filterStart=null,serverFilterStart=null,empty=null;
  const timings=[];let timingBytes=0,droppedSamples=0,droppedBytes=0,emittedSamples=0;
  try{filters=safeScannerPreferences(JSON.parse(localStorage.getItem(scannerPreferenceKey)));searchDraft=sessionStorage.getItem('predict-scanner-search')||'';}catch{}
  byId('search').value=searchDraft;byId('results').replaceChildren();
  const metrics=entry=>{const bytes=new TextEncoder().encode(JSON.stringify(entry)).length;emittedSamples++;timings.push({entry,bytes});timingBytes+=bytes;while(timings.length>256||timingBytes>2097152){const removed=timings.shift();timingBytes-=removed.bytes;droppedSamples++;droppedBytes+=removed.bytes;}document.dispatchEvent(new CustomEvent('predict:scanner-paint',{detail:entry}));};
  // Two rAF boundaries include one browser rendering opportunity after DOM mutation.
  const painted=(kind,start,metadata={})=>requestAnimationFrame(()=>requestAnimationFrame(()=>{const paintedAt=performance.now();metrics({kind,ms:paintedAt-start,paintedAt,paintedWallAt:Date.now(),...metadata});}));
  const expireAt=r=>Date.parse(r.expires_at);
  const authority=r=>!incompatible&&!stopped&&verified&&r.current&&Date.now()<expireAt(r);
  const title=r=>r.event_context?.title||r.occurrence_id;
  function positionText(p) {
    const native=p.native_key.at(-1),side=/^(yes|no)$/i.test(native)?native.toUpperCase():native;
    return [side,p.predicate.participant||p.predicate.outcome_id,({not_win:'does not win',win:'wins'})[p.predicate.predicate]||p.predicate.predicate].filter(Boolean).join(' · ');
  }
  function status(r) {
    if(incompatible)return 'Update required';if(stopped)return 'Stopped';if(Date.now()>=expireAt(r))return 'Expired';if(!verified)return 'Freshness unverified';if(!r.current)return 'Last-known research';
    const clocks=r.source_clocks.map(c=>Date.parse(c.book_at||c.source_at)).filter(Number.isFinite);
    return clocks.length===2?Math.max(0,Math.floor((Date.now()-Math.min(...clocks))/1000))+'s original age':'Original age unavailable';
  }
  function select(row) {
    if(!page)return;
    const encoded=JSON.stringify(row);if(new TextEncoder().encode(encoded).length>262144){byId('warning').hidden=false;byId('warning').textContent='This comparison exceeds the selection limit. Inspect it after a supported update.';return;}
    selected={identity:scannerSelection(page,row),row:JSON.parse(encoded)};
    byId('selection').hidden=false;renderSelected();render();
    document.dispatchEvent(new CustomEvent('predict:scanner-selection',{detail:{selection:selected.identity,row:selected.row,amountPreferenceKey:'predict-board-settings'}}));
    byId('close').focus({preventScroll:true});
  }
  function renderSelected() {
    if(!selected || byId('selection').dataset.ticketOwned==='true')return;
    const {row,identity}=selected;
    const latest=page?.rows.find(r=>r.id===identity.row_id);
    const sameContext=page?.server_id===identity.server_id&&page?.epoch===identity.epoch;
    let note='Selected discovery allocation · read-only';
    if(incompatible)note='Previous selection · update required';else if(stopped)note='Previous selection · collection stopped';else if(Date.now()>=expireAt(row))note='Previous selection · original inputs expired';else if(!sameContext)note='Previous selection · server context changed';else if(!verified)note='Previous selection · current comparison unavailable';else if(!latest)note='Previous selection · absent from this ranked page or selected scope';else if(latest.dependency_revision!==identity.dependency_revision||latest.economic_revision!==identity.economic_revision)note='Previous selection · inputs changed; select the current row to inspect it';else if(!row.current)note='Last-known research · read-only';
    if(byId('selection-status').textContent!==note)byId('selection-status').textContent=note;
    const body=byId('selection-content');body.replaceChildren();
    for(const p of row.positions){const n=make('div');n.append(make('strong',positionText(p)),make('p',label(p.native_key[0])+' · '+(p.common_odds?.american||'—')+' American'),make('small','Native identity: '+p.native_key.join(' / ')));body.append(n);}
    const detail=make('p',title(row)+' · '+label(row.market)+' / '+label(row.period)+' · '+row.metric.display+'% · observed allocation '+(row.supported_capital_usd===null?'—':row.supported_capital_usd+' USD'));
    body.prepend(detail);byId('selection-identity').textContent=JSON.stringify({selection:identity,source_clocks:row.source_clocks,expires_at:row.expires_at,metric_basis:row.metric_basis,conditioning:row.conditioning},null,2);
  }
  function createRow(id) {
    const n=make('article',undefined,'scanner-row');n.dataset.rowId=id;
    const event=make('div',undefined,'event'),heading=make('h2'),context=make('small');event.append(heading,context);
    const legs=[0,1].map(()=>{const n=make('div',undefined,'leg'),text=make('div'),name=make('strong'),venue=make('small'),price=make('span',undefined,'american');text.append(name,venue);n.append(text,price);return {n,name,venue,price};});
    const metric=make('div'),edge=make('div',undefined,'edge'),basis=make('small');metric.append(edge,basis);
    const size=make('div',undefined,'size'),state=make('div',undefined,'row-state'),button=make('button','Select');button.type='button';
    button.onclick=()=>{const row=page?.rows.find(r=>r.id===id);if(row)select(row);};
    n.onpointerenter=()=>{hover=id;};n.onpointerleave=()=>{hover=null;queueMicrotask(()=>{if(!interactionActive()){held=false;render();}});};
    n.append(event,...legs.map(l=>l.n),metric,size,state,button);const entry={n,heading,context,legs,edge,basis,size,state,button};nodes.set(id,entry);return entry;
  }
  function interactionActive(){return hover!==null||!!document.activeElement?.closest('.scanner-row');}
  function render() {
    if(!page)return;
    const started=performance.now(),matches=page.rows.filter(r=>JSON.stringify([r.event_context,r.positions,r.occurrence_id]).toLowerCase().includes(searchDraft.toLowerCase()));
    const target=matches.map(r=>r.id),activeId=document.activeElement?.closest('.scanner-row')?.dataset.rowId;
    const orderChanged=shown.filter(id=>target.includes(id)).join()!==target.filter(id=>shown.includes(id)).join();
    const protectedRemoval=new Set([activeId,hover].filter(id=>id&&!target.includes(id)&&nodes.has(id)));
    if((orderChanged||protectedRemoval.size)&&interactionActive())held=true;
    if(held){shown=[...shown.filter(id=>target.includes(id)||protectedRemoval.has(id)),...target.filter(id=>!shown.includes(id))];}
    else shown=target;
    byId('order').hidden=!held;byId('order').textContent='Ranking updated · apply order';
    byId('count').textContent=page.total_matching+' matching '+(filters.category==='covered_outcome_arb'?'arb candidates':filters.category==='conditional_hedge'?'conditional hedges':'EV research rows')+(searchDraft?' · '+matches.length+' found on this page':'')+(held?' · display order held':'');
    const parent=byId('results');
    for(const id of shown) {
      const entry=nodes.get(id)||createRow(id),r=page.rows.find(r=>r.id===id),rank=page.ranked_ids.indexOf(id);
      if(!r){entry.n.dataset.authority='previous';entry.state.textContent='Withdrawn from this page';entry.button.disabled=false;entry.button.setAttribute('aria-disabled','true');entry.button.textContent='Removed';entry.edge.textContent='—';continue;}
      entry.n.dataset.authority=authority(r)?'current':'previous';entry.n.dataset.category=r.category;entry.n.dataset.dependencyRevision=r.dependency_revision;entry.n.dataset.economicRevision=r.economic_revision;entry.n.dataset.pairId=r.pair_id;entry.n.setAttribute('aria-label',title(r));entry.n.dataset.selected=String(selected?.identity.row_id===id);entry.button.setAttribute('aria-controls','scanner-selection');entry.button.setAttribute('aria-expanded',String(selected?.identity.row_id===id));
      entry.heading.textContent='#'+(page.offset+rank+1)+'  '+title(r);
      entry.context.textContent=[r.league,label(r.market),label(r.period)].join(' · ');
      r.positions.forEach((p,i)=>{const l=entry.legs[i];l.name.textContent=positionText(p);l.venue.textContent=label(p.native_key[0]);l.price.textContent=p.common_odds?.supported?p.common_odds.american:'—';l.price.setAttribute('aria-label',p.common_odds?.supported?p.common_odds.american+' American odds':'American odds unavailable');});
      entry.edge.textContent=(r.metric?.display??'—')+(r.metric?.display?'%':'');
      entry.basis.textContent=r.category==='covered_outcome_arb'?'Complete minimum':r.category==='conditional_hedge'?'Decisive only · can lose':r.current?'Expected return':'Last-known EV';
      entry.size.textContent=r.supported_capital_usd===null?'—':r.supported_capital_usd+' USD';entry.size.setAttribute('aria-label','Observed supported allocation '+entry.size.textContent);
      entry.state.textContent=status(r)+(arrivals.cue(id)?' · '+arrivals.cue(id):'')+(held&&shown.indexOf(id)!==rank?' · order held':'');entry.state.classList.toggle('held',held&&shown.indexOf(id)!==rank);entry.button.disabled=false;entry.button.removeAttribute('aria-disabled');entry.button.textContent='Select';entry.button.setAttribute('aria-label','Select '+title(r)+' · '+r.positions.map(positionText).join(' / '));
    }
    for(const [id,entry] of nodes)if(!shown.includes(id)){entry.n.remove();nodes.delete(id);}
    if(shown.length){empty?.remove();empty=null;shown.forEach((id,i)=>{const n=nodes.get(id).n;if(parent.children[i]!==n)parent.insertBefore(n,parent.children[i]||null);});}
    else{if(!empty){empty=make('p',undefined,'scanner-empty');parent.append(empty);}empty.textContent=searchDraft?'No matches on this page. Search does not cover other pages.':healthMessage();}
    byId('prev').disabled=page.offset===0;byId('next').disabled=page.next_offset===null;
    byId('page').textContent=page.total_matching?'Rows '+(page.offset+1)+'–'+(page.offset+page.rows.length)+' of '+page.total_matching:'No result rows';
    if(selected)renderSelected();
    if(filterStart!==null){painted('filter-local',filterStart,{generation:lastGeneration,rows:page.rows.length,waitingMs:0});filterStart=null;}
    return performance.now()-started;
  }
  function healthMessage() {
    if(incompatible)return 'Update required to verify this scanner.';if(stopped||page?.coverage.state==='stopped')return 'Collection stopped. Previous comparisons have no current authority.';if(!verified)return 'Current comparison unavailable. Previous prices have unverified freshness.';
    const c=page.coverage;if(Date.now()>=Date.parse(page.expires_at))return 'Original inputs expired. Waiting for a current comparison.';
    if(page.unsupported_filters.length)return 'Selected scope is unavailable or unsupported.';
    if(c.no_qualifying_opportunities&&c.complete)return 'Checked selected markets · no qualifying opportunities.';
    return ({evaluated_positive:'Selected markets checked',evaluated_zero:'Checked selected markets · no qualifying opportunities.',not_evaluated:'Still evaluating the selected markets…',partial:'Partially evaluated · coverage is incomplete',unavailable:'Comparable markets unavailable',unsupported:'Selected scope is unsupported',stopped:'Collection stopped'})[c.state]||'Coverage is incomplete';
  }
  function updateHealth() {
    byId('health').hidden=false;
    if(!page){byId('health').textContent=incompatible?'Update required to verify this scanner.':'Current comparison unavailable. Waiting for a supported response.';return;}const message=healthMessage();if(byId('health').textContent!==message)byId('health').textContent=message;const c=page.coverage;
    byId('health').hidden=message==='Selected markets checked' && c.complete && !c.errors.length;
    byId('coverage-detail').textContent=c.evaluated_pairs+' of '+c.compatible_pairs+' compatible pairs evaluated in the selected scope. '+(c.qualifying_pairs===null?'Qualifying count not established. ':c.qualifying_pairs+' qualifying pairs. ')+(c.complete?'Evaluation complete.':'Incomplete evaluation; zero results do not establish checked-zero.')+(c.errors.length?' A shared evaluation problem affects this scope. See Admin.':'');
  }
  function capabilityOptions() {
    const signature=JSON.stringify(page.filter_options);if(signature===optionsSignature)return;optionsSignature=signature;
    for(const k of ['sports','leagues','markets','periods']){const n=byId(k);n.replaceChildren(new Option('All supported',''),...page.filter_options[k].map(v=>new Option(label(v),v)));n.value=filters[k][0]||'';}
    const venues=byId('venue-options');venues.replaceChildren();
    for(const v of page.filter_options.venues){const l=make('label'),input=make('input');input.type='checkbox';input.value=v;input.checked=!filters.venues.length||filters.venues.includes(v);input.name='venue';input.onchange=changeFilters;l.append(input,make('span',label(v)));venues.append(l);}
  }
  function restoreForm(){
    const advanced=[];
    if(filters.minimum_edge!==null)advanced.push('edge ≥ '+filters.minimum_edge+'%');
    if(filters.minimum_size!==null)advanced.push('size ≥ $'+filters.minimum_size);
    if(filters.venues.length)advanced.push(filters.venues.map(label).join(', '));
    byId('advanced-label').textContent='Size & sources'+(advanced.length?' · '+advanced.join(' · '):'');
    byId('category').value=filters.category;for(const k of ['minimum_edge','minimum_size'])if(document.activeElement!==byId(k))byId(k).value=filters[k]||'';for(const k of ['sports','leagues','markets','periods'])if(byId(k).options.length>1)byId(k).value=filters[k][0]||'';}
  function changeFilters(event) {
    const next=scannerDefaults();next.category=byId('category').value;
    for(const k of ['sports','leagues','markets','periods'])next[k]=byId(k).value?[byId(k).value]:[];
    const venueInputs=[...byId('venue-options').querySelectorAll('input')],checked=venueInputs.filter(n=>n.checked).map(n=>n.value).sort();
    // Empty server venue filter means all venues. Use a supported one-leg set for
    // no eligible pair when none are checked; never silently broaden selection.
    if(!checked.length&&venueInputs.length){if(event?.target?.name==='venue')event.target.checked=true;byId('warning').textContent='Select at least one execution venue. Both legs must be eligible.';byId('warning').hidden=false;return;}
    next.venues=checked.length===venueInputs.length?[]:checked;
    for(const k of ['minimum_edge','minimum_size']){const value=byId(k).value.trim();if(value&&!/^\d{1,8}(\.\d{1,6})?$/.test(value)){byId('warning').textContent='Use a nonnegative decimal for the minimum filter.';byId('warning').hidden=false;return;}next[k]=value||null;}
    byId('warning').hidden=true;filters=next;restoreForm();try{localStorage.setItem(scannerPreferenceKey,JSON.stringify(filters));}catch{}
    arrivals.reset();summaries.reset();verified=false;held=false;hover=null;render();updateHealth();serverFilterStart=performance.now();reader.configure(filters);
  }
  const reader=new ScannerReader({assetRevision:SCANNER_ASSET_REVISION,onPage:(value,timing)=>{
    const received=performance.now();const reset=page&&(page.server_id!==value.server_id||page.epoch!==value.epoch);
    if(reset){held=false;hover=null;}
    if(serverFilterStart!==null){painted('filter-server',timing.available,{waitingMs:timing.available-serverFilterStart,retrievalMs:timing.retrievalMs,rows:value.rows.length});serverFilterStart=null;}
    page=value;lastGeneration=timing.generation;verified=true;stopped=value.coverage.state==='stopped';ticket.observe(value);summaries.observe(filters,value);
    capabilityOptions();restoreForm();render();updateHealth();
    byId('stop').disabled=stopped;byId('stop').textContent=stopped?'Collection stopped':'Stop collection';
    const bindings=value.rows.map(r=>({row_id:r.id,event_id:r.occurrence_id,pair_id:r.pair_id,dependency_revision:r.dependency_revision,economic_revision:r.economic_revision,native_keys:r.positions.map(p=>p.native_key),source_clocks:r.source_clocks,calculation_started_at:r.calculation_started_at,evaluated_at:r.evaluated_at,calculation_ms:r.calculation_ms}));
    painted('revision',timing.available,{revision:value.publication_revision,server_id:value.server_id,epoch:value.epoch,mode:value.mode,rows:value.rows.length,bytes:timing.bytes,retrievalMs:timing.retrievalMs,acceptedAt:received,domAppliedAt:performance.now(),requestStartedAt:timing.started,bodyAvailableAt:timing.available,causal:value.causal,bindings});
  },onCycle:async()=>{void summaries.read();await ticket.tick();if(page&&!stopped&&!incompatible)await arrivals.read(filters,page);},onState:state=>{verified=false;ticket.deny('Scanner connection unverified. Check the exact ticket.');arrivals.reset();summaries.reset('Observation history interrupted · coverage is unknown.');if(state==='resync'){held=false;byId('warning').hidden=false;byId('warning').textContent='Market revision changed. Restarting this page coherently.';}render();updateHealth();},onCompatibility:()=>{ticket.cancel();ticket.deny('Update required. Previous allocations cannot be used.');arrivals.reset();summaries.reset('Update required to read observation summaries.');incompatible=true;verified=false;byId('update').hidden=false;render();updateHealth();}});
  restoreForm();
  byId('filters').onsubmit=e=>e.preventDefault();
  for(const k of ['category','sports','leagues','markets','periods','minimum_edge','minimum_size'])byId(k).onchange=changeFilters;
  byId('filters').onreset=e=>{e.preventDefault();filters=scannerDefaults();optionsSignature='';if(page)capabilityOptions();restoreForm();byId('warning').hidden=true;try{localStorage.removeItem(scannerPreferenceKey);}catch{}arrivals.reset();summaries.reset();verified=false;render();reader.configure(filters);};
  byId('search').oninput=()=>{filterStart=performance.now();searchDraft=byId('search').value;try{sessionStorage.setItem('predict-scanner-search',searchDraft);}catch{}render();};
  byId('order').onclick=()=>{hover=null;document.activeElement?.blur();held=false;render();byId('order').hidden=true;};
  byId('results').addEventListener('focusout',()=>queueMicrotask(()=>{if(!interactionActive()){held=false;render();}}));
  byId('close').onclick=()=>{const id=selected?.identity.row_id;selected=null;byId('selection').hidden=true;document.dispatchEvent(new CustomEvent('predict:scanner-close'));render();(nodes.get(id)?.button||byId('results')).focus({preventScroll:true});};
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&selected){e.preventDefault();byId('close').click();}});
  byId('prev').onclick=()=>{verified=false;reader.configure(filters,Math.max(0,page.offset-100));};
  byId('next').onclick=()=>{if(page.next_offset!==null){verified=false;reader.configure(filters,page.next_offset);}};
  byId('reload').onclick=()=>location.reload();
  byId('stop').onclick=async()=>{ticket.cancel();ticket.deny('Collection stopped. Previous allocations cannot be used.');arrivals.reset();summaries.reset('Collection stopped · observation history is censored.');stopped=true;verified=false;reader.close();render();updateHealth();byId('stop').disabled=true;byId('stop').textContent='Stopping…';try{const r=await fetch('/api/admin/current',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'stop'})});if(!r.ok)throw Error();byId('stop').textContent='Collection stopped';}catch{byId('stop').textContent='Stop unconfirmed';byId('warning').hidden=false;byId('warning').textContent='Stop could not be confirmed. Open Admin to check collection.';}};
  let expiry=setInterval(()=>{if(page){ticket.sweep();render();updateHealth();}},250);
  addEventListener('pagehide',()=>{ticket.cancel();ticket.deny('Page inactive. Check the exact ticket on return.');arrivals.reset();summaries.reset();reader.close();clearInterval(expiry);});
  // Bounded delivery/render diagnostics: observations only, no API or financial authority.
  Object.defineProperty(window,'predictScannerObservations',{value:()=>({timings:timings.map(v=>v.entry),retainedBytes:timingBytes,emittedSamples,droppedSamples,droppedBytes,diagnosticBounds:{samples:256,bytes:2097152},bounds:SCANNER_BOUNDS,identity:page?{server_id:page.server_id,epoch:page.epoch,publication_revision:page.publication_revision,query_id:page.query_id,offset:page.offset}:null,selection:selected?.identity||null,activeReaders:reader.controller?1:0})});
  addEventListener('pageshow',event=>{if(event.persisted){ticket.deny('Returned to page. Check the exact ticket.');arrivals.reset();expiry=setInterval(()=>{if(page){ticket.sweep();render();updateHealth();}},250);verified=false;render();updateHealth();reader.closed=false;reader.page=null;reader.configure(filters);}});
  if(document.querySelector('meta[name="predict-scanner-asset"]').content!==SCANNER_ASSET_REVISION){reader.incompatible=true;incompatible=true;byId('update').hidden=false;}
  reader.configure(filters);
}
bootScanner();

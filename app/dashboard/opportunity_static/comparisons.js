'use strict';
const PriceComparisons=(()=>{
 const seen=new Set(),markets=new Set(),samples=[];
 const observer={ready_at:typeof performance==='undefined'?null:performance.timeOrigin+performance.now(),hidden_calls:0,missing_timing:0,dropped_samples:0};
 const implied=x=>(Number(x)*100).toFixed(4)+'%';
 const age=x=>x==null?'unknown':Math.max(0,Math.floor(Number(x)))+'s';
 function displayedPrice(l,x,esc){
  if(l.ask==null)return 'Price unavailable';
  if(x.manual_raw)return l.venue==='novig'||l.venue==='prophetx'?'Decimal odds '+esc(l.decimal_odds)+' · raw implied '+esc(implied(l.ask)):'$'+esc(l.ask);
  if(x.cross_source)return l.price_basis==='native_contract_price'?'$'+esc(l.ask)+' per $1 normal-win claim':'Decimal odds '+esc(l.decimal_odds)+' · raw implied '+esc(implied(l.ask));
  return x.aggregated?'Decimal odds '+esc(l.decimal_odds)+' · raw implied '+esc(implied(l.ask)):'$'+esc(l.ask);
 }
 function rules(x,esc){
  const a=x.rule_analysis;if(!a)return '';
  return '<p><strong>Rule and identity research</strong><br>'+esc(a.version)+' · '+esc(a.status)+'<br>'+esc(a.basis||a.summary)+'</p>'+Object.entries(a.books||{}).map(([book,b])=>'<p>'+esc(book)+': provider-reported event '+esc(b.crosswalk.book_event_id)+' · outcome '+esc(b.crosswalk.book_outcome_id)+' · market ID '+esc(b.crosswalk.book_market_id??'not supplied')+'<br>Native contract and effective rules not verified.</p>').join('')+'<details><summary>Sources, applicability and missing facts</summary><pre>'+esc(JSON.stringify(a,null,2))+'</pre></details>';
 }
 function render(r,esc,link){
  return (r.comparisons||[]).map(x=>`<tr class="opportunity-card comparison-card" data-id="${esc(x.id)}"><td><strong>${esc(x.outcome)}</strong><small>${esc(BoardView.title(x.game_title).name)}</small><small>${esc(x.identity.competition)} · ${esc(BoardView.words(x.identity.family||'moneyline'))} · ${esc(BoardView.words(x.identity.period))}${x.identity.line==null?'':' · line '+esc(x.identity.line)}</small><small>${esc((x.mode==='synthetic'?'Simulation · ':'')+(x.historical?'Saved observations':'Current observations'))}</small></td><td colspan="2"><div class="price-pair">${x.legs.map(l=>`<section aria-label="${esc(l.label)} price"><strong>${esc(l.label)}</strong><span class="buy-price">${displayedPrice(l,x,esc)}</span><small>${l.top_size==null?'Quantity unknown':esc(l.top_size)+' contracts at this price'}</small><small>${x.historical?'At saved time: ':''}${esc(BoardView.sourceState(l.connection))} · ${esc(BoardView.sourceState(l.status))}<br>Market ${esc(BoardView.sourceState(l.market_state))}</small><small>Receipt age ${esc(age(l.age_seconds))} · source age ${esc(age(l.source_age_seconds))}</small>${l.url?`${BoardView.externalLink(l.url,'Open '+l.label+' market ↗',esc)}`:'<small>'+ (x.mode==='synthetic'?'Simulation · no market link':'No verified market link')+'</small>'}</section>`).join('')}</div><p>${x.lower_raw?esc(x.lower_raw)+(x.lower_raw==='Equal'?' raw prices':(x.cross_source?' lower displayed value':x.aggregated?' lower raw implied probability':' lower raw buy price'))+' · '+(x.cross_source?esc((Number(x.raw_difference)*100).toFixed(4))+' display-scale points':x.aggregated?esc((Number(x.raw_difference)*100).toFixed(4))+' percentage points':'$'+esc(x.raw_difference))+' difference':'Raw comparison unavailable'}</p><small>${esc(({INCOMPATIBLE:'Settlement rules differ',UNKNOWN:'Settlement not verified'})[x.settlement_status]||('Settlement '+x.settlement_status.toLowerCase()))}. Prices recorded separately; synchronized freshness unverified.</small><small>${x.entry_lower?esc(x.entry_lower)+' lower provisional entry cost':'Provisional entry-cost ranges overlap or are unavailable'} · EV unavailable without probability</small></td><td><details><summary>Details</summary><p>Details stay fixed while open. Reopen to see updates.</p>${typeof PredictDecision==='undefined'?'':PredictDecision.summary(x.decision,esc)+PredictDecision.controls(x,esc)}${x.native_raw||x.cross_source||x.manual_raw?'<p><a href="/api/calculate?download=true&amp;public_binding_version=public-contract-bindings-1&amp;session='+encodeURIComponent(x.session)+'&amp;hash='+encodeURIComponent(x.hash)+'&amp;cutoff='+encodeURIComponent(x.cutoff)+'&amp;quantity='+encodeURIComponent(x.legs[0].entry.quantity)+'">Download retained comparison</a></p>':''}${x.cross_source?'<p>'+esc(x.raw_comparison_units)+'. Shared settlement, fee units and execution remain unverified.</p>':''}${rules(x,esc)}${x.native_raw?'<p>'+esc(x.native_review?.settlement?.correspondence||'Outcome correspondence is limited to the selected native review.')+' Quantity changes and health re-emissions are not price changes.</p>':''}<p>${esc(x.settlement)}</p><p>Net comparison unavailable where material costs or settlement are unknown. Raw prices are not an arbitrage claim.</p>${x.legs.map(l=>`<p>${esc(l.label)} · ${esc(l.contract)}<br>${esc(l.depth_limit)}<br>Provisional cost for ${esc(l.entry.quantity)} contracts: ${l.entry.lower==null?'unavailable':'$'+esc(l.entry.lower)+' to $'+esc(l.entry.upper)}<br>${esc(l.entry.basis)}</p>`).join('')}<p>Receipt alignment: ${esc(x.timing.receipt_skew_seconds??'unknown')}s. ${esc(x.timing.reason)}</p>${(x.alternatives||[]).length?`<p><strong>Other native contracts for this outcome</strong><br>Distinct contracts may settle differently. Quantities are separate, not additive.</p>${x.alternatives.map(a=>`<p>${a.legs.map(l=>esc(l.label)+' · '+esc(l.contract)+' · '+(l.ask==null?'price unavailable':'$'+esc(l.ask))+' · '+esc(l.top_size??'unknown')+' contracts').join('<br>')}<br><a href="${esc(link(a))}">Inspect this alternative →</a></p>`).join('')}`:''}<pre>${esc(JSON.stringify({alternatives:x.alternatives,identity:x.identity,legs:x.legs,source_correspondence:x.source_correspondence,manual_binding:x.manual_binding,settlement:x.settlement_audit,timing:x.timing,cutoff:x.cutoff},null,2))}</pre><a data-focus-key="game-details" href="${esc(link(x))}">Game details →</a></details></td></tr>`).join('');
 }
 function measure(r){
  if(!r.live)return;
  if(document.visibilityState!=='visible'){observer.hidden_calls++;return;}
  const fresh=[];
  for(const x of r.comparisons||[])for(const l of x.legs){
   const market=r.capture+':'+l.venue+':'+l.native_identity.market_id;
   const key=market+':'+(l.application_received_at||l.received_at);
   if(!l.book_id||seen.has(key))continue;
   seen.add(key);fresh.push({...l,sample_kind:markets.has(market)?'subsequent_update':'initial_state'});markets.add(market);
  }
  while(markets.size>4096)markets.delete(markets.values().next().value);
  while(seen.size>4096)seen.delete(seen.values().next().value);
  // Double rAF brackets a browser paint opportunity; not physical display latency.
  requestAnimationFrame(()=>requestAnimationFrame(()=>{
   const visible=performance.timeOrigin+performance.now();
   for(const l of fresh){const receipt=Date.parse(l.application_received_at||l.received_at),calculated=Date.parse(r.calculated_at);
    if(!Number.isFinite(receipt)||!Number.isFinite(calculated)){observer.missing_timing++;continue;}
    samples.push({sample_kind:l.sample_kind,session:r.capture,venue:l.venue,market_id:l.native_identity.market_id,contract:l.contract,book_id:l.book_id,application_received_at:l.application_received_at||l.received_at,observer_ready_at:observer.ready_at,browser_received_at:r.browser_received_at,visible_at:visible,request_started_at:r.request_started_at,calculated_at:r.calculated_at,publication_prepared_at:r.publication_prepared_at,calculation_duration_ms:r.calculation_duration_ms,browser_receipt_to_visible_ms:r.browser_received_at==null?null:visible-r.browser_received_at,local_timing:l.local_timing,pipeline:r.book_pipeline?.[l.book_id],receipt_to_calculation_ms:calculated-receipt,calculation_to_visible_ms:visible-calculated,receipt_to_visible_ms:visible-receipt,source_to_receipt_seconds:l.source_to_receipt_seconds});
   }
   if(samples.length>2048){observer.dropped_samples+=samples.length-2048;samples.splice(0,samples.length-2048);}
  }));
 }
 return {render,measure,samples,observer};
})();

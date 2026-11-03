// The ordinary app reads one immutable result. No feed polling mutates its math.
(() => {
  const byId = id => document.getElementById(id);
  const node = (tag, text, cls) => {const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
  const num = v => {if(v==null)return null;const p=String(v).split('/');return Number(p[0])/(p.length===2?Number(p[1]):1);};
  const fmt = v => v==null?'Unavailable':num(v).toLocaleString(undefined,{maximumFractionDigits:3});
  const api='/api/comparison-snapshot';
  const view=location.pathname==='/odds'?'odds':location.pathname==='/arbs'?'arbs':'ev';
  let current=null, offset=0, busy=false, selected=null, generation=0;
  const prior=[];
  const status=message=>{byId('status').textContent=message;};
  async function request(url,body) {
    const r=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});
    const v=await r.json();if(!r.ok)throw Error(v.reason||v.error||v.message||'Request failed');return v;
  }
  function query() {
    const q=new URLSearchParams({view,offset:String(offset),limit:'25',metric:byId('sort').value});
    for(const id of ['league','venue','family','game','search'])if(byId(id).value)q.set(id,byId(id).value);
    return q;
  }
  function form(a) {
    byId('amount').value=a.amount;byId('buffer').value=String(num(a.buffer)*100);byId('benchmark').value=a.benchmark_venue;
    byId('scenario').value=a.scenario;byId('scoring').value=a.scoring||'unavailable';byId('sizing').value=a.sizing;byId('exception-probability').value=a.exception_probability||'';
    for(const v of ['kalshi','polymarket_us','novig','prophetx'])byId('fee-'+v).value=a.fees[v]??'';
  }
  function settingsValue() {
    return {amount:byId('amount').value,buffer:String(Number(byId('buffer').value)/100),benchmark_venue:byId('benchmark').value,
      scoring:byId('scoring').value,scenario:byId('scenario').value,sizing:byId('sizing').value,exception_probability:byId('exception-probability').value||null,
      fees:Object.fromEntries(['kalshi','polymarket_us','novig','prophetx'].map(v=>[v,byId('fee-'+v).value||null]))};
  }
  function fillOptions(id,items) {
    const e=byId(id),old=e.value,first=e.options[0].cloneNode(true);e.replaceChildren(first);
    for(const [value,label] of items){const o=node('option',label);o.value=value;e.append(o);}e.value=old;
  }
  function age(q) {
    const at=q.times?.source_at;
    return at?`${Date.parse(at)>Date.now()?'Source clock ahead':Math.round((Date.now()-Date.parse(at))/60000)+' min old'} · captured source: ${q.source_state}`:`Source time unknown · captured source: ${q.source_state}`;
  }
  function button(label,fn) {const e=node('button',label,'secondary');e.type='button';e.onclick=fn;return e;}
  function inspectButton(row,label='Details') {return button(label,()=>openDetails(current.id,row.id));}
  function quoteLabel(q) {const s=q.selection||{},g=current?.games?.find(g=>g.game_key===q.game_key);
    const participant=g?.participants?.find(p=>p.id===s.participant)?.name||s.label||(s.participant&&s.participant!=='combined'?'Unresolved participant':'');
    return [participant,s.predicate,s.signed_line,['YES','NO','Long','Short'].includes(q.native_side)?q.native_side:null].filter(v=>v!=null&&v!=='').join(' · ');}

  function draw(v,replace=false) {
    current=v;
    if(v.id){const url=new URL(location.href);url.searchParams.set('result_id',v.id);window.history.replaceState(null,'',url);}
    if(v.history){prior.splice(0,prior.length,...v.history.filter(h=>h.snapshot_id!==v.snapshot_id).map(h=>h.id));byId('prior-snapshot').hidden=!prior.length;}
    if(v.id)for(const link of document.querySelectorAll('a[href]')) {const u=new URL(link.href);if(['/', '/ev', '/odds', '/arbs'].includes(u.pathname)){u.searchParams.set('result_id',v.id);link.href=u.href;}}
    if(v.state==='empty') {form(v.defaults);status('No comparison snapshot yet. Capture available prices to begin.');byId('content').replaceChildren();return;}
    if(replace) {
      form(v.assumptions);
      fillOptions('game',v.games.map(g=>[g.game_key,g.title]));
      fillOptions('league',v.scope.leagues.map(x=>[x,x]));
    }
    byId('applied').textContent=`$${fmt(v.assumptions.amount)} · ${fmt(num(v.assumptions.buffer)*100)}% buffer · ${v.assumptions.benchmark_venue} · ${v.assumptions.revision.slice(0,8)}`;
    status(`Captured ${new Date(v.captured_at).toLocaleString()} · ${v.counts.observations} prices · ${v.counts.gross_numeric} gross / ${v.counts.net_numeric} assumed net · ${v.counts.unmatched} unmatched · snapshot ${v.snapshot_id.slice(0,8)}`);
    const content=byId('content');content.replaceChildren();
    const coverage=node('details',undefined,'secondary-controls');coverage.append(node('summary','Assumptions and source coverage'));
    coverage.append(node('p','Math is fixed to this capture. Source ages and live availability are separate. Gross EV conditions on decisive outcomes; assumed scenarios do not establish executable or verified returns.'));
    for(const source of ['kalshi','polymarket_us','novig','prophetx','pinnacle']) {
      const c=v.coverage?.[source],s=v.sources[source];
      const minutes=at=>Math.round((Date.parse(v.captured_at)-Date.parse(at))/60000);
      const clocks=c?.newest?` · source age at capture ${minutes(c.newest)}–${minutes(c.oldest)} min`:'';
      coverage.append(node('p',`${source} · ${c?.count||0} captured ${source==='pinnacle'?'reference prices':'prices'}${clocks}${c?.unknown_clock?' · '+c.unknown_clock+' missing source times':''}${s?' · '+s.state:''}${s?.reason?' — '+s.reason:''}`));
    }
    coverage.append(node('p',`Next 72 hours · ${v.reference_count} reference observations · ${v.issues.length} capture/matching issues. Missing inputs disable only dependent metrics.`));
    coverage.append(node('pre',JSON.stringify({assumptions:v.assumptions,issues:v.issues},null,2)));content.append(coverage);
    if(view==='odds') {
      const wrap=node('div',undefined,'odds-scroll'),table=node('table',undefined,'odds-grid');
      const head=node('tr');for(const t of ['Game / outcome','Kalshi','Polymarket US','Novig','ProphetX','Pinnacle · reference'])head.append(node('th',t));table.append(head);
      for(const group of v.rows) {
        const q=group.quotes[0],tr=node('tr');tr.append(node('th',`${q.game_title} · ${q.market.market} · ${quoteLabel(q)}${group.comparable?'':' · unmatched'}`));
        for(const venue of ['kalshi','polymarket_us','novig','prophetx']) {
          const td=node('td');const quotes=group.quotes.filter(x=>x.venue===venue);
          if(!quotes.length)td.textContent='—';
          for(const quote of quotes){td.append(inspectButton(quote,quote.common_odds?.american||'Original price'),node('small',age(quote)));}
          tr.append(td);
        }
        const ref=group.quotes.find(x=>x.reference_odds)?.reference_odds;
        tr.append(node('td',ref?.american||'—'));table.append(tr);
      }wrap.append(table);content.append(wrap);
    } else {
      for(const row of v.rows) {
        const card=node('article',undefined,'snapshot-result');card.append(node('h2',row.game_title));
        card.append(node('p',row.kind==='pair'?`${row.market.market} · ${row.venues.join(' + ')} · opposing scenarios`:`${row.venue} · ${row.market.market} · ${quoteLabel(row)} · ${row.common_odds?.american||'odds unavailable'}`));
        if(row.kind==='pair')card.append(node('p',`Assumed scenario minimum: ${fmt(row.minimum_return_percent)}${row.minimum_return_percent==null?'':'%'}`));
        else {
          card.append(node('p',`Gross decisive EV: ${fmt(row.gross_return_percent)}${row.gross_return_percent==null?'':'%'} · Assumed ${v.assumptions.scenario==='decisive_only'?'conditional ':''}net: ${fmt(row.net_return_percent)}${row.net_return_percent==null?'':'%'}`));
          card.append(node('p',`Other-instrument price difference: ${row.price_difference_cents==null?'Needs a comparable priced instrument':fmt(row.price_difference_cents)+' cents'} · ${age(row)}`));
        }
        const missing=[...(row.math?.missing||[]),...(row.probability_missing?[row.probability_missing]:[])];
        if(missing.length)card.append(node('p','Needed: '+missing.join('; '),'muted'));
        card.append(inspectButton(row));content.append(card);
      }
    }
    if(!v.rows.length)content.append(node('p','No comparisons match these filters in this snapshot.'));
    const pager=node('div',undefined,'board-controls');const previous=button('Previous',()=>read({pageOffset:Math.max(0,offset-25)}));previous.disabled=offset===0;
    const next=button('Next',()=>read({pageOffset:offset+25}));next.disabled=offset+25>=v.total;
    pager.append(previous,node('span',`${v.total?offset+1:0}–${Math.min(offset+25,v.total)} of ${v.total}`),next);content.append(pager);
  }
  async function read({replace=false, resultId=current?.id, pageOffset=0}={}) {
    if (busy) return;
    const ticket = ++generation;
    const q = query();
    q.set('offset', String(pageOffset));
    if (resultId) q.set('result_id', resultId);
    try {
      const v = await request(api+'?'+q);
      if (ticket !== generation) return;
      offset = v.offset ?? 0;
      draw(v, replace || !current);
    } catch (e) {
      if (ticket === generation) status('Read failed: '+e.message);
    }
  }
  async function operation(action) {
    if(busy)return;busy=true;++generation;byId('refresh-snapshot').disabled=true;
    for(const e of document.querySelectorAll('.selection select,.selection input,#sort,#settings button,#latest-snapshot,#prior-snapshot'))e.disabled=true;
    status(`${action==='refresh'?'Capturing available local prices':'Recalculating captured prices'}… ${current?.id?'Previous snapshot remains displayed.':''}`);
    try {
      const body={action};if(current?.id)body.expected=current.id;
      if(action==='recalculate')body.assumptions=settingsValue();
      const q=query();q.set('offset','0');
      const v=await request(api+'?'+q,body);
      offset=0;
      draw(v,true);byId('prior-snapshot').hidden=!prior.length;
    } catch(e){status(`${action==='refresh'?'Refresh':'Recalculation'} failed: ${e.message}`);}
    finally{busy=false;byId('refresh-snapshot').disabled=false;for(const e of document.querySelectorAll('.selection select,.selection input,#sort,#settings button,#latest-snapshot,#prior-snapshot'))e.disabled=false;}
  }
  async function openDetails(resultId,id) {
    selected={resultId,id};byId('details-title').textContent='Captured math and Originals';byId('detail-content').textContent='Loading exact selected inputs…';
    if(!byId('details').open)byId('details').showModal();
    try {
      const value=await request(api+'/details?'+new URLSearchParams({result_id:resultId,id}));
      if(selected?.resultId!==resultId||selected?.id!==id)return;
      const box=byId('detail-content');box.replaceChildren(node('p',`Snapshot ${value.snapshot_id} · result ${value.result_id} · captured ${new Date(value.captured_at).toLocaleString()}`));
      box.append(node('h3','Calculation'));
      if(value.row.math?.formula)box.append(node('p',value.row.math.formula));
      const math=value.row.math||{};
      const metrics=[['Probability (decisive benchmark)',value.row.probability],['Cost per normal $1 claim',value.row.cost_per_normal_claim],['Gross decisive EV (%)',value.row.gross_return_percent],['Deployed funding ($)',math.deployed_capital_usd],['Quantity per leg',math.quantity_per_leg],['Acquisition by leg ($)',math.acquisition_usd?.join(' + ')],['Upfront fees ($)',math.upfront_fees_usd?.join(' + ')],['Net expected profit before buffer ($)',math.fee_adjusted_expected_profit_usd],['Single buffer ($)',math.buffer_usd],['Buffered expected profit ($)',math.buffered_profit_usd],['Buffered scenario minimum ($)',math.scenario_minimum_usd],['Assumed net EV (%)',value.row.net_return_percent],['Opposing minimum (%)',value.row.minimum_return_percent]];
      const table=node('table');for(const [label,amount] of metrics.filter(([label])=>value.row.kind==='pair'?!['Probability (decisive benchmark)','Cost per normal $1 claim','Gross decisive EV (%)','Assumed net EV (%)'].includes(label):label!=='Opposing minimum (%)')){const tr=node('tr');tr.append(node('th',label),node('td',amount??'Unavailable'));table.append(tr);}box.append(table);
      if(value.row.kind!=='pair')box.append(node('p','Gross return = 100 × (decisive probability / normalized cost − 1). Fees and exceptional outcomes excluded from gross.'));
      if(math.missing?.length)box.append(node('p','Needed for the calculation: '+math.missing.join(', ')));
      if(math.meaning)box.append(node('p',math.meaning));
      for(const si of [value.row.snapshot_identity,...(value.row.snapshot_identities||[])].filter(Boolean)){box.append(node('h3','Snapshot identity and scope'),node('p',`Season: ${si.observed_context.season??'unknown'} · stage: ${si.observed_context.stage??'unknown'} · ${si.method} · ${si.scoring_basis}. Strict eligibility is not established.`));if(si.assumption)box.append(node('p',si.assumption));box.append(node('p',si.equality_basis));}
      if(value.row.probability_missing)box.append(node('p',value.row.probability_missing));
      const benchmark=value.row.snapshot_benchmark;
      const embedded=value.row.reference;
      if(!benchmark&&embedded?.odds&&value.row.probability!=null){
        box.append(node('h3','Captured benchmark inputs'),node('p',`${embedded.bookmaker} · proportional no-vig · decisive outcomes`));
        embedded.odds.forEach((odd,i)=>{
          const label=`Pinnacle Original ${i+1}: decimal odds ${odd}${i===embedded.selected?' · selected side':''} · source time ${embedded.source_at?.[i]||'unknown'}`;
          const witness=value.references[i];
          if(witness){const details=node('details');details.append(node('summary',label),node('pre',JSON.stringify(witness,null,2)));box.append(details);}
          else box.append(node('p',label+' · embedded quote only, separate Original unavailable'));
        });
      }
      if(benchmark){
        box.append(node('h3','Captured Pinnacle benchmark'),node('p',`Historical captured prices · proportional no-vig · ${benchmark.conditioning}. Source age at capture: ${benchmark.age_seconds} seconds. Current or executable eligibility is not established.`));
        for(const [i,id] of benchmark.ids.entries()){
          const ref=value.references.find(r=>r.id===id);
          const original=node('details');original.append(node('summary',`Pinnacle Original ${i+1}: decimal odds ${benchmark.odds[i]}${i===benchmark.selected?' · selected side':''}`),node('pre',JSON.stringify(ref??{id,reason:'Original unavailable'},null,2)));box.append(original);
        }
      }
      const exact=node('details');exact.append(node('summary','Exact intermediate values and assumption revision'),node('pre',JSON.stringify({result:value.row,assumptions:value.assumptions,benchmark_diagnostics:value.benchmark_diagnostics},null,2)));box.append(exact);
      const originals=node('details');originals.append(node('summary','Exact Originals, reference prices and source clocks'),node('pre',JSON.stringify({originals:value.originals,references:value.references},null,2)));box.append(originals);
    }catch(e){if(selected?.resultId===resultId && selected?.id===id)byId('detail-content').textContent=e.message;}
  }
  byId('title').textContent=view==='odds'?'Captured odds':view==='arbs'?'Opposing-outcome scenarios':'Ranked comparisons';
  byId('sort-setting').hidden=view==='odds';
  byId('sort').replaceChildren();
  for(const [value,label] of view==='arbs'?[['minimum_return_percent','Scenario minimum %']]:[['gross_return_percent','Gross decisive EV %'],['net_return_percent','Assumed net EV %'],['price_difference_cents','Price difference (cents)']]){const o=node('option',label);o.value=value;byId('sort').append(o);}
  byId('period').closest('label').hidden=true;
  fillOptions('family',[['winner','Winner'],['spread','Spread'],['total','Total']]);
  fillOptions('venue',['kalshi','polymarket_us','novig','prophetx'].map(x=>[x,x]));
  byId('settings').onsubmit=e=>{e.preventDefault();operation('recalculate');};
  byId('refresh-snapshot').onclick=()=>operation('refresh');
  byId('restore').hidden=true;
  byId('prior-snapshot').onclick=()=>prior.length && read({replace:true,resultId:prior[0]});
  byId('details').onclose=()=>{selected=null;};
  byId('close-details').onclick=()=>byId('details').close();
  for(const id of ['league','venue','family','game','sort'])byId(id).onchange=()=>read();
  byId('search').onchange=()=>read();
  byId('stop').onclick=async()=>{try{await request('/api/admin/current',{action:'stop'});status('Collection stopped. Captured mathematics remains unchanged.');}catch(e){status(e.message);}};
  byId('latest-snapshot').onclick=()=>read({replace:true,resultId:null});
  const requested=new URLSearchParams(location.search).get('result_id');
  byId('refresh-snapshot').disabled=true;
  read({replace:true,resultId:requested}).then(()=>{
    if(!current) return;
    // Preserve the earlier Details-only browser settings as editable inputs.
    // They become snapshot-wide only after the user presses Recalculate.
    try {const saved=JSON.parse(sessionStorage.getItem('predict-board-settings'));if(saved&&!sessionStorage.getItem('predict-snapshot-settings-migrated')) {
      if(saved.amount)byId('amount').value=saved.amount;if(saved.buffer)byId('buffer').value=String(num(saved.buffer)*100);if(saved.benchmark_venue)byId('benchmark').value=saved.benchmark_venue;
      sessionStorage.setItem('predict-snapshot-settings-migrated','1');
    }}catch{}
  }).catch(e=>status('Snapshot read failed: '+e.message)).finally(()=>{byId('refresh-snapshot').disabled=false;});
})();

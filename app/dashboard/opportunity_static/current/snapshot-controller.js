// One immutable comparison revision. Browsing never dispatches provider work.
(() => {
  const {el,num,fmt,name,link,button}=UI,byId=id=>document.getElementById(id),api='/api/comparison-snapshot';
  const initial=new URLSearchParams(location.search),admin=location.pathname==='/admin',section=initial.get('section')||'overview';
  const view=location.pathname==='/odds'?'odds':location.pathname==='/arbs'?'arbs':'ev';
  let liveMode=!initial.get('result_id'), liveCursor=null, following=false;
  let current=null,offset=Number(initial.get('offset')||0),busy=false,generation=0,selection=initial.get('selection'),league=initial.get('league')||'',detailGeneration=0,selectionInitialized=false;
  const status=t=>byId('status').textContent=t,prior=[];
  const filters=['venue','family','game','search'];
  async function request(url,body){const r=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const v=await r.json();if(!r.ok)throw Error(v.reason||v.error||'Request failed');return v;}
  function query(){const q=new URLSearchParams({view,group:'outcome',offset:String(offset),limit:'25',metric:byId('sort').value});if(league)q.set('league',league);for(const id of filters)if(byId(id).value||(id==='game'&&!current&&initial.get(id)))q.set(id,byId(id).value||initial.get(id));return q;}
  function saveURL(){const u=new URL(location.href),q=query();for(const id of ['league',...filters,'offset','metric']){q.get(id)?u.searchParams.set(id,q.get(id)):u.searchParams.delete(id);}if(current?.id&&!liveMode)u.searchParams.set('result_id',current.id);else u.searchParams.delete('result_id');if(selection)u.searchParams.set('selection',selection);else u.searchParams.delete('selection');history.replaceState(history.state,'',u);UI.carry(liveMode?null:current?.id);}
  function contextKey(){const u=new URL(location.href);u.searchParams.delete('result_id');u.searchParams.delete('notice');u.searchParams.sort();return 'predict-context:'+u.pathname+u.search;}
  function remember(id){if(id){selection=id;saveURL();}const state={scroll:scrollY,focus:selection};history.replaceState(state,'',location.href);try{sessionStorage.setItem(contextKey(),JSON.stringify(state));}catch{}}
  function originURL(row){const u=new URL(location.href);u.searchParams.set('result_id',current.id);u.searchParams.set('selection',row.id);return u.pathname+u.search;}
  function gameURL(row){const u=new URL('/odds',location.origin);u.searchParams.set('result_id',current.id);u.searchParams.set('game',row.game_key);u.searchParams.set('selection',row.id);u.searchParams.set('selected_metric',byId('sort').value);u.searchParams.set('family',row.market.market);u.searchParams.set('back',originURL(row));return u.pathname+u.search;}
  function inspectURL(row,metric=initial.get('selected_metric')||byId('sort').value){const q=new URLSearchParams({section:'inspection',result_id:current.id,selection:row.id,selected_metric:metric,back:originURL(row)});return '/admin?'+q;}
  function releaseToken(token){fetch('/api/comparison-current/lease?'+new URLSearchParams({lease_id:token}),{method:'DELETE',headers:{'Content-Type':'application/json'},keepalive:true}).then(r=>{if(!r.ok)throw Error('Lease release refused');}).catch(()=>status('Evidence release unavailable; its bounded lease will expire automatically.'));}
  const inspection=SnapshotLive.create({request,release:releaseToken,onChange:renderInspection,onError:message=>{status(message);selection=inspection.state.pinned?.row.id||null;saveURL();}});
  let panelKey=null,opener=null;
  function renderInspection({pinned,notice,opening,error}){
    const key=JSON.stringify([pinned?.lease?.lease_id,notice&&[notice.state,notice.old,notice.latest,notice.can_adopt],!!opening,error]);if(key===panelKey)return;panelKey=key;
    let panel=byId('math-inspection');
    if(!pinned&&!opening&&!error){panel?.remove();return;}
    const active=document.activeElement?.id,scroll=panel?.scrollTop||0,openDetails=[...(panel?.querySelectorAll('details[open]')||[])].map(e=>e.querySelector('summary')?.textContent);
    if(!panel){panel=el('dialog');panel.id='math-inspection';panel.setAttribute('aria-label','Math & fees');panel.className='math-drawer';document.body.append(panel);}
    panel.replaceChildren();
    const close=button('Close',()=>closeInspection());close.id='close-inspection';const head=el('header',null,'math-head');head.append(el('h2','Math & fees'),close);panel.append(head);
    if(opening)panel.append(el('p','Retaining the exact displayed inputs…'));
    if(error){const message=el('p',error);message.setAttribute('role','alert');panel.append(message);}
    if(pinned){
      const {row,result,metric,details}=pinned;
      panel.dataset.priceRevision=row.price_revision||'';panel.dataset.economicRevision=row.economic_revision||'';
      panel.dataset.evidenceResultId=details.evidence_result_id;
      const inspect='/admin?'+new URLSearchParams({section:'inspection',result_id:pinned.lease.result_id,selection:row.id,selected_metric:metric,back:location.pathname+location.search});
      const sourceLabel=el('label','Source','math-source'),sources=el('select');sources.id='inspection-source';
      const group=result.rows?.find(g=>(g.quotes||[g]).some(q=>q.id===row.id));
      const choices=group?.quotes||[row];
      for(const q of choices){const o=el('option',name(q.venue||'Both sides')+(choices.filter(v=>v.venue===q.venue).length>1?' · '+q.id.slice(0,8):''));o.value=q.id;sources.append(o);}sources.value=row.id;sources.disabled=!!opening;
      sources.onchange=()=>{const latest=current?.rows?.flatMap(g=>g.quotes||[g]).find(q=>q.id===sources.value);const q=latest||choices.find(q=>q.id===sources.value);if(q)openInspection(q,latest?current:result,metric);};sourceLabel.append(sources);panel.append(sourceLabel);
      panel.append(el('p','Pinned inputs · list updates independently','math-pin'));
      if(notice){
        const box=el('section');box.id='selection-update';box.setAttribute('aria-live','polite');
        box.append(el('strong',notice.state==='removed'?'Selected offer removed':notice.state==='unavailable'?'Selected offer unavailable':'New prices available'));
        box.append(SnapshotDrawer.changes(notice));
        const facts=el('details');facts.append(el('summary','Exact old / latest changes'),el('pre',JSON.stringify(notice,null,2)));box.append(facts);
        const adopt=button('Use latest prices',()=>inspection.adopt());adopt.id='adopt-selection';adopt.disabled=!notice.can_adopt||!!opening;box.append(adopt);panel.append(box);
      }
      panel.append(SnapshotDrawer.content(pinned,inspect));
    }
    const first=!panel.open;if(first){if(matchMedia('(max-width:1099px)').matches){panel.showModal();panel.setAttribute('aria-modal','true');}else panel.show();}
    for(const d of panel.querySelectorAll('details'))if(openDetails.includes(d.querySelector('summary')?.textContent))d.open=true;
    panel.scrollTop=scroll;
    if(active&&panel.querySelector('#'+CSS.escape(active)))byId(active).focus({preventScroll:true});else if(first)close.focus({preventScroll:true});
    for(const b of document.querySelectorAll('.p-why-button'))b.setAttribute('aria-expanded',String(b.closest('[data-row]')?.dataset.row===pinned?.row.id));
  }
  function closeInspection(){const id=inspection.state.pinned?.row.id;inspection.close();for(const b of document.querySelectorAll('.p-why-button'))b.setAttribute('aria-expanded','false');selection=null;saveURL();const target=[...document.querySelectorAll('[data-row]')].find(e=>e.dataset.row===id)?.querySelector('.p-why-button');(target||(opener?.isConnected?opener:null)||byId('content')).focus({preventScroll:true});}
  function selected(id){if(!id){closeInspection();return;}const row=current?.rows.flatMap(g=>g.quotes||[g]).find(r=>r.id===id);if(row)openInspection(row,current,current.metric);}
  function openInspection(row,result,metric){selectionInitialized=true;if(!document.activeElement?.closest('#math-inspection'))opener=document.activeElement;selection=row.id;saveURL();inspection.open(row,result,metric).then(ok=>{if(ok&&liveMode)inspection.check().catch(()=>status('Latest selection temporarily unavailable; pinned inputs retained.'));});}
  window.addEventListener('pagehide',()=>inspection.close());
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&byId('math-inspection')){e.preventDefault();closeInspection();}});
  setInterval(()=>{if(!document.hidden)inspection.renew();},30*60*1000);
  function settingsForm(a){byId('amount').value=a.amount;byId('buffer').value=String(num(a.buffer)*100);byId('benchmark').value=a.benchmark_venue;for(const k of ['scenario','scoring','sizing'])byId(k).value=a[k]||'unavailable';byId('exception-probability').value=a.exception_probability??'';for(const v of ['kalshi','polymarket_us','novig','prophetx'])byId('fee-'+v).value=a.fees[v]??'';byId('applied').textContent=`$${fmt(a.amount)} · ${fmt(num(a.buffer)*100)}% buffer · ${name(a.benchmark_venue)}`;}
  function settingsValue(){return {amount:byId('amount').value,buffer:String(Number(byId('buffer').value)/100),benchmark_venue:byId('benchmark').value,scenario:byId('scenario').value,scoring:byId('scoring').value,sizing:byId('sizing').value,exception_probability:byId('exception-probability').value||null,fees:Object.fromEntries(['kalshi','polymarket_us','novig','prophetx'].map(v=>[v,byId('fee-'+v).value||null]))};}
  function options(id,items){const e=byId(id),value=e.value||initial.get(id);e.replaceChildren(e.options[0]);for(const [v,label] of items){const o=el('option',label);o.value=v;e.append(o);}e.value=value||'';}
  function restoreContext(){let saved=history.state;try{saved=saved||JSON.parse(sessionStorage.getItem(contextKey()));}catch{}if(saved){requestAnimationFrame(()=>{scrollTo(0,saved.scroll);const target=[...document.querySelectorAll('[data-row]')].find(e=>e.dataset.row===saved.focus)?.querySelector('a');target?.focus({preventScroll:true});});}}
  function backTarget(){
    const url=UI.localURL(initial.get('back'));
    if(url){
      if(current?.id)url.searchParams.set('result_id',current.id);
      return url.pathname+url.search;
    }
    return '/?result_id='+encodeURIComponent(current?.id||'');
  }
  function draw(v,replace=false){
    current=v;document.body.dataset.publicationGeneration=String(v.generation||'');document.body.dataset.publishedAt=v.publication?.published_at||'';if(v.state==='initializing'){status('Synchronizing sources and preparing current comparisons…');byId('content').replaceChildren(el('p','Waiting for the first source publication.','p-empty'));return;}if(v.state==='empty'){settingsForm(v.defaults);status('No comparisons available. Automatic collection will publish available inputs.');byId('content').replaceChildren();return;}
    if(replace){settingsForm(v.assumptions);options('game',v.games.map(g=>[g.game_key,g.title]));}saveURL();
    const u=new URL(backTarget(),location.origin);u.searchParams.set('result_id',v.id);byId('return-result').href=u.pathname+u.search;
    prior.splice(0,prior.length,...(v.history||[]).filter(h=>h.snapshot_id!==v.snapshot_id).map(h=>h.id));byId('prior-snapshot').hidden=!prior.length;
    const game=v.games.find(g=>g.game_key===byId('game').value),inGame=view==='odds'&&!!game;
    byId('title').textContent=admin?'Admin':inGame?game.title:view==='odds'?'Markets':'Opportunities';document.title='Predict · '+byId('title').textContent;
    byId('caption').textContent=admin?'Sources, usage and calculation settings':`${inGame?game.league+' · Full game':'Next 72 hours'} · Prices saved ${new Date(v.captured_at).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})}`;
    byId('back').hidden=!inGame&&!admin;byId('back').href=backTarget();byId('back').textContent='← Back to comparison';
    byId('markets').hidden=!inGame;byId('leagues').hidden=inGame;byId('search').hidden=inGame;byId('mode').closest('label').hidden=view==='odds';byId('sort-setting').hidden=view==='odds';
    byId('result-count').textContent=`${v.total.toLocaleString()} ${view==='arbs'?'outcome pairs':'outcomes'} · ${v.position_count.toLocaleString()} ${view==='arbs'?'combinations':'source prices'} · ${v.unranked_count??0} unranked`;
    ++detailGeneration;const content=byId('content');content.replaceChildren();
    if(admin){drawAdmin(v);saveURL();return;}
    collectionStatus(v);
    const actions={game:gameURL,inspect:inspectURL,remember,selected,openInspection,inGame};
    const list=el('div',null,'comparison-list');
    if(view!=='arbs')list.append(el('p','EV per $100 of risk · decisive outcomes · Select a source for math & fees.','compare-basis'));
    for(const row of v.rows)list.append(SnapshotViews.comparison(row,v,v.metric,actions));
    if(!v.rows.length)list.append(el('p','No results match these filters in this capture. Try another league or market.','p-empty'));content.append(list);for(const b of list.querySelectorAll('.p-why-button'))b.setAttribute('aria-expanded',String(b.closest('[data-row]')?.dataset.row===inspection.state.pinned?.row.id));
    if(selection&&!selectionInitialized&&!inspection.state.pinned&&!inspection.state.opening){selectionInitialized=true;const row=v.rows.flatMap(g=>g.quotes||[g]).find(q=>q.id===selection);if(row)openInspection(row,v,v.metric);else if(inGame)showGameSelection(v,selection);}
    const pager=el('div',null,'pager'),prev=button('Previous',()=>read({pageOffset:Math.max(0,offset-25),focusResults:true})),next=button('Next',()=>read({pageOffset:offset+25,focusResults:true}));prev.disabled=offset===0;next.disabled=offset+25>=v.total;pager.append(prev,el('span',`${v.total?offset+1:0}–${Math.min(offset+25,v.total)} of ${v.total}`),next);content.append(pager);
    for(const b of document.querySelectorAll('[data-league]'))b.setAttribute('aria-pressed',String(b.dataset.league===league));for(const b of document.querySelectorAll('[data-family]'))b.setAttribute('aria-pressed',String(b.dataset.family===byId('family').value));saveURL();
  }
  async function collectionStatus(v){
    const box=byId('price-status');if(!box||admin)return;
    if(v.publication){const p=v.publication,wasOpen=box.querySelector('details')?.open;const summary=el('summary',`${p.state[0].toUpperCase()+p.state.slice(1)} · ${p.current_prices.toLocaleString()} current prices · ${p.retained_prices.toLocaleString()} retained`),more=el('details');more.open=!!wasOpen;more.append(summary,el('p','Automatic collection. Retained prices await current evidence; individual source clocks determine freshness.'));for(const [venue,source] of Object.entries(p.sources||{}))more.append(el('p',name(venue)+': '+String(source.state||'pending').replaceAll('_',' ')));box.replaceChildren(more);return;}
    const captured=new Date(v.captured_at),age=Date.now()-captured.getTime();
    const note=el('div',age>30*60*1000?'This saved comparison is over 30 minutes old. Refresh prices to capture the newest collected inputs.':'Saved comparison. Individual source times are shown beside each price; availability can change.');
    box.replaceChildren(note);
    try{const live=await request('/api/admin/status');if(current?.id!==v.id)return;
      const running=live.dispatch_enabled&&live.data_runtime?.state==='running';
      const parts=[];for(const p of live.sources||[])for(const [venue,s] of Object.entries(p.status||{})){
        const label=s.state==='available'?'receiving':s.state==='budget_delayed'?'15-minute schedule':s.state.replaceAll('_',' ');
        const due=s.next_due_at?` · next ${new Date(s.next_due_at).toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'})}`:'';
        parts.push(`${name(venue)}: ${label}${due}`);
      }
      box.append(el('div',(running?'Collection running. ':'Collection is not active. ')+parts.join(' · ')),el('small','Collection status checked '+new Date().toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'})+'. This does not renew saved prices.'));
    }catch{if(current?.id===v.id)box.append(el('div','Collection status unavailable. Saved prices remain readable.'));}
  }
  async function showGameSelection(v,id){const ticket=++detailGeneration;try{const data=await request(api+'/details?'+new URLSearchParams({result_id:v.id,id}));if(ticket!==detailGeneration||current.id!==v.id||selection!==id)return;const box=SnapshotViews.why(data.row,v,data.row.kind==='pair'?'minimum_return_percent':initial.get('selected_metric')||'gross_return_percent',inspectURL(data.row));box.id='selected-why';byId('content').prepend(box);}catch(e){if(ticket===detailGeneration)status('Selected position unavailable: '+e.message);}}
  async function drawAdmin(v){
    if(section==='calculations')return;
    const content=byId('content');
    if(['inspection','timing'].includes(section)&&selection){content.textContent='Loading exact selected inputs…';const ticket=++detailGeneration;try{const d=await request(api+'/details?'+new URLSearchParams({result_id:v.id,id:selection}));if(ticket!==detailGeneration||current.id!==v.id)return;content.replaceChildren(SnapshotViews.inspection(d,v,initial.get('selected_metric')));}catch(e){if(ticket===detailGeneration)content.textContent='Inspection failed: '+e.message;}return;}
    content.append(el('h2',section==='timing'?'Quote timing':'Exact inspection'),el('p','Choose Why on a position, then Inspect exact inputs in Admin to see its original records and separate clocks.'));
    for(const [venue,c] of Object.entries(v.coverage||{})){const card=el('article',null,'p-market-card');card.append(el('h2',name(venue)),el('p',`${c.count} captured prices · ${c.unknown_clock} without a provider-update clock`),el('p',`Provider update range: ${c.oldest||'Unknown'} to ${c.newest||'Unknown'}`),el('p','Successful confirmation and last price change are quote-specific; provider updates alone establish neither.'));content.append(card);}
  }
  async function read({replace=false,resultId=liveMode?null:current?.id,pageOffset=0,focusResults=false,background=false}={}){
    if(busy)return;const ticket=++generation,q=query();q.set('offset',String(pageOffset));if(resultId)q.set('result_id',resultId);if(liveMode&&!resultId&&pageOffset&&liveCursor)q.set('expected_cursor',liveCursor);
    if(!background)status('Loading comparison…');try{const v=await request((liveMode&&!resultId?'/api/comparison-current':api)+'?'+q);if(ticket!==generation||liveMode&&!resultId&&current?.generation>v.generation)return;if(v.state==='page_changed'){await read({replace,resultId,pageOffset:0,focusResults,background});return;}offset=v.offset||0;liveCursor=v.cursor||liveCursor;status(initial.get('notice')==='recalculated'?'Recalculation complete. These results use the updated assumptions.':'');const y=scrollY,focused=document.activeElement,focusRow=focused?.closest('[data-row]')?.dataset.row;const drawStarted=performance.now();draw(v,replace||!current?.id);document.body.dataset.renderMs=String(Math.round(performance.now()-drawStarted));if(background){scrollTo(0,y);if(focusRow){const target=[...document.querySelectorAll('[data-row]')].find(e=>e.dataset.row===focusRow)?.querySelector('button,a');(target||byId('content')).focus({preventScroll:true});}}if(v.state==='ready'&&!performance.getEntriesByName('predict-useful').length)requestAnimationFrame(()=>{performance.mark('predict-useful');document.body.dataset.usefulMs=String(Math.round(performance.now()));});if(focusResults){byId('content').focus();byId('content').scrollIntoView({block:'start'});}}catch(e){if(ticket===generation){status('Read failed: '+e.message);const retry=button('Retry',()=>read({replace,resultId,pageOffset}));byId('status').append(' ',retry);}}
  }
  function disable(yes){for(const e of document.querySelectorAll('#refresh-snapshot,#ordinary-controls input,#ordinary-controls select,#ordinary-controls button,#settings button,#settings input,#settings select,#latest-snapshot,#prior-snapshot'))e.disabled=yes;}
  async function operation(action){if(busy)return;if(action==='refresh'&&liveMode){await read({replace:true,resultId:null});return;}if(action==='recalculate'&&current?.publication){busy=true;disable(true);try{const v=await request('/api/comparison-current/settings',{expected:current.assumptions.revision,assumptions:settingsValue()});current.assumptions=v.assumptions;settingsForm(v.assumptions);status('Settings saved. Current comparisons are recalculating automatically.');byId('return-result').href='/';}catch(e){status('Settings could not be applied: '+e.message);}finally{busy=false;disable(false);}return;}const started=performance.now();busy=true;++generation;disable(true);status(`${action==='refresh'?'Refreshing local prices':'Recalculating captured inputs'}… Previous results remain displayed.`);try{const body={action};if(current?.id)body.expected=current.id;if(action==='recalculate')body.assumptions=settingsValue();const q=query();q.set('offset','0');const v=await request(api+'?'+q,body);offset=0;draw(v,true);status(action==='refresh'?'Prices refreshed. A new saved comparison is ready.':'Recalculation complete.');if(action==='recalculate'&&admin){const target=new URL(byId('return-result').href);target.searchParams.set('notice','recalculated');location.href=target;}}catch(e){status(`${action==='refresh'?'Refresh':'Recalculation'} failed: ${e.message}. Previous results retained.`);}finally{document.body.dataset.operationMs=String(Math.round(performance.now()-started));busy=false;disable(false);}}
  options('venue',['kalshi','polymarket_us','novig','prophetx'].map(v=>[v,name(v)]));options('family',['winner','spread','total'].map(v=>[v,name(v)]));
  byId('sort').replaceChildren();for(const [value,label] of view==='arbs'?[['minimum_return_percent','Scenario minimum %']]:[['conditional_return_percent','EV after reviewed trade fees %'],['conservative_return_percent','Conservative public-fee estimate %'],['gross_return_percent','EV before fees %'],['net_return_percent','Assumed net EV %'],['price_difference_cents','Price difference ¢']]){const o=el('option',label);o.value=value;byId('sort').append(o);}if([...byId('sort').options].some(o=>o.value===initial.get('metric')))byId('sort').value=initial.get('metric');
  for(const id of filters)if(id!=='game')byId(id).value=initial.get(id)||'';
  byId('mode').value=view==='arbs'?'arbs':'ev';byId('mode').onchange=()=>{const u=new URL(location.href);u.pathname=byId('mode').value==='arbs'?'/arbs':'/';u.searchParams.delete('metric');u.searchParams.delete('offset');location.href=u;};
  for(const value of ['','NFL','NCAAF','NBA','NCAAB','MLB','NHL']){const b=button(value||'All sports',()=>{league=value;read();},'');b.dataset.league=value;b.setAttribute('aria-pressed',String(value===league));byId('leagues').append(b);}
  for(const value of ['','winner','spread','total']){const b=button(value?name(value):'All markets',()=>{byId('family').value=value;read();},'');b.dataset.family=value;byId('markets').append(b);}
  for(const id of ['venue','family','game','sort'])byId(id).onchange=()=>{read();};
  let searchTimer;byId('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{read();},200);};
  byId('restore').onclick=()=>{if(current?.defaults){settingsForm(current.defaults);status('Defaults loaded in this form. Recalculate to apply them.');}};
  byId('settings').onsubmit=e=>{e.preventDefault();operation('recalculate');};byId('refresh-snapshot').onclick=()=>operation('refresh');byId('latest-snapshot').onclick=()=>{selected(null);liveMode=true;read({replace:true,resultId:null});};byId('prior-snapshot').onclick=()=>{selection=null;liveMode=false;read({replace:true,resultId:prior[0]});};
  if(admin){byId('admin-nav').append(UI.adminNav());byId('ordinary-controls').hidden=true;byId('snapshot-tools').hidden=true;byId('refresh-snapshot').hidden=true;byId('calculation-panel').hidden=section!=='calculations';}
  document.addEventListener('click',e=>{const a=e.target.closest('a');if(a&&new URL(a.href).origin===location.origin)remember();});
  async function follow(){
    if(following)return;following=true;
    const ticket=generation;
    try{if(liveMode&&!admin&&!busy&&!document.hidden){
      const next=await request('/api/comparison-current/updates?'+new URLSearchParams({after:liveCursor||''}));
      if(ticket!==generation)return;
      if(next.changed)await read({pageOffset:offset,background:true});
      if(liveMode)await inspection.check();
    }}catch{if(liveMode)status('Live connection interrupted; reconnecting. Retained prices do not regain freshness.');}
    finally{following=false;setTimeout(follow,2000);}
  }
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&liveMode){inspection.renew();read({pageOffset:offset,background:true});}});
  if(!admin)setTimeout(follow,2000);
  if(liveMode){byId('refresh-snapshot').textContent='Show latest';byId('snapshot-tools').querySelector('span').textContent='Automatic publication · Source freshness checked independently';}
  disable(true);
  read({replace:true,resultId:initial.get('result_id'),pageOffset:offset}).then(restoreContext).finally(()=>{disable(false);if(!current?.id)byId('settings').querySelector('[type=submit]').disabled=true;});
})();

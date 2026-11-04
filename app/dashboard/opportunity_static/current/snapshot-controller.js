// One immutable comparison revision. Browsing never dispatches provider work.
(() => {
  const {el,num,fmt,name,link,button}=UI,byId=id=>document.getElementById(id),api='/api/comparison-snapshot';
  const initial=new URLSearchParams(location.search),admin=location.pathname==='/admin',section=initial.get('section')||'overview';
  const view=location.pathname==='/odds'?'odds':location.pathname==='/arbs'?'arbs':'ev';
  let current=null,offset=Number(initial.get('offset')||0),busy=false,generation=0,selection=initial.get('selection'),league=initial.get('league')||'',detailGeneration=0;
  const status=t=>byId('status').textContent=t,prior=[];
  const filters=['venue','family','game','search'];
  async function request(url,body){const r=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const v=await r.json();if(!r.ok)throw Error(v.reason||v.error||'Request failed');return v;}
  function query(){const q=new URLSearchParams({view,offset:String(offset),limit:'25',metric:byId('sort').value});if(league)q.set('league',league);for(const id of filters)if(byId(id).value||(id==='game'&&!current&&initial.get(id)))q.set(id,byId(id).value||initial.get(id));return q;}
  function saveURL(){const u=new URL(location.href),q=query();for(const id of ['league',...filters,'offset','metric']){q.get(id)?u.searchParams.set(id,q.get(id)):u.searchParams.delete(id);}if(current?.id)u.searchParams.set('result_id',current.id);if(selection)u.searchParams.set('selection',selection);else u.searchParams.delete('selection');history.replaceState(history.state,'',u);UI.carry(current?.id);}
  function contextKey(){const u=new URL(location.href);u.searchParams.delete('result_id');u.searchParams.delete('notice');u.searchParams.sort();return 'predict-context:'+u.pathname+u.search;}
  function remember(id){if(id){selection=id;saveURL();}const state={scroll:scrollY,focus:selection};history.replaceState(state,'',location.href);try{sessionStorage.setItem(contextKey(),JSON.stringify(state));}catch{}}
  function originURL(row){const u=new URL(location.href);u.searchParams.set('result_id',current.id);u.searchParams.set('selection',row.id);return u.pathname+u.search;}
  function gameURL(row){const u=new URL('/odds',location.origin);u.searchParams.set('result_id',current.id);u.searchParams.set('game',row.game_key);u.searchParams.set('selection',row.id);u.searchParams.set('selected_metric',byId('sort').value);u.searchParams.set('family',row.market.market);u.searchParams.set('back',originURL(row));return u.pathname+u.search;}
  function inspectURL(row,metric=initial.get('selected_metric')||byId('sort').value){const q=new URLSearchParams({section:'inspection',result_id:current.id,selection:row.id,selected_metric:metric,back:originURL(row)});return '/admin?'+q;}
  function selected(id){selection=id;saveURL();}
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
    current=v;if(v.state==='empty'){settingsForm(v.defaults);status('No comparison captured yet. Refresh prices to capture available local inputs.');byId('content').replaceChildren();return;}
    if(replace){settingsForm(v.assumptions);options('game',v.games.map(g=>[g.game_key,g.title]));}saveURL();
    const u=new URL(backTarget(),location.origin);u.searchParams.set('result_id',v.id);byId('return-result').href=u.pathname+u.search;
    prior.splice(0,prior.length,...(v.history||[]).filter(h=>h.snapshot_id!==v.snapshot_id).map(h=>h.id));byId('prior-snapshot').hidden=!prior.length;
    const game=v.games.find(g=>g.game_key===byId('game').value),inGame=view==='odds'&&!!game;
    byId('title').textContent=admin?'Admin':inGame?game.title:view==='odds'?'Markets':'Opportunities';document.title='Predict · '+byId('title').textContent;
    byId('caption').textContent=admin?'Sources, usage and calculation settings':`${inGame?game.league+' · Full game':'Next 72 hours'} · Prices saved ${new Date(v.captured_at).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})}`;
    byId('back').hidden=!inGame&&!admin;byId('back').href=backTarget();byId('back').textContent='← Back to comparison';
    byId('markets').hidden=!inGame;byId('leagues').hidden=inGame;byId('search').hidden=inGame;byId('mode').closest('label').hidden=view==='odds';byId('sort-setting').hidden=view==='odds';
    byId('result-count').textContent=`${v.total.toLocaleString()} ${view==='odds'?'market groups':'positions'} · ${view==='odds'?'All lines and native sides':SnapshotViews.metricLabel(v.metric,v.assumptions)+' ↓'}`;
    ++detailGeneration;const content=byId('content');content.replaceChildren();
    if(admin){drawAdmin(v);saveURL();return;}
    const actions={game:gameURL,inspect:inspectURL,remember,selected,inGame};
    const list=el('div',null,view==='odds'?'market-list':'p-result-list');
    for(const row of v.rows)list.append(view==='odds'?SnapshotViews.markets(row,v,actions):SnapshotViews.card(row,v,v.metric,actions));
    if(!v.rows.length)list.append(el('p','No results match these filters in this capture. Try another league or market.','p-empty'));content.append(list);
    if(selection){const row=v.rows.find(r=>r.id===selection);if(row&&view!=='odds'){const card=[...list.children].find(e=>e.dataset.row===row.id);card.append(SnapshotViews.why(row,v,v.metric,inspectURL(row)));card.querySelector('.p-why-button').setAttribute('aria-expanded','true');}else if(inGame)showGameSelection(v,selection);}
    const pager=el('div',null,'pager'),prev=button('Previous',()=>read({pageOffset:Math.max(0,offset-25),focusResults:true})),next=button('Next',()=>read({pageOffset:offset+25,focusResults:true}));prev.disabled=offset===0;next.disabled=offset+25>=v.total;pager.append(prev,el('span',`${v.total?offset+1:0}–${Math.min(offset+25,v.total)} of ${v.total}`),next);content.append(pager);
    for(const b of document.querySelectorAll('[data-league]'))b.setAttribute('aria-pressed',String(b.dataset.league===league));for(const b of document.querySelectorAll('[data-family]'))b.setAttribute('aria-pressed',String(b.dataset.family===byId('family').value));saveURL();
  }
  async function showGameSelection(v,id){const ticket=++detailGeneration;try{const data=await request(api+'/details?'+new URLSearchParams({result_id:v.id,id}));if(ticket!==detailGeneration||current.id!==v.id||selection!==id)return;const box=SnapshotViews.why(data.row,v,data.row.kind==='pair'?'minimum_return_percent':initial.get('selected_metric')||'gross_return_percent',inspectURL(data.row));box.id='selected-why';byId('content').prepend(box);}catch(e){if(ticket===detailGeneration)status('Selected position unavailable: '+e.message);}}
  async function drawAdmin(v){
    if(section==='calculations')return;
    const content=byId('content');
    if(['inspection','timing'].includes(section)&&selection){content.textContent='Loading exact selected inputs…';const ticket=++detailGeneration;try{const d=await request(api+'/details?'+new URLSearchParams({result_id:v.id,id:selection}));if(ticket!==detailGeneration||current.id!==v.id)return;content.replaceChildren(SnapshotViews.inspection(d,v,initial.get('selected_metric')));}catch(e){if(ticket===detailGeneration)content.textContent='Inspection failed: '+e.message;}return;}
    content.append(el('h2',section==='timing'?'Quote timing':'Exact inspection'),el('p','Choose Why on a position, then Inspect exact inputs in Admin to see its original records and separate clocks.'));
    for(const [venue,c] of Object.entries(v.coverage||{})){const card=el('article',null,'p-market-card');card.append(el('h2',name(venue)),el('p',`${c.count} captured prices · ${c.unknown_clock} without a provider-update clock`),el('p',`Provider update range: ${c.oldest||'Unknown'} to ${c.newest||'Unknown'}`),el('p','Successful confirmation and last price change are quote-specific; provider updates alone establish neither.'));content.append(card);}
  }
  async function read({replace=false,resultId=current?.id,pageOffset=0,focusResults=false}={}){
    if(busy)return;const ticket=++generation,q=query();q.set('offset',String(pageOffset));if(resultId)q.set('result_id',resultId);
    status('Loading saved comparison…');try{const v=await request(api+'?'+q);if(ticket!==generation)return;offset=v.offset||0;status(initial.get('notice')==='recalculated'?'Recalculation complete. These results use the updated assumptions.':'');draw(v,replace||!current);if(!performance.getEntriesByName('predict-useful').length)requestAnimationFrame(()=>{performance.mark('predict-useful');document.body.dataset.usefulMs=String(Math.round(performance.now()));});if(focusResults){byId('content').focus();byId('content').scrollIntoView({block:'start'});}}catch(e){if(ticket===generation){status('Read failed: '+e.message);const retry=button('Retry',()=>read({replace,resultId,pageOffset}));byId('status').append(' ',retry);}}
  }
  function disable(yes){for(const e of document.querySelectorAll('#refresh-snapshot,#ordinary-controls input,#ordinary-controls select,#ordinary-controls button,#settings button,#settings input,#settings select,#latest-snapshot,#prior-snapshot'))e.disabled=yes;}
  async function operation(action){if(busy)return;const started=performance.now();busy=true;++generation;disable(true);status(`${action==='refresh'?'Refreshing local prices':'Recalculating captured inputs'}… Previous results remain displayed.`);try{const body={action};if(current?.id)body.expected=current.id;if(action==='recalculate')body.assumptions=settingsValue();const q=query();q.set('offset','0');const v=await request(api+'?'+q,body);offset=0;draw(v,true);status(action==='refresh'?'Prices refreshed. A new saved comparison is ready.':'Recalculation complete.');if(action==='recalculate'&&admin){const target=new URL(byId('return-result').href);target.searchParams.set('notice','recalculated');location.href=target;}}catch(e){status(`${action==='refresh'?'Refresh':'Recalculation'} failed: ${e.message}. Previous results retained.`);}finally{document.body.dataset.operationMs=String(Math.round(performance.now()-started));busy=false;disable(false);}}
  options('venue',['kalshi','polymarket_us','novig','prophetx'].map(v=>[v,name(v)]));options('family',['winner','spread','total'].map(v=>[v,name(v)]));
  byId('sort').replaceChildren();for(const [value,label] of view==='arbs'?[['minimum_return_percent','Scenario minimum %']]:[['gross_return_percent','Before-fee estimate %'],['conditional_return_percent','After trade-fee estimate %'],['net_return_percent','Assumed net EV %'],['price_difference_cents','Price difference ¢']]){const o=el('option',label);o.value=value;byId('sort').append(o);}if([...byId('sort').options].some(o=>o.value===initial.get('metric')))byId('sort').value=initial.get('metric');
  for(const id of filters)if(id!=='game')byId(id).value=initial.get(id)||'';
  byId('mode').value=view==='arbs'?'arbs':'ev';byId('mode').onchange=()=>{const u=new URL(location.href);u.pathname=byId('mode').value==='arbs'?'/arbs':'/';u.searchParams.delete('metric');u.searchParams.delete('offset');location.href=u;};
  for(const value of ['','NFL','NCAAF','NBA','NCAAB','MLB','NHL']){const b=button(value||'All sports',()=>{league=value;selection=null;read();},'');b.dataset.league=value;b.setAttribute('aria-pressed',String(value===league));byId('leagues').append(b);}
  for(const value of ['','winner','spread','total']){const b=button(value?name(value):'All markets',()=>{byId('family').value=value;read();},'');b.dataset.family=value;byId('markets').append(b);}
  for(const id of ['venue','family','game','sort'])byId(id).onchange=()=>{selection=null;read();};
  let searchTimer;byId('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{selection=null;read();},200);};
  byId('restore').onclick=()=>{if(current?.defaults){settingsForm(current.defaults);status('Defaults loaded in this form. Recalculate to apply them.');}};
  byId('settings').onsubmit=e=>{e.preventDefault();operation('recalculate');};byId('refresh-snapshot').onclick=()=>operation('refresh');byId('latest-snapshot').onclick=()=>{selection=null;read({replace:true,resultId:null});};byId('prior-snapshot').onclick=()=>{selection=null;read({replace:true,resultId:prior[0]});};
  if(admin){byId('admin-nav').append(UI.adminNav());byId('ordinary-controls').hidden=true;byId('snapshot-tools').hidden=true;byId('refresh-snapshot').hidden=true;byId('calculation-panel').hidden=section!=='calculations';}
  document.addEventListener('click',e=>{const a=e.target.closest('a');if(a&&new URL(a.href).origin===location.origin)remember();});
  disable(true);
  read({replace:true,resultId:initial.get('result_id'),pageOffset:offset}).then(restoreContext).finally(()=>{disable(false);if(!current?.id)byId('settings').querySelector('[type=submit]').disabled=true;});
})();

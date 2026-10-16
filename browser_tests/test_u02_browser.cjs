// Replay supplied current-row responses and labeled authored states.
// Every request is intercepted; this runner cannot reach an app or provider.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
if(process.argv.length!==4)throw Error('Provide response and partial-failure fixture paths: node browser_tests/test_u02_browser.cjs <responses.json> <partial.json>');
const f=JSON.parse(fs.readFileSync(path.resolve(process.argv[2]))),partial=JSON.parse(fs.readFileSync(path.resolve(process.argv[3])));
const {chromium}=require(process.env.PREDICT_PLAYWRIGHT_MODULE);
const output=path.resolve(__dirname,'../test-results/u02-replay'),assets=path.resolve(__dirname,'../app/dashboard/opportunity_static/current');
const clone=structuredClone,states=['numeric_current','numeric_last_known','missing_reference','unsupported_inputs','calculation_failed','not_evaluated'];
function summarize(rows){const counts=Object.fromEntries(states.map(s=>[s,0]));let positive=0;for(const r of rows){counts[r.availability.state]++;positive+=Number(r.availability.current_opportunity_eligible);}const total=rows.length,n=counts.numeric_current+counts.numeric_last_known;return {version:'predict-calculation-availability-1',scope:'evaluated_results_before_filter',games:1,total_results:total,numeric_results:n,current_results:counts.numeric_current,positive_results:positive,counts,outcome:positive?'positive':!n?'unavailable':n<total?'partial':!counts.numeric_current?'last_known_only':'evaluated_no_positive',causes:[]};}
function authoredCurrent(){
 const v=clone(f.slate_ev),b=clone(f.ev),g=v.games.find(g=>g.game_key===b.game_key),source=b.rows.find(r=>r.availability.numeric_metrics.includes('buffered_ev_usd'));
 b.rows=['2','0','-3','-1'].map((n,i)=>{const r=clone(source);r.quote_id+=':authored:'+i;r.details.quote_id=r.quote_id;r.availability.state='numeric_current';r.availability.reason_codes=[];r.freshness.status='current';r.availability.numeric_metrics.forEach(k=>r.availability.metrics[k]={state:'numeric_current',reason_codes:[]});r.financial_metrics.buffered_ev_usd=String(Number(n)*10);r.financial_metrics.buffered_return_percent=n;r.classification.main_positive_eligible=i===0;r.classification.positive_rule_sensitive_eligible=false;r.availability.current_opportunity_eligible=i===0;r.ranking_eligible=i===0;if(i===3){r.financial_metrics.buffered_ev_usd=null;r.financial_metrics.buffered_return_percent=null;r.financial_metrics.conditional_buffered_ev_usd='-10';r.financial_metrics.conditional_buffered_return_percent='-1';r.availability.numeric_metrics=r.availability.numeric_metrics.filter(k=>k!=='buffered_ev_usd');r.availability.metrics.buffered_ev_usd={state:'unsupported_inputs',reason_codes:['complete_probability_partition_unsupported']};}return r;});
 b.availability=summarize(b.rows);v.games=[g];v.boards=[b];v.errors=[];v.availability=b.availability;v.coverage={...v.coverage,total_games:1,returned_games:1,next_offset:null,complete:true};return v;
}
(async()=>{
 fs.mkdirSync(path.join(output,'screenshots'),{recursive:true});const browser=await chromium.launch({headless:true,...(process.env.PREDICT_CI_CHROMIUM?{executablePath:process.env.PREDICT_CI_CHROMIUM}:{})});const checks=[];
 try{for(const width of [1280,390]){ console.log('width',width);
  const context=await browser.newContext({viewport:{width,height:1000},timezoneId:'America/New_York',serviceWorkers:'block'}),page=await context.newPage();let scenario='authentic',changedDetails=false,slateDelay=0;const errors=[],requests=[];
  page.on('pageerror',e=>errors.push(e.message));await page.clock.install({time:new Date(f.slate.as_of)});
  await context.route('**/*',async route=>{
   const u=new URL(route.request().url());assert.equal(u.hostname,'u02.invalid');requests.push({path:u.pathname,query:Object.fromEntries(u.searchParams)});
   if(u.pathname.startsWith('/current/assets/'))return route.fulfill({path:path.join(assets,path.basename(u.pathname)),contentType:u.pathname.endsWith('.js')?'text/javascript':'text/css'});
   if(u.pathname==='/api/boards/slate'){
    if(slateDelay)await new Promise(resolve=>setTimeout(resolve,slateDelay));
    const view=u.searchParams.get('view'),filter=u.searchParams.get('filter');let v=clone(u.searchParams.get('amount')==='500'&&view==='ev'?f.amount500:f['slate_'+view]);
    if(scenario==='partial'&&view==='ev')v=clone(partial);
    if(scenario==='current'&&view==='ev')v=authoredCurrent();
    if(scenario==='failed'){
     v.boards=[];v.errors=v.games.map(g=>({...clone(partial.errors[0]),game_key:g.game_key}));v.availability={...v.availability,counts:Object.fromEntries(states.map(s=>[s,s==='calculation_failed'?v.games.length:0])),numeric_results:0,current_results:0,positive_results:0,total_results:v.games.length,outcome:'unavailable',causes:[]};
    }
    if(scenario==='missing'&&view==='ev'){
     v.boards=v.boards.filter(b=>b.availability.numeric_results===0);v.games=v.games.filter(g=>v.boards.some(b=>b.game_key===g.game_key));v.errors=[];v.coverage={...v.coverage,total_games:v.games.length,returned_games:v.games.length};
     v.availability={...v.availability,counts:Object.fromEntries(states.map(s=>[s,s==='missing_reference'?v.boards.reduce((n,b)=>n+b.rows.length,0):0])),numeric_results:0,current_results:0,positive_results:0,total_results:v.boards.reduce((n,b)=>n+b.rows.length,0),outcome:'unavailable',games:v.games.length,causes:[]};
    }
    v.filter=filter;for(const b of v.boards){b.filter=filter;if(view!=='odds'&&filter!=='all')b.rows=b.rows.filter(r=>r.classification[filter==='hedges'?'positive_rule_sensitive_eligible':'main_positive_eligible']);}
    return route.fulfill({json:v});
   }
   if(u.pathname==='/api/boards/details'){
    if(changedDetails)return route.fulfill({status:409,json:{error:'current_inputs_changed_or_removed'}});
    const d=u.searchParams.has('pair')?f.pair_details:f.details;
    if(u.searchParams.get('game')!==d.game_key||u.searchParams.get('context_id')!==d.calculation_context.context_id)return route.fulfill({status:409,json:{error:'current_inputs_changed_or_removed'}});
    return route.fulfill({json:d});
   }
   if(u.pathname==='/api/boards/inputs')return route.fulfill({json:f.inputs});
   if(u.pathname==='/api/admin/current')return route.fulfill({json:{stopped:true}});
   assert(!u.pathname.startsWith('/api/'),'No other endpoints permitted');return route.fulfill({path:path.join(assets,'stored.html'),contentType:'text/html'});
  });
  async function label(text){await page.evaluate(text=>{let n=document.getElementById('evidence');if(!n){n=document.createElement('div');n.id='evidence';n.style.cssText='padding:7px 16px;background:#fff4ce;color:#493900;font:12px system-ui';document.body.prepend(n);}n.textContent=text;},text||'Supplied response fixtures · intercepted UI check · no provider requests');}
  async function shot(name){await label(scenario==='authentic'?undefined:'Authored '+scenario+' state · intercepted UI check · not installed/live');await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:path.join(output,'screenshots',name+'-'+width+'.png')});}
  async function openSettings(){if(!await page.locator('.calculation-settings').evaluate(n=>n.open))await page.locator('.calculation-settings>summary').click();}
  async function noOverflow(){assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'page overflow');}
  await page.goto('http://u02.invalid/');await page.waitForSelector('.slate-summary');assert.equal(await page.locator('#game').inputValue(),'');assert(await page.locator('#purpose').isVisible());assert.equal(await page.locator('#amount').count(),1);await shot('odds');await noOverflow();
  const short=f.slate_odds.boards.flatMap(b=>b.prices).find(q=>q.native_side==='Short');assert(short);const shortButton=page.locator('.slate-price-cell button').filter({hasText:'Short'}).first();assert(await shortButton.isVisible()||await shortButton.count());
  // Genuine original endpoint fixture retains exact source facts and selected identity.
  const original=f.inputs.quote_id;
  const originalKey=await page.locator('.slate-price-cell button').evaluateAll((nodes,id)=>nodes.find(n=>n.dataset.key.endsWith(id))?.dataset.key,original);
  if(originalKey){await page.locator('button[data-key="'+originalKey+'"]').click();await page.waitForSelector('#detail-content pre',{state:'attached'});assert((await page.locator('#detail-content').innerText()).includes('Original native price'));await page.keyboard.press('Escape');}
  for(const view of ['ev','arbs']){ console.log('view',view);
   await page.goto('http://u02.invalid/'+view);await page.getByRole('button',{name:'View last-known estimates',exact:true}).waitFor();assert.equal(await page.locator('.slate-result').count(),0);await shot(view+'-positive');
   await page.getByRole('button',{name:'View last-known estimates',exact:true}).click();await page.waitForSelector('.slate-result');assert.equal(await page.locator('[data-filter=all]').evaluate(n=>n===document.activeElement),true);
   const expected=f['slate_'+view].boards.reduce((n,b)=>n+b.rows.length,0);assert.equal(await page.locator('.slate-result').count(),expected);
   const compact=await page.locator('.slate-result').evaluateAll(nodes=>nodes.every(n=>n.querySelectorAll('.metric').length<=1&&n.querySelectorAll('.slate-result-note').length<=1&&!/Combined deployment|Complete EV unknown|\$/.test(n.innerText)));assert(compact);
   assert.equal(await page.locator('.availability-notice').count(),1);await shot(view+'-all');await page.locator('#content').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,'screenshots',view+'-comparisons-'+width+'.png')});await noOverflow();
   const targetGame=f[view].game_key;await page.locator('#game').selectOption(targetGame);assert((await page.locator('.slate-summary').innerText()).includes('1 matching games'));
   const id=view==='ev'?f.details.quote.id:f.pair_details.pair.id;const key=targetGame+':'+id;const btn=page.locator('button[data-key="'+key+'"]');assert.equal(await btn.count(),1);await btn.click();await page.waitForSelector('.selected-primary');assert(await page.locator('#details').isVisible());
   assert((await page.locator('#detail-content').innerText()).includes('Requested funding'));await page.locator('#details').evaluate(n=>n.scrollTop=0);await page.screenshot({path:path.join(output,'screenshots',view+'-details-top-'+width+'.png')});await page.locator('#details details').last().locator('summary').click();assert((await page.locator('#detail-content pre').innerText()).includes('evaluation_frame'));await noOverflow();await page.screenshot({path:path.join(output,'screenshots',view+'-details-'+width+'.png')});
   await page.locator('#close-details').focus();await page.keyboard.press('Shift+Tab');assert(await page.locator('#details').evaluate(n=>n.contains(document.activeElement)));
   await page.keyboard.press('Escape');assert.equal(await page.locator('button[data-key="'+key+'"]').evaluate(n=>n===document.activeElement),true);
   const returnButton=page.locator('button[data-key="'+key+'"]');await returnButton.focus();const scroll=await page.evaluate(()=>scrollY);await page.clock.runFor(10010);await page.waitForTimeout(100);assert.equal(await returnButton.evaluate(n=>n===document.activeElement),true);assert(Math.abs(await page.evaluate(()=>scrollY)-scroll)<5);
   await page.locator('#game').selectOption('');await page.locator('#search').fill('Seattle');assert((await page.locator('.slate-summary').innerText()).includes(f['slate_'+view].games.filter(g=>g.title.toLowerCase().includes('seattle')).length+' matching games'));await page.clock.runFor(10010);await page.waitForTimeout(100);assert.equal(await page.locator('#search').inputValue(),'Seattle');await page.locator('#search').fill('');
  }
  console.log('settings');
  // Settings requests use the actual server-produced $500 response; Restore returns the $1,000 frame.
  await page.goto('http://u02.invalid/ev');await page.getByRole('button',{name:'View last-known estimates',exact:true}).click();
  await openSettings();await page.locator('#amount').fill('500');await page.locator('#amount').press('Enter');await page.waitForFunction(()=>document.getElementById('applied').textContent.includes('$500.00'));assert.equal(await page.locator('#amount').inputValue(),'500');
  assert(requests.some(r=>r.query.amount==='500'));await openSettings();await page.locator('#restore').click();await page.waitForFunction(()=>document.getElementById('applied').textContent.includes('$1,000.00'));assert.equal(await page.locator('#buffer').inputValue(),'0.5');assert.equal(await page.locator('#benchmark').inputValue(),'pinnacle');
  console.log('draft and invalidation');
  await openSettings();await page.locator('#amount').fill('500');await page.getByRole('button',{name:'Apply',exact:true}).click();await page.waitForFunction(()=>document.getElementById('applied').textContent.includes('$500.00'));await openSettings();await page.locator('#restore').click();await page.waitForFunction(()=>document.getElementById('applied').textContent.includes('$1,000.00'));
  // Draft and focus survive polling; a changed context replaces the entire selected report.
  await openSettings();await page.locator('#amount').fill('777');await page.clock.runFor(10010);await page.waitForTimeout(100);assert.equal(await page.locator('#amount').inputValue(),'777');await page.keyboard.press('Escape');
  await page.locator('#game').selectOption(f.ev.game_key);const key=f.ev.game_key+':'+f.details.quote.id;await page.locator('button[data-key="'+key+'"]').click();await page.waitForSelector('.selected-primary');changedDetails=true;await page.clock.runFor(10010);await page.waitForSelector('#detail-content .warning');assert.equal(await page.locator('.selected-primary').count(),0);await page.keyboard.press('Escape');changedDetails=false;
  // Authored presentational state matrix, always labeled separately from authentic replay.
  for(const mode of ['current','partial','missing','failed']){console.log('mode',mode);scenario=mode;await page.evaluate(()=>{sessionStorage.removeItem('predict-board-slate-game');sessionStorage.removeItem('predict-board-slate-search');});await page.goto('http://u02.invalid/ev');await page.waitForSelector('.slate-summary');if(mode==='current'){assert.equal(await page.locator('.slate-result').count(),1);await page.locator('[data-filter=all]').click();await page.waitForFunction(()=>document.querySelectorAll('.slate-result').length===4);const t=await page.locator('.slate-result-values').allTextContents();assert(t.some(s=>s.includes('+2.00%'))&&t.some(s=>s.includes('0.00%'))&&t.some(s=>s.includes('-3.00%'))&&t.some(s=>s.includes('decisive outcomes only')));}if(mode==='partial'){await page.locator('[data-filter=all]').click();await page.waitForSelector('.slate-result');await page.locator('.availability-causes>summary').click();assert((await page.locator('#content').innerText()).includes('Calculation read failed')); }if(['missing','failed'].includes(mode)){assert.equal(await page.locator('.slate-result .metric').count(),0);assert(!(await page.locator('#content').innerText()).includes('No positive EV found'));}await shot('state-'+mode);await page.evaluate(()=>document.documentElement.style.fontSize='20px');await noOverflow();await page.screenshot({path:path.join(output,'screenshots','state-'+mode+'-large-'+width+'.png')});}
  scenario='authentic';await page.goto('http://u02.invalid/ev');await page.getByRole('button',{name:'View last-known estimates',exact:true}).click();await page.waitForSelector('.slate-result');assert.equal(await page.locator('[data-filter=all]').evaluate(n=>n===document.activeElement),true);await page.evaluate(()=>{document.documentElement.style.fontSize='20px';for(const n of document.querySelectorAll('.slate-game-heading h2,.slate-instrument h3,.slate-leg strong'))n.textContent+=' · Extremely long native participant and original instrument terms';});await noOverflow();await page.screenshot({path:path.join(output,'screenshots','long-labels-large-'+width+'.png')});
  // Stop remains reachable and uses only the existing control endpoint in this intercepted test.
  await page.locator('#stop').click();await page.waitForFunction(()=>document.getElementById('stop').disabled);assert(requests.some(r=>r.path==='/api/admin/current'));
  assert.deepEqual(errors,[]);checks.push({width,authentic_replay:true,authored_states:['current','partial','missing','failed'],exact_details_original:true,settings_restore:true,poll_focus_scroll_draft:true,context_invalidation:true,overflow:false,provider_requests:0});await context.close();
 }}finally{await browser.close();}
 fs.writeFileSync(path.join(output,'browser-verification.json'),JSON.stringify({evidence_class:'intercepted supplied response fixtures and labeled authored states',checks},null,2)+'\n');console.log('PASS supplied response replay: desktop/390px, last-known discovery and compact rows, exact Details/Original, settings/Enter/Restore, polling/focus/draft/scroll, context expiry, signed/conditional/partial/missing/all-failed states, large text/long labels and Stop');
})().catch(e=>{console.error(e);process.exitCode=1;});

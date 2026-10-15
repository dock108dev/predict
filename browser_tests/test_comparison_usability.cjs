// Authentic retained response interception: never connects to installed app/SQL/provider.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PREDICT_PLAYWRIGHT_MODULE||'playwright');
const source=process.env.PREDICT_RETAINED_RESPONSES,output=process.env.PREDICT_USABILITY_EVIDENCE;
assert(source&&output,'Explicit retained source and evidence destination required');
const assets=path.resolve('app/dashboard/opportunity_static/current');
const oracle=JSON.parse(fs.readFileSync(path.join(output,'reconciliation.json')));
const fixtures=Object.fromEntries(['odds','ev','arbs'].map(v=>[v,JSON.parse(fs.readFileSync(path.join(source,v==='odds'?'codec2-final-odds.json':'final-'+v+'.json')))]));
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PREDICT_CI_CHROMIUM?{executablePath:process.env.PREDICT_CI_CHROMIUM}:{})});
 const checks=[];fs.mkdirSync(path.join(output,'screenshots'),{recursive:true});
 try{for(const width of [1280,390]){
  const context=await browser.newContext({viewport:{width,height:1000},timezoneId:'America/New_York',serviceWorkers:'block'}),page=await context.newPage(),errors=[],requests=[];
  page.on('pageerror',e=>errors.push(e.message));await page.clock.install();
  await context.route('**/*',async route=>{
   const url=new URL(route.request().url());requests.push(url.pathname);assert.equal(url.hostname,'retained.invalid');
   if(url.pathname.startsWith('/current/assets/'))return route.fulfill({path:path.join(assets,path.basename(url.pathname)),contentType:url.pathname.endsWith('.js')?'text/javascript':'text/css'});
   if(url.pathname==='/api/boards/slate'){
    const view=url.searchParams.get('view'),filter=url.searchParams.get('filter');
    const v=structuredClone(fixtures[view]);v.filter=filter;
    for(const b of v.boards){b.filter=filter;if(view!=='odds'&&filter!=='all')b.rows=b.rows.filter(r=>r.classification[filter==='hedges'?'positive_rule_sensitive_eligible':'main_positive_eligible']);}
    return route.fulfill({json:v});
   }
   assert(!url.pathname.startsWith('/api/'),'Only saved slate reads permitted');
   return route.fulfill({path:path.join(assets,'stored.html'),contentType:'text/html'});
  });
  async function label(){await page.evaluate(()=>{
   let note=document.getElementById('replay-evidence');if(!note){note=document.createElement('div');note.id='replay-evidence';note.style.cssText='padding:8px 16px;background:#fff4ce;color:#493900;font:13px system-ui';document.body.prepend(note);}
   note.textContent='Retained API replay · October 14, 2026 source frame · intercepted browser evidence · no live data';
  });}
  for(const view of ['odds','ev','arbs']){
   console.log('checking',width,view);
   await page.goto('http://retained.invalid/'+(view==='odds'?'':view));await page.waitForSelector('.slate-summary');await label();
   if(view!=='odds'){
    await page.locator('#filters [data-filter=all]').click();console.log('selected all',view);await page.waitForSelector('.slate-result');
    const expected=oracle.rows.filter(r=>r.view===view);
    for(let attempt=0;attempt<100 && await page.locator('.slate-result').count()!==expected.length;attempt++)await new Promise(resolve=>setTimeout(resolve,50));
    console.log('rows',await page.locator('.slate-result').count(),expected.length);assert.equal(await page.locator('.slate-result').count(),expected.length);
    for(const r of expected){
     const node=page.locator('.slate-result').filter({has:page.locator('button[data-key="'+r.game+':'+r.id+'"]')});
     const text=await node.innerText();for(const value of r.expected)assert(text.includes(value),view+' '+r.id+' expected '+value);
    }
    if(view==='arbs'){
     assert((await page.locator('.slate-summary').innerText()).includes('80 cross-venue comparisons'));
     assert.equal(await page.locator('.same-venue-history button').count(),62);
     assert.equal(await page.locator('.slate-result table').count(),0);
    }
   }else{
    for(const n of oracle.native){const node=page.locator('.slate-price-cell button[data-key="'+n.inputs_identity.game_key+':'+n.quote_id+'"]');assert.equal(await node.count(),1);assert((await node.innerText()).includes(n.native_side));}
    for(const r of oracle.odds){const g=page.locator('.slate-odds[data-key="'+r.game+'"]');const row=g.locator('.slate-price-row').filter({hasText:fixtures.odds.games.find(g=>g.game_key===r.game).participants.find(p=>p.id===r.participant).name});const text=await row.locator('.slate-fair').innerText();assert(text.includes('Fair '+r.fair));assert(text.includes('Offered '+r.offered));}
   }
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),view+' clipping');
   await page.screenshot({path:path.join(output,'screenshots','retained-'+view+'-'+width+'.png')});
   await page.locator('#content').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,'screenshots','retained-'+view+'-comparisons-'+width+'.png')});await page.evaluate(()=>scrollTo(0,0));
   if(view==='odds')for(const [index,game] of fixtures.odds.games.filter(g=>oracle.native.some(n=>n.inputs_identity.game_key===g.game_key)).entries()){
    await page.locator('#game').selectOption(game.game_key);await page.screenshot({path:path.join(output,'screenshots','retained-example-'+(index+1)+'-'+width+'.png'),fullPage:true});
   }
   if(view!=='odds'){
    await page.locator('#search').fill('Seattle');await page.screenshot({path:path.join(output,'screenshots','retained-'+view+'-seattle-'+width+'.png'),fullPage:true});
    const button=page.locator('.slate-result button').first();await button.focus();const identity=await button.getAttribute('data-key');await page.evaluate(()=>scrollBy(0,250));const y=await page.evaluate(()=>scrollY);
    await page.clock.runFor(10010);await page.waitForTimeout(100);
    assert.equal(await page.locator('#search').inputValue(),'Seattle');assert.equal(await page.evaluate(()=>document.activeElement.dataset.key),identity);assert(Math.abs(await page.evaluate(()=>scrollY)-y)<5,'arrival preserves scroll');
   }
   await page.locator('#game').selectOption('');await page.locator('#search').fill('');
   await page.evaluate(()=>document.documentElement.style.fontSize='20px');assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),view+' enlarged clipping');
   checks.push({width,view,overflow:false,independent_values:true,exact_observed_sides:view==='odds',evidence_class:'retained intercepted replay'});
  }
  assert.deepEqual(errors,[]);assert(requests.filter(p=>p.startsWith('/api/')).every(p=>p==='/api/boards/slate'));await context.close();
 }}finally{await browser.close();}
 fs.writeFileSync(path.join(output,'browser-verification.json'),JSON.stringify({checks,provider_requests:0,installed:false,owner_acceptance:false},null,2)+'\n');
 console.log('PASS retained desktop/390px: 6 native sides, 28 offered/fair conversions, 190 independent saved values, 80 cross-venue/62 advanced portfolios, focus/search/scroll arrivals, enlarged text; no clipping or page errors');
})().catch(e=>{console.error(e);process.exitCode=1;});

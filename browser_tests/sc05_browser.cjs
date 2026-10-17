const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),{spawn}=require('node:child_process');
const root=path.resolve(__dirname,'..'),out=process.env.PREDICT_SC05_REPORT||path.join(root,'test-results/sc05/browser');fs.mkdirSync(path.join(out,'screenshots'),{recursive:true});
(async()=>{
 const {chromium}=require(process.env.PREDICT_PLAYWRIGHT_MODULE||'playwright');
 const server=spawn(process.env.PYTHON||'python',['-m','tests.sc05_preview','--port','8805'],{cwd:root,stdio:['ignore','pipe','pipe']});let serverLog='';server.stderr.on('data',d=>serverLog+=d);const base='http://127.0.0.1:8805';let browser;
 try{
  for(let i=0;i<160;i++){try{if((await fetch(base+'/api/scanner/client')).ok)break;}catch{}await new Promise(r=>setTimeout(r,50));if(i===159)throw Error(serverLog);}
  const ctl=async value=>{const r=await fetch(base+'/__test/state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});assert(r.ok);return r.json();};
  browser=await chromium.launch({headless:true,...(process.env.PREDICT_CI_CHROMIUM?{executablePath:process.env.PREDICT_CI_CHROMIUM}:{})});
  const context=await browser.newContext({viewport:{width:1440,height:900},reducedMotion:'reduce',serviceWorkers:'block',permissions:['clipboard-read','clipboard-write']}),page=await context.newPage(),errors=[],external=[];
  page.on('pageerror',e=>errors.push(String(e)));await context.route('**/*',r=>{if(new URL(r.request().url()).origin!==base){external.push(r.request().url());return r.abort();}return r.continue();});
  await page.addInitScript(()=>{const real=Date.now.bind(Date),start=real(),base=Date.parse('2026-10-11T12:00:00Z');window.sc05DateOffset=0;Date.now=()=>base+(real()-start)+window.sc05DateOffset;});
  const shot=async name=>page.screenshot({path:path.join(out,'screenshots',name+'.png')}),overflow=async()=>assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'horizontal overflow');
  const waitReady=()=>page.waitForFunction(()=>window.predictTicketObservations?.().ready===true),row=()=>page.locator('.scanner-row button').first();
  await page.goto(base);await page.locator('#scanner-category').selectOption('conditional_hedge');await page.waitForSelector('.scanner-row');
  assert.equal(await page.locator('#scanner-sound').getAttribute('aria-pressed'),'false');
  await row().click();await waitReady();await page.waitForTimeout(60);await shot('desktop-ready');await overflow();
  assert(await page.locator('#scanner-results').isVisible());assert.equal(await page.locator('.ticket-leg').count(),2);
  const firstIdentity=await page.evaluate(()=>window.predictTicketObservations().selection);assert(firstIdentity.engine_binding);
  // Periodic scanner redraws cannot erase form drafts, focus, or disclosures.
  await page.locator('#scanner-selection-content>details>summary').click();await page.locator('#ticket-amount').fill('40.12345678');await page.waitForTimeout(1200);assert.equal(await page.locator('#ticket-amount').inputValue(),'40.12345678');assert(await page.locator('#scanner-selection-content>details').getAttribute('open')!==null);assert(await page.locator('#ticket-amount').evaluate(n=>n===document.activeElement));assert(!(await page.evaluate(()=>window.predictTicketObservations().ready)));
  await page.locator('#ticket-amount').fill('40');await page.getByRole('button',{name:'Check amount',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#scanner-selection-content').textContent.includes('Proposed replacement'));assert(!(await page.evaluate(()=>window.predictTicketObservations().ready)));
  await shot('replacement');await page.getByRole('button',{name:'Adopt updated allocations'}).click();await waitReady();
  await page.getByRole('button',{name:'Copy validated allocations'}).click();await page.waitForFunction(()=>document.querySelector('#scanner-selection-content').textContent.includes('allocations copied'));
  const copied=JSON.parse(await page.evaluate(()=>navigator.clipboard.readText()));assert.equal(copied.positions.length,2);assert(!JSON.stringify(copied).includes('american'));assert.equal(copied.funding.requested_amount_usd,'40');
  await page.keyboard.press('Escape');await page.waitForFunction(()=>document.getElementById('scanner-selection').hidden);assert(await row().evaluate(n=>n===document.activeElement));
  // Selection => binding => real backend finance + actual SQL => second rAF.
  const samples=[];
  for(let i=0;i<30;i++){
    const kind=['native','stake','mixed'][i%3],amount=i%2?'500':'40';
    await ctl({action:'fixture',kind,amount});await page.reload();await page.waitForSelector('.scanner-row');
    await row().click();await waitReady();await page.waitForFunction(()=>window.predictTicketObservations().samples.some(s=>s.operation==='select'&&s.ready));
    const s=await page.evaluate(()=>window.predictTicketObservations().samples.find(s=>s.operation==='select'&&s.ready));samples.push({...s,sample:i+1,kind,amount});
  }
  const p95=x=>[...x].sort((a,b)=>a-b)[Math.ceil(.95*x.length)-1];assert(p95(samples.map(s=>s.totalMs))<=1000);assert(Math.max(...samples.map(s=>s.totalMs))<=2000);
  // Changed inputs remove authority and retain the old frame until explicit adoption.
  await ctl({action:'fixture',kind:'native',amount:'100'});await page.reload();await page.waitForSelector('.scanner-row');await row().click();await waitReady();const before=await page.locator('.ticket-result').first().innerText();
  await ctl({action:'change',price:'0.21'});await page.waitForFunction(()=>!window.predictTicketObservations().ready);await page.waitForFunction(()=>document.querySelector('#scanner-selection-content').textContent.includes('Proposed replacement'));assert.equal(await page.locator('.ticket-result').first().innerText(),before);await shot('changed-previous');
  await page.getByRole('button',{name:'Adopt updated allocations'}).click();await waitReady();
  // Missing production destinations cannot authorize allocation or navigation.
  await ctl({action:'missing'});await page.keyboard.press('Escape');await row().click();await page.waitForFunction(()=>window.predictTicketObservations().state==='temporarily_unavailable');assert(await page.getByRole('button',{name:'Copy validated allocations'}).isDisabled());assert.equal(await page.locator('#scanner-selection a[href]').count(),0);await shot('missing-destinations');
  // Mobile sheet, text enlargement, Tab containment and Escape return.
  await page.setViewportSize({width:390,height:900});await page.evaluate(()=>document.documentElement.style.fontSize='24px');await overflow();await shot('mobile-enlarged');
  await page.locator('#scanner-close').focus();await page.keyboard.press('Shift+Tab');assert(await page.locator('#scanner-selection').evaluate(n=>n.contains(document.activeElement)));await page.keyboard.press('Escape');assert(await row().evaluate(n=>n===document.activeElement));
  await page.evaluate(()=>document.documentElement.style.fontSize='16px');await page.setViewportSize({width:1440,height:900});
  // Late selection / amount bodies must never cross the selected generation.
  await ctl({action:'fixture',kind:'native',amount:'100'});await page.reload();await page.waitForSelector('.scanner-row');await ctl({action:'delay',seconds:.25});await row().click();await page.keyboard.press('Escape');await row().click();await waitReady();await ctl({action:'delay',seconds:0});
  await page.locator('#ticket-amount').fill('40');await page.getByRole('button',{name:'Check amount',exact:true}).click();await page.locator('#ticket-amount').fill('50');await page.getByRole('button',{name:'Check amount',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#scanner-selection-content').textContent.includes('Proposed replacement'));await page.getByRole('button',{name:'Adopt updated allocations'}).click();await waitReady();assert((await page.locator('#scanner-selection-content').innerText()).includes('Requested $50.00'));
  await ctl({action:'loss'});await page.waitForFunction(()=>window.predictTicketObservations().state==='no_longer_qualifying');assert(await page.getByRole('button',{name:'Copy validated allocations'}).isDisabled());await shot('no-longer-qualifying');
  // Local expiry works while transport fails, without reusing GET ttl_seconds.
  await ctl({action:'transport',enabled:true});await page.evaluate(()=>window.sc05DateOffset=24*3600*1000);await page.waitForTimeout(400);assert(!(await page.evaluate(()=>window.predictTicketObservations().ready)));assert(await page.getByRole('button',{name:'Copy validated allocations'}).isDisabled());await shot('expired-disconnected');
  await ctl({action:'transport',enabled:false});await ctl({action:'restart'});await page.reload();await page.waitForSelector('.scanner-row');await row().click();await waitReady();await page.locator('#scanner-stop').click();assert(!(await page.evaluate(()=>window.predictTicketObservations().ready)));await shot('stopped');
  await ctl({action:'restart'});await page.reload();await page.waitForSelector('.scanner-row');await row().click();await waitReady();await ctl({action:'epoch'});await page.waitForFunction(()=>!window.predictTicketObservations().ready);await shot('epoch');
  // Filter-wide transition integration, including observations below rank 100.
  await ctl({action:'restart'});await ctl({action:'transitions'});await page.reload();await page.locator('#scanner-category').selectOption('covered_outcome_arb');await page.waitForFunction(()=>document.querySelectorAll('.scanner-row').length===100);await page.waitForFunction(()=>window.predictArrivalObservations?.().cursor!==null);await page.waitForTimeout(900);
  const lower=await (await fetch(base+'/api/scanner?offset=100&limit=100')).json(),keys=lower.rows.map(r=>r.id);assert(keys.length===30);
  const initial=await page.evaluate(()=>window.predictArrivalObservations());assert.equal(initial.sounds,0);
  await ctl({action:'transition_change',row:keys[0],edge:'20'});await page.waitForFunction(n=>window.predictArrivalObservations().accepted>n,initial.accepted);assert.equal((await page.evaluate(()=>window.predictArrivalObservations())).sounds,0);assert((await page.locator('#scanner-arrivals').innerText()).includes('improved'));
  await page.locator('#scanner-sound').click();assert.equal(await page.locator('#scanner-sound').getAttribute('aria-pressed'),'true');
  await ctl({action:'rank_only'});await page.waitForTimeout(1000);assert.equal((await page.evaluate(()=>window.predictArrivalObservations())).sounds,0);
  await ctl({action:'transition_change',row:keys[1],edge:'21'});await page.waitForFunction(()=>window.predictArrivalObservations().sounds===1);await page.waitForTimeout(900);assert.equal((await page.evaluate(()=>window.predictArrivalObservations())).sounds,1);
  await shot('quiet-filter-wide-arrivals');await page.locator('#scanner-sound').click();
  // Filter changes, local search, page changes, overflow and reload are silent.
  await page.locator('#scanner-search').fill('no matching title');await page.waitForTimeout(900);assert.equal((await page.evaluate(()=>window.predictArrivalObservations())).sounds,1);await page.locator('#scanner-search').fill('');
  await page.locator('#scanner-minimum_edge').fill('30');await page.locator('#scanner-minimum_edge').press('Tab');await page.waitForTimeout(1000);assert.equal((await page.evaluate(()=>window.predictArrivalObservations())).sounds,1);
  await ctl({action:'overflow'});await page.waitForTimeout(1000);assert((await page.locator('#scanner-arrivals').innerText()).includes('earlier observations unknown'));assert.equal((await page.evaluate(()=>window.predictArrivalObservations())).sounds,1);
  const arrivalObservations=await page.evaluate(()=>window.predictArrivalObservations());
  const state=await ctl({});if(!process.env.SC05_PORTABLE){assert(state.sql_capture_enabled);assert(state.witness.length>=30);}assert.equal(state.provider_requests,0);assert.deepEqual(errors,[]);assert.equal(external.length,0);
  fs.writeFileSync(path.join(out,'verification.json'),JSON.stringify({evidence_class:process.env.SC05_PORTABLE?'Actual Chromium; authored full-finance selected tickets without SQL capture. Not current source/link, installed, hosted or 500-event proof.':'Actual Chromium; authored full-finance selected tickets with real disposable SQL capture then authored qualified partition substitution. Not current source/link, installed, hosted or 500-event proof.',browser:await browser.version(),hardware:{platform:os.platform(),release:os.release(),arch:os.arch(),cpus:os.cpus()[0]?.model,memoryBytes:os.totalmem()},workload:{selectedEventsAtATime:1,samples:30,kinds:['native','stake','mixed'],amounts:['40','500'],desktop:[1440,900],mobile:[390,900],enlargedRootPixels:24},p95Ms:p95(samples.map(s=>s.totalMs)),maximumMs:Math.max(...samples.map(s=>s.totalMs)),samples,arrivalObservations,sqlWitness:state.witness,providerRequests:0,externalRequests:0,checks:['desktop panel/mobile sheet','draft focus disclosures survive scanner expiry sweeps','binding and strict operation schemas','explicit replacement adoption','top-level action authority','copy feedback and exact native allocations','missing destinations','Escape/focus containment','amount and selection races','local expiry with transport failure','Stop/epoch'],previewPeakRssBytes:state.peak_rss_bytes,nodePeakRssBytes:process.resourceUsage().maxRSS*1024},null,2)+'\n');
  console.log('PASS SC05 actual browser: p95 '+p95(samples.map(s=>s.totalMs)).toFixed(2)+'ms, max '+Math.max(...samples.map(s=>s.totalMs)).toFixed(2)+'ms');
 }finally{if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});

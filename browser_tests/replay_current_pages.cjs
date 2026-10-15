// Replay exact disposable current-row API pages. No installed app/provider access.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {pathToFileURL}=require('node:url');
const {chromium}=require(process.env.PREDICT_PLAYWRIGHT_MODULE||'playwright');
const pattern=process.env.PREDICT_CURRENT_PAGE_PATTERN,folder=process.env.PREDICT_CURRENT_PAGE_OUTPUT;
assert(pattern&&pattern.includes('{offset}')&&folder,'Explicit captured-page {offset} pattern and output required');
const output=path.resolve(folder),assets=path.resolve('app/dashboard/opportunity_static/current');fs.mkdirSync(output,{recursive:true});
(async()=>{
 const {SlateAccumulator}=await import(pathToFileURL(path.join(assets,'board-client.js')));
 const inspect=()=>{
  let accumulator,first;const pages=[];
  for(let offset=0;offset<500;offset+=50){
   const source=pattern.replace('{offset}',String(offset)),wire=fs.readFileSync(source),page=JSON.parse(wire);
   if(!accumulator){first={policy:page.policy,view:page.view,filter:page.filter,read_revision:page.read_revision,epoch:page.epoch,total_games:page.games.length};accumulator=new SlateAccumulator({amount:first.policy.requested_amount_usd,buffer:first.policy.buffer_rate,benchmark_venue:first.policy.benchmark_venue,benchmark_method:first.policy.benchmark_method,sizing_mode:first.policy.sizing_mode,view:first.view,filter:first.filter});}
   accumulator.append(page,wire.length);pages.push({offset,source,wire_bytes:wire.length,sha256:crypto.createHash('sha256').update(wire).digest('hex')});
   if(accumulator.complete)break;
  }
  const value=accumulator.result();return {...first,pages,aggregate:{version:value.version,boards:value.boards.length,errors:value.errors.length,rows:value.boards.reduce((n,b)=>n+b.rows.length,0),visible_rows:value.boards.reduce((n,b)=>n+b.rows.filter(r=>first.view!=='arbs'||r.legs?.length===2&&r.legs[0].venue!==r.legs[1].venue).length,0),coverage:value.coverage,bounds:value.bounds}};
 };
 const report={evidence_class:process.env.PREDICT_CURRENT_PAGE_EVIDENCE_CLASS||'Exact disposable current SQL API response replay; no installed/live/provider claim',...inspect(),checks:[],details_request:'Not exercised: no selected Details response fixture supplied; current row selection identities checked by client guards',bootstrap:'For financial views only, initial Positive uses a derived filter projection; measured All read uses exact original SQL page bytes'};
 const browser=await chromium.launch({headless:true,...(process.env.PREDICT_CI_CHROMIUM?{executablePath:process.env.PREDICT_CI_CHROMIUM}:{})});
 try{for(const width of [1280,390]){
  const context=await browser.newContext({viewport:{width,height:900},timezoneId:'America/New_York',serviceWorkers:'block'}),page=await context.newPage(),errors=[],requests=[];await page.clock.install();
  page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
  await context.route('**/*',async route=>{
   const req=route.request(),url=new URL(req.url());assert.equal(req.method(),'GET');assert.equal(url.hostname,'current-pages.invalid');
   if(url.pathname.startsWith('/current/assets/'))return route.fulfill({path:path.join(assets,path.basename(url.pathname)),contentType:url.pathname.endsWith('.js')?'text/javascript':'text/css'});
   if(url.pathname==='/api/boards/slate'){
    assert.equal(url.searchParams.get('limit'),'50');assert.equal(url.searchParams.get('view'),report.view);const filter=url.searchParams.get('filter');assert([report.filter,'positive'].includes(filter));
    const offset=Number(url.searchParams.get('offset')),captured=report.pages.find(p=>p.offset===offset);assert(captured);if(offset)assert.equal(url.searchParams.get('expected_revision'),report.read_revision);
    requests.push({offset,filter});
    if(filter!==report.filter){const projected=JSON.parse(fs.readFileSync(captured.source));projected.filter=filter;for(const b of projected.boards){b.filter=filter;b.rows=b.rows.filter(r=>r.freshness?.status==='current'&&r.classification?.main_positive_eligible);}return route.fulfill({json:projected});}
    return route.fulfill({body:fs.readFileSync(captured.source),contentType:'application/json'});
   }
   if(!url.pathname.startsWith('/api/'))return route.fulfill({path:path.join(assets,'stored.html'),contentType:'text/html'});
   throw Error('Unexpected replay request '+url.pathname);
  });
  try{
   await page.goto('http://current-pages.invalid/'+(report.view==='odds'?'':report.view));await page.waitForSelector('.slate-summary',{timeout:60000});
   if(report.view!=='odds'&&report.filter==='all'){await page.locator('#filters [data-filter=all]').click();await page.waitForFunction(()=>document.querySelector('.slate-summary')?.textContent.includes('all current results'),null,{timeout:60000});}
   const gameSelector=report.view==='odds'?'.slate-game':'.slate-comparison-game',exactRequests=()=>requests.filter(r=>r.filter===report.filter).length;
   assert.equal(await page.locator(gameSelector).count(),report.total_games);assert.equal(exactRequests(),report.pages.length);assert.deepEqual(errors,[]);
   if(report.view!=='odds')assert.equal(await page.locator('.slate-result').count(),report.aggregate.visible_rows,'every supplied current row remains visible');
   const cdp=await context.newCDPSession(page),heap=await cdp.send('Runtime.getHeapUsage');await cdp.detach();
   const measurement=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth,used_js_heap_bytes:performance.memory?.usedJSHeapSize??null,total_js_heap_bytes:performance.memory?.totalJSHeapSize??null,dom_nodes:document.getElementsByTagName('*').length,status:document.getElementById('status').textContent}));measurement.used_js_heap_bytes=heap.usedSize;measurement.total_js_heap_bytes=heap.totalSize;measurement.heap_measurement='CDP Runtime.getHeapUsage, JavaScript heap only';assert(!measurement.overflow);
   const last=await page.locator('#game option').last().getAttribute('value');await page.locator('#game').selectOption(last);assert.equal(await page.locator(gameSelector).count(),1);assert.equal(exactRequests(),report.pages.length,'selection remains local with exact all-game coverage');
   await page.locator('#game').selectOption('');await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:path.join(output,'current-pages-'+width+'.png')});
   report.checks.push({width,pages:exactRequests(),bootstrap_projection_pages:requests.filter(r=>r.filter!==report.filter).length,games:report.total_games,rendered_rows:report.view==='odds'?null:report.aggregate.visible_rows,exact_last_game_filter:true,row_selection_context_guards_passed:true,...measurement});
  }finally{await context.close();}
 }}finally{await browser.close();}
 report.all_passed=true;fs.writeFileSync(path.join(output,'current-pages.json'),JSON.stringify(report,null,2)+'\n');console.log('PASS exact current SQL replay: '+report.total_games+' games, '+report.pages.length+' coherent pages, '+report.aggregate.coverage.wire_bytes+' total wire bytes, desktop/390 all-game rendering and local last-game selection');
})().catch(e=>{console.error(e);process.exitCode=1;});

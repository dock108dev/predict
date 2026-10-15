// Fully intercepted ordinary-browser journey. This creates no installed/owner/provider evidence.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PREDICT_PLAYWRIGHT_MODULE || 'playwright');
const assets = path.resolve('app/dashboard/opportunity_static/current');
const {fixture,board:currentBoard,context:currentContext,coverage,bounds}=require('../tests/current_board_fixture.cjs');
const copy = value => JSON.parse(JSON.stringify(value));
const secondKey = 'synthetic-second-occurrence';
const catalog = [copy(fixture.catalog.games[0]), {...copy(fixture.catalog.games[0]), game_key:secondKey, title:'Second synthetic NFL game',start_at:'2026-10-17T00:15:00+00:00'}];
function slate(view,filter,state) {
  const boards = catalog.map(g => {
    const b=currentBoard(fixture[view],g.game_key); b.filter=filter;
    for (const q of b.prices) q.inputs_identity.game_key=g.game_key;
    if(state.mixed && g.game_key===secondKey) { b.status='mixed'; b.prices[0].freshness.status='historical';b.prices[0].freshness.reasons=['source_stale']; }
    if(view!=='odds' && filter!=='all') b.rows=b.rows.filter(r=>r.classification[filter==='hedges'?'positive_rule_sensitive_eligible':'main_positive_eligible']);
    if(state.paused || state.pending) b.delivery_state='pending';
    if(state.stopped) b.delivery_state='stopped';
    return b;
  });
  return {version:'predict-comparison-slate-2',epoch:'authored-reset-1',read_revision:'authored-read-1',coverage:coverage(state.empty?0:catalog.length),view,filter,policy:copy(boards[0].policy),games:state.empty?[]:catalog,boards:state.empty?[]:boards,stopped:state.stopped,as_of:'2026-10-14T00:00:00+00:00',bounds:copy(bounds),storage:{state:state.paused?'unavailable':'available',error:state.paused?'current_database_storage_cap':null}};
}
(async()=>{
  const options={headless:true};if(process.env.PREDICT_CI_CHROMIUM)options.executablePath=process.env.PREDICT_CI_CHROMIUM;
  const browser=await chromium.launch(options);
  try {
    for(const width of [1280,390]) {
      const context=await browser.newContext({viewport:{width,height:900},timezoneId:'America/New_York',serviceWorkers:'block'}),page=await context.newPage(),errors=[],requests=[],state={paused:false,stopped:false,failure:false,empty:false,mixed:false};
      page.on('pageerror',error=>errors.push(error.message));
      await page.clock.install();
      await context.addInitScript(()=>{sessionStorage.setItem('predict-board-game','old-single-game');sessionStorage.setItem('predict-board-search','old-single-team');});
      await context.route('**/*',async route=>{
        const url=new URL(route.request().url());requests.push(url);
        assert.equal(url.hostname,'board.invalid','external browser traffic refused');
        if(url.pathname.startsWith('/current/assets/'))return route.fulfill({path:path.join(assets,path.basename(url.pathname)),contentType:url.pathname.endsWith('.js')?'text/javascript':'text/css'});
        if(!url.pathname.startsWith('/api/'))return route.fulfill({path:path.join(assets,'stored.html'),contentType:'text/html'});
        if(url.pathname==='/api/admin/current'){assert.equal(JSON.parse(route.request().postData()).action,'stop');state.stopped=true;return route.fulfill({json:{stopped:true}});}
        if(state.failure)return route.fulfill({status:503,json:{error:'Saved reads temporarily unavailable'}});
        if(url.pathname==='/api/boards/slate'){assert(!url.searchParams.has('game'));return route.fulfill({json:slate(url.searchParams.get('view'),url.searchParams.get('filter'),state)});}
        if(url.pathname==='/api/boards/details'){
          const v=copy(fixture[url.searchParams.has('pair')?'pair':'single']),game=url.searchParams.get('game');
          if(state.changedDetails)return route.fulfill({status:409,json:{reason:'current_inputs_changed_or_removed'}});
          v.calculation_context=currentContext(v.policy,game);v.original_inputs_identity.context_id=v.calculation_context.context_id;
          v.game_key=game;v.original_inputs_identity.game_key=game;
          return route.fulfill({json:v});
        }
        if(url.pathname==='/api/boards/inputs'){const game=url.searchParams.get('game');return route.fulfill({json:{version:'predict-board-inputs-2',game_key:game,calculation_context:currentContext(fixture.odds.policy,game),quote_id:url.searchParams.get('quote'),evidence:{contract:'authored',source_at:'2026-10-14T00:00:00+00:00'}}});}
        throw Error('Unexpected browser request '+url.pathname);
      });
      try {
        await page.goto('http://board.invalid/');await page.waitForSelector('.slate-game');
        assert.equal(await page.locator('.slate-game').count(),2);assert.equal(await page.locator('#game').inputValue(),'','old single-game session does not hide slate');
        assert((await page.locator('.slate-coverage').innerText()).includes('Novig 2/2'));
        if(process.env.PREDICT_SLATE_SCREENSHOTS){fs.mkdirSync(process.env.PREDICT_SLATE_SCREENSHOTS,{recursive:true});await page.screenshot({path:path.join(process.env.PREDICT_SLATE_SCREENSHOTS,'authored-odds-'+width+'.png')});}
        const reads=()=>requests.filter(u=>u.pathname==='/api/boards/slate').length,initialReads=reads();
        await page.locator('#search').fill('Second');assert.equal(await page.locator('.slate-game').count(),1);await page.locator('#search').fill('');
        await page.locator('#game').selectOption(secondKey);assert.equal(await page.locator('.slate-game').count(),1);await page.locator('#game').selectOption('');assert.equal(await page.locator('.slate-game').count(),2);assert.equal(reads(),initialReads,'local search/filter must not fan out reads');
        assert.equal(requests.filter(u=>u.pathname==='/api/boards/games').length,0);
        state.mixed=true;await page.reload();await page.waitForSelector('.slate-game');assert.equal(await page.locator('.slate-game').count(),2);assert((await page.locator('button[aria-label*="As-of inputs"]').count())>0);assert((await page.locator('button[aria-label*="Current inputs"]').count())>0);state.mixed=false;
        state.paused=true;await page.reload();await page.waitForSelector('.slate-game');
        assert((await page.locator('#status').innerText()).includes('Saving paused — storage limit reached'));assert(!(await page.locator('#content').innerText()).includes('Calculation pending'));
        state.paused=false;await page.goto('http://board.invalid/arbs');await page.waitForSelector('.empty');
        await page.getByRole('button',{name:'Show all comparisons',exact:true}).click();await page.waitForSelector('.slate-arb');assert.equal(await page.locator('.slate-arb').count(),28);
        if(process.env.PREDICT_SLATE_SCREENSHOTS)await page.screenshot({path:path.join(process.env.PREDICT_SLATE_SCREENSHOTS,'authored-arbs-'+width+'.png')});
        const pairKey=secondKey+':'+fixture.pair.pair.id,button=page.locator('button[data-key="'+pairKey+'"]');await button.click();await page.waitForSelector('#detail-content dl');
        const detailUrl=requests.filter(u=>u.pathname==='/api/boards/details').at(-1);assert.equal(detailUrl.searchParams.get('game'),secondKey);assert.equal(detailUrl.searchParams.get('context_id'),currentContext(fixture.arbs.policy,secondKey).context_id);assert(!detailUrl.searchParams.has('result_id'));
        await page.locator('#detail-content details[data-key=originals] summary').click();const detailReads=requests.filter(u=>u.pathname==='/api/boards/details').length;
        await page.clock.runFor(10010);await page.waitForFunction(()=>document.getElementById('details').open);await page.waitForTimeout(50);
        assert(requests.filter(u=>u.pathname==='/api/boards/details').length>detailReads,'arrival refreshes exact held Details');assert(await page.locator('#detail-content details[data-key=originals]').evaluate(el=>el.open));assert.equal(requests.filter(u=>u.pathname==='/api/boards/details').at(-1).searchParams.get('game'),secondKey);
        assert.equal(await page.getByRole('button',{name:'Load original input envelopes'}).count(),0);
        assert.equal(requests.filter(u=>u.pathname==='/api/boards/history').length,0);
        state.changedDetails=true;
        await page.clock.runFor(10010);await page.waitForFunction(()=>document.getElementById('detail-content').textContent.includes('Current inputs changed'));
        assert.equal(await page.locator('#detail-content dl').count(),0,'changed input clears all old money, prices and ages');
        state.changedDetails=false;
        await page.locator('#close-details').focus();
        await page.keyboard.press('Shift+Tab');assert(await page.evaluate(()=>document.getElementById('details').contains(document.activeElement)));
        await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement.id),'close-details');await page.keyboard.press('Escape');assert.equal(await page.evaluate(()=>document.activeElement.dataset.key),pairKey);
        await page.locator('#sort').selectOption('start');assert((await page.locator('.slate-comparison-game').first().innerText()).includes(fixture.catalog.games[0].title));
        await page.locator('#search').fill('Second');assert.equal(await page.locator('.slate-arb').count(),14);await page.locator('#search').fill('');
        await page.locator('.calculation-settings>summary').click();
        await page.locator('#amount').fill('1250');
        await page.clock.runFor(10010);await page.waitForTimeout(30);
        assert.equal(await page.locator('#amount').inputValue(),'1250','polls preserve the expanded settings draft');
        await page.locator('#amount').fill('0');await page.locator('#amount').press('Enter');
        assert.equal(await page.locator('#status').getAttribute('data-state'),'error','invalid funding has visible feedback');
        await page.locator('#restore').click();await page.waitForSelector('.slate-arb');assert.equal(await page.locator('#amount').inputValue(),'1000');assert.equal(await page.locator('#game').inputValue(),'');
        await page.evaluate(()=>document.documentElement.style.fontSize='20px');assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'no document overflow at enlarged text');
        state.failure=true;await page.reload();await page.waitForSelector('#retry:not([hidden])');state.failure=false;await page.locator('#retry').click();await page.waitForSelector('.empty');await page.getByRole('button',{name:'Show all comparisons',exact:true}).click();await page.waitForSelector('.slate-arb');
        await page.locator('#stop').click();await page.waitForFunction(()=>document.getElementById('status').textContent.includes('Collection stopped'));assert(await page.locator('#stop').isDisabled());
        state.empty=true;await page.reload();await page.waitForSelector('.empty');assert(!(await page.locator('#settings').isVisible()));assert.equal(await page.getByRole('link',{name:'Check sources in Admin'}).getAttribute('href'),'/admin');
        assert.deepEqual(errors,[]);
        console.log('PASS intercepted slate browser width='+width+' all games, local filters, one batched read, coverage, mixed ages, paused saving, exact cross-game Details/focus/arrivals, sort, restore, failure/retry and Stop/empty');
      } catch(error) { const folder=path.resolve('test-results/slate-browser');fs.mkdirSync(folder,{recursive:true});await page.screenshot({path:path.join(folder,'failure-'+width+'.png'),fullPage:true});throw error; }
      finally {await context.close();}
    }
    // The actual controller must collect all bounded pages before publishing.
    const pagingContext=await browser.newContext({viewport:{width:1280,height:900},serviceWorkers:'block'}),pagingPage=await pagingContext.newPage();
    const many=Array.from({length:500},(_,i)=>({...copy(catalog[0]),game_key:'authored-page-game:'+i,title:'Authored game '+i}));
    let pageRequests=0,revisionChanged=false;
    await pagingContext.route('**/*',async route=>{
      const url=new URL(route.request().url());assert.equal(url.hostname,'paging.invalid');
      if(url.pathname.startsWith('/current/assets/'))return route.fulfill({path:path.join(assets,path.basename(url.pathname)),contentType:url.pathname.endsWith('.js')?'text/javascript':'text/css'});
      if(url.pathname==='/api/boards/slate'){
        pageRequests++;const offset=Number(url.searchParams.get('offset')),limit=Number(url.searchParams.get('limit'));assert.equal(limit,50);
        if(offset)assert.equal(url.searchParams.get('expected_revision'),'authored-read-500');
        if(revisionChanged&&offset)return route.fulfill({status:409,json:{reason:'current_slate_changed'}});
        const boards=many.slice(offset,offset+limit).map(g=>{const b=currentBoard(fixture.odds,g.game_key);b.prices=[];return b;});
        return route.fulfill({json:{version:'predict-comparison-slate-2',epoch:'authored-reset-1',view:'odds',filter:'all',policy:fixture.odds.policy,games:many,boards,errors:[],stopped:false,read_revision:'authored-read-500',coverage:coverage(500,offset,limit),bounds}});
      }
      if(!url.pathname.startsWith('/api/'))return route.fulfill({path:path.join(assets,'stored.html'),contentType:'text/html'});
      throw Error('Unexpected paged request '+url.pathname);
    });
    try{
      await pagingPage.goto('http://paging.invalid/');await pagingPage.waitForSelector('.slate-game');
      assert.equal(await pagingPage.locator('.slate-game').count(),500);assert.equal(pageRequests,10);
      assert((await pagingPage.locator('.slate-summary').innerText()).includes('500 of 500 games'));
      await pagingPage.locator('#search').fill('Authored game 499');assert.equal(await pagingPage.locator('.slate-game').count(),1);assert.equal(pageRequests,10,'filter remains local after all pages');
      revisionChanged=true;await pagingPage.reload();await pagingPage.waitForSelector('#retry:not([hidden])');
      assert.equal(await pagingPage.locator('.slate-game').count(),0,'changed page never publishes partial first-page counts or prices');
      console.log('PASS actual controller: all 500 events in ten coherent bounded pages; selected search preserved; changed page withholds incomplete slate');
    }finally{await pagingContext.close();}
    // Native Window timers must work without Playwright's clock replacement.
    // The original-input dialog pauses the actual controller, then closing it
    // resumes automatic pending reads and eventually selects the stable delay.
    const context=await browser.newContext({viewport:{width:1265,height:712},timezoneId:'America/New_York',serviceWorkers:'block'}),page=await context.newPage(),errors=[],state={pending:true,paused:false,stopped:false};let nativeReads=0,active=0,maximumActive=0;
    page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
    await context.route('**/*',async route=>{
      const url=new URL(route.request().url());assert.equal(url.hostname,'native-timers.invalid');
      if(url.pathname.startsWith('/current/assets/'))return route.fulfill({path:path.join(assets,path.basename(url.pathname)),contentType:url.pathname.endsWith('.js')?'text/javascript':'text/css'});
      if(url.pathname==='/api/boards/slate'){
        nativeReads++;active++;maximumActive=Math.max(maximumActive,active);state.pending=nativeReads<=2;
        await new Promise(resolve=>setTimeout(resolve,50));await route.fulfill({json:slate(url.searchParams.get('view'),url.searchParams.get('filter'),state)});active--;return;
      }
      if(url.pathname==='/api/boards/inputs')return route.fulfill({json:{version:'predict-board-inputs-2',game_key:url.searchParams.get('game'),calculation_context:currentContext(fixture.odds.policy,url.searchParams.get('game')),quote_id:url.searchParams.get('quote'),evidence:{source:'authored'}}});
      if(!url.pathname.startsWith('/api/'))return route.fulfill({path:path.join(assets,'stored.html'),contentType:'text/html'});
      throw Error('Unexpected native-timer request '+url.pathname);
    });
    try {
      await page.goto('http://native-timers.invalid/');await page.waitForSelector('.slate-game');assert.equal(nativeReads,1);
      await page.locator('.slate-price-cell button').first().click();await page.waitForSelector('#details[open]');await page.waitForTimeout(2300);assert.equal(nativeReads,1,'original-input modal pauses native polling');
      await page.locator('#close-details').click();await page.waitForFunction(()=>!document.getElementById('status').textContent.includes('calculations pending'),{timeout:12000});
      assert.equal(nativeReads,3,'native timers continue across pending replies until complete');assert.equal(maximumActive,1);await page.waitForTimeout(2300);assert.equal(nativeReads,3,'stable native timer waits ten seconds');assert.deepEqual(errors,[]);
      console.log('PASS real native Window timers: original-input pause/resume, three automatic pending→complete saved reads, one in-flight read, stable delay and zero console errors');
    }finally{await context.close();}
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

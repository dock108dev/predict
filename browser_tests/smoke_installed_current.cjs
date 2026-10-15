// Bounded, read-only D03 smoke against the explicitly supplied local installation.
// Creates isolated browser preferences; never changes owner settings or presses Stop/Refresh.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PREDICT_PLAYWRIGHT_MODULE||'playwright');
const target=process.env.PREDICT_INSTALLED_SMOKE_URL,folder=process.env.PREDICT_INSTALLED_SMOKE_OUTPUT;
assert(target&&folder,'Explicit local installed URL and evidence destination required');
const base=new URL(target);assert(['localhost','127.0.0.1','[::1]'].includes(base.hostname),'Installed smoke must target an explicit loopback server');
const output=path.resolve(folder);fs.mkdirSync(output,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PREDICT_CI_CHROMIUM?{executablePath:process.env.PREDICT_CI_CHROMIUM}:{})});
 const report={evidence_class:'Actual installation read-only D03 smoke; no live coverage or owner acceptance claim',url:base.origin,checks:[],errors:[],reported_provider_requests:0,provider_request_evidence:'Zero slate counters; Details may omit its counter; GET-only comparison routes do not acquire',mutations:0,owner_preferences:'isolated browser context; unchanged',full_d04:false};
 try{for(const width of [1280,390]){
  const context=await browser.newContext({viewport:{width,height:900},timezoneId:'America/New_York',serviceWorkers:'block'}),page=await context.newPage(),errors=[],requests=[],responses=[];
  page.on('pageerror',e=>errors.push('page: '+e.message));page.on('console',m=>{if(m.type()==='error'&&!(/409/.test(m.text())&&m.location().url.includes('/api/boards/details')))errors.push('console: '+m.text());});
  await context.route('**/*',async route=>{
   const req=route.request(),url=new URL(req.url());
   if(req.method()!=='GET'||url.origin!==base.origin){report.mutations+=req.method()==='GET'?0:1;errors.push('Refused request '+req.method()+' '+url.pathname);return route.abort();}
   const allowed=['/','/ev','/arbs'].includes(url.pathname)||url.pathname.startsWith('/current/assets/')||['/api/boards/slate','/api/boards/details','/api/boards/inputs'].includes(url.pathname);
   if(!allowed){if(url.pathname==='/favicon.ico')return route.fulfill({status:204});errors.push('Refused unexpected read '+url.pathname);return route.abort();}
   requests.push({method:req.method(),path:url.pathname,query:Object.fromEntries(url.searchParams)});return route.continue();
  });
  page.on('response',response=>{
   if(!new URL(response.url()).pathname.startsWith('/api/'))return;
   responses.push((async()=>{
    const v=await response.json(),routePath=new URL(response.url()).pathname;
    if(Object.hasOwn(v,'provider_requests')){if(v.provider_requests!==0)errors.push('Nonzero API provider request counter: '+routePath);report.reported_provider_requests+=v.provider_requests||0;}
    else if(routePath!=='/api/boards/details')errors.push('Required slate provider request counter absent: '+routePath);
    return {path:routePath,status:response.status(),provider_requests:v.provider_requests??null,provider_counter_supplied:Object.hasOwn(v,'provider_requests'),version:v.version,coverage:v.coverage,error:v.error,reason:v.reason};
   })().catch(error=>{
    if(/No data found|navigated away|aborted|Target closed/i.test(error.message))return {path:new URL(response.url()).pathname,status:response.status(),observation:'response body cancelled during browser navigation',provider_requests:null};
    errors.push('Response observation failed: '+error.message);return {path:new URL(response.url()).pathname,observation_error:error.message};
   }));
  });
  try{
   for(const view of ['odds','ev','arbs']){
    await page.goto(new URL(view==='odds'?'/':'/'+view,base).href);
    await page.waitForFunction(()=>{const n=document.getElementById('status');return n&&!n.textContent.startsWith('Loading')&&(document.querySelector('.slate-summary')||!document.getElementById('retry').hidden);},null,{timeout:45000});
    assert(await page.locator('#retry').isHidden(),'Current read unavailable: '+await page.locator('#status').innerText());
    if(view!=='odds'&&await page.locator('#filters').isVisible()){
     await page.locator('#filters [data-filter=all]').click();
     await page.waitForFunction(()=>!document.getElementById('retry').hidden||document.querySelector('.slate-summary')?.textContent.includes('all current results'),null,{timeout:45000});
     assert(await page.locator('#retry').isHidden());
    }
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);assert(!overflow,view+' overflow at '+width);
    await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:path.join(output,view+'-'+width+'.png')});
    const check={width,view,status:await page.locator('#status').innerText(),games:await page.locator('#game option').count()-1,rows:await page.locator('.slate-result').count(),overflow,details:'not_selected'};
    if(view==='ev'&&check.rows){
     check.details_attempts=[];
     for(let attempt=0;attempt<2;attempt++){
      const selected=page.locator('.slate-result button').first();if(!await selected.count())break;
      const key=await selected.getAttribute('data-key');await selected.click();
      await page.waitForFunction(()=>document.querySelector('#detail-content dl')||document.querySelector('#detail-content .warning'),null,{timeout:45000});
      const warning=page.locator('#detail-content .warning');
      if(await warning.count()){
       const message=await warning.innerText();assert(message.includes('current_inputs_changed_or_removed')||message.includes('current_selection_removed'),'Unexpected Details refusal: '+message);
       assert.equal(await page.locator('#detail-content dl').count(),0,'Changed context removes old money');
       check.details='changed_or_removed_explicit_coherent_state';check.details_attempts.push({attempt:attempt+1,state:check.details,message});
       await page.screenshot({path:path.join(output,'details-changed-'+width+'-'+attempt+'.png')});await page.locator('#close-details').click();
       if(attempt===0){
        // One permitted fresh GET navigation/reselection, never acquisition.
        await page.goto(new URL('/ev',base).href);await page.waitForSelector('.slate-summary',{timeout:45000});
        if(!await page.locator('#filters').isVisible())break;
        await page.locator('#filters [data-filter=all]').click();await page.waitForFunction(()=>document.querySelector('.slate-summary')?.textContent.includes('all current results')||!document.getElementById('retry').hidden,null,{timeout:45000});assert(await page.locator('#retry').isHidden());
        continue;
       }
       break;
      }
      assert.equal(await page.locator('#detail-content dl').count(),1);assert(!(await page.locator('#detail-content').innerText()).includes('Saved calculation history'));
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      await page.screenshot({path:path.join(output,'details-'+width+'.png')});
      await page.locator('#close-details').click();assert.equal(await page.evaluate(()=>document.activeElement.dataset.key),key);check.details='current_context_opened_and_closed_focus_restored';check.details_attempts.push({attempt:attempt+1,state:check.details});break;
     }
    }
    await Promise.all(responses);
    report.checks.push(check);
   }
   const api=await Promise.all(responses);assert.deepEqual(errors,[]);report.checks.push({width,api_reads:api,only_gets:requests.every(r=>r.method==='GET'),console_errors:errors});
  }catch(e){errors.push(e.message);report.errors.push({width,errors});await page.screenshot({path:path.join(output,'failure-'+width+'.png')});}
  finally{await context.close();}
 }}finally{await browser.close();}
 report.all_passed=report.errors.length===0&&report.mutations===0;report.details_available=report.checks.filter(c=>c.view==='ev').every(c=>c.details==='current_context_opened_and_closed_focus_restored');
 fs.writeFileSync(path.join(output,'installed-smoke.json'),JSON.stringify(report,null,2)+'\n');
 assert(report.all_passed,JSON.stringify(report.errors));console.log('PASS D03 installed smoke 1280/390: Odds/EV/Arbs, available current Details, no overflow/console errors, GET-only no-acquisition reads; details_available='+report.details_available);
})().catch(e=>{console.error(e);process.exitCode=1;});

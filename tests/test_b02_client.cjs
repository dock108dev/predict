// Authored availability mutations around authentic current-row API responses.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {pathToFileURL}=require('node:url');
const {Element}=require('./ev07_dom.cjs');
(async()=>{
 const {checkAvailability,checkBoard,SlateAccumulator}=await import(pathToFileURL(path.resolve('app/dashboard/opportunity_static/current/board-client.js')));
 const {createComparisonSlate}=await import(pathToFileURL(path.resolve('app/dashboard/opportunity_static/current/comparison-slate-views.js')));
 const f=JSON.parse(fs.readFileSync(process.argv[2]||'/tmp/predict-u02-api-output.json'));
 const context=v=>({amount:v.policy.requested_amount_usd,buffer:v.policy.buffer_rate,benchmark_venue:v.policy.benchmark_venue,benchmark_method:v.policy.benchmark_method,view:v.view,filter:v.filter,game:v.game_key});
 checkAvailability(f.ev.availability,true);checkBoard(f.ev,context(f.ev));
 const r=f.ev.rows.find(r=>r.availability.state==='numeric_last_known');assert(r);
 const bad=structuredClone(f.ev);const b=bad.rows.find(r=>r.availability.state==='numeric_last_known');b.ranking_eligible=true;
 assert.throws(()=>checkBoard(bad,context(bad)),/Last-known/);
 const missing=structuredClone(f.ev.availability);missing.numeric_results++;assert.throws(()=>checkAvailability(missing,true),/counts/);
 const acc=new SlateAccumulator(context(f.slate));acc.append(f.slate,JSON.stringify(f.slate).length);const complete=acc.result();
 const inspected=f.slate.boards.flatMap(b=>b.rows);
 assert.equal(complete.availability.numeric_results,inspected.filter(r=>r.availability.numeric_metrics.length).length);
 assert.equal(complete.availability.counts.missing_reference,inspected.filter(r=>r.availability.state==='missing_reference').length);
 assert.equal(complete.availability.counts.unsupported_inputs,inspected.filter(r=>r.availability.state==='unsupported_inputs').length);
 const content=new Element('div');const draw=createComparisonSlate({content,onDetails(){},onOriginal(){}});
 const v=structuredClone(f.slate);v.boards.forEach(b=>b.rows=[]);draw.draw(v,{view:'ev',filter:'positive'});
 assert(content.textContent.includes('Last-known estimates available'));assert(content.textContent.includes('View last-known estimates')); 
 assert(!content.textContent.includes('No positive EV found'));
 // An entirely unevaluated scope has no successful-empty claim.
 v.boards.forEach(b=>b.availability.outcome='unavailable');draw.draw(v,{view:'ev',filter:'positive'});
 assert(!content.textContent.includes('No positive EV found'));
 const failed=structuredClone(f.slate);failed.boards=[];failed.errors=failed.games.map(g=>({game_key:g.game_key,reason:'authored_failure',availability:{version:'predict-calculation-availability-1',state:'calculation_failed',reason_codes:['calculation_read_failed'],numeric_metrics:[],metrics:{},current_opportunity_eligible:false}}));
 failed.availability={...failed.availability,total_results:failed.games.length,numeric_results:0,current_results:0,positive_results:0,outcome:'unavailable',counts:{numeric_current:0,numeric_last_known:0,missing_reference:0,unsupported_inputs:0,calculation_failed:failed.games.length,not_evaluated:0},causes:[]};
 const allFailed=new SlateAccumulator(context(failed));allFailed.append(failed,JSON.stringify(failed).length);
 assert.equal(allFailed.result().availability.counts.calculation_failed,failed.games.length);
 assert.equal(allFailed.result().availability.outcome,'unavailable');
 console.log('PASS B02 exact numeric states, conservative current guard, scoped counts and truthful empty rendering');
})().catch(e=>{console.error(e);process.exitCode=1;});

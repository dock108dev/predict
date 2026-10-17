const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
  const data=source=>'data:text/javascript;base64,'+Buffer.from(source).toString('base64');
  const ticket=data(fs.readFileSync('app/dashboard/opportunity_static/current/ticket-client.js','utf8'));
  const source=fs.readFileSync('app/dashboard/opportunity_static/current/scanner-summaries.js','utf8').replace("from './ticket-client.js'","from '"+ticket+"'");
  const {checkSummary,summaryQuery,summaryCopy,bootSummaries,SUMMARY_BOUNDS}=await import(data(source));
  const clone=x=>JSON.parse(JSON.stringify(x)),examples={};
  for(const name of ['observed','checked-zero','unavailable','joint-threshold-incomplete'])examples[name]=JSON.parse(fs.readFileSync('docs/examples/opportunity-summaries-1/'+name+'.json'));
  const v=examples.observed,filters=v.filters,context={server_id:v.server_id,epoch:v.epoch};
  for(const example of Object.values(examples))assert.equal(checkSummary(example,example.filters,context),example);
  const malformed=edit=>{const bad=clone(v);edit(bad);assert.throws(()=>checkSummary(bad,filters,context));};
  malformed(x=>x.epoch='other');malformed(x=>x.filters.category='ev');malformed(x=>x.counts.observed_episodes=10001);
  malformed(x=>x.edge_percent.maximum='1/0');malformed(x=>x.duration_seconds.maximum_observed=Infinity);
  malformed(x=>x.history.complete=true);malformed(x=>x.bounds.physical_bytes=10485761);malformed(x=>x.provider_requests=1);
  malformed(x=>{x.coverage.checked_zero=true;x.coverage.complete=false;});
  const zero=clone(examples['checked-zero']);zero.coverage.compatible_pairs=0;assert.throws(()=>checkSummary(zero,zero.filters,context));
  const unknown=clone(examples.unavailable);unknown.coverage.checked_zero=false;assert.throws(()=>checkSummary(unknown,unknown.filters,context));
  assert.equal(summaryQuery(filters).toString(),'category=covered_outcome_arb');
  const selected=clone(filters);selected.venues=['kalshi','polymarket_us'];selected.minimum_edge='2';selected.minimum_size='70';
  assert.equal(summaryQuery(selected).get('minimum_size'),'70');assert(!summaryQuery(selected).has('offset'));
  assert.match(summaryCopy(v).count,/3 observed arb episodes/);assert.match(summaryCopy(v).range,/Edge and size maxima may differ/);
  assert.match(summaryCopy(examples['joint-threshold-incomplete']).coverage,/threshold matches are incomplete/);
  assert.match(summaryCopy(examples.unavailable).count,/zero is not established/);
  assert.match(summaryCopy(examples['checked-zero']).coverage,/checked; no current matches/);
  const historical=clone(v);historical.coverage.checked_zero=true;checkSummary(historical,filters,context);
  class Node extends EventTarget{constructor(){super();this.textContent='';this.open=false;}}
  const elements=new Map(['disclosure','summary-count','summary-range','summary-coverage'].map(k=>['scanner-'+k,new Node()]));
  const original={document:globalThis.document,window:globalThis.window,performance:globalThis.performance,fetch:globalThis.fetch,addEventListener:globalThis.addEventListener};
  globalThis.document=new EventTarget();document.hidden=false;document.getElementById=id=>elements.get(id);
  globalThis.window={};globalThis.addEventListener=()=>{};
  let time=0,calls=[],pending=[];Object.defineProperty(globalThis,'performance',{value:{now:()=>time},configurable:true});
  let mode='ready';globalThis.fetch=async(url,options)=>{calls.push({url,options});if(mode==='pending')return new Promise(resolve=>pending.push(resolve));if(mode==='large')return new Response(' '.repeat(65537));return new Response(JSON.stringify(v));};
  const session=bootSummaries(),panel=elements.get('scanner-disclosure'),count=elements.get('scanner-summary-count');
  session.observe(filters,context);await session.read();assert.equal(calls.length,0,'collapsed disclosure must not read summaries');
  panel.open=true;await session.read();assert.equal(calls.length,1);assert.match(count.textContent,/3 observed arb episodes/);
  assert.equal(window.predictSummaryObservations().accepted,1);await session.read();assert.equal(calls.length,1,'optional read is throttled');
  document.hidden=true;time=3000;await session.read();assert.equal(calls.length,1);document.hidden=false;
  mode='pending';const old=session.read();await new Promise(setImmediate);assert.equal(calls.length,2);
  session.observe({...filters,category:'ev'},context);assert(calls[1].options.signal.aborted);assert(!count.textContent.includes('3 observed'));
  pending[0](new Response(JSON.stringify(v)));await old;assert(!count.textContent.includes('3 observed'),'old scoped response cannot publish');
  session.observe(filters,context);mode='large';time=6000;await session.read();assert.match(count.textContent,/unavailable/);
  assert.equal(window.predictSummaryObservations().activeReaders,0);assert.equal(SUMMARY_BOUNDS.responseBytes,65536);
  mode='pending';time=9000;const closing=session.read();await new Promise(setImmediate);panel.open=false;panel.dispatchEvent(new Event('toggle'));
  assert(calls.at(-1).options.signal.aborted);pending.at(-1)(new Response(JSON.stringify(v)));await closing;
  session.reset('Collection stopped · observation history is censored.');panel.open=true;await session.read();assert.equal(calls.length,4,'Stop/reset has no old read context');
  for(const [key,value] of Object.entries(original))Object.defineProperty(globalThis,key,{value,configurable:true,writable:true});
  const controller=fs.readFileSync('app/dashboard/opportunity_static/current/scanner-controller.js','utf8');
  assert(controller.includes('void summaries.read();'),'summary read must not delay scanner acceptance');
  assert(controller.includes('timingBytes>2097152'),'causal observation retention has a byte bound');
  assert(controller.includes('domAppliedAt:performance.now()'));assert(controller.includes('source_clocks:r.source_clocks'));
  const metricSource=controller.match(/  const metrics=entry=>\{[^\n]+\};/)[0],events=[];
  const diagnostic=Function('document','CustomEvent','TextEncoder','const timings=[];let timingBytes=0,droppedSamples=0,droppedBytes=0,emittedSamples=0;'+metricSource+'return {push:metrics,read:()=>({timings,timingBytes,droppedSamples,droppedBytes,emittedSamples})};')({dispatchEvent:event=>events.push(event)},class{constructor(type,options){this.type=type;this.detail=options.detail;}},TextEncoder);
  const workload=JSON.parse(fs.readFileSync('tests/fixtures/sc04/workload.json'));
  const sample={kind:'revision',bindings:workload.rows.slice(0,100).map(r=>({row_id:r.id,event_id:r.occurrence_id,pair_id:r.pair_id,dependency_revision:r.dependency_revision,economic_revision:r.economic_revision,native_keys:r.positions.map(p=>p.native_key),source_clocks:r.source_clocks,calculation_started_at:r.calculation_started_at,evaluated_at:r.evaluated_at,calculation_ms:r.calculation_ms}))};
  const size=new TextEncoder().encode(JSON.stringify(sample)).length;
  for(let i=0;i<256;i++)diagnostic.push(sample);
  const stats=diagnostic.read();assert.equal(stats.timings.length,Math.min(256,Math.floor(2097152/size)));
  assert.equal(stats.droppedSamples,256-stats.timings.length);assert.equal(stats.emittedSamples,256);assert.equal(events.length,256);
  assert.equal(stats.droppedBytes,stats.droppedSamples*size);assert(stats.timingBytes<=2097152);assert(stats.droppedSamples>0,'large pages disclose diagnostic eviction');
  // Product HTTP proofs come from the durable checkpoint, independently of
  // the small latest-request ring and unrelated trace/poll activity.
  {
    const crypto=require('node:crypto'),os=require('node:os'),path=require('node:path');
    const {Harness}=require('../browser_tests/sc06_support.cjs');
    const folder=fs.mkdtempSync(path.join(os.tmpdir(),'predict-sc06-http-proof-'));
    try {
      const entries=[],expectedTickets=[];
      for(let i=0;i<3300;i++){
        entries.push({stage:'fixture_non_http',index:i,path:'/__test/state',note:'Original Unicode 雪 and escaped\nline'});
        if(i<30){
          const ticket={state:'unchanged',ready_for_manual_action:true,
            selection:{row_id:'row:'+i,dependency_revision:'dependency:'+i,economic_revision:'economic:'+i},
            timing:{validation_ms:i},error:null,
            selected_frame:{id:'early-ticket-frame:'+i,dependency_revision:'dependency:'+i,expires_at:'2030-01-01T00:00:00Z'}};
          expectedTickets.push(ticket);
          entries.push({stage:'product_http',path:'/api/scanner/ticket',method:'POST',started:i+.1,completed:i+.2,status:200,ticket});
        }
      }
      const prefix=Buffer.from(entries.map(entry=>JSON.stringify(entry)).join('\n')+'\n');
      const file=path.join(folder,'raw.jsonl');
      fs.writeFileSync(file,prefix);
      // Orderly shutdown may append after the final benchmark checkpoint.
      fs.appendFileSync(file,JSON.stringify({stage:'after_checkpoint',must_not_join:true})+'\n');
      const final={requests:[{path:'/__test/state',method:'GET'},entries.findLast(entry=>entry.stage==='product_http')],
        recorder:{product_http:{product_entries:30,durable_enqueued:30,durable_enqueue_failed:0},
          stream:{path:file,written_bytes:prefix.length,written_entries:entries.length,dropped:0,error:null}}};
      const harness=Object.create(Harness.prototype);harness.resources=()=>{};
      await harness.loadTraces(final);
      assert.equal(final.requests.length,30,'all early HTTP proofs survive the latest-request ring');
      assert.deepEqual(final.requests.map(entry=>entry.ticket),expectedTickets);
      assert.equal(final.requests[0].ticket.selected_frame.id,'early-ticket-frame:0');
      assert(final.requests.every(entry=>entry.stage==='product_http'&&entry.path==='/api/scanner/ticket'));
      assert(!final.requests.some(entry=>entry.path.startsWith('/__test/')),'test polls cannot become product request proofs');
      assert.deepEqual(final.request_proof_source,{kind:'durable_product_http_stream',entries:30});
      assert.equal(final.traces.length,entries.length);
      assert(final.traces.every((entry,index)=>entry.raw_trace_line===index+1));
      assert(!final.traces.some(entry=>entry.stage==='after_checkpoint'));
      assert.equal(final.trace_stream_checkpoint.entries,entries.length);
      assert.equal(final.trace_stream_checkpoint.bytes,prefix.length);
      assert.equal(final.trace_stream_checkpoint.sha256_prefix,crypto.createHash('sha256').update(prefix).digest('hex'));
      assert(fs.statSync(file).size>final.trace_stream_checkpoint.bytes,'checkpoint excludes later shutdown bytes');
      const missingProof={recorder:clone(final.recorder)};missingProof.recorder.product_http.durable_enqueued=31;
      await assert.rejects(harness.loadTraces(missingProof),/all durable product HTTP entries reconstructed/);
    } finally {fs.rmSync(folder,{recursive:true,force:true});}
  }
  console.log('PASS SC06 scope validation, coverage-backed zero, censoring, rational extrema, bounded optional reads, abort/late scope isolation, causal diagnostic bounds and durable early HTTP ticket proofs');
})().catch(e=>{console.error(e);process.exitCode=1;});

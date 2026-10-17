/* Full-finance actual500-event SQL → projection → HTTP → Chromium qualification. */
const assert=require('node:assert/strict'),os=require('node:os');
const {Harness,MaterialFeed,wait,stats,complete}=require('./sc06_support.cjs');
(async()=>{
 const h=new Harness('timing',8817),r=h.report;Object.assign(r,{samples:[],ticket_samples:[],feed_admissions:[],machine:{platform:os.platform(),release:os.release(),arch:os.arch(),cpus:os.cpus().length,cpu:os.cpus()[0]?.model,total_memory:os.totalmem()}});
 let feed=null;
 try{
  await h.start();const page=h.page;
  r.cold=await h.completePaint();r.cold.first_usable_ms=r.cold.first_usable?.paintedAt??null;r.cold.first_complete_ms=r.cold.complete?r.cold.dom.second_frame_observed_at:null;
  r.cold.boundary='navigation-relative browser performance.now; initial typed SQL admission precedes browser launch';r.cold.required_gate=false;r.cold.classification=r.cold.complete?'quiet cold complete before original expiry':'quiet cold incomplete/expired; retained separately from required warm responsiveness';r.cold.correlation=h.correlation;
  if(!r.cold.complete)r.failures.push({stage:'cold_first_complete',required_gate:false,reason:'No actual complete500-event publication and exact visible second-frame observation before bounded70s wait; cold partial/expiry is retained, and genuine material catchup must establish required warm baseline.'});
  const index=0;r.selected_event_index=index;
  if(process.env.PREDICT_SC06_MATERIAL_FEED==='1'){
   feed=new MaterialFeed(h,index);await feed.start();h.write('timing.json');
  }else r.material_feed={enabled:false,definition:'No background clock or material updates; only explicitly recorded controlled2leg samples.'};
  // The required warm baseline comes from actual complete500 current finance.
  // A declared genuine material feed may establish it after quiet cold expiry.
  const warmBaseline=feed?await feed.enter(0):await h.state();r.warm_baseline=warmBaseline;
  assert(complete(warmBaseline),'required warm baseline must be actual500 current/complete before reload');
  await page.reload();await h.correlate();
  const warm=await h.completePaint(3000,'warm',warmBaseline);r.warm={...warm,baseline:warmBaseline,usable_ms:warm.complete?warm.dom.second_frame_observed_at:null,baseline_complete:complete(warmBaseline),qualification:warm.complete&&complete(warmBaseline)?'complete500-event warm publication':'incomplete; not qualified'};
  if(feed)feed.leave();h.write('timing.json');
  assert(r.warm.complete&&r.warm.usable_ms>=0&&r.warm.usable_ms<=3000,'required actual500 current warm reload did not paint within3s');
  await h.screenshot('warm-scanner');if(process.env.PREDICT_SC06_COLD_ONLY==='1'){r.diagnostic_only=true;r.qualified=false;r.final=await h.state(true);await h.loadTraces(r.final);h.write('timing.json');console.log(JSON.stringify({diagnostic_only:true,cold_complete:r.cold.complete,cold_ms:r.cold.first_complete_ms,warm_complete:r.warm.complete,warm_ms:r.warm.usable_ms,coverage:r.final.global_coverage,peak_python_rss_bytes:r.final.peak_rss_bytes}));return;}let correlation=h.correlation;
  for(let i=0;i<30;i++){
   if(i%10===0)correlation=await h.correlate();
   if(feed)await feed.enter(0);
   const admission=await h.update(i+1,index);if(feed)feed.claimTarget(admission);const observed=await h.paintFor(admission),scope=await h.state();
   const sample={sample:i+1,admission,...observed,scope,correlation};
   if(observed.paint){sample.exact_commit_match=observed.paint.causal?.sql_post_commit_observation?.current_rows_revision===admission.commit_observation?.current_rows_revision;sample.accepted_to_painted_ms=observed.paint.paintedAt-observed.paint.acceptedAt;if(observed.dom?.exists){sample.receipt_to_painted_ms=observed.dom.second_frame_observed_at-(admission.receipt_monotonic*1000+correlation.offset_ms);sample.uncertainty_ms=correlation.uncertainty_ms;}}
   r.samples.push(sample);if(feed)feed.leave();if(!sample.matched)r.failures.push({stage:'material',sample:i+1,disposition:observed.paint?'superseded_or_not_visible':'bounded18s_timeout'});h.resources();h.write('timing.json');
  }
  await h.screenshot('material-updates');
  for(let i=0;i<30;i++){await page.locator('#scanner-search').fill(i%2?'Authored':'000');await wait(35);}await page.locator('#scanner-search').fill('');await wait(70);
  r.local_filter_samples=await page.evaluate(()=>window.predictScannerObservations().timings.filter(t=>t.kind==='filter-local'));
  // A selected attempt always follows its own actual material source receipt.
  // Only the ready frame's own second-rAF event counts as usable latency.
  for(let i=0;i<30;i++){
   if(i%10===0)correlation=await h.correlate();
   if(feed)await feed.enter(0);
   const admission=await h.update('ticket-'+(i+1),index);if(feed)feed.claimTarget(admission);const material=await h.paintFor(admission),sample={sample:i+1,admission,material,ready:false,correlation};
   r.ticket_samples.push(sample);
   if(!material.matched){sample.reason='matching current visible row unavailable';r.failures.push({stage:'selected_ticket',sample:i+1,reason:sample.reason});if(feed)feed.leave();continue;}
   const row=material.row;await h.post('/__test/destinations?row_id='+encodeURIComponent(row.row_id),{});
   const selector='[data-row-id="'+row.row_id+'"] button',target=page.locator(selector);
   if(!await target.count()){sample.reason='row absent from delivered global page';if(feed)feed.leave();continue;}
   sample.before_scope=await h.state();sample.began=await page.evaluate(()=>performance.now());await target.click();
   const started=Date.now();let terminal=null;
   while(Date.now()-started<18000){terminal=await page.evaluate(began=>{const observation=window.predictTicketObservations?.(),paint=window.sc06Tickets.find(s=>s.operation==='select'&&s.started>=began);if(paint)return {paint,current_ready:observation?.ready,state:observation?.state,selection:observation?.selection};if(observation&&!observation.active&&document.getElementById('scanner-selection-status').textContent.includes('unavailable'))return {paint:null,current_ready:false,state:observation.state,status:document.getElementById('scanner-selection-status').textContent};return null;},sample.began);if(terminal)break;await wait(20);}
   sample.terminal=terminal;sample.timeout_ms=terminal?null:18000;sample.scope=await h.state();
   const painted=terminal?.paint,selection=terminal?.selection;
   sample.ready=!!(painted?.ready&&terminal.current_ready===true&&painted.visible===true&&painted.status?.includes('Ready for manual inspection')&&typeof painted.frame_id==='string'&&selection?.row_id===row.row_id&&selection.dependency_revision===row.dependency_revision&&selection.economic_revision===row.economic_revision);
   sample.total_ms=sample.ready?painted.totalMs:null;sample.waiting_ms=await page.evaluate(()=>performance.now())-sample.began;
   if(!sample.ready)r.failures.push({stage:'selected_ticket',sample:i+1,reason:terminal?'nonready terminal':'bounded18s timeout'});
   await page.keyboard.press('Escape');if(feed)feed.leave();h.resources();h.write('timing.json');
  }
  if(feed)await feed.close();
  r.final=await h.state(true);await h.loadTraces(r.final);h.resources();await h.screenshot('final');
  r.cold.boundary='navigation-relative browser performance.now; initial typed SQL admission precedes browser launch';const initialAdmission=r.final.samples.find(a=>a.sample==='initial'),coldCorrelation=r.cold.original_second_raf_proof?.correlation||r.cold.correlation;if(initialAdmission&&coldCorrelation){r.cold.initial_typed_receipt_to_first_complete_ms=Number.isFinite(r.cold.first_complete_ms)?r.cold.first_complete_ms-(initialAdmission.receipt_monotonic*1000+coldCorrelation.offset_ms):null;r.cold.initial_typed_receipt_to_first_usable_ms=Number.isFinite(r.cold.first_usable_ms)?r.cold.first_usable_ms-(initialAdmission.receipt_monotonic*1000+coldCorrelation.offset_ms):null;}r.warm.boundary='reload navigation-relative browser performance.now';const traces=r.final.traces;if(feed)feed.dispositions(r.final);r.visible_paint_witnesses={file:'timing-visible-paints.jsonl',entries:h.visiblePaints.length,bytes:h.visibleBytes,dropped:h.visibleDropped};
  for(const sample of r.samples){if(!sample.row)continue;const publication=traces.find(t=>t.stage==='publication'&&t.revision===sample.paint.revision),finance=traces.filter(t=>t.stage==='finance'&&t.pair_id===sample.row.pair_id&&t.end<=publication?.end).at(-1),capture=traces.filter(t=>t.stage==='capture'&&t.end<=finance?.start&&t.current_rows_revision===sample.admission.commit_observation?.current_rows_revision).at(-1);
   sample.stages={capture,finance,publication:publication?{...publication,bindings:publication.bindings.filter(b=>b.row_id===sample.row.row_id)}:null,queue_wait_ms:finance&&capture?(finance.start-capture.end)*1000:null,queue_meaning:'upper bound: detached capture completion to financial start',http_request_started_at:sample.paint.requestStartedAt,http_body_available_at:sample.paint.bodyAvailableAt,http_validated_at:sample.paint.acceptedAt,dom_applied_at:sample.paint.domAppliedAt,second_animation_frame_at:sample.paint.paintedAt};
   sample.exact_finance_clocks=!!finance&&finance.source.length===2&&finance.source.every(s=>sample.admission.source.some(a=>a.source.native_event_id===s.source[1]&&a.source_at===s.clocks.source_at));
   sample.complete_proof=sample.matched&&sample.exact_commit_match&&sample.exact_finance_clocks&&!!capture&&!!publication&&sample.paint.revision===publication.revision;
  }
  for(const sample of r.ticket_samples){const frame=sample.terminal?.paint?.frame_id,request=r.final.requests.find(q=>q.method==='POST'&&q.path==='/api/scanner/ticket'&&q.ticket?.selected_frame?.id===frame);sample.backend_request=request||null;sample.fresh_sql_proof=request?traces.find(t=>t.stage==='ticket_fresh_selected'&&t.start>=request.started&&t.end<=request.completed&&t.instruments===2&&t.pairs===1&&t.source.length===2&&t.source.every(s=>sample.admission.source.some(a=>a.source.native_event_id===s.native_key[1]&&a.source_at===s.clocks.source_at))):null;sample.exact_backend_frame=!!frame&&request?.ticket.ready_for_manual_action===true&&request.ticket.selection?.dependency_revision===sample.material.row?.dependency_revision;sample.ready=sample.ready&&sample.exact_backend_frame&&!!sample.fresh_sql_proof;}
  r.qualification_scope='30 controlled exact source operations admitted in complete500 quiet gaps amid declared finite material feed; every background event latency/disposition retained separately. Background batches are not asserted to meet controlled2/3s paint budgets.';r.results={receipt_to_painted:stats(r.samples.filter(s=>s.complete_proof).map(s=>s.receipt_to_painted_ms)),accepted_publication_application:stats(r.samples.filter(s=>s.complete_proof).map(s=>s.accepted_to_painted_ms)),selected_ticket:stats(r.ticket_samples.filter(s=>s.ready).map(s=>s.total_ms)),local_filter:stats(r.local_filter_samples.map(s=>s.ms)),matched_material_samples:r.samples.filter(s=>s.complete_proof).length,ready_ticket_samples:r.ticket_samples.filter(s=>s.ready).length,material_samples_with_complete500_scope:r.samples.filter(s=>complete(s.scope)).length,ticket_samples_with_complete500_scope:r.ticket_samples.filter(s=>complete(s.before_scope)&&complete(s.scope)).length,peak_python_rss_bytes:r.final.peak_rss_bytes,peak_node_rss_bytes:process.resourceUsage().maxRSS*1024,sql_bytes:r.final.sql_bytes,provider_requests:r.final.provider_requests};
  await page.setViewportSize({width:390,height:844});await page.locator('#scanner-disclosure').evaluate(n=>n.open=true);await h.screenshot('mobile-disclosure');r.mobile_horizontal_overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);r.recorder_retention=await h.retention();
  if(feed){const events=feed.admissions.flatMap(a=>a.event_dispositions.map(e=>({...e,kind:a.feed_kind})));r.background_results={event_revisions:events.length,steady_receipt_to_publication:stats(events.filter(e=>e.kind==='steady').map(e=>e.published_after_receipt_ms)),initial_catchup_receipt_to_publication:stats(events.filter(e=>e.kind!=='steady').map(e=>e.published_after_receipt_ms)),published_over3000ms:events.filter(e=>e.published_after_receipt_ms>3000).length,visible_painted:events.filter(e=>!!e.visible_paint).length,unobserved_visible_paint:events.filter(e=>!e.visible_paint).length,quiet_gap_admission_wait:stats(feed.witnesses.map(s=>s.waiting_ms)),claim:'publication latency is separate from paint; no universal2/3s background latency qualification'};}r.qualified=r.warm.baseline_complete&&r.warm.complete&&Number.isFinite(r.warm.usable_ms)&&r.warm.usable_ms>=0&&r.warm.usable_ms<=3000&&r.results.receipt_to_painted.samples===30&&r.results.selected_ticket.samples===30&&r.results.accepted_publication_application.samples===30&&r.results.local_filter.samples>=30&&(!feed||feed.h.report.material_feed.actual_duration_ms<=480000&&!feed.coverageDropped)&&r.results.matched_material_samples===30&&r.results.ready_ticket_samples===30&&r.results.material_samples_with_complete500_scope===30&&r.results.ticket_samples_with_complete500_scope===30&&r.results.receipt_to_painted.p95<=2000&&r.results.receipt_to_painted.max<=3000&&r.results.selected_ticket.p95<=1000&&r.results.selected_ticket.max<=2000&&r.results.accepted_publication_application.p95<=250&&r.results.local_filter.p95<=100&&r.final.recorder.stream.dropped===0&&!r.final.recorder.stream.error&&r.final.trace_stream_checkpoint.entries===r.final.recorder.stream.written_entries&&h.visibleDropped===0&&r.external_requests.length===0&&r.browser_errors.length===0&&r.final.provider_requests===0&&!r.mobile_horizontal_overflow;
  h.write('timing.json');console.log(JSON.stringify({cold_complete_ms:r.cold.first_complete_ms,warm_ms:r.warm.usable_ms,...r.results,qualified:r.qualified}));assert(r.qualified,'SC06 responsiveness gates remain unmet; all measurements and failures retained');
 }catch(error){r.failures.push({stage:'harness',error:String(error),stack:error.stack});h.write('timing.json');throw error;}
 finally{if(feed)await feed.close();await h.close();h.write('timing.json');if(!r.qualified)process.exitCode=1;}
})().catch(e=>{console.error(e);process.exitCode=1;});

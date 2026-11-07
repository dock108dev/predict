// Deterministic asynchronous transport races; no app, SQL or provider access.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {SnapshotLive}=vm.runInNewContext(fs.readFileSync('app/dashboard/opportunity_static/current/snapshot-live.js','utf8')+';({SnapshotLive})',{structuredClone,URLSearchParams});
const copy=structuredClone;
const row=(revision='a')=>({id:'offer',venue:'polymarket_us',source:{provider:'polymarket_us',native_side:'Short'},evidence_result_id:'member-'+revision,price_revision:'price-'+revision,economic_revision:'economic-'+revision,original:{value:revision},conditional_return_percent:'-1',price_current:true,metric_status:{after_trade_fee_ev:{state:'available',reasons:[]}},current_reasons:[],times:{received_at:revision},reference_calculation:{pair:[revision]}});
const result={id:'root-a',generation:1,cursor:'1',assumptions:{revision:'old'},games:[]};
const latest=r=>({state:r?'ready':'removed',row:r,result_id:'root-'+r?.price_revision,generation:2,cursor:'2',assumptions:{revision:'new'}});
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
(async()=>{
 let now=row(),events=[],errors=[],leases=new Map(),nextToken=0,intercept=null;
 async function request(url,body){
   if(intercept){const answer=intercept(url,body);if(answer)return answer;}
   if(body){const token='token-'+(++nextToken);leases.set(token,body.result_id);events.push('retain '+token);return {lease_id:token,result_id:body.result_id};}
   if(url.includes('/selection'))return latest(copy(now));
   const q=new URL('http://fixture'+url).searchParams,revision=q.get('result_id').replace('member-','');
   events.push('details '+revision);return {row:row(revision),evidence_result_id:q.get('result_id'),assumptions:{revision},originals:[revision],references:[revision]};
 }
 const controller=SnapshotLive.create({request,release:t=>{events.push('release '+t);leases.delete(t);},onError:e=>errors.push(e)});
 await controller.open(now,result,'conditional_return_percent');const original=controller.state.pinned;
 now={...row(),times:{received_at:'identical confirmation'},captured_at:'new',evidence_result_id:'confirmation-member'};
 await controller.check();assert.equal(controller.state.notice,null,'confirmation clocks/member IDs are not material');
 // Reference-only economic change, followed by withdrawal on the same root.
 now={...row(),economic_revision:'reference-b',conditional_return_percent:'-3'};
 await controller.check();assert.equal(controller.state.pinned,original);assert.equal(controller.state.notice.old.after_trade_fee,'-1');assert.equal(controller.state.notice.latest.after_trade_fee,'-3');
 now={...now,conditional_return_percent:null,metric_status:{after_trade_fee_ev:{state:'withdrawn',reasons:['fee_expired']}}};
 await controller.check();assert.equal(controller.state.notice.latest.after_trade_fee,null);assert.equal(controller.state.pinned.row.conditional_return_percent,'-1');
 // Atomic adoption: dependencies and lease become one new object, only then old lease released.
 now=row('b');events=[];await controller.adopt();assert.equal(controller.state.pinned.row.price_revision,'price-b');assert.equal(controller.state.pinned.details.references[0],'b');assert.equal(controller.state.pinned.result.assumptions.revision,'new');assert.equal(controller.state.pinned.details.assumptions.revision,'b');assert.equal(leases.size,1);assert(events.indexOf('details b')<events.findIndex(v=>v.startsWith('release')));
 // Late old check cannot replace newer latest notice.
 const late=deferred();let calls=0;intercept=url=>url.includes('/selection')&&++calls===1?late.promise:null;
 const oldCheck=controller.check();now=row('c');await controller.check();late.resolve(latest(row('a')));await oldCheck;
 assert.equal(controller.state.notice.latest.price_revision,'price-c');intercept=null;
 // Raced-out replacement releases its candidate and leaves previous exact context.
 const pinned=controller.state.pinned;let reads=0;
 intercept=url=>url.includes('/selection')?Promise.resolve(latest(row(++reads===1?'c':'d'))):null;
 assert.equal(await controller.adopt(),false);assert.equal(controller.state.pinned,pinned);assert.equal(leases.size,1);assert(errors.at(-1).includes('changed while retaining'));intercept=null;
 // Removed or unavailable cannot adopt another row. Null economics can be pinned.
 now=null;await controller.check();assert.equal(controller.state.notice.state,'removed');assert.equal(await controller.adopt(),false);assert.equal(controller.state.pinned,pinned);
 const unavailable={...latest(row('c')),state:'unavailable'};intercept=url=>url.includes('/selection')?Promise.resolve(unavailable):null;
 assert.equal(await controller.adopt(),false);intercept=null;
 // Close while retention is in flight: no orphan lease or resurrection.
 const held=deferred();intercept=(url,body)=>body?held.promise:null;
 const pending=controller.open(row('e'),result,'conditional_return_percent');controller.close();
 held.resolve({lease_id:'pending',result_id:'member-e'});await pending;assert.equal(controller.state.pinned,null);assert.equal(leases.size,0);assert(events.includes('release pending'));intercept=null;
 // Exact displayed revision mismatch refuses rather than silently adopting.
 const pendingRow={...row('pending'),economic_revision:null};
 intercept=url=>url.includes('/details')?Promise.resolve({row:pendingRow,evidence_result_id:'member-pending'}):null;
 await controller.open(pendingRow,result,'conditional_return_percent');assert.equal(controller.state.pinned.row.economic_revision,null);controller.close();
 intercept=(url,body)=>body?Promise.reject(Error('Selected evidence expired')):null;
 assert.equal(await controller.open(row('expired'),result,'conditional_return_percent'),false);
 assert.equal(controller.state.pinned,null);assert(controller.state.error.includes('expired'));
 assert.equal(leases.size,0);controller.close();assert.equal(controller.state.error,null);
 console.log('PASS L03 inspection: exact pin, confirmations, reference/expiry changes, stale responses, atomic adoption, race refusal, removed/unavailable, null economics and lease cleanup');
})().catch(e=>{console.error(e);process.exitCode=1;});

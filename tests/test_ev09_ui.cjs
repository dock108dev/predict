const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const asModule=s=>'data:text/javascript;base64,'+Buffer.from(s).toString('base64');
(async()=>{
 const {ReadRecovery,requireCapture,selectionMeaning}=await import(asModule(fs.readFileSync('app/dashboard/opportunity_static/current/current-client.js','utf8')));
 const quote={source:{provider:'native',native_event_id:'E',native_market_id:'M',native_outcome_id:'O',native_side:'YES',quote_side:'ask',binding_id:'receipt-one'},binding:{selection:{predicate:'win'}},native_contract:{material_sha256:'first',scope:{period:'full_game'},predicate:{participant:'A',predicate:'win'}}};
 const updated=JSON.parse(JSON.stringify(quote));updated.source.binding_id='receipt-two';updated.native_contract.material_sha256='second';assert.equal(selectionMeaning(updated),selectionMeaning(quote),'a new receipt preserves exact economic identity');updated.source.native_side='NO';assert.notEqual(selectionMeaning(updated),selectionMeaning(quote),'side changes require explicit reselection');
 let now=0;const budget=new ReadRecovery({now:()=>now,lifetime:10,maximum:3});
 assert.equal(budget.begin(),10);now=4;assert.equal(budget.begin(),6);now=9;budget.begin();assert.throws(()=>budget.begin(),/Choose Retry/);budget.reset();budget.begin();now=20;assert.throws(()=>budget.begin(),/Choose Retry/);budget.close();
 const value={runtime_id:'R',state_revision:2},notice={runtime_id:'R',state_revision:3,calculation_epoch:4,eligibility:'ready'};
 const headers=(epoch,deadline)=>({headers:{get:key=>key==='X-Predict-Epoch'?epoch:key==='X-Predict-Eligibility-Deadline'?deadline:null}});
 assert.throws(()=>requireCapture(headers('3'),value,notice),/inputs changed/);
 requireCapture(headers('3'),value,null); // Body arrives first, then notice withholds.
 assert.throws(()=>requireCapture(headers('3'),{...value,state_revision:3},notice),/inputs changed/);
 assert.throws(()=>requireCapture(headers('4',new Date(Date.now()-1).toISOString()),{...value,state_revision:3},notice),/inputs changed/);
 requireCapture(headers('4',new Date(Date.now()+10000).toISOString()),{...value,state_revision:3},notice);
 const source=fs.readFileSync('app/dashboard/opportunity_static/current/selected-details.js','utf8').replace('export class SelectedDetails','class SelectedDetails')+'\nthis.SelectedDetails=SelectedDetails;';
 const env={URLSearchParams,AbortController,setTimeout,clearTimeout};vm.runInNewContext(source,env);
 let aborted=0,requests=0;const loader=new env.SelectedDetails((url,{signal})=>{requests++;return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>{aborted++;reject(Object.assign(Error('cancelled'),{name:'AbortError'}));}));});
 const first=loader.load({quote_id:'native:YES'});const duplicate=loader.load({quote_id:'native:YES'});assert.equal(requests,1);loader.cancel();assert.equal(await first,null);assert.equal(await duplicate,null);assert.equal(aborted,1);
 const next=loader.load({quote_id:'native:NO'});const newer=loader.load({quote_id:'other:YES'});assert.equal(await next,null);loader.cancel();assert.equal(await newer,null);assert.equal(aborted,3);
 console.log('PASS: finite recovery, notice/body order, expiry and real Details cancellation without acquisition');
})().catch(e=>{console.error(e);process.exitCode=1;});

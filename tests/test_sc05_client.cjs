const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
const src=fs.readFileSync('app/dashboard/opportunity_static/current/ticket-client.js','utf8');
const {TicketSession,checkedTicket,boundedTicketJSON}=await import('data:text/javascript;base64,'+Buffer.from(src).toString('base64'));
const clone=x=>JSON.parse(JSON.stringify(x)),example=JSON.parse(fs.readFileSync('docs/examples/selected-ticket-1/selected.json')),bound=example.selection;
const discovery={selection:{...bound,policy_revision:bound.discovery_policy_revision,publication_revision:1,query_id:'page'},row:{id:bound.row_id}};
const calls=[],bodies=[];let now=0,mode='ready',pending=[];
const fetcher=async(url,options={})=>{calls.push(url);if(url.includes('/binding'))return new Response(JSON.stringify({version:'predict-ticket-selection-1',selection:bound}));
 if(mode==='delay')return new Promise(resolve=>pending.push(resolve));
 if(mode==='fail')return new Response('{}',{status:503});
 const command=options.body?JSON.parse(options.body):null;if(command)bodies.push(command);
 const v=clone(example);v.client_id='authored_browser_01';v.sequence=command?.sequence||bodies.at(-1).sequence;
 if(command?.operation==='adopt')v.replacement_frame=null;
 return new Response(JSON.stringify(v));};
const s=new TicketSession({onChange:()=>{},fetcher,clientId:'authored_browser_01',timer:()=>now,clock:()=>Date.parse('2026-10-11T12:00:00Z')});
await s.select(discovery,'40');assert(s.actionable());assert.deepEqual(bodies[0].selection,bound);assert(!('query_id' in bodies[0].selection));assert.equal(bodies[0].amount,'40');
const deadline=s.deadline;now=1000;await s.tick();assert.equal(s.deadline,deadline,'status must not renew TTL');
now=45001;await s.tick();assert.equal(bodies.at(-1).operation,'revalidate');assert.equal(s.deadline,165001);
await s.perform('revalidate');assert.equal(bodies.at(-1).amount,'40');assert(!('selection' in bodies.at(-1)));assert.equal(bodies.at(-1).operation,'revalidate');
await s.perform('adopt');assert(!('amount' in bodies.at(-1)));assert(!('selection' in bodies.at(-1)));
const top=clone(example);top.ready_for_manual_action=false;s.value=top;assert(!s.actionable(),'historical ready is not authority');
s.value=clone(example);s.value.client_id=s.clientId;s.value.sequence=s.sequence;s.blocked='';now=s.deadline;assert(!s.actionable());
now=0;await s.select(discovery,'40');mode='fail';await s.perform('revalidate');mode='ready';await s.tick();assert(!s.actionable(),'GET cannot restore failed revalidation authority');
await s.perform('revalidate');assert(s.actionable());
s.observe({server_id:bound.server_id,epoch:bound.epoch,rows:[],coverage:{state:'evaluated_positive'}});assert(s.actionable(),'page absence is not withdrawal');
mode='delay';const old=s.perform('revalidate');await new Promise(setImmediate);assert.equal(pending.length,1);mode='ready';await s.select(discovery,'50');const accepted=s.value;pending[0](new Response(JSON.stringify(example)));await old;assert.equal(s.value,accepted,'late body cannot publish');
const bad=clone(s.value);bad.selection.epoch='crossed';assert.throws(()=>checkedTicket(bad,s.clientId,bound,s.value.ticket_id,s.sequence));
await assert.rejects(boundedTicketJSON(async()=>new Response(' '.repeat(1048577)),'/'),/capacity/);
await s.close();assert.equal(bodies.at(-1).operation,'close');assert(!('selection' in bodies.at(-1)));assert(!('amount' in bodies.at(-1)));assert(bodies.every((b,i)=>i===0||b.sequence>bodies[i-1].sequence));
// A failed initial binding has no ticket deadline. Explicit scanner denials
// remain authoritative while periodic expiry sweeps continue independently.
const denial=new TicketSession({onChange:()=>{},fetcher:async()=>new Response('{}',{status:404}),clientId:'authored_denial_01',timer:()=>now,clock:()=>Date.parse('2026-10-11T12:00:00Z')});
now=0;await denial.select(discovery);assert.equal(denial.deadline,0);
for(const reason of ['Update required. Previous allocations cannot be used.','Collection stopped.','Server context changed. Rebind this exact position.']){
 denial.cancel();denial.deny(reason);denial.sweep();assert.equal(denial.blocked,reason);assert(!denial.actionable());
}
now=0;mode='ready';await s.select(discovery,'40');assert(s.actionable());
now=s.deadline;s.cancel();s.deny('Update required. Previous allocations cannot be used.');s.sweep();assert.equal(s.blocked,'Update required. Previous allocations cannot be used.');assert(!s.actionable());
now=0;await s.select(discovery,'40');now=s.deadline;s.sweep();assert.equal(s.blocked,'Original inputs or ticket lifetime expired.');assert(!s.actionable());
const view=fs.readFileSync('app/dashboard/opportunity_static/current/ticket-view.js','utf8').replace(/^import[^;]+;\n/gm,'').split('export function bootTicket()')[0];
const {nativeDecimal,nativeAllocation,qualifiedURL}=await import('data:text/javascript;base64,'+Buffer.from(view).toString('base64'));
assert.equal(nativeDecimal('123456789/1000000000'),'0.123456789');assert.equal(nativeDecimal('1/100'),'0.01');assert.throws(()=>nativeDecimal('1/3'));
const precision=clone(example.selected_frame);precision.result.legs[0].native_quantity='123456789/1000000000';assert.equal(JSON.parse(nativeAllocation(precision)).positions[0].quantity,'0.123456789');
for(const url of ['http://kalshi.com/x','https://evil.test/x','https://kalshi.com/','https://kalshi.com/x?q=1','https://kalshi.com/x#frag','https://user@kalshi.com/x'])assert.equal(qualifiedURL({state:'verified',url,provenance:{evidence_class:'reviewed_source'}}),null);
assert.equal(qualifiedURL(example.selected_frame.destinations[0]),example.selected_frame.destinations[0].url);
console.log('PASS SC05 binding, command schemas, amount, TTL, top authority, late bodies, exact identity, failed revalidation, page absence and bounds');
})().catch(e=>{console.error(e);process.exitCode=1;});

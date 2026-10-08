const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{const source=fs.readFileSync('app/dashboard/opportunity_static/current/current-client.js','utf8');const client=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
assert.deepEqual(Object.keys(client),['NoticeGate']);
const {NoticeGate}=client,schema='predict-current-1',gate=new NoticeGate(schema),notice=(runtime,revision)=>({schema,runtime_id:runtime,state_revision:revision});
assert(gate.accept(notice('a',2)));assert(!gate.accept(notice('a',2)));assert(!gate.accept(notice('a',1)));assert(gate.accept(notice('a',3)));assert(gate.accept(notice('b',1)));
for(const invalid of [{...notice('b',2),schema:'bad'},notice(null,2),notice('b',0),notice('b',1.5),notice('b',Number.MAX_SAFE_INTEGER+1)])assert.throws(()=>gate.accept(invalid),/Unsupported update schema/);
const current=fs.readFileSync('app/dashboard/opportunity_static/current/current.js','utf8');
assert(!/\b(ReviewRequests|leaseStatus|quoteById)\b/.test(current));
console.log('Current client: duplicate/out-of-order notices, runtime changes, invalid notices and removed held-review guard pass');})().catch(e=>{console.error(e);process.exitCode=1;});

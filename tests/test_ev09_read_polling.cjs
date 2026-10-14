const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
 const source=fs.readFileSync('app/dashboard/opportunity_static/current/board-client.js','utf8');
 const {LatestRead}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
 const requests=[],reader=new LatestRead(()=>new Promise(resolve=>requests.push(resolve)));
 const old=reader.read('old-settings',x=>x);assert.equal(reader.pending,true);
 // Periodic reads coalesce; an explicit changed-settings read still supersedes.
 if(!reader.pending)reader.read('periodic',x=>x);assert.equal(requests.length,1);
 const selected=reader.read('new-settings',x=>x);assert.equal(requests.length,2);
 requests[0](new Response('{"settings":"old"}'));assert.equal(await old,null);
 assert.equal(reader.pending,true,'old completion cannot clear the current read');
 requests[1](new Response('{"settings":"new"}'));assert.equal((await selected).settings,'new');
 assert.equal(reader.pending,false);
 let release;const failing=new LatestRead(()=>new Promise((_,reject)=>release=reject));
 const failure=failing.read('unavailable',x=>x);release(Error('saved read failed'));
 await assert.rejects(failure,/saved read failed/);assert.equal(failing.pending,false);
 console.log('PASS in-progress periodic coalescing, explicit settings supersession, delayed completion and failed-read release');
})().catch(e=>{console.error(e);process.exitCode=1;});

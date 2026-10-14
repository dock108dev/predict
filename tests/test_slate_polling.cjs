// Saved-only completion scheduling: no timer starts overlapping or paused reads.
const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
 const source=fs.readFileSync('app/dashboard/opportunity_static/current/board-client.js','utf8');
 const {SavedReadPoller}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
 const timers=new Map(), scheduled=[], cancelled=[];let next=0,reads=0,inFlight=false,paused=false;
 const poll=new SavedReadPoller({onRead:()=>{reads++;inFlight=true;},canRead:()=>!inFlight&&!paused,
  setTimer:(callback,delay)=>{const key=++next;timers.set(key,callback);scheduled.push({key,delay,callback});return key;},
  clearTimer:key=>{cancelled.push(key);timers.delete(key);}});
 const fire=()=>{const entry=scheduled.at(-1);timers.delete(entry.key);entry.callback();};
 const pending={stopped:false,storage:{state:'available'},boards:[{delivery_state:'pending'}]},stable={...pending,boards:[{delivery_state:'complete'}]};
 poll.setSlate(pending);poll.schedule();assert.equal(scheduled.at(-1).delay,2000);assert.equal(timers.size,1);
 fire();assert.equal(reads,1);assert.equal(timers.size,0,'next read waits for current completion');
 poll.schedule();assert.equal(timers.size,0,'in-flight read cannot overlap');
 inFlight=false;poll.setSlate(stable);poll.schedule();assert.equal(scheduled.at(-1).delay,10000);fire();assert.equal(reads,2);
 inFlight=false;poll.setSlate(pending);poll.schedule();assert.equal(scheduled.at(-1).delay,2000);
 const obsolete=scheduled.at(-1).callback;poll.cancel();obsolete();assert.equal(reads,2,'cancelled timer cannot start a read');
 poll.setSlate({...pending,storage:{state:'unavailable',error:'current_database_storage_cap'}});poll.schedule();assert.equal(scheduled.at(-1).delay,10000,'saving refusal disables fast mode');
 poll.setSlate({...pending,stopped:true});poll.schedule();assert.equal(scheduled.at(-1).delay,10000,'Stop disables fast mode');assert.equal(timers.size,1,'only one timer is retained');
 paused=true;fire();assert.equal(reads,2,'original-input modal blocks an already scheduled read');poll.schedule();assert.equal(timers.size,0);
 paused=false;poll.setSlate(pending);poll.schedule();assert.equal(scheduled.at(-1).delay,2000,'closing original-input modal can resume completion scheduling');
 poll.setSlate(null);poll.schedule();assert.equal(scheduled.at(-1).delay,10000,'failed saved read returns to slow mode');poll.cancel();assert.equal(timers.size,0);assert(cancelled.length>0);
 // Window timer functions can reject arbitrary receivers. Defaults must call
 // them on globalThis even though the poller owns the scheduler wrapper.
 const originalSet=globalThis.setTimeout,originalClear=globalThis.clearTimeout;let nativeCallback,nativeReads=0,nativeClears=0;
 try {
  globalThis.setTimeout=function(callback,delay){assert.equal(this,globalThis,'native timer receiver');nativeCallback=callback;assert.equal(delay,2000);return 7;};
  globalThis.clearTimeout=function(key){assert.equal(this,globalThis,'native clear receiver');assert.equal(key,7);nativeClears++;};
  const nativePoll=new SavedReadPoller({onRead:()=>nativeReads++,canRead:()=>true});nativePoll.setSlate(pending);nativePoll.schedule();nativePoll.cancel();assert.equal(nativeClears,1);nativePoll.schedule();nativeCallback();nativePoll.schedule();nativeCallback();assert.equal(nativeReads,2);
 } finally {globalThis.setTimeout=originalSet;globalThis.clearTimeout=originalClear;}
 console.log('PASS pending→stable completion polling, one in-flight/one timer, cancellation, unavailable/Stop fast-mode refusal and original-input modal pause');
})().catch(error=>{console.error(error);process.exitCode=1;});

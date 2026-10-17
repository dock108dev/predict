import { boundedTicketJSON } from './ticket-client.js';
// Filter-wide publication evidence, independent of Find, rank and pagination.
export function bootArrivals() {
  const button=document.getElementById('scanner-sound'),status=document.getElementById('scanner-arrivals');
  let sounds=0,accepted=0,enabled=false,audio=null,cursor=null,generation=0,lastScope='',seen=new Set(),cues=new Map(),controller=null;
  button.onclick=async()=>{enabled=!enabled;button.setAttribute('aria-pressed',String(enabled));button.textContent=enabled?'Sound on · mute':'Sound off · enable';if(enabled){try{audio=audio||new AudioContext();await audio.resume();}catch{enabled=false;button.textContent='Sound unavailable';button.setAttribute('aria-pressed','false');}}};
  function reset(){generation++;controller?.abort();controller=null;cursor=null;seen.clear();cues.clear();}
  async function read(filters,page) {
    const scope=JSON.stringify(filters);if(scope!==lastScope){reset();lastScope=scope;}
    if(document.hidden){reset();return;}
    if(controller)return;const gen=generation;controller=new AbortController();const active=controller,timeout=setTimeout(()=>active.abort(),1800);
    const q=new URLSearchParams({category:filters.category});for(const k of ['venues','sports','leagues','markets','periods'])if(filters[k].length)q.set(k,filters[k].join(','));for(const k of ['minimum_edge','minimum_size'])if(filters[k]!==null)q.set(k,filters[k]);
    if(cursor)for(const k of ['cursor','server_id','epoch','scope'])q.set(k,cursor[k]);
    try{const {value:v}=await boundedTicketJSON((...args)=>fetch(...args),'/api/scanner/transitions?'+q,{signal:active.signal},528384);
      if(gen!==generation)return;
      if(v.version!=='predict-scanner-transitions-1'||v.server_id!==page.server_id||v.epoch!==page.epoch||!Number.isSafeInteger(v.cursor)||v.cursor<0||!Array.isArray(v.events)||v.events.length>256||!['censored','continuous'].includes(v.continuity)||typeof v.scope!=='string')throw Error('transition_identity_invalid');
      if(cursor&&(v.cursor<cursor.cursor||v.scope!==cursor.scope||v.server_id!==cursor.server_id||v.epoch!==cursor.epoch)){cursor=null;return;}
      const baseline=cursor===null;cursor={cursor:v.cursor,server_id:v.server_id,epoch:v.epoch,scope:v.scope};
      if(baseline||v.continuity!=='continuous'){status.textContent='Arrival history starts here · earlier observations unknown.';return;}
      const events=v.events.filter(e=>{if(typeof e.id!=='string'||!['new','improved','matching','no_longer_matching','withdrawn','unavailable','first_observation'].includes(e.kind)||seen.has(e.id))return false;seen.add(e.id);if(seen.size>512)seen.delete(seen.values().next().value);return true;});
      if(!events.length)return;accepted+=events.length;
      for(const e of events){const row=e.after||e.before;if(!row?.id)continue;cues.set(row.id,{kind:e.kind,until:performance.now()+5000});if(cues.size>256)cues.delete(cues.keys().next().value);}
      status.textContent=events.length+' observed '+(events.length===1?'transition':'transitions')+' in selected filters · '+[...new Set(events.map(e=>e.kind.replaceAll('_',' ')))].join(', ')+'.';
      if(enabled&&!document.hidden&&events.some(e=>e.audible===true)){try{const o=audio.createOscillator(),g=audio.createGain();o.frequency.value=520;g.gain.setValueAtTime(.035,audio.currentTime);g.gain.exponentialRampToValueAtTime(.001,audio.currentTime+.12);o.connect(g);g.connect(audio.destination);o.start();sounds++;o.stop(audio.currentTime+.12);}catch{}}
    }catch{if(gen===generation){reset();status.textContent='Arrival history interrupted · reconnect will start silently.';}}
    finally{clearTimeout(timeout);if(controller===active)controller=null;}
  }
  function cue(id){const v=cues.get(id);if(v&&v.until>performance.now())return v.kind.replaceAll('_',' ');cues.delete(id);return '';}
  document.addEventListener('visibilitychange',()=>reset());addEventListener('pagehide',reset);
  Object.defineProperty(window,'predictArrivalObservations',{value:()=>({enabled,sounds,accepted,cursor:cursor?.cursor||null,retainedEvents:seen.size,cues:cues.size,activeReaders:controller?1:0})});
  return {read,reset,cue};
}

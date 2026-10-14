// Server metadata owns financial defaults; browser preferences are read-only requests.
// A recovery episode spans notices as well as HTTP errors. New source notices
// cannot renew its lifetime. Only completion or deliberate Retry/settings do.
export class ReadRecovery {
  constructor({now=()=>performance.now(),lifetime=300000,maximum=4}={}){this.now=now;this.lifetime=lifetime;this.maximum=maximum;this.reset();}
  reset(){globalThis.clearTimeout(this.timer);this.timer=null;this.started=null;this.attempts=0;this.exhausted=false;}
  begin(){if(this.started===null)this.started=this.now();if(this.exhausted||this.attempts>=this.maximum||this.now()-this.started>=this.lifetime){this.exhausted=true;throw Error('Updates are moving too quickly to complete this view. Choose Retry to read it again.');}this.attempts++;return Math.max(1,this.lifetime-(this.now()-this.started));}
  retry(callback){if(this.timer||this.exhausted)return;if(this.started===null)this.started=this.now();if(this.attempts>=this.maximum||this.now()-this.started>=this.lifetime){this.exhausted=true;return;}const wait=Math.min(4000,500*2**Math.max(0,this.attempts-1));this.timer=globalThis.setTimeout(()=>{this.timer=null;callback();},wait);}
  close(){globalThis.clearTimeout(this.timer);this.timer=null;this.exhausted=true;}
}

export function requireCapture(response,value,notice){
  const state=value.snapshot||value,epoch=response.headers?.get?.('X-Predict-Epoch'),deadline=response.headers?.get?.('X-Predict-Eligibility-Deadline');
  const superseded=notice&&state.runtime_id===notice.runtime_id&&(state.state_revision<notice.state_revision||notice.eligibility==='pending'||epoch!==null&&epoch!==undefined&&Number(epoch)<(notice.calculation_epoch??0));
  if(superseded||deadline&&Date.now()>=Date.parse(deadline))throw Object.assign(Error('Current inputs changed. Reading the same view again…'),{retryable:true});
}

export function captureExpiry(response,onExpire){
  const deadline=response.headers?.get?.('X-Predict-Eligibility-Deadline');
  if(!deadline)return null;
  const remaining=Date.parse(deadline)-Date.now();
  if(!Number.isFinite(remaining))throw Error('Current eligibility clock unavailable');
  return globalThis.setTimeout(onExpire,Math.min(2147483647,Math.max(0,remaining)));
}

export function selectionMeaning(quote){
  const source=quote.source||{},contract=quote.native_contract||{};
  // Receipt binding IDs/material hashes can advance with a price observation.
  // Preserve exact instrument orientation and declared economic terms instead.
  return JSON.stringify([
    ['provider','native_event_id','native_market_id','native_outcome_id','native_side','quote_side','native_line','binding_version'].map(k=>source[k]??null),
    quote.binding?.selection,contract.predicate,contract.scope,contract.result_policy,contract.wording
  ]);
}

export class SizingPolicy {
  constructor(storage=globalThis.sessionStorage){this.policy=null;this.override=null;this.bufferOverride=null;this.generation=0;this.storage=storage;try{const v=JSON.parse(storage?.getItem('predict-effective-settings-1')||'null');if(v){this.validate(v.ceiling,v.buffer);this.override=v.ceiling;this.bufferOverride=v.buffer;}}catch{/* Ignore invalid browser preference, never owner config. */}}
  get ceiling(){return this.override??this.policy?.capital_ceiling_usd??null;}
  get buffer(){return this.bufferOverride??this.policy?.buffer_rate??null;}
  validate(ceiling,buffer){if(typeof ceiling!=='string'||!/^\d+(\.\d{1,2})?$/.test(ceiling)||Number(ceiling)<=0||Number(ceiling)>100000)throw Error('Enter a ceiling above $0 and at most $100,000, with up to two decimal places.');if(typeof buffer!=='string'||!/^\d+(\.\d+)?$/.test(buffer)||buffer.length>256||Number(buffer)<0||Number(buffer)>1)throw Error('Enter a buffer rate from 0 to 1; 0.005 means 0.5%.');}
  update(policy){
    if(!policy||typeof policy.version!=='string'||typeof policy.revision!=='string'||typeof policy.capital_ceiling_usd!=='string'||!/^\d+(\.\d+)?$/.test(policy.capital_ceiling_usd)||Number(policy.capital_ceiling_usd)<=0)throw Error('Server sizing policy unavailable');
    const changed=this.policy?.revision!==policy.revision;this.policy=policy;if(changed)this.generation++;return changed;
  }
  persist(){try{if(this.override===null&&this.bufferOverride===null)this.storage?.removeItem('predict-effective-settings-1');else this.storage?.setItem('predict-effective-settings-1',JSON.stringify({ceiling:this.ceiling,buffer:this.buffer}));}catch{/* Preferences can work for this view if browser storage is unavailable. */}}
  setCeiling(value){this.override=value;this.generation++;this.persist();}
  setSettings(ceiling,buffer){this.validate(ceiling,buffer);this.override=ceiling;this.bufferOverride=buffer;this.generation++;this.persist();}
  reset(){this.override=null;this.bufferOverride=null;this.generation++;this.persist();}
  params(){return {ceiling:this.ceiling,buffer:this.buffer,request_generation:String(this.generation)};}
  matches(metric,generation){return generation===this.generation&&metric?.estimate_policy?.version===this.policy?.version&&metric.estimate_policy.buffer_rate===this.buffer&&metric.estimate_policy.capital_ceiling_usd===this.ceiling;}
  accepts(response,generation){return generation===this.generation&&String(response.request_generation)===String(generation)&&response.estimate_policy?.capital_ceiling_usd===this.ceiling&&response.estimate_policy?.buffer_rate===this.buffer;}
}

// Request ordering is independent of DOM rendering and provider ownership.
export class NoticeGate {
  constructor(schema) {
    this.schema = schema;
    this.last = null;
  }

  accept(notice) {
    if (notice.schema !== this.schema ||
        typeof notice.runtime_id !== 'string' ||
        !Number.isSafeInteger(notice.state_revision) ||
        notice.state_revision < 1) {
      throw Error('Unsupported update schema');
    }
    if (this.last && notice.runtime_id === this.last.runtime_id &&
        (notice.state_revision < this.last.state_revision ||
         (notice.state_revision === this.last.state_revision &&
          ((notice.calculation_epoch ?? 0) < (this.last.calculation_epoch ?? 0) ||
           ((notice.calculation_epoch ?? 0) === (this.last.calculation_epoch ?? 0) && notice.eligibility === this.last.eligibility))))) {
      return false;
    }
    this.last = notice;
    return true;
  }
}

// One latest board, no patch history. A runtime/cursor reset returns a snapshot.
export function applyChanges(previous,update){
  if(update.schema!=='predict-current-changes-1')return update;
  if(!previous||update.base_revision!==previous.state_revision||update.snapshot?.runtime_id!==previous.runtime_id||update.snapshot?.schema!==previous.schema||!Number.isSafeInteger(update.snapshot.state_revision)||update.snapshot.state_revision<previous.state_revision||!Array.isArray(update.events)||!Array.isArray(update.removed_events))throw Error('Unsupported change cursor');
  const events=new Map(previous.events.map(e=>[e.id,e]));
  for(const id of update.removed_events)events.delete(id);
  for(const event of update.events)events.set(event.id,event);
  const current={...update.snapshot,events:[...events.values()].sort((a,b)=>a.start_at.localeCompare(b.start_at)||a.id.localeCompare(b.id))};
  // Source ages are clocks, not economic calculations. Rebase unchanged rows to
  // the new server clock so patch traffic cannot keep their ages artificially low.
  const clock=Date.parse(current.clock_at),age=at=>at===null?null:Math.max(0,(clock-Date.parse(at))/1000);
  current.events=current.events.map(e=>({...e,groups:e.groups.map(g=>({...g,outcomes:g.outcomes.map(o=>{
    const aged=q=>({...q,age_seconds:age(q.times.source_at),confirmation_age_seconds:q.book_confirmation?age(q.book_confirmation.confirmed_at):null});
    return {...o,quotes:Object.fromEntries(Object.entries(o.quotes).map(([v,q])=>[v,aged(q)])),alternatives:Object.fromEntries(Object.entries(o.alternatives||{}).map(([v,qs])=>[v,qs.map(aged)]))};
  })}))}));
  return current;
}

// Preserve every control while giving initial narrow prices visible space.
export function initializeBoardControls(){
  const narrow=matchMedia('(max-width:680px)').matches;
  for(const control of document.querySelectorAll?.('.board-controls')||[])control.open=!narrow;
}

// This additive reader publishes original prices only. Complete financial
// readers and pinned Details retain their own revision/eligibility gates.
export function validateRetainedPrices(value,{settingsGeneration,runtimeId=null,generationId=null,page=0,policy=null}={}){
  const fail=()=>{throw Error('Unsupported retained price identity or progress');};
  const text=(v,max=160)=>typeof v==='string'&&v.length>0&&Array.from(v).length<=max;
  const fields=(v,required,optional=[])=>v&&typeof v==='object'&&!Array.isArray(v)&&required.every(k=>Object.hasOwn(v,k))&&Object.keys(v).every(k=>required.includes(k)||optional.includes(k));
  const integer=v=>Number.isSafeInteger(v)&&v>=0;
  const decimal=v=>typeof v==='string'&&v.length<=256&&/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(v)&&Math.abs(Number(v.split(/[eE]/)[1]||0))<=256;
  const stamp=v=>v===null||typeof v==='string'&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(v)&&Number.isFinite(Date.parse(v))&&new Date(v).toISOString().slice(0,19)===v.slice(0,19);
  const parts=v=>{const [coefficient,exponent]=v.split(/[eE]/),places=(coefficient.split('.')[1]||'').length-Number(exponent||0);return [BigInt(coefficient.replace('.','')),places];};
  const scaledPair=(a,b)=>{const [x,xp]=parts(a),[y,yp]=parts(b),places=Math.max(0,xp,yp);return [x*10n**BigInt(places-xp),y*10n**BigInt(places-yp),10n**BigInt(places)];};
  const compare=(a,b)=>{const [x,y]=scaledPair(a,b);return x===y?0:x>y?1:-1;},complement=(a,b)=>{const [x,y,unit]=scaledPair(a,b);return x+y===unit;};
  const p=value?.estimate_policy,progress=value?.progress,pg=value?.pagination;
  if(!fields(value,['schema','mode','runtime_id','generation_id','settings_generation','estimate_policy','status','input_clock_at','validation_at','input_epoch','state_revision','error','progress','rows','pagination']))fail();
  if(value?.schema!=='predict-retained-prices-1'||!['current','synthetic'].includes(value.mode)||!text(value.runtime_id)||!text(value.generation_id)||!integer(value.settings_generation)||value.settings_generation!==settingsGeneration||runtimeId&&value.runtime_id!==runtimeId||generationId&&value.generation_id!==generationId||!['pending','ready','rejected','superseded','stopped'].includes(value.status))fail();
  if(!p||p.version!=='predict-estimate-policy-2'||!text(p.revision)||!decimal(p.capital_ceiling_usd)||compare(p.capital_ceiling_usd,'0')<=0||compare(p.capital_ceiling_usd,'100000')>0||!decimal(p.buffer_rate)||compare(p.buffer_rate,'0')<0||compare(p.buffer_rate,'1')>0||policy&&['version','revision','capital_ceiling_usd','buffer_rate'].some(k=>p[k]!==policy[k]))fail();
  if(!stamp(value.input_clock_at)||!stamp(value.validation_at)||value.input_clock_at!==null&&value.validation_at!==null&&Date.parse(value.input_clock_at)>Date.parse(value.validation_at)||!(value.error===null||typeof value.error==='string'&&value.error.length<=160))fail();
  if(value.status==='ready'){if(!integer(value.input_epoch)||!integer(value.state_revision)||value.state_revision<1)fail();}
  else if(value.input_epoch!==null||value.state_revision!==null)fail();
  if(!fields(progress,['discovery_status','discovered_prices','validated_prices','total_prices',...['singles','pairs'].flatMap(kind=>['discovered','ready','refused','pending','total'].map(k=>k+'_'+kind))])||!['validating_prices','prices_complete','evaluating','complete'].includes(progress.discovery_status)||!integer(progress.discovered_prices)||progress.discovered_prices>16000||!integer(progress.validated_prices)||progress.validated_prices>progress.discovered_prices||!(progress.total_prices===null||integer(progress.total_prices)&&progress.total_prices<=16000&&progress.total_prices>=progress.discovered_prices))fail();
  if(progress.discovery_status!=='validating_prices'&&(progress.total_prices===null||progress.validated_prices!==progress.total_prices))fail();
  if(progress.discovery_status==='validating_prices'&&progress.total_prices!==null)fail();
  for(const kind of ['singles','pairs']){
    const ready=progress['ready_'+kind],pending=progress['pending_'+kind],refused=progress['refused_'+kind],total=progress['total_'+kind],discovered=progress['discovered_'+kind];
    if(!integer(ready)||!integer(refused)||!integer(discovered)||discovered>160000||ready+refused>discovered||!(total===null||integer(total)&&total<=160000&&total>=discovered))fail();
    if(total===null){if(pending!==null)fail();}else if(!integer(pending)||ready+pending+refused!==total)fail();
    if(progress.discovery_status==='complete'&&(total===null||pending!==0))fail();
  }
  if(value.status==='ready'&&progress.discovery_status!=='complete')fail();
  const terminal=['rejected','superseded','stopped'].includes(value.status);
  if(!fields(pg,['page','page_size','total_rows','has_more'])||pg.page!==page||pg.page_size!==1||!integer(pg.total_rows)||pg.total_rows>16000||pg.total_rows!==(terminal?0:progress.validated_prices)||typeof pg.has_more!=='boolean'||!Array.isArray(value.rows)||value.rows.length>1||pg.has_more!==(page*1+value.rows.length<pg.total_rows)||!terminal&&page*1>pg.total_rows||value.rows.length!==Math.min(1,Math.max(0,pg.total_rows-page*1)))fail();
  if(value.rows.length&&(value.input_clock_at===null||value.validation_at===null))fail();
  const ids=new Set(),nativeIds=new Set();
  for(const row of value.rows){
    const n=row?.native,o=row?.original,t=row?.times,e=row?.event;
    if(!fields(row,['id','revision','venue','native','original','times','event','market','period','selection'])||!text(row.id)||ids.has(row.id)||!integer(row.revision)||row.revision<1||!['kalshi','polymarket_us','novig','prophetx'].includes(row.venue)||!fields(n,['provider','event_id','market_id','outcome_id','side','quote_side'])||!Object.values(n).every(k=>text(k,2048))||!fields(e,['id','title','league','start_at'])||!text(e.id)||!text(e.league,2048)||!text(e.title,2048)||!stamp(e.start_at)||!['winner','spread','total'].includes(row.market)||!text(row.period,2048)||!text(row.selection,2048))fail();
    ids.add(row.id);
    const nativeId=JSON.stringify([row.venue,...['provider','event_id','market_id','outcome_id','side','quote_side'].map(k=>n[k])]);if(nativeIds.has(nativeId))fail();nativeIds.add(nativeId);
    if(!fields(o,['value','units','payout','payout_units','quantity_units','role'],['native_value','native_units','transformation'])||!decimal(o.value)||!['decimal_odds','usd_per_contract','cents_per_contract'].includes(o.units)||compare(o.value,'0')<0||o.units==='decimal_odds'&&compare(o.value,'1')<=0||o.units==='usd_per_contract'&&compare(o.value,'1')>0||o.units==='cents_per_contract'&&compare(o.value,'100')>0||!(o.payout===null||decimal(o.payout)&&compare(o.payout,'0')>0)||!(o.payout_units===null||text(o.payout_units,2048))||!text(o.quantity_units,2048)||o.role!=='comparison')fail();
    if(o.native_value!==undefined||o.native_units!==undefined||o.transformation!==undefined){
      if(!decimal(o.native_value)||!text(o.native_units)||!['identity','one_minus_native_bid'].includes(o.transformation))fail();
      if(o.transformation==='identity'&&(o.native_value!==o.value||o.native_units!==o.units))fail();
      if(o.transformation==='one_minus_native_bid'&&(o.native_units!=='usd_per_contract'||o.units!=='usd_per_contract'||compare(o.native_value,'0')<0||compare(o.native_value,'1')>0||!complement(o.native_value,o.value)))fail();
    }
    if(!fields(t,['source_at','received_at','projected_at','source_time_kind'])||!['source_at','received_at','projected_at'].every(k=>stamp(t[k]))||!['provider_quote','provider_book','unknown','synthetic'].includes(t.source_time_kind)||t.source_time_kind==='synthetic'&&value.mode!=='synthetic'||(t.source_at===null)!==(t.source_time_kind==='unknown')||['source_at','received_at','projected_at'].some(k=>t[k]!==null&&Date.parse(t[k])>Date.parse(value.input_clock_at)))fail();
  }
  if(['rejected','superseded','stopped'].includes(value.status)&&value.rows.length)fail();
  return value;
}

export class RetainedPriceBootstrap {
  constructor(root,sizing,{fetcher=globalThis.fetch.bind(globalThis),setTimer=globalThis.setTimeout.bind(globalThis),clearTimer=globalThis.clearTimeout.bind(globalThis)}={}){
    Object.assign(this,{root,sizing,fetcher,setTimer,clearTimer,token:0,active:Boolean(root),snapshot:null,runtimeId:null,completeIdentity:null});
  }
  cancel(){this.token++;this.abort?.abort();this.abort=null;this.clearTimer(this.timer);this.clearTimer(this.timeout);this.timer=null;this.timeout=null;}
  close(){this.active=false;this.cancel();}
  refresh(notice=null){
    if(!this.active)return;this.cancel();this.snapshot=null;this.completeIdentity=null;this.runtimeId=notice?.runtime_id?.startsWith('retained-loading:')?null:notice?.runtime_id||null;
    this.show('Loading retained original prices…');this.read(0);
  }
  complete(runtime,revision){
    if(runtime.startsWith('retained-loading:'))return;
    this.completeIdentity={runtime,revision};
    if(!this.snapshot||this.snapshot.status==='ready'&&this.snapshot.runtime_id===runtime&&this.snapshot.state_revision===revision){this.cancel();if(this.root)this.root.hidden=true;}
  }
  show(message){if(!this.root)return;this.root.hidden=false;this.root.textContent=message;}
  async body(response,signal){
    if(!response.body?.getReader)throw Error('Retained price response body unavailable');
    const reader=response.body.getReader(),decoder=new TextDecoder(),cancel=()=>{reader.cancel().catch(()=>{});};let bytes=0,result='';
    signal?.addEventListener('abort',cancel,{once:true});if(signal?.aborted)cancel();
    try{for(;;){const part=await reader.read();if(signal?.aborted)throw Object.assign(Error('Retained read cancelled'),{name:'AbortError'});if(part.done)break;bytes+=part.value.byteLength;if(bytes>256*1024)throw Error('Retained price page exceeds its bound');result+=decoder.decode(part.value,{stream:true});}return JSON.parse(result+decoder.decode());}
    finally{signal?.removeEventListener('abort',cancel);await reader.cancel();reader.releaseLock();}
  }
  async read(page,generationId=null){
    if(!this.active)return;this.cancel();const token=this.token,settingsGeneration=this.sizing.generation,ownerPolicy=this.sizing.policy;
    const abort=new AbortController();this.abort=abort;this.timeout=this.setTimer(()=>abort.abort(),10000);
    try{
      const params=new URLSearchParams({settings_generation:String(settingsGeneration),page:String(page)});if(generationId)params.set('generation_id',generationId);
      const response=await this.fetcher('/api/current/prices?'+params,{signal:abort.signal}),next=await this.body(response,abort.signal);
      if(token!==this.token||settingsGeneration!==this.sizing.generation||!this.active)return;
      if(response.status===409&&next.error==='retained_prices_unavailable'&&next.reason==='Retained generation changed'){
        this.snapshot=null;this.show('Loading the latest retained price generation…');
        this.timer=this.setTimer(()=>this.read(0),50);return;
      }
      if(!response.ok)throw Error(next.reason||next.error||'Retained prices unavailable');
      validateRetainedPrices(next,{settingsGeneration,runtimeId:this.runtimeId,generationId,page,policy:ownerPolicy});
      const previous=this.snapshot;
      if(previous?.generation_id===next.generation_id){
        const changed=previous.mode!==next.mode||previous.input_clock_at!==next.input_clock_at||JSON.stringify(previous.estimate_policy)!==JSON.stringify(next.estimate_policy)||['discovered_prices','validated_prices','discovered_singles','discovered_pairs','ready_singles','refused_singles','ready_pairs','refused_pairs'].some(k=>next.progress[k]<previous.progress[k])||['total_prices','total_singles','total_pairs'].some(k=>previous.progress[k]!==null&&next.progress[k]!==previous.progress[k]);
        const priorRows=new Map(previous.rows.map(row=>[row.id,row]));
        if(changed||next.rows.some(row=>priorRows.has(row.id)&&JSON.stringify(priorRows.get(row.id))!==JSON.stringify(row)))throw Error('Retained generation changed its original identity or counts');
      }
      this.snapshot=next;this.runtimeId=next.runtime_id;this.render(next);
      if(this.completeIdentity&&next.status==='ready'&&next.runtime_id===this.completeIdentity.runtime&&next.state_revision===this.completeIdentity.revision){this.complete(next.runtime_id,next.state_revision);return;}
      if(next.status==='pending')this.timer=this.setTimer(()=>this.read(page,next.generation_id),next.rows.length?500:50);
    }catch(error){if(token!==this.token||!this.active)return;this.snapshot=null;this.show('Retained prices unavailable: '+(error.name==='AbortError'?'Read timed out.':error.message));}
    finally{if(token===this.token){this.clearTimer(this.timeout);this.timeout=null;this.abort=null;}}
  }
  render(value){
    const node=(tag,text,className)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n;};
    const p=value.progress,total=x=>x===null?'unknown':String(x),terminal=['rejected','superseded','stopped'].includes(value.status);
    const old=new Map([...this.root.children].filter(n=>n.dataset.quoteId).map(n=>[n.dataset.quoteId,n])),children=[];
    this.root.hidden=false;this.root.dataset.runtimeId=value.runtime_id;this.root.dataset.generationId=value.generation_id;
    const heading=node('p',(value.mode==='synthetic'?'Authored offline · ':'')+(terminal?'Retained prices '+value.status:'Original prices · '+(value.status==='ready'?'server calculation complete':'calculating estimates')),'retained-heading');heading.setAttribute('role','status');children.push(heading);
    if(terminal){this.root.replaceChildren(...children,node('p',value.error||'This candidate is no longer available. Complete admitted prices remain separate.'));return;}
    children.push(node('p','Validated prices '+p.validated_prices+' / '+total(p.total_prices)+' · singles '+p.ready_singles+' ready / '+total(p.total_singles)+' · pairs '+p.ready_pairs+' ready / '+total(p.total_pairs),'retained-progress'));
    children.push(node('p','Estimates remain withheld until eligible complete results are available. Server ceiling $'+value.estimate_policy.capital_ceiling_usd+'; buffer rate '+value.estimate_policy.buffer_rate+'.','retained-disclosure'));
    for(const row of value.rows){
      const previous=old.get(row.id),key=JSON.stringify([row,value.generation_id,value.input_clock_at]);
      if(previous?.retainedKey===key){children.push(previous);continue;}
      const article=node('article',undefined,'retained-price');article.dataset.quoteId=row.id;article.retainedKey=key;
      article.append(node('h2',row.event.title),node('p',row.selection+' · '+row.native.side+' · '+row.market.replaceAll('_',' ')+' · '+row.period.replaceAll('_',' ')),node('p',row.event.league+' · starts '+(row.event.start_at||'unknown')));
      article.append(node('strong',(row.original.native_value??row.original.value)+' '+(row.original.native_units??row.original.units).replaceAll('_',' '),'retained-number'),node('span',row.venue+' · original source: '+(row.times.source_at||'unknown'),'retained-clock'));
      if(row.original.transformation==='one_minus_native_bid')article.append(node('p','Original native bid; acquisition complement '+row.original.value+' '+row.original.units.replaceAll('_',' ')));
      const details=node('details');details.append(node('summary','Original identity and clocks'),node('p',row.native.provider+' · event '+row.native.event_id+' · market '+row.native.market_id+' · outcome '+row.native.outcome_id+' · '+row.native.side+' / '+row.native.quote_side),node('p','Quote '+row.id+' · revision '+row.revision),node('p','Receipt: '+(row.times.received_at||'unknown')+' · projection: '+(row.times.projected_at||'unknown')+' · source kind: '+row.times.source_time_kind),node('p','Generation '+value.generation_id+' · input clock '+value.input_clock_at+' · validated '+value.validation_at));article.append(details);children.push(article);
    }
    if(!value.rows.length)children.push(node('p','Validating original prices; the discovered inventory is still incomplete.'));
    children.push(node('p','Validated prices '+p.validated_prices+' / '+total(p.total_prices)+' · singles ready '+p.ready_singles+', pending '+total(p.pending_singles)+', refused '+p.refused_singles+' / '+total(p.total_singles)+' · pairs ready '+p.ready_pairs+', pending '+total(p.pending_pairs)+', refused '+p.refused_pairs+' / '+total(p.total_pairs)+' · discovery '+p.discovery_status.replaceAll('_',' ')+' · validated '+value.validation_at,'retained-progress'));
    children.push(node('p','Original retained prices only. Estimates remain withheld until eligible complete results are available; Details uses the complete admitted revision.','retained-disclosure'));
    const navKey=JSON.stringify([value.generation_id,value.pagination.page,value.pagination.has_more]),oldNav=[...this.root.children].find(n=>n.retainedNavKey===navKey),nav=oldNav||node('div');
    if(!oldNav){nav.retainedNavKey=navKey;for(const [label,page,enabled]of[['Previous prices',value.pagination.page-1,value.pagination.page>0],['More prices',value.pagination.page+1,value.pagination.has_more]])if(enabled){const button=node('button',label);button.type='button';button.onclick=()=>this.read(page,value.generation_id);nav.append(button);}}children.push(nav);
    // Keep unchanged originals attached: polling must preserve open disclosures,
    // focused summaries and scroll anchors rather than replace the same rows.
    const keep=new Set(children);for(const child of [...this.root.children])if(!keep.has(child))child.remove();
    let before=this.root.children[0];for(const child of children){if(child!==before)this.root.insertBefore(child,before);before=this.root.children[[...this.root.children].indexOf(child)+1];}
  }
}

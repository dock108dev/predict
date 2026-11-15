// Tab-local, bounded diagnostics. No provider payload, credentials or full status.
export class DiagnosticSession {
  constructor(){this.clear();}
  clear(){this.startedAt=new Date().toISOString();this.events=[];this.observations=new Map();this.visible=new Set();this.dropped=0;this.scope=null;this.lastSources=null;this.render();}
  record(kind,facts={}){
    this.events.push({observed_at:new Date().toISOString(),kind,...facts});
    if(this.events.length>1000){this.events.shift();this.dropped++;}this.render();
  }
  mount(summary,list){this.summary=summary;this.list=list;this.render();}
  unmount(){this.summary=null;this.list=null;}
  render(){if(!this.summary||this.list.contains(document.activeElement))return;
    this.summary.textContent=`Since ${this.startedAt}: ${this.events.length} retained events, ${this.dropped} older events discarded. This tab's sampled observations cannot establish continuous opportunity duration. Changing filters or pages leaves unobserved gaps.`;
    this.list.replaceChildren(...this.events.slice(-12).reverse().map(x=>{const li=document.createElement('li'),detail=document.createElement('details'),summary=document.createElement('summary'),proof=document.createElement('pre');
      summary.textContent=`${x.observed_at} · ${x.kind.replaceAll('_',' ')}${x.game?' · '+x.game:''}${x.venue?' · '+x.venue:''}${x.direction?' · '+x.direction.replaceAll('_',' '):''}`;
      proof.textContent=JSON.stringify(x,null,2);detail.append(summary,proof);li.append(detail);return li;}));
  }
  observe(page,filters){
    const context=JSON.stringify([filters,page.offset,page.offset?page.browse_id:null]);
    if(context!==this.scope){this.record('display_scope',{filters,offset:page.offset,browse_id:page.browse_id});this.scope=context;this.visible.clear();}
    const visible=new Set();
    const groups=page.rows?.length ? page.rows : page.price_preview || [];
    for(const group of groups)for(const offer of group.offers||[]){
      visible.add(offer.id);
      const value={id:offer.id,venue:offer.venue,game:group.game_title,selection:offer.selection,
        odds:offer.odds,before_fee:offer.before_fee,after_fee:offer.after_fee,conservative:offer.conservative,current:offer.current,
        source_at:offer.source_clock_at,confirmation_at:offer.confirmed_at,received_at:offer.received_at,captured_at:offer.captured_at,
        published_at:page.publication?.published_at,game_state:offer.game_state};
      const prior=this.observations.get(offer.id);
      const metrics=['before_fee','after_fee','conservative'];
      const priceChanged=prior&&prior.odds?.decimal!==value.odds?.decimal;
      const calculationChanged=prior&&metrics.some(k=>prior[k]!=null&&value[k]!=null&&prior[k]!==value[k]);
      if(!prior)this.record('first_observation',value);
      else if(priceChanged||calculationChanged){
        const a=Number(prior.odds?.decimal),b=Number(value.odds?.decimal);
        this.record('material_change',{...value,previous:prior,direction:Number.isFinite(a)&&Number.isFinite(b)?b>a?'decimal_odds_up':b<a?'decimal_odds_down':'unchanged_odds':'unknown'});
      }else if(value.received_at!==prior.received_at||value.confirmation_at!==prior.confirmation_at||value.current!==prior.current)
        this.record('unchanged_price_confirmation',value);
      if(prior&&metrics.some(k=>(prior[k]!=null)!==(value[k]!=null)))
        this.record('calculation_availability_change',{...value,previous:prior});
      if(prior?.current&&!value.current)this.record('price_withdrawn',{...value,reasons:offer.current_reasons});
      this.observations.delete(offer.id);this.observations.set(offer.id,value);
    }
    for(const id of this.visible)if(!visible.has(id))this.record('left_displayed_population',{id,reason:'No longer displayed in this sampled page; source withdrawal or opportunity duration is not inferred.'});
    this.visible=visible;
    while(this.observations.size>2000)this.observations.delete(this.observations.keys().next().value);
    this.record('display_read',{delivery_clocks:page.delivery_clocks,generation:page.generation,offset:page.offset,publication_at:page.publication?.published_at,
      read_at:page.publication?.read_at,displayed_at:new Date().toISOString(),publication_state:page.publication?.state,
      rows:groups.length});
    this.sources(page.publication);
  }
  sources(publication){
    if(!publication?.data_runtime&&!publication?.sources)return;
    const runtime=publication.data_runtime;
    const facts={runtime_healthy:runtime?.healthy,stopped:runtime?.stopped,paused:runtime?.paused_sources,
      sources:Object.entries(publication.sources||{}).map(([provider,source])=>({
        provider,state:source.state,reason_code:source.reason_code,
      }))};
    const key=JSON.stringify(facts);
    if(key!==this.lastSources)this.record('source_collection_change',facts);
    this.lastSources=key;
  }
  export(){
    const data={schema:'predict-diagnostic-session-1',started_at:this.startedAt,exported_at:new Date().toISOString(),dropped_events:this.dropped,
      semantics:{order:'Browser observation order, not provider receipt order; original receipt clocks are separate.',
        scope:'Only prices displayed in this tab and sampled source status. First observation may follow an earlier unobserved publication; capture is not necessarily first capture.',
        duration:'First/last observations do not establish continuous availability or exact opportunity lifetimes.',
        retention:'1000 events and 2000 comparison keys, tab memory only; no raw provider payloads.'},events:this.events};
    const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download='predict-session-'+this.startedAt.replaceAll(':','-')+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),0);
  }
}

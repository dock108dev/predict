// Exact-current selected evidence, with latest-only delivery and no acquisition.
export class SelectedDetails {
  constructor(fetcher=(...args)=>fetch(...args)){this.fetcher=fetcher;this.generation=0;this.key=null;this.pending=null;this.abort=null;}
  cancel(){globalThis.clearTimeout(this.timeout);this.timeout=null;this.abort?.abort();this.abort=null;this.generation++;this.key=null;this.pending=null;}
  async load(context,{lifetime=300000}={}){
    const key=JSON.stringify(context);
    if(key===this.key&&this.pending)return this.pending;
    this.cancel();const generation=this.generation;this.key=key;
    const controller=new AbortController();this.abort=controller;
    const timeout=globalThis.setTimeout(()=>controller.abort(),Math.min(300000,lifetime));this.timeout=timeout;
    const operation=(async()=>{
      const response=await this.fetcher('/api/current/details?'+new URLSearchParams(context),{signal:controller.signal});
      const value=await response.json();
      if(generation!==this.generation)return null;
      if(!response.ok)throw Object.assign(Error(value.reason||'Selected evidence unavailable'),{status:response.status,retryable:response.status===409||response.status===503});
      const deadline=response.headers?.get?.('X-Predict-Eligibility-Deadline');
      if(deadline&&Date.now()>=Date.parse(deadline))throw Object.assign(Error('Selected inputs expired; reading the same contract again…'),{retryable:true});
      if(value.runtime_id!==context.runtime_id||String(value.state_revision)!==String(context.state_revision)||value.quote?.id!==context.quote_id)throw Error('Selected evidence revision changed');
      if(context.quote_revision!==undefined&&String(value.quote.revision)!==String(context.quote_revision))throw Error('Selected native revision changed');
      if(context.request_generation!==undefined&&String(value.request_generation)!==String(context.request_generation))throw Error('Settings generation changed');
      if(context.buffer!==undefined&&(value.estimate_policy?.buffer_rate!==context.buffer||value.estimate_policy?.capital_ceiling_usd!==context.ceiling))throw Error('Effective policy changed');
      if(context.pair_id&&!value.funded_pairs?.some(p=>p.id===context.pair_id&&p.objective===context.objective&&p.revision===context.pair_revision))throw Error('Exact funded pair changed');
      for(const pair of value.funded_pairs||[]){
        if(pair.runtime_id!==context.runtime_id||String(pair.state_revision)!==String(context.state_revision)||pair.legs?.length!==2||!pair.legs.some(leg=>leg.quote_id===context.quote_id))throw Error('Opposing evidence revision changed');
        if(context.opposing_quote_id&&!pair.legs.some(leg=>leg.quote_id===context.opposing_quote_id&&String(leg.quote_revision)===String(context.opposing_quote_revision)))throw Error('Opposing native revision changed');
        if(value.leg_quotes&&pair.legs.some(leg=>value.leg_quotes[leg.quote_id]?.revision!==leg.quote_revision||value.leg_quotes[leg.quote_id]?.binding?.selection?.group_id!==leg.group_id))throw Error('Leg evidence context changed');
      }
      return value;
    })();
    this.pending=(async()=>{try{return await operation;}catch(error){if(generation!==this.generation)return null;this.key=null;this.pending=null;if(error.name==='AbortError')throw Error('Details took too long. Close and reselect this price to try again.');throw error;}finally{globalThis.clearTimeout(timeout);if(this.abort===controller)this.abort=null;}})();
    return this.pending;
  }
}

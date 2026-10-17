// Scanner v1: one bounded page, exact server ordering, no financial calculations.
export const SCANNER_PROTOCOL = 'predict-opportunity-scanner-1';
export const SCANNER_BOUNDS = Object.freeze({page:100,rows:4096,responseBytes:2097152,retainedBytes:4194304,requestsPerRead:2,timeoutMs:5000});
export const scannerDefaults = () => ({venues:[],sports:[],leagues:[],markets:[],periods:[],category:'covered_outcome_arb',minimum_edge:null,minimum_size:null});
export const scannerPreferenceKey = 'predict-scanner-preferences-1';
const scannerDimensions = ['venues','sports','leagues','markets','periods'];
export function safeScannerPreferences(value) {
  const out=scannerDefaults();
  if(!value || typeof value!=='object')return out;
  for(const key of scannerDimensions)if(Array.isArray(value[key]) && value[key].length<=16 && value[key].every(x=>typeof x==='string' && /^[\w-]{1,64}$/.test(x)))out[key]=[...new Set(value[key])].sort();
  if(['covered_outcome_arb','conditional_hedge','ev'].includes(value.category))out.category=value.category;
  for(const key of ['minimum_edge','minimum_size'])if(typeof value[key]==='string' && /^\d{1,8}(\.\d{1,6})?$/.test(value[key]))out[key]=value[key];
  return out;
}
export function scannerQuery(filters,offset=0,prior=null) {
  const q=new URLSearchParams({category:filters.category,offset:String(offset),limit:'100'});
  for(const k of scannerDimensions)if(filters[k].length)q.set(k,filters[k].join(','));
  for(const k of ['minimum_edge','minimum_size'])if(filters[k]!==null)q.set(k,filters[k]);
  if(prior && prior.offset===offset){q.set('since',String(prior.publication_revision));q.set('epoch',prior.epoch??'');q.set('query_id',prior.query_id);}
  else if(prior)q.set('expected_revision',String(prior.publication_revision));
  return q;
}
export function checkScannerPage(v,filters,offset,prior=null) {
  if(v?.version!==SCANNER_PROTOCOL)throw Error('scanner_incompatible');
  if(!['snapshot','unchanged','replace_page','resync'].includes(v.mode) || typeof v.server_id!=='string' || !(v.epoch===null || typeof v.epoch==='string') || !Number.isSafeInteger(v.publication_revision) || v.publication_revision<0 || typeof v.query_id!=='string')throw Error('scanner_identity_invalid');
  if(v.offset!==offset || v.limit!==100 || !Array.isArray(v.rows) || v.rows.length>100 || !Array.isArray(v.ranked_ids) || !Number.isSafeInteger(v.total_matching) || v.total_matching<0 || v.total_matching>4096 || !(v.next_offset===null || (Number.isSafeInteger(v.next_offset)&&v.next_offset>offset&&v.next_offset<=4096)))throw Error('scanner_page_bounds');
  for(const key of [...scannerDimensions,'category','minimum_edge','minimum_size'])if(JSON.stringify(v.filters?.[key])!==JSON.stringify(filters[key]))throw Error('scanner_filters_crossed');
  if(prior && v.mode!=='resync' && (v.server_id!==prior.server_id || v.epoch!==prior.epoch || (prior.offset===offset && v.query_id!==prior.query_id) || v.publication_revision<prior.publication_revision))throw Error('scanner_resync_required');
  if(prior && prior.offset!==offset && v.publication_revision!==prior.publication_revision)throw Error('scanner_page_revision_changed');
  if(v.mode==='unchanged') {
    if(!prior || prior.offset!==offset || v.publication_revision!==prior.publication_revision || JSON.stringify(v.ranked_ids)!==JSON.stringify(prior.ranked_ids) || v.rows.length)throw Error('scanner_unchanged_invalid');
  } else if(v.ranked_ids.length!==v.rows.length || new Set(v.ranked_ids).size!==v.rows.length || v.rows.some((r,i)=>r.id!==v.ranked_ids[i]))throw Error('scanner_rank_identity');
  for(const row of v.rows) {
    if(typeof row.id!=='string' || !row.opportunity_id || !row.dependency_revision || !row.economic_revision || row.category!==filters.category || row.metric_basis!==v.metric_basis || !Array.isArray(row.positions) || row.positions.length!==2 || !Array.isArray(row.venues) || new Set(row.venues).size!==2 || row.positions.some(p=>!Array.isArray(p.native_key) || !p.predicate || !row.venues.includes(p.native_key[0])) || !Number.isFinite(Date.parse(row.expires_at)))throw Error('scanner_row_invalid');
    if(row.category==='covered_outcome_arb' && (!row.current || !row.settlement_complete || row.conditioning!=='all_required_feasible_states'))throw Error('scanner_category_invalid');
  }
  if(!v.coverage || !Array.isArray(v.unsupported_filters) || !Array.isArray(v.coverage.errors) || !v.filter_options || typeof v.coverage.complete!=='boolean')throw Error('scanner_coverage_invalid');
  return v.mode==='unchanged'?{...v,rows:prior.rows}:v;
}
export function scannerSelection(page,row) {
  return Object.freeze({server_id:page.server_id,epoch:page.epoch,publication_revision:page.publication_revision,query_id:page.query_id,row_id:row.id,opportunity_id:row.opportunity_id,pair_id:row.pair_id,dependency_revision:row.dependency_revision,economic_revision:row.economic_revision,readiness_policy_revision:page.readiness_policy_revision,policy_revision:page.policy.revision});
}
export const ScannerReader = class {
  constructor({fetcher=(...args)=>globalThis.fetch(...args),onPage,onState,onCompatibility,assetRevision,onCycle}) {Object.assign(this,{fetcher,onPage,onState,onCompatibility,assetRevision,onCycle});this.generation=0;this.page=null;this.offset=0;this.filters=scannerDefaults();this.closed=false;this.controller=null;this.timer=null;this.incompatible=false;}
  configure(filters,offset=0) {this.filters=safeScannerPreferences(filters);this.offset=offset;this.cancel();if(offset===0)this.page=null;this.read();}
  cancel() {this.generation++;clearTimeout(this.timer);this.controller?.abort();this.controller=null;}
  close() {this.closed=true;this.cancel();}
  async json(url,signal) {
    if(signal.aborted)throw new DOMException('Superseded','AbortError');
    const r=await this.fetcher(url,{signal,cache:'no-store',headers:{Accept:'application/json'}});
    if(r.status===409)throw Error('scanner_page_revision_changed');
    if(!r.ok)throw Error('scanner_transport_unavailable');
    if(Number(r.headers.get('content-length'))>SCANNER_BOUNDS.responseBytes)throw Error('scanner_response_bound');
    const stream=r.body?.getReader();let bytes=0,parts=[];
    if(!stream)throw Error('scanner_stream_required');
    try {while(true){if(signal.aborted)throw new DOMException('Superseded','AbortError');const item=await stream.read();if(item.done)break;bytes+=item.value.byteLength;if(bytes>SCANNER_BOUNDS.responseBytes)throw Error('scanner_response_bound');parts.push(item.value);}}catch(e){await stream.cancel();throw e;}
    const data=new Uint8Array(bytes);let at=0;for(const part of parts){data.set(part,at);at+=part.byteLength;}
    const available=performance.now();
    return {value:JSON.parse(new TextDecoder().decode(data)),bytes,available};
  }
  async read() {
    if(this.closed || this.incompatible || this.controller)return;
    const generation=this.generation,filters=this.filters,offset=this.offset,prior=this.page;
    const controller=new AbortController();this.controller=controller;
    const timeout=setTimeout(()=>controller.abort(),SCANNER_BOUNDS.timeoutMs);
    const start=performance.now();let available=null;
    try {
      const compatibility=(await this.json('/api/scanner/client',controller.signal)).value;
      if(generation!==this.generation || this.closed)return;
      if(compatibility.protocol!==SCANNER_PROTOCOL || compatibility.asset_revision!==this.assetRevision || !compatibility.assets_valid) {this.incompatible=true;this.onCompatibility();return;}
      const response=await this.json('/api/scanner?'+scannerQuery(filters,offset,prior),controller.signal);available=response.available;
      if(generation!==this.generation || this.closed)return;
      const page=checkScannerPage(response.value,filters,offset,prior);
      // Each accepted response replaces the entire retained page. No append cache.
      this.page=page;this.failures=0;this.onPage(page,{generation,started:start,available,bytes:response.bytes,retrievalMs:available-start});
      await this.onCycle?.();
    } catch(e) {
      if(generation!==this.generation || this.closed)return;
      if(e.message==='scanner_incompatible'){this.incompatible=true;this.onCompatibility();return;}
      if(['scanner_page_revision_changed','scanner_resync_required'].includes(e.message)) {this.page=null;this.offset=0;this.onState('resync');}
      else {this.failures=(this.failures||0)+1;this.onState('unavailable');}
    } finally {
      clearTimeout(timeout);
      if(generation===this.generation){this.controller=null;if(!this.closed&&!this.incompatible)this.timer=setTimeout(()=>this.read(),Math.min(10000,this.failures?1000*2**Math.min(this.failures,3):500));}
    }
  }
};

// Exact server frames only. One workspace identity, one active generation, no queue.
export const TICKET_PROTOCOL='predict-selected-ticket-1';
export const ticketBounds=Object.freeze({responseBytes:1048576,timeoutMs:2400,renewMs:45000,ttlMs:120000,observations:256});
export async function boundedTicketJSON(fetcher,url,options={},limit=ticketBounds.responseBytes) {
  const r=await fetcher(url,{cache:'no-store',...options});
  if(!r.ok){const e=Error('ticket_request_unavailable');e.status=r.status;throw e;}
  if(Number(r.headers.get('content-length'))>limit)throw Error('ticket_response_capacity');
  const stream=r.body?.getReader();if(!stream)throw Error('ticket_stream_required');
  let size=0;const parts=[];
  try{while(true){if(options.signal?.aborted)throw Error('ticket_superseded');const {done,value}=await stream.read();if(done)break;size+=value.byteLength;if(size>limit)throw Error('ticket_response_capacity');parts.push(value);}}catch(e){await stream.cancel();throw e;}
  const bytes=new Uint8Array(size);let i=0;for(const p of parts){bytes.set(p,i);i+=p.byteLength;}
  return {value:JSON.parse(new TextDecoder().decode(bytes)),available:performance.now(),bytes:size};
}
export function checkedTicket(v,client,selection,ticket,sequence) {
  if(v?.version!==TICKET_PROTOCOL || v.client_id!==client || !Number.isSafeInteger(v.sequence) || v.sequence!==sequence || (ticket&&v.ticket_id!==ticket) || typeof v.ticket_id!=='string')throw Error('ticket_identity_crossed');
  if(JSON.stringify(v.selection)!==JSON.stringify(selection))throw Error('ticket_selection_crossed');
  if(!['unchanged','revised','no_longer_qualifying','temporarily_unavailable','withdrawn','expired','stopped'].includes(v.state) || typeof v.ready_for_manual_action!=='boolean')throw Error('ticket_state_invalid');
  for(const frame of [v.selected_frame,v.replacement_frame].filter(Boolean))if(frame.engine_binding!==selection.engine_binding || frame.readiness_policy_revision!==selection.readiness_policy_revision || !Number.isFinite(Date.parse(frame.expires_at)) || !Array.isArray(frame.result?.manual_legs) || frame.result.manual_legs.length!==2)throw Error('ticket_frame_crossed');
  if(v.ready_for_manual_action && (v.state!=='unchanged' || !v.selected_frame || v.replacement_frame || v.selected_frame.dependency_revision!==v.latest?.dependency_revision))throw Error('ticket_authority_invalid');
  return v;
}
export const TicketSession=class {
  constructor({onChange,fetcher=(...args)=>globalThis.fetch(...args),clock=()=>Date.now(),timer=()=>performance.now(),clientId}) {
    Object.assign(this,{onChange,fetcher,clock,timer});this.clientId=clientId||('ticket_'+crypto.randomUUID().replaceAll('-',''));this.sequence=0;this.generation=0;this.controller=null;this.value=null;this.selection=null;this.discovery=null;this.bound=null;this.draft='';this.lastCommand=-Infinity;this.deadline=0;this.blocked='';this.pending=false;this.samples=[];
  }
  cancel(){this.generation++;this.controller?.abort();this.controller=null;this.pending=false;}
  deny(reason){this.blocked=reason;this.onChange(this);}
  actionable(){const f=this.value?.selected_frame;return !this.pending&&!this.blocked&&this.value?.ready_for_manual_action===true&&!!f&&this.clock()<Date.parse(f.expires_at)&&this.timer()<this.deadline;}
  amount(){return this.draft.trim()||this.value?.replacement_frame?.result.funding.requested_amount_usd||this.value?.selected_frame?.result.funding.requested_amount_usd;}
  async select(discovery,draft=this.draft){this.cancel();this.value=null;this.bound=null;this.selection=discovery.selection;this.discovery=discovery;this.rebindDiscovery=null;this.needsRebind=false;this.draft=draft;this.started=this.timer();return this.perform('select');}
  async perform(op,useDefault=false) {
    if(!this.discovery)return;
    this.cancel();const gen=this.generation,controller=new AbortController();this.controller=controller;this.pending=true;this.blocked='Checking exact positions…';this.onChange(this);
    const start=this.timer(),timeout=setTimeout(()=>controller.abort(),ticketBounds.timeoutMs);let bindingMs=0;
    try {
      if(op==='select') {
        const q=new URLSearchParams();for(const k of ['server_id','epoch','row_id','dependency_revision','economic_revision'])q.set(k,this.selection[k]);
        const b=await boundedTicketJSON(this.fetcher,'/api/scanner/ticket/binding?'+q,{signal:controller.signal},16384);
        if(gen!==this.generation)return;const selection=b.value.selection;
        if(b.value.version!=='predict-ticket-selection-1'||!selection||Object.keys(selection).length!==10||['server_id','epoch','row_id','opportunity_id','pair_id','dependency_revision','economic_revision','readiness_policy_revision'].some(k=>selection[k]!==this.selection[k]))throw Error('ticket_binding_crossed');
        this.bound=selection;bindingMs=this.timer()-start;
      }
      if(this.sequence>=Number.MAX_SAFE_INTEGER-1)throw Error('ticket_sequence_exhausted');
      const sequence=++this.sequence,body={operation:op,client_id:this.clientId,sequence};
      if(op==='select')body.selection=this.bound;else body.ticket_id=this.value?.ticket_id;
      if(op==='select'||op==='revalidate'){const amount=useDefault?undefined:this.amount();if(amount!==undefined&&amount!=='')body.amount=amount;}
      if(op==='adopt')body.replacement_frame_id=this.value?.replacement_frame?.id;
      this.lastCommand=start;this.deadline=start+ticketBounds.ttlMs;
      const response=await boundedTicketJSON(this.fetcher,'/api/scanner/ticket',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:controller.signal});
      if(gen!==this.generation)return;
      this.value=checkedTicket(response.value,this.clientId,this.bound,op==='select'?null:body.ticket_id,sequence);this.blocked='';
      if(!this.draft)this.draft=this.amount()||'';
      this.sample={operation:op,started:op==='select'?this.started:start,bindingMs,httpAndBackendMs:response.available-start-bindingMs,bodyAvailable:response.available,backend:this.value.timing||null};
    }catch(e){if(gen===this.generation&&e.status===409&&this.value)this.needsRebind=true;if(gen===this.generation)this.blocked='Current ticket unavailable. Previous allocations cannot be used.';}
    finally{clearTimeout(timeout);if(gen===this.generation){this.controller=null;this.pending=false;this.onChange(this);}}
  }
  async tick() {
    if(!this.discovery||this.pending)return;
    this.sweep();if(this.timer()>=this.deadline)return;
    if(this.timer()-this.lastCommand>=ticketBounds.renewMs){await this.perform('revalidate');return;}
    if(!this.value)return;
    const gen=this.generation,controller=new AbortController();this.controller=controller;
    const timeout=setTimeout(()=>controller.abort(),ticketBounds.timeoutMs);
    try{const response=await boundedTicketJSON(this.fetcher,'/api/scanner/ticket?'+new URLSearchParams({client_id:this.clientId,ticket_id:this.value.ticket_id}),{signal:controller.signal});
      if(gen!==this.generation)return;
      this.value=checkedTicket(response.value,this.clientId,this.bound,this.value.ticket_id,this.sequence);
      // A successful GET never restores authority lost by a failed command or draft.
      this.onChange(this);
      if(this.value.state==='revised'&&!this.value.replacement_frame&&!this.blocked)await this.perform('revalidate');
    }catch(e){if(gen===this.generation){if(e.status===409)this.needsRebind=true;this.deny('Current ticket unavailable. Previous allocations cannot be used.');}}
    finally{clearTimeout(timeout);if(gen===this.generation&&this.controller===controller)this.controller=null;}
  }
  observe(page){if(!this.selection)return;const row=page.rows.find(r=>r.id===this.selection.row_id);
    if(row)this.rebindDiscovery={selection:{...this.selection,server_id:page.server_id,epoch:page.epoch,readiness_policy_revision:page.readiness_policy_revision,policy_revision:page.policy?.revision,dependency_revision:row.dependency_revision,economic_revision:row.economic_revision},row};
    if(page.server_id!==this.selection.server_id||page.epoch!==this.selection.epoch){this.needsRebind=true;this.cancel();this.deny('Server context changed. Rebind this exact position.');return;}
    if(page.coverage.state==='stopped'){this.cancel();this.deny('Collection stopped.');return;}
    if(row&&this.value?.selected_frame&&row.dependency_revision!==this.value.selected_frame.dependency_revision){this.blocked='Inputs changed. Preparing a separate replacement.';this.onChange(this);if(!this.pending&&!this.value.replacement_frame)this.perform('revalidate');}
  }
  sweep(){if(!this.discovery||this.blocked)return;const f=this.value?.selected_frame;if(this.timer()>=this.deadline||f&&this.clock()>=Date.parse(f.expires_at)){this.deny('Original inputs or ticket lifetime expired.');}}
  async close(){const old=this.value;this.cancel();this.discovery=null;this.selection=null;this.bound=null;this.value=null;this.blocked='';this.onChange(this);if(!old)return;
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),ticketBounds.timeoutMs);
    try{await boundedTicketJSON(this.fetcher,'/api/scanner/ticket',{method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,body:JSON.stringify({operation:'close',client_id:this.clientId,sequence:++this.sequence,ticket_id:old.ticket_id})});}catch{}finally{clearTimeout(timeout);}}
};

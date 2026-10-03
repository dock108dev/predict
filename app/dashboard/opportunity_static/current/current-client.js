// Request ordering is independent of DOM rendering and provider ownership.
export class ReviewRequests {
  constructor(create,release){this.create=create;this.release=release;this.generation=0;this.queue=Promise.resolve();}
  invalidate(){this.generation++;}
  replace(request,onSuccess,onFailure){const generation=++this.generation;
    this.queue=this.queue.catch(()=>{}).then(async()=>{if(generation!==this.generation)return;
      try{const next=await this.create(request);if(generation!==this.generation){await this.release(next.selection_id);return;}onSuccess(next);}
      catch(error){if(generation===this.generation)onFailure(error);}
    });return this.queue;
  }
}
export class NoticeGate {
  constructor(schema){this.schema=schema;this.last=null;}
  accept(notice){if(notice.schema!==this.schema||typeof notice.runtime_id!=='string'||!Number.isSafeInteger(notice.state_revision)||notice.state_revision<1)throw Error('Unsupported update schema');
    if(this.last&&notice.runtime_id===this.last.runtime_id&&notice.state_revision<=this.last.state_revision)return false;
    this.last=notice;return true;
  }
}

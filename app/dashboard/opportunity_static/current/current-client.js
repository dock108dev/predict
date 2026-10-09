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
        notice.state_revision <= this.last.state_revision) {
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

// Authored client transport/recovery frames. Disposable SQL/real-ingress
// coverage is separate; no owner state, collection or provider is contacted.
const assert = require('node:assert/strict');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {fixture, board, coverage, bounds, copy} = require('./current_board_fixture.cjs');
const asset = name => pathToFileURL(path.resolve('app/dashboard/opportunity_static/current', name)).href;
const readAt = '2026-10-17T14:00:00.000Z', expiresAt = '2026-10-17T14:00:30.000Z';
const token = name => 'authored_read_token_' + name;
function frame(count = 60, revision = 'authored-publication-1') {
  const games = Array.from({length:count}, (_,index) => ({...copy(fixture.catalog.games[0]),
    game_key:'authored-game:' + index, title:'Authored game ' + index,
    sport:['football','basketball','baseball'][index % 3], league:['NFL','NBA','MLB'][index % 3]}));
  const boards = games.map(game => {
    const value = board(fixture.odds, game.game_key);
    value.prices = value.prices.slice(0,1); value.rows = [];
    value.read_at = readAt;
    value.prices[0].times = {...value.prices[0].times, source_at:'2026-10-17T13:59:59.000Z', received_at:'2026-10-17T14:00:00.000Z'};
    return value;
  });
  return {version:'predict-comparison-slate-2', epoch:'authored-reset-1', read_revision:revision,
    read_token:token(revision), read_expires_at:expiresAt, read_at:readAt, as_of:'2026-10-17T13:59:58.000Z',
    view:'odds', filter:'all', policy:copy(fixture.odds.policy), games, boards, errors:[], stopped:false, bounds:copy(bounds)};
}
function page(value, offset = 0) {
  return {...copy(value), boards:copy(value.boards.slice(offset,offset+50)), coverage:coverage(value.games.length,offset)};
}
const ok = value => new Response(JSON.stringify(value));
const refused = reason => new Response(JSON.stringify({error:'current_inputs_unavailable',reason,provider_requests:0}),{status:409});

(async () => {
  const {defaults, SlateAccumulator, LatestRead, readSlate, checkInputs} = await import(asset('board-client.js'));
  const {relativeAge} = await import(asset('board-elements.js'));
  const context = {...defaults,view:'odds',filter:'all'};
  // Variable byte-boundary pages must cover every game, including >10 pages,
  // without changing the 8 MiB page or 80 MiB complete-read envelopes.
  const variable = frame(61), accumulator = new SlateAccumulator(context);
  let cursor=0;
  for (const count of [31, 17, ...Array(13).fill(1)]) {
    const part=page(variable,cursor);
    part.boards=copy(variable.boards.slice(cursor,cursor+count));
    part.coverage={...part.coverage,returned_games:count,next_offset:cursor+count<61?cursor+count:null,complete:cursor+count===61};
    accumulator.append(part,new TextEncoder().encode(JSON.stringify(part)).length);cursor+=count;
  }
  assert.equal(accumulator.result().boards.length,61);
  assert.equal(new Set(accumulator.result().boards.map(b=>b.game_key)).size,61);
  const stalled=page(variable);stalled.boards=[];stalled.coverage.returned_games=0;stalled.coverage.next_offset=0;
  assert.throws(()=>new SlateAccumulator(context).append(stalled,100));
  let current = frame(), nextToken = 0, providerRequests = 0;
  const captured = new Map(), requests = [];
  const localAPI = async url => {
    const query = new URL(url,'http://authored.local');
    if (query.pathname !== '/api/boards/slate') { providerRequests++; throw Error('Only retained local reads are permitted'); }
    const q = query.searchParams, offset = Number(q.get('offset')); requests.push(q);
    assert.equal(q.get('view'),'odds'); assert.equal(q.get('filter'),'all'); assert.equal(q.get('limit'),'50');
    let value;
    if (!offset) {
      assert.equal(q.get('read_token'),null,'fresh reads cannot reuse abandoned tokens');
      assert.equal(q.get('expected_revision'),null,'fresh reads capture current publication');
      value = copy(current); value.read_token = token(++nextToken); captured.set(value.read_token,value);
    } else {
      value = captured.get(q.get('read_token')); assert(value,'continuation uses its own token');
      assert.equal(q.get('expected_revision'),value.read_revision);
    }
    const response = page(value,offset);
    if (requests.length === 1) {
      current = frame(61,'authored-publication-2');
      current.boards[0].prices[0].original.value = '2.4';
      current.boards[0].prices[0].quote_revision++;
    }
    return ok(response);
  };
  const first = await readSlate(new LatestRead(localAPI),context);
  assert.equal(first.games.length,60); assert.equal(first.boards.length,60);
  assert.equal(new Set(first.boards.map(b=>b.game_key)).size,60,'every captured game appears once');
  assert.equal(new Set(first.games.map(g=>g.sport)).size,3);
  assert(!first.games.some(g=>g.game_key==='authored-game:60'),'newly published game stays outside captured frame');
  assert.equal(first.boards[0].prices[0].original.value,'2.3','publication cannot replace captured price');
  assert(first.boards.every(b=>b.read_at===readAt),'page arrival cannot advance captured read clock');
  const clocks = JSON.stringify(first.boards.map(b=>b.prices.map(q=>q.times)));
  assert.equal(relativeAge(first.boards[0].prices[0].times.source_at,Date.parse(readAt)),'1s old');
  assert.equal(relativeAge(first.boards[0].prices[0].times.source_at,Date.parse(readAt)+5000),'6s old');
  assert.equal(JSON.stringify(first.boards.map(b=>b.prices.map(q=>q.times))),clocks,'aging never mutates clocks');
  const fresh = await readSlate(new LatestRead(localAPI),context);
  assert.equal(fresh.games.length,61); assert.equal(fresh.boards[0].prices[0].original.value,'2.4');
  assert.notEqual(fresh.read_token,first.read_token,'independent fresh reads have separate tokens');

  const original = frame(), firstPage = page(original), secondPage = page(original,50);
  for (const change of [
    p=>p.read_token=token('other-tab'), p=>delete p.read_token, p=>p.read_revision='new-publication',
    p=>p.epoch='after-reset', p=>p.view='ev', p=>p.filter='positive',
    p=>p.read_at='2026-10-17T14:00:01.000Z', p=>p.read_expires_at='2026-10-17T14:00:31.000Z',
    p=>p.as_of='2026-10-17T14:00:00.000Z', p=>p.stopped=true,
    p=>p.policy={...p.policy,revision:'other-policy'}, p=>p.games[0].title='other-catalog',
  ]) {
    const accumulator = new SlateAccumulator(context); accumulator.append(copy(firstPage),1000);
    const changed = copy(secondPage); change(changed);
    assert.throws(()=>accumulator.append(changed,1000),'crossed frame must never enter prior partial frame');
    assert.throws(()=>accumulator.result(),/incomplete/);
  }

  for (const reason of ['current_slate_read_expired','current_slate_read_capacity','current_slate_read_authority_changed']) {
    const calls = []; let recoveries = 0, visible = first;
    const released = [];
    const reader = new LatestRead(async (url, options) => {
      if (options.method === 'DELETE') { released.push(new URL(url,'http://authored.local').searchParams.get('read_token')); return ok({released:true}); }
      const q = new URL(url,'http://authored.local').searchParams; calls.push(q);
      if (calls.length === 1) return ok(firstPage);
      if (calls.length === 2) return refused(reason);
      return ok(page(current,Number(q.get('offset'))));
    });
    const recovered = await readSlate(reader,context,{onRecovery:error=>{
      recoveries++; assert.equal(error.reason,reason); assert.equal(error.status,409);
      assert.equal(visible,first,'failed partial read cannot replace prior complete values');
    }});
    visible = recovered;
    assert.equal(recoveries,1); assert.equal(calls.length,4);
    assert.deepEqual(released,[firstPage.read_token],'only abandoned traversal is released before recovery');
    assert.equal(calls[2].get('offset'),'0'); assert.equal(calls[2].get('read_token'),null);
    assert.equal(visible.games.length,61); assert.equal(visible.read_token,current.read_token);
    assert.equal(visible.boards[0].prices[0].original.value,'2.4');
  }
  for (const reason of ['current_slate_read_expired','current_slate_read_capacity']) {
    let calls = 0, recoveries = 0;
    await assert.rejects(readSlate(new LatestRead(async()=>{calls++;return refused(reason);}),context,
      {onRecovery:()=>recoveries++}),error => error.message.includes(reason) && error.requiresReload === true);
    assert.equal(calls,2,'repeated refusal cannot create an endless recovery loop'); assert.equal(recoveries,1);
  }
  const cancelledReleases=[];let pageCalls=0;
  const stopAfterPage=new LatestRead(async(url,options)=>{
    if(options.method==='DELETE'){cancelledReleases.push(new URL(url,'http://authored.local').searchParams.get('read_token'));return ok({released:true});}
    pageCalls++;return ok(firstPage);
  });
  assert.equal(await readSlate(stopAfterPage,context,{isCurrent:()=>pageCalls===0}),null);
  assert.deepEqual(cancelledReleases,[firstPage.read_token]);
  let completeReleases=0;
  const completeFrame=frame(1);
  await readSlate(new LatestRead(async(_url,options)=>{if(options.method==='DELETE')completeReleases++;return ok(page(completeFrame));}),context);
  assert.equal(completeReleases,0,'displayed complete results keep their lease');
  let busyCalls = 0;
  await assert.rejects(readSlate(new LatestRead(async()=>{busyCalls++;return new Response(JSON.stringify({error:'current_read_busy',reason:'Read capacity; retry shortly.'}),{status:429});}),context),/Read capacity/);
  assert.equal(busyCalls,2);
  for (const reason of ['current_slate_read_context_changed','current_slate_read_token_required','slate_response_byte_capacity']) {
    let calls = 0;
    await assert.rejects(readSlate(new LatestRead(async()=>{calls++;return refused(reason);}),context),new RegExp(reason));
    assert.equal(calls,1,'crossed context or invalid bound cannot be silently retried');
  }
  const missing = copy(firstPage); delete missing.read_token;
  await assert.rejects(readSlate(new LatestRead(async()=>ok(missing)),context),/token unavailable/);

  // A request deadline is a visible read failure, whereas explicit cancellation
  // supersedes its generation. Neither may silently restart a partial frame.
  const savedSetTimeout = globalThis.setTimeout, savedClearTimeout = globalThis.clearTimeout;
  const deadlines = [];
  try {
    globalThis.setTimeout = callback => { deadlines.push(callback); return deadlines.length; };
    globalThis.clearTimeout = () => {};
    let timeoutCalls = 0, timeoutRecoveries = 0;
    const slowReader = new LatestRead((_url,{signal}) => {
      timeoutCalls++;
      return new Promise((_resolve,reject) => signal.addEventListener('abort',()=>reject(new DOMException('Deadline','AbortError'))));
    });
    const timedRead = readSlate(slowReader,context,{onRecovery:()=>timeoutRecoveries++});
    deadlines.at(-1)();
    await assert.rejects(timedRead,error=>error.code==='current_read_timeout' && error.name!=='AbortError' && /timed out/.test(error.message));
    assert.equal(timeoutCalls,1,'deadline enters ordinary failure budget without an immediate fresh retry');
    assert.equal(timeoutRecoveries,0); assert.equal(slowReader.pending,false);
    let delayed;
    const ignoresAbort = new LatestRead(()=>new Promise(resolve=>{delayed=resolve;}));
    const lateRead = readSlate(ignoresAbort,context); deadlines.at(-1)(); delayed(ok(firstPage));
    await assert.rejects(lateRead,error=>error.code==='current_read_timeout');
    const superseded = readSlate(slowReader,context); deadlines.at(-1)(); slowReader.cancel();
    assert.equal(await superseded,null,'explicit cancellation still wins over a pending deadline failure');
  } finally {
    globalThis.setTimeout = savedSetTimeout; globalThis.clearTimeout = savedClearTimeout;
  }

  let deliver, cancelledCalls = 0;
  const cancelledReader = new LatestRead(()=>{cancelledCalls++;return new Promise(resolve=>{deliver=resolve;});});
  const abandoned = readSlate(cancelledReader,context); cancelledReader.cancel(); deliver(ok(firstPage));
  assert.equal(await abandoned,null); assert.equal(cancelledCalls,1,'abandoned requests cannot ask for another page');
  let recoveringCalls = 0;
  const recoveringReader = new LatestRead(async()=>{recoveringCalls++;return refused('current_slate_read_expired');});
  assert.equal(await readSlate(recoveringReader,context,{onRecovery:()=>recoveringReader.cancel()}),null);
  assert.equal(recoveringCalls,1,'cancellation during recovery cannot start a fresh frame');
  const waiting = [];
  const sharedReader = new LatestRead(()=>new Promise(resolve=>waiting.push(resolve)));
  const oldTab = readSlate(sharedReader,context), newTab = readSlate(sharedReader,context);
  waiting[0](ok(firstPage)); assert.equal(await oldTab,null,'superseded tab completion cannot publish');
  const single = frame(1,'new-tab'); waiting[1](ok(page(single)));
  assert.equal((await newTab).read_token,single.read_token);
  const independentTabs = await Promise.all(['tab-a','tab-b'].map(name=>{
    const own = frame(60,name);
    return readSlate(new LatestRead(async url=>ok(page(own,Number(new URL(url,'http://authored.local').searchParams.get('offset'))))),context);
  }));
  assert.notEqual(independentTabs[0].read_token,independentTabs[1].read_token);
  assert(independentTabs.every(v=>v.boards.length===60),'independent tab reads complete their own frame');

  const selectedBoard = first.boards[0], q = selectedBoard.prices[0];
  const identity = {...q.inputs_identity,quote_revision:q.quote_revision,observation_revision:'selected-observation',policy_revision:selectedBoard.policy.revision};
  const inputs = {version:'predict-board-inputs-2',game_key:selectedBoard.game_key,quote_id:q.quote_id,
    quote_revision:q.quote_revision,observation_revision:identity.observation_revision,calculation_context:selectedBoard.calculation_context,evidence:{original:q.original}};
  checkInputs(inputs,{...context,game:selectedBoard.game_key},identity);
  for (const change of [x=>x.quote_revision++,x=>x.observation_revision='new-observation',x=>x.calculation_context.context_id='new-context']) {
    const changed = copy(inputs); change(changed);
    // A newer paging token cannot authorize any replacement selected input.
    changed.read_token = fresh.read_token;
    assert.throws(()=>checkInputs(changed,{...context,game:selectedBoard.game_key},identity));
  }
  assert.equal(providerRequests,0);
  console.log('PASS authored 60-game multisport captured/fresh reads, token/context/clock nonmixing, one fresh recovery, refusal/timeout/cancellation/tab bounds, original clocks aging and exact selected-input guards; zero provider dispatches');
})().catch(error=>{console.error(error);process.exitCode=1;});

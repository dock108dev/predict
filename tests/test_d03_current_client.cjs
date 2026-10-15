// Authored current transport checks; no acquisition or installed/live evidence.
const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
const {fixture,board,coverage,bounds,copy}=require('./current_board_fixture.cjs');
(async()=>{
 const {checkBoard,checkSlate,checkDetails,checkInputs,SlateAccumulator,defaults}=await import(pathToFileURL(path.resolve('app/dashboard/opportunity_static/current/board-client.js')));
 const c={...defaults,view:'odds',filter:'all'},games=Array.from({length:500},(_,i)=>({...copy(fixture.catalog.games[0]),game_key:'authored-game:'+i,title:'Authored game '+i}));
 const completed=new Set(),assembled=new SlateAccumulator(c);
 for(let offset=0;offset<500;offset+=50){
  const boards=games.slice(offset,offset+50).map(g=>{const b=board(fixture.odds,g.game_key);b.prices=[];return b;});
  const v={version:'predict-comparison-slate-2',epoch:'authored-reset-1',read_revision:'authored-reset:revision:engine',policy:fixture.odds.policy,games,boards,errors:[],view:'odds',filter:'all',stopped:false,bounds,coverage:coverage(500,offset)};
  checkSlate(v,c);assembled.append(v,Buffer.byteLength(JSON.stringify(v)));if(offset<450)assert.throws(()=>assembled.result(),/incomplete/);for(const b of v.boards)completed.add(b.game_key);
  for(const mutate of [x=>x.coverage.total_games=499,x=>x.coverage.returned_games=49,x=>x.coverage.next_offset=offset,x=>x.boards.pop(),x=>x.read_revision='',x=>x.bounds.maximum_games=200,x=>x.games.push({...games[0],game_key:'501st'})]){const broken=copy(v);mutate(broken);assert.throws(()=>checkSlate(broken,c));}
 }
 assert.equal(completed.size,500,'every catalog game represented exactly once');
 const complete=assembled.result();assert.equal(complete.version,'predict-comparison-slate-view-2');assert.equal(complete.boards.length,500);assert.equal(complete.coverage.page_count,10);assert.equal(complete.coverage.returned_games,500);assert(complete.coverage.wire_bytes>0);assert.equal(complete.bounds.maximum_page_bytes,8388608);assert.equal(complete.bounds.maximum_read_bytes,83886080);assert(!Object.hasOwn(complete.bounds,'maximum_bytes'),'aggregate never claims one page wire limit');assert.throws(()=>checkSlate(complete,c));assert.throws(()=>assembled.append(complete,1),/capacity/);
 const samplePage={version:'predict-comparison-slate-2',epoch:'authored-reset-1',read_revision:'same-read',policy:fixture.odds.policy,games:games.slice(0,1),boards:[board(fixture.odds,games[0].game_key)],view:'odds',filter:'all',stopped:false,bounds,coverage:coverage(1)};
 for(const size of [-1,1.5,8388609])assert.throws(()=>new SlateAccumulator(c).append(samplePage,size),/capacity/);
 const last=new SlateAccumulator(c);last.append(samplePage,8388608);assert.equal(last.result().coverage.wire_bytes,8388608);
 assert.notEqual(last.result().boards,samplePage.boards,'no duplicate page board-array ownership');assert.equal(last.result().boards[0],samplePage.boards[0],'board graphs retained by reference, never cloned');
 const b=copy(fixture.ev),ev={...c,view:'ev',game:b.game_key},selected=b.rows.find(r=>r.quote_id===fixture.single.quote.id).details;
 checkBoard(b,ev);checkDetails(fixture.single,ev,selected);
 for(const mutate of [x=>x.version='predict-comparison-board-1',x=>x.calculation_context.context_id='after-reset',x=>x.prices[0].inputs_identity.context_id='before-reset',x=>x.rows[0].details.context_id='prior-inputs',x=>x.result_id='legacy-result']){const broken=copy(b);mutate(broken);assert.throws(()=>checkBoard(broken,ev));}
 for(const mutate of [x=>x.calculation_context.context_id='after-restart',x=>x.original_inputs_identity.context_id='crossed',x=>x.quote.id='removed',x=>x.snapshot_id='legacy']){const broken=copy(fixture.single);mutate(broken);assert.throws(()=>checkDetails(broken,ev,selected));}
 const q=b.prices[0],identity={...q.inputs_identity,policy_revision:b.policy.revision},inputs={version:'predict-board-inputs-2',game_key:b.game_key,quote_id:q.quote_id,calculation_context:b.calculation_context,evidence:{original:q.original}};
 checkInputs(inputs,ev,identity);
 for(const mutate of [x=>x.quote_id='crossed',x=>x.game_key='other-game',x=>x.calculation_context.context_id='after-reset',x=>x.evidence=null,x=>x.version='predict-board-inputs-1']){const broken=copy(inputs);mutate(broken);assert.throws(()=>checkInputs(broken,ev,identity));}
 console.log('PASS D03 500-event/50-per-page complete coverage, omitted/crossed pages, v2 current identities, reset/restart/removed Details and selected Original guards');
})().catch(e=>{console.error(e);process.exitCode=1;});

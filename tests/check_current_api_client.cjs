// Cross-language check of real Python current-row API output. The caller owns
// the data/evidence class; this reads only the supplied response fixture.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
(async()=>{
 const fixture=JSON.parse(fs.readFileSync(process.argv[2]));
 const {checkBoard,checkSlate,checkDetails,checkInputs}=await import(pathToFileURL(path.resolve('app/dashboard/opportunity_static/current/board-client.js')));
 const context=v=>({amount:v.policy.requested_amount_usd,buffer:v.policy.buffer_rate,benchmark_venue:v.policy.benchmark_venue,benchmark_method:v.policy.benchmark_method,sizing_mode:v.policy.sizing_mode,view:v.view,filter:v.filter,game:v.game_key});
 for(const name of ['odds','ev','arbs'])checkBoard(fixture[name],context(fixture[name]));
 checkSlate(fixture.slate,context(fixture.slate));
 const d=fixture.details,board=d.pair?fixture.arbs:fixture.ev;
 const row=board.rows.find(r=>d.pair?r.pair_id===d.pair.id:r.quote_id===d.quote.id);assert(row,'selected current row');
 checkDetails(d,context(board),row.details);
 const original=fixture.odds.prices.find(q=>q.quote_id===fixture.inputs.quote_id);assert(original,'selected original current quote');
 checkInputs(fixture.inputs,context(fixture.odds),{...original.inputs_identity,policy_revision:fixture.odds.policy.revision});
 assert.equal(fixture.inputs.evidence.original.value,original.original.value);
 assert.equal(fixture.inputs.evidence.original.units,original.original.units);
 console.log('PASS actual Python current-row API → JavaScript v2 guards: Odds, EV, Arbs, selected Details, selected Original native price/units and paged slate');
})().catch(e=>{console.error(e);process.exitCode=1;});

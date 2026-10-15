// Authored v2 context bindings around retained v1 financial examples. These
// identities test transport only; they do not claim production/current data.
const fs = require('node:fs');
const copy = value => JSON.parse(JSON.stringify(value));
const fixture = JSON.parse(fs.readFileSync('tests/fixtures/ev09-u01-responses.json'));
function context(policy, game) {
  return {context_id:'authored-context:'+game,epoch:'authored-reset-1',dependency_revision:'authored-dependency-1',policy_revision:policy.revision,engine_binding:'authored-engine-1'};
}
function board(value, game=value.game_key) {
  const v=copy(value);v.version='predict-comparison-board-2';v.game_key=game;
  v.calculation_context=context(v.policy,game);v.calculation_context.dependency_revision=v.input_version;delete v.result_id;delete v.snapshot_id;
  for(const q of v.prices) Object.assign(q.inputs_identity,{game_key:game,context_id:v.calculation_context.context_id});
  for(const row of v.rows) if(row.details){delete row.details.result_id;delete row.details.snapshot_id;row.details.context_id=v.calculation_context.context_id;}
  return v;
}
for(const key of ['odds','ev','arbs']) fixture[key]=board(fixture[key]);
for(const key of ['single','pair']){
 const v=fixture[key],game=fixture.ev.game_key;v.version='predict-board-details-2';v.game_key=game;v.calculation_context=context(v.policy,game);v.calculation_context.dependency_revision=fixture.ev.input_version;delete v.result_id;delete v.snapshot_id;delete v.original_inputs_identity.result_id;v.original_inputs_identity.context_id=v.calculation_context.context_id;
}
function coverage(total,offset=0,limit=50){const returned=Math.min(limit,total-offset),next=offset+returned<total?offset+returned:null;return {total_games:total,offset,limit,returned_games:returned,next_offset:next,complete:next===null};}
const bounds={maximum_games:500,maximum_page_games:50,maximum_bytes:8388608};
module.exports={fixture,board,context,coverage,bounds,copy};

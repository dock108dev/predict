const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url'),path=require('node:path');
(async()=>{
 const {followGame}=await import(pathToFileURL(path.resolve('app/dashboard/opportunity_static/current/board-client.js')));
 const old={game_key:'old',scope:'NFL/full_game/winner',start_at:'2026-10-16T00:15:00+00:00',participants:[{id:'NFL:SEA',role:'away'},{id:'NFL:DEN',role:'home'}],members:[['the_odds_api','original-event'],['kalshi','original-native']],matches:[{status:'matched',conflicts:[]}]};
 const current={...old,game_key:'new',members:[...old.members,['polymarket_us','new-member']]};
 assert.equal(followGame(old,[current],'old'),'new');
 assert.equal(followGame(current,[old],'new'),'old');
 assert.equal(followGame(old,[old,current],'old'),'old');
 assert.equal(followGame(null,[current],'old'),'old');
 for(const change of [
  {start_at:'2026-10-17T00:15:00+00:00'},
  {participants:[{id:'NFL:SEA',role:'home'},{id:'NFL:DEN',role:'away'}]},
  {participants:[{id:'NFL:KC',role:'away'},{id:'NFL:DEN',role:'home'}]},
  {members:[['the_odds_api','different-event']]},
  {scope:'NFL/full_game/spread'},
  {matches:[{status:'unresolved',conflicts:[]}]},
  {matches:[{status:'matched',conflicts:['source_role_or_identity_conflict']}]},
 ])assert.equal(followGame(old,[{...current,...change}],'old'),'old');
 assert.equal(followGame(old,[current,{...current,game_key:'ambiguous'}],'old'),'old');
 assert.equal(followGame({...old,matches:[]},[current],'old'),'old');
 assert.equal(followGame({...old,members:null},[current],'old'),'old');
 const pinned={game_key:'old',result_id:'immutable-result',snapshot_id:'immutable-snapshot'};
 followGame(old,[current],'old');assert.deepEqual(pinned,{game_key:'old',result_id:'immutable-result',snapshot_id:'immutable-snapshot'});
 console.log('PASS exact member/role/start continuity; conflicts, replacement, ambiguity and saved Details boundaries');
})().catch(e=>{console.error(e);process.exitCode=1;});

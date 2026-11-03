const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');const path=require('node:path');
(async()=>{
 const {groupedPriceRows,bestPrices,cellOffers}=await import(pathToFileURL(path.resolve('app/dashboard/opportunity_static/current/odds-grid.js')));
 const q=(id,venue,value,state='current')=>({quote_id:id,venue,source:{quote_side:'buy'},same_outcome:{supported:true,key:['game','line']},selection:{participant:'home',predicate:'cover',signed_line:'-6.5'},market:{market:'spread',period:'full_game'},original:{value,units:'decimal_odds'},common_odds:{supported:true},observation_display:{state}});
 const a=q('a','novig','2'),b=q('b','kalshi','200000000000000000001/100000000000000000000'),ref=q('ref','pinnacle','20'),stale=q('old','prophetx','100','last_known');
 const group=groupedPriceRows({prices:[a,b,ref,stale]})[0];assert.equal(group.quotes.length,4);assert.deepEqual([...bestPrices(group)],['b']);
 assert.deepEqual([...bestPrices({...group,comparable:false})],[]);
 const native={...b,quote_id:'no',same_outcome:{supported:true,key:['game','not_win']}};
 assert.equal(groupedPriceRows({prices:[a,b,native]}).length,2);
 assert.equal(cellOffers({...group,quotes:[stale,{...a,venue:'prophetx'}]},'prophetx')[0].quote_id,'a');
 const expired={...b,observation_display:{state:'current',current_until:'2020-01-01T00:00:00Z'}};
 assert.deepEqual([...bestPrices({...group,quotes:[a,expired]})],['a']);
 console.log('PASS exact best price, currentness, reference exclusion, native outcome separation and unqualified guards');
})().catch(e=>{console.error(e);process.exitCode=1;});

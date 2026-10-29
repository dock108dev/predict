// Authored presentation examples, never live financial qualification.
const assert=require('node:assert/strict');
const {Element}=require('./ev07_dom.cjs');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
global.fetch=()=>{throw Error('Presentation must not acquire data');};
(async()=>{
 const {dashboardScope,dashboardMessage,drawOpportunityDashboard,compareExactPercent,dashboardMetric}=await import(pathToFileURL(path.resolve('app/dashboard/opportunity_static/current/opportunity-dashboard.js')));
 const g={game_key:'authored',title:'Authored Home at Away',league:'NFL',start_at:'2026-10-25T17:00:00Z',participants:[{id:'home',name:'Home'},{id:'away',name:'Away'}]};
 const fields={ev:['buffered_ev_usd','buffered_return_percent'],arbs:['buffered_complete_modeled_minimum_usd','buffered_complete_minimum_return_percent'],conditional:['conditional_buffered_ev_usd','conditional_buffered_return_percent']};
 function row(id,value,state='numeric_current',kind='ev'){
  const [field,pct]=fields[kind];
  const q={quote_id:id,venue:'novig',native_side:'bookmaker_outcome',selection:{participant:'home',predicate:'win'},market:{market:'moneyline',period:'full_game'},original:{value:'2.0',units:'decimal_odds'},availability:{state,numeric_metrics:value==null?[]:[field],metrics:{[field]:{state,reason_codes:[]}},current_opportunity_eligible:state==='numeric_current'},financial_metrics:{[field]:value,[pct]:value},freshness:{status:state==='numeric_current'?'current':'historical'},classification:{main_positive_eligible:Number(value)>0},details:{context_id:'authored-context',quote_id:id}};
  if(kind==='arbs'){q.pair_id=id;delete q.quote_id;q.legs=[{...q,quote_id:'a'}, {...q,quote_id:'b',venue:'prophetx'}];q.details={context_id:'authored-context',pair_id:id};}
  return q;
 }
 function slate(rows,complete=true){return {games:[g],boards:[{game_key:g.game_key,rows,prices:rows.flatMap(r=>r.legs||[r]),availability:{evaluation_complete:complete,causes:[]}}],errors:[],stopped:false};}
 let v=slate([row('negative','-3'),row('zero','0'),row('less-negative','-1')]);
 assert.equal(dashboardScope(v,'ev').state,'evaluated_no_positive');
 assert.equal(compareExactPercent('1.00000000000000000001','1.00000000000000000002'),1);
 assert.equal(compareExactPercent('1e-20','0.00000000000000000002'),1);
 assert.equal(compareExactPercent('1/3','0.3333333333333333333333'),-1);
 const positive=slate([row('b','1.004'),row('a','1.003'),row('c','2')]);
 assert.deepEqual(dashboardScope(positive,'ev').positive.map(e=>e.row.quote_id),['c','b','a']);
 const conditional=slate([row('conditional','9','numeric_current','conditional')],false);
 assert.equal(dashboardScope(conditional,'ev').positive.length,0);
 assert.notEqual(dashboardScope(conditional,'ev').state,'evaluated_no_positive');
 for(const state of ['missing_inputs','unsupported_inputs','missing_reference','not_evaluated','calculation_failed']){
  const a=slate([row(state,null,state)],false), scope=dashboardScope(a,'ev');
  assert.equal(scope.positive.length,0);assert.notEqual(scope.state,'evaluated_no_positive');
  assert.ok(dashboardMessage(scope,'ev').length);
 }
 assert.equal(dashboardScope(slate([row('old','5','numeric_last_known')]),'ev').state,'last_known');
 assert.equal(dashboardScope(slate([row('p','3'),row('missing',null,'missing_inputs')],false),'ev').state,'partial');
 const empty=slate([],false);empty.boards[0].delivery_state='pending';assert.equal(dashboardScope(empty,'ev').state,'pending');
 assert.equal(dashboardScope({...positive,dashboard_error:'read failed'},'ev').state,'failed');
 assert.equal(dashboardScope({...positive,dashboard_error:'read failed'},'ev').positive.length,0);
 assert.equal(dashboardScope(positive,'ev',{league:'NBA'}).state,'no_matches');
 assert.equal(dashboardScope(null,'ev').state,'loading');
 assert.equal(dashboardScope(positive,'ev',{source:'kalshi'}).positive.length,0);
 const arb=slate([row('covered','2','numeric_current','arbs')]);assert.equal(dashboardScope(arb,'arbs').positive.length,1);
 arb.boards[0].rows[0].legs[1].venue='novig';assert.equal(dashboardScope(arb,'arbs').positive.length,0);
 const root=new Element('section');let clicked;
 const gross=row('gross',null,'unsupported_inputs');gross.gross_decisive_benchmark={available:true,state:'numeric_last_known',return_percent:'-475/214'};
 const trade=row('trade',null,'unsupported_inputs');trade.conditional_trade_benchmark={available:true,state:'numeric_last_known',return_percent:'-1/1000000'};
 assert.equal(dashboardScope(slate([trade],false),'ev').positive.length,0);
 trade.conditional_trade_benchmark.normalization_label='one-contract, one-fill scenario';
 assert.match(dashboardMetric(trade,'trade').label,/one-contract, one-fill scenario/);
 v=slate([...v.boards[0].rows,gross,trade]);
 drawOpportunityDashboard(root,{ev:v,arbs:empty},{},(r,b,game)=>clicked={r,game});
 assert.match(root.textContent,/Positive arbitrage/);assert.match(root.textContent,/Positive expected value/);assert.match(root.textContent,/before fees and exceptional settlement/);
 const research=root.querySelectorAll('details').find(d=>d.dataset.key==='research:ev:false');
 assert.deepEqual(research.querySelectorAll('article').map(n=>n.dataset.key.split(':').pop()),['zero','less-negative','negative']);
 research.querySelector('button').onclick();assert.equal(clicked.r.quote_id,'zero');assert.equal(clicked.game,g);
 assert.match(root.textContent,/Last-known.*Gross comparisons/);
 assert.match(root.textContent,/Last-known.*Conditional trade-fee benchmarks/);
 assert.match(root.textContent,/Not calibrated full net EV or executable sizing/);
 assert.ok(root.querySelectorAll('a').some(a=>a.href==='/odds'));
 drawOpportunityDashboard(root,{ev:v},{league:'NHL',source:'kalshi',family:'winner',period:'full_game',search:'Seattle'},()=>{},['ev']);
 const oddsLink=root.querySelectorAll('a').find(a=>a.href?.startsWith('/odds'));
 assert.equal(oddsLink.href,'/odds?sport=NHL&venue=kalshi&family=moneyline&period=full_game&search=Seattle');
 assert.match(root.textContent,/No retained games or markets match these filters/);
 drawOpportunityDashboard(root,{ev:null},{},()=>{},['ev']);
 assert.match(root.textContent,/Loading saved results/);assert(!root.textContent.includes('Calculations pending'));
 console.log('PASS authored dashboard: exact ordering, distinct metrics, all availability states, filters, coherent Details, no acquisition');
})().catch(e=>{console.error(e);process.exitCode=1;});

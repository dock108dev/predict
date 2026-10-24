// Authored presentation examples. No provider, database, or financial qualification.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {pathToFileURL}=require('node:url');
const {Element}=require('./ev07_dom.cjs');
document.createTextNode=value=>{const n=new Element('span');n.textContent=value;return n;};
global.fetch=()=>{throw Error('Renderer must remain a local read');};
(async()=>{
 const base=pathToFileURL(process.cwd()+'/app/dashboard/opportunity_static/current/');
 const {renderOriginalDetails,renderSavedDetails}=await import(new URL('stored-details.js',base));
 const {priceResearch,typedGameTitle}=await import(new URL('board-elements.js',base));
 const f=JSON.parse(fs.readFileSync('tests/fixtures/ev09-u01-responses.json'));
 const participants=[{id:'home',name:'Green Bay'},{id:'away',name:'Detroit'}];
 const now=new Date().toISOString(),until=new Date(Date.now()+60000).toISOString();
 const q={...f.odds.prices[0],quote_id:'selected',venue:'kalshi',native_side:'no',selection:{participant:'home',predicate:'not_win'},market:{market:'winner',period:'full_game'},original:{value:'43.00000001',units:'cents'},event:{title:'Green Bay covers -3.5',league:'NFL',start_at:until},times:{source_at:now,received_at:now,source_time_kind:'provider_book'},observation_display:{state:'current',current_until:until},freshness:{status:'current',reasons:[]}};
 const peer={...q,quote_id:'peer',venue:'polymarket_us',native_side:'short',original:{value:'0.44',units:'usd_per_contract'}};
 const root=new Element('div');
 for(const [value,n] of [['1','1'],['-1','-1'],['0','0']]){
  q.gross_comparison={available:true,value,unit:'cents',exact:{numerator:n,denominator:'1'},display_status:'current',comparison_quote_id:'peer',inputs:[q,peer].map(x=>({...x,gross_comparison:undefined}))};
  const before=JSON.stringify(q);renderOriginalDetails(q,{evidence:{title:q.event.title}},{root,participants,title:q.event.title});
  assert(root.children[0].textContent.includes('Green Bay vs Detroit · Winner'));
  assert(!root.children[0].textContent.includes('covers'));
  const lead=root.querySelector('.price-lead');assert(lead.textContent.includes('43.00000001 cents'));assert(lead.textContent.includes('0.44 usd per contract'));
  assert(lead.textContent.includes('NO'));assert(lead.textContent.includes('Short'));
  assert(root.querySelector('.comparison-takeaway').textContent.includes(n==='0'?'equals':n==='1'?'lower than':'higher than'));
  assert(root.querySelector('.comparison-takeaway').textContent.includes('before costs'));
  assert(root.querySelectorAll('details').every(x=>!x.open));assert.equal(JSON.stringify(q),before);
 }
 for(const state of ['current','pending','last_known','unknown']){q.observation_display.state=state;assert.equal(priceResearch(q),state!=='current');}
 q.observation_display.state='current';q.freshness.reasons=['pregame_ended'];assert(priceResearch(q));
 q.gross_comparison={available:false,reason:'occurrence_identity_ambiguous'};
 renderOriginalDetails(q,{evidence:{status:'Supplement failed'}},{root,participants});assert(root.querySelector('.price-lead').textContent.includes('43.00000001'));assert(root.querySelector('.comparison-takeaway').textContent.includes('occurrence identity ambiguous'));
 renderSavedDetails(f.single,{root,participants:f.catalog.games[0].participants});
 assert(root.querySelectorAll('details').every(x=>!x.open));assert(root.textContent.includes('Selected amount, fees, buffer & reconciliation'));

 const modeled=structuredClone(f.single);
 const estimate=modeled.quote.calculations.funded_estimate;
 estimate.modeled_basis={product:"Authored NFLWIN scenario",probability:"Uncalibrated",scenario_parameters:{refund_given_void:"1"},sensitivity:{buffered_ev_low_usd:"-1",buffered_ev_high_usd:"2",sign_changes:true,threshold_condition:"Tie and void fixed",break_even_expected_void_receipt_per_face:"0.5",break_even_receipt_feasible:true,break_even_void_probability_zero_receipt:"0.001",break_even_void_feasible:true,formula:"Explicit parameter formula"}};
 estimate.financial_metrics={...estimate.financial_metrics,conditional_buffered_ev_usd:"1",buffered_ev_usd:"2"};
 renderSavedDetails(modeled,{root,participants:f.catalog.games[0].participants});
 assert(root.textContent.includes("Assumptions reverse the sign."));
 assert(root.textContent.includes("Conditional net EV · decisive outcomes · buffered"));
 assert(root.textContent.includes("Hypothetical refund scenario · buffered"));
 assert(root.textContent.includes("Break-even void rate"));
 assert(root.textContent.includes("not a confidence interval or guaranteed minimum"));

 const {createComparisonSlate}=await import(new URL('comparison-slate-views.js',base));
 const game=f.catalog.games[0], failed={...game,game_key:'failed-game',title:'Failed game',participants:[{id:'x',name:'Failed'},{id:'y',name:'Opponent'}]};
 const slate={policy:f.odds.policy,games:[game,failed],boards:[f.odds],errors:[{game_key:failed.game_key,reason:'board_compact_response_capacity'}]};
 const content=new Element('section');createComparisonSlate({content,onOriginal(){},onDetails(){}}).draw(slate,{view:'odds',filter:'all',source:'kalshi',family:'winner'});
 assert(content.textContent.includes('Other returned games remain usable'));
 assert(content.textContent.includes('Failed vs Opponent · Prices unavailable'));
 assert(content.textContent.includes('board_compact_response_capacity'));
 assert(content.querySelectorAll('.slate-odds').length>0,'healthy games survive the local failure');
 assert(!content.textContent.includes('Failed vs Opponent · No retained prices'),'failure is not an empty price count');
 assert.equal(typedGameTitle([], 'Fallback'),'Fallback');
 console.log('PASS U2 captured pair, signed direction, NO/Short, exact original units, typed heading, collapsed evidence, research and supplemental failure');
})().catch(e=>{console.error(e);process.exitCode=1;});

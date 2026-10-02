const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const context={BoardView:{words:x=>x,title:x=>({name:x}),sourceState:x=>x},PredictDecision:require('../app/dashboard/opportunity_static/decision.js')};
vm.createContext(context);vm.runInContext(fs.readFileSync('app/dashboard/opportunity_static/comparisons.js','utf8')+';this.render=PriceComparisons.render',context);
const leg={label:'Novig via The Odds API',ask:'.4',decimal_odds:'2.5',contract:'Outcome',entry:{quantity:'1',lower:null,basis:'No executable depth'},depth_limit:'Published limits are not depth'};
const row={id:'retained',aggregated:true,historical:true,identity:{competition:'NFL',family:'moneyline',period:'full_game'},legs:[leg,{...leg,label:'ProphetX via The Odds API'}],outcome:'Example',game_title:'Example',lower_raw:'Equal',raw_difference:'0',timing:{reason:'Historical',receipt_skew_seconds:'0'},settlement_status:'UNKNOWN',settlement:'Unknown terms'};
const text=context.render({comparisons:[row]},String,()=>'/game');
assert(text.includes('Decimal odds 2.5'));assert(text.includes('raw implied 40.0000%'));assert(!text.includes('$.4'));assert(!text.includes('Simulation · no market link'));assert(text.includes('Contract sizing unavailable'));assert(!text.includes('class="size-evaluate"'));
console.log('PASS: aggregate odds units, historical links, and sizing isolation');

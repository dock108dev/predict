const assert=require('assert'),fs=require('fs'),vm=require('vm');
const context=vm.createContext({Set,Number,JSON,BoardView:require('../app/dashboard/opportunity_static/presentation.js')});
vm.runInContext(fs.readFileSync('app/dashboard/opportunity_static/comparisons.js','utf8')+'\nthis.api=PriceComparisons;',context);
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const leg={label:'Kalshi',ask:'0.5000',top_size:null,connection:'disconnected',status:'stale or unavailable',market_state:'unknown',entry:{quantity:'100',lower:null,basis:'Unknown costs'},contract:'<img onerror=alert(1)>'};
const row={id:'a',outcome:'<script>',game_title:'Event',identity:{competition:'NFL',period:'full_game',line:null},legs:[leg,{...leg,label:'Polymarket US'}],historical:true,mode:'synthetic',timing:{reason:'unknown'},settlement_status:'INCOMPATIBLE'};
const html=context.api.render({comparisons:[row]},esc,()=>'/game');
assert(html.includes('&lt;script&gt;'));assert(!html.includes('<script>'));assert(html.includes('Quantity unknown'));assert(html.includes('Simulation · Saved observations'));assert(html.includes('Settlement rules differ'));assert(html.includes('Raw comparison unavailable'));assert(html.includes('Disconnected'));assert(html.includes('$0.5000'));
console.log('Price comparison presentation: PASS');

for(const url of ['javascript:alert(1)','data:text/html,test','file:///tmp/test','//attacker.example','https://user:secret@example.com','https://example.com/\\evil']){
 const unsafe=context.api.render({comparisons:[{...row,legs:[{...leg,url}]}]},esc,()=>'/game');
 assert(!unsafe.includes('target="_blank"'));
}
const allowed=context.api.render({comparisons:[{...row,legs:[{...leg,url:'https://kalshi.com/markets/example?market=A&side=yes'}]}]},esc,()=>'/game');
assert(allowed.includes('https://kalshi.com/markets/example?market=A&amp;side=yes'));
assert(allowed.includes('rel="noopener noreferrer"'));

assert(html.includes('Full game'));
assert(!html.split('<details>')[0].includes('full_game'));
assert(html.includes('full_game')); // Original evidence remains unchanged in Details.
assert(!html.includes('line none'));
assert(html.includes('At saved time: Disconnected'));
const zeroLine=context.api.render({comparisons:[{...row,identity:{...row.identity,line:0}}]},esc,()=>'/game');
assert(zeroLine.includes('line 0'));
const current=context.api.render({comparisons:[{...row,historical:false}]},esc,()=>'/game');
assert(current.includes('Current observations'));
assert(!current.includes('At saved time:'));

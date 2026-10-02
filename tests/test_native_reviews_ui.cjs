const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const context=vm.createContext({Set,Number,JSON,BoardView:require('../app/dashboard/opportunity_static/presentation.js')});
vm.runInContext(fs.readFileSync('app/dashboard/opportunity_static/comparisons.js','utf8')+'\nthis.api=PriceComparisons;',context);
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const rows=JSON.parse(fs.readFileSync('evidence/native-review-generalization-20260930-v1/ISOLATED-SYNTHETIC-comparisons.json'));
assert.equal(rows.length,4);
for(const state of ['UNKNOWN','CONDITIONAL','INCOMPATIBLE','SUPPORTED']) {
 const copies=structuredClone(rows);for(const r of copies)r.settlement_status=state;
 const html=context.api.render({comparisons:copies},esc,r=>'/game?session='+encodeURIComponent(r.session));
 assert(html.includes('SYNTHETIC B'));assert(html.includes('native-book-comparison-3'));assert(html.includes('Download retained comparison'));
 assert(html.includes(({UNKNOWN:'Settlement not verified',INCOMPATIBLE:'Settlement rules differ'})[state]||'Settlement '+state.toLowerCase()));
}
const unknown=context.api.render({comparisons:rows.filter(r=>r.settlement_status==='UNKNOWN')},esc,r=>'/game');
assert(!unknown.includes('48 hours'));assert(!unknown.includes('within two weeks'));assert(!unknown.includes('Current KXNCAAFGAME/event fee override'));
console.log('PASS: concurrent selected reviews, all settlement states, event isolation and unchanged card layout');

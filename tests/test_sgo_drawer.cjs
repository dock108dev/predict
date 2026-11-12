// Render-only fixture: no browser, database, provider, or live account access.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {Element}=require('./ev07_dom.cjs');
document.createTextNode=value=>{const n=new Element('span');n.textContent=value;return n;};
document.querySelector=()=>null;
global.window={};
const folder='app/dashboard/opportunity_static/current/';
const code=['ui-common.js','snapshot-views.js','snapshot-drawer.js'].map(x=>fs.readFileSync(folder+x,'utf8')).join('\n')+'\nglobalThis.drawer=SnapshotDrawer;';
vm.runInThisContext(code);
const row={id:'pinned',kind:'single',venue:'novig',game_title:'Away at Home',selection:{predicate:'over',signed_line:'224.5'},
  market:{market:'total',period:'full_game'},source:{provider:'sportsgameodds'},original:{value:'-110',units:'american_odds'},
  times:{source_at:'2026-11-10T20:00:00Z',received_at:'2026-11-10T20:00:01Z'},display:{offered:{american:'-110',decimal:'1.91'}},
  probability:'1/2',gross_return_percent:'2',conditional_return_percent:null,reference_calculation:{available:true,venue:'sportsgameodds_books',
    method:'sgo-book-median-proportional-1',fair_decimal_odds:'2',contributors:[{venue:'book-a',inputs:[{side:'over',price_american:'-110',line:'224.5',source_at:'2026-11-10T20:00:00Z',received_at:'2026-11-10T20:00:01Z'}]}]},
  sgo_fair_comparison:{available:true,price_american:'-105',line:'225',same_line:false,received_at:'2026-11-10T20:00:01Z'}};
const result={games:[],assumptions:{benchmark_venue:'pinnacle'}};
const details={assumptions:{},row:{},originals:[]};
const before=JSON.stringify(row);
const view=drawer.content({row,result,details,metric:'gross_return_percent'},'/inspect');
assert(view.textContent.includes('SportsGameOdds bookmaker median'));
assert(view.textContent.includes('median of their decisive probabilities'));
assert(view.textContent.includes('Fair American odds'));
assert(view.textContent.includes('different line; not the fair price for this offer'));
assert(view.textContent.indexOf('EV before trade fees') < view.textContent.indexOf('SportsGameOdds fair odds'),
  'the offer calculation should precede the separate vendor comparison');
assert(view.textContent.includes('Original source timeUnknown'));
assert(view.textContent.includes('Price providerSportsGameOdds'));
assert(view.textContent.includes('Source typeAggregate'));
assert(view.textContent.includes('2026-11-10T20:00:01Z'));
assert.equal(JSON.stringify(row),before,'pinned inputs must not be mutated by rendering');
const unavailable={...row,probability:null,gross_return_percent:null,reference_calculation:{available:false,venue:'sportsgameodds_books'}};
const empty=drawer.content({row:unavailable,result,details,metric:'gross_return_percent'},'/inspect');
assert(empty.textContent.includes('SportsGameOdds bookmaker median reference unavailable'));
assert(empty.textContent.includes('Fair price unavailable in the pinned display'));
const vendorUnavailable={...row,sgo_fair_comparison:{...row.sgo_fair_comparison,available:false}};
const unavailableView=drawer.content({row:vendorUnavailable,result,details,metric:'gross_return_percent'},'/inspect');
assert(unavailableView.textContent.includes('Unavailable from SportsGameOdds'));
assert(unavailableView.textContent.includes('This baseline is unavailable or incomplete'));
console.log('PASS SGO saved details fixture');

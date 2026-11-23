// Real renderers: exact selection, focused offers, references, immutable export and timing.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {Element}=require('./ev07_dom.cjs');
const downloads=[],revoked=[];
const context={document,Date,Intl,JSON,Math,Number,String,BigInt,Map,Set,Error,URLSearchParams,
 Blob,URL:{createObjectURL:blob=>{downloads.push(blob);return 'blob:exact-evidence';},revokeObjectURL:url=>revoked.push(url)},
 clock:value=>new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'}).format(new Date(value))};
const strip=source=>source.replace(/^import .*;\n/gm,'').replace(/export /g,'');
const load=(name,names)=>Object.assign(context,vm.runInNewContext('(()=>{'+strip(fs.readFileSync('app/dashboard/opportunity_static/current/'+name,'utf8'))+';return {'+names+'};})()',context));
load('workspace-format.js','dateTime,venue,readable,percent,odds,selection,number');
load('data-market.js','marketRow,renderMarket,renderMarketInput');
const positive={id:'positive-main',revision:'exact-revision',venue:'kalshi',outcome:'Utah Jazz',family:'spread',line:'27/2',main_role:'main',price:'109',price_units:'american_odds',fee_mode:{enabled:false},calculation:{status:'positive',net_ev_percent:'56/25'}};
const negative={...positive,id:'negative-other',outcome:'Other team',line:'-13.5',calculation:{status:'negative',net_ev_percent:'-2'}};
const alternate={...positive,id:'alternate',line:'14.5',main_role:'alternate',calculation:{status:'positive',net_ev_percent:'20'}};
const row={id:'game|spread|full_game',pull_id:'pull-2',title:'Jazz at Other team',sport:'NBA',start_at:'2026-11-24T00:00:00Z',family:'spread',state:'complete',received_at:'2026-11-23T22:00:00Z',headline:positive,previous_capture:{pull_id:'pull-1'}};
const value={row,offers:[positive,negative,alternate],selected_offer:positive,reference_inputs:[{facts:{venue:'fanduel',side:'away',line:'13.5',price_american:'110',received_at:row.received_at}}],snapshot:{event:{away:'Utah Jazz'}},history:[{pull_id:'pull-1',state:'complete',received_at:'2026-11-23T21:00:00Z'}]};
(async()=>{
 let navigation;const tr=context.marketRow(row,new URLSearchParams('sport=NBA&calculation_status=positive&token=sql-lease'),q=>navigation=q);
 assert.match(tr.textContent,/Utah Jazz \+13.5/);assert.match(tr.textContent,/\+109/);assert.match(tr.textContent,/\+2.24%/);assert(!tr.textContent.includes('27/2'));
 tr.querySelector('a').onclick({button:0,preventDefault(){}});assert.equal(navigation.get('offer'),positive.id);assert.equal(navigation.get('revision'),positive.revision);assert.equal(navigation.get('pull'),row.pull_id);assert.equal(navigation.get('calculation_status'),'positive');
 const root=new Element('div');let selected,capture;context.renderMarket(root,value,{positive:true,onSelect:offer=>selected=offer,onCapture:item=>capture=item});
 assert(!root.textContent.includes('Other team -13.5'));assert(!root.textContent.includes('+14.5'),'Default positive focus excludes alternate despite its larger EV');root.querySelectorAll('button').find(b=>b.textContent==='Reference inputs').onclick();assert.match(root.textContent,/FanDuel/);assert.match(root.textContent,/Utah Jazz \+13.5/);
 root.querySelectorAll('button').find(b=>b.textContent==='Alternates').onclick();assert.match(root.textContent,/Alternate/);root.querySelectorAll('button').find(b=>b.textContent==='Inspect').onclick();assert.equal(selected.id,alternate.id);
 root.querySelectorAll('button').find(b=>b.textContent==='History').onclick();root.querySelectorAll('button').find(b=>b.textContent.startsWith('Previous capture')).onclick();assert.equal(capture.pull_id,'pull-1');
 context.renderMarket(root,value,{positive:true,includeAlternates:true,onSelect:()=>{},onCapture:()=>{}});assert(root.textContent.includes('+14.5'),'Explicit include alternates widens the focused population');
 const cleanup=context.renderMarketInput(root,value);assert.match(root.textContent,/Stored screening EV \+2.24%/);assert.match(root.textContent,/Fees OFF/);assert.match(root.textContent,/Supporting reference prices in this pull/);assert.equal(root.querySelector('a').href,'blob:exact-evidence');
 const exported=JSON.parse(await downloads[0].text());assert.equal(exported.selected_offer.revision,positive.revision);assert.equal(exported.row.pull_id,row.pull_id);cleanup();assert.deepEqual(revoked,['blob:exact-evidence']);
 const incomplete=context.marketRow({...row,state:'failed',headline:null,reason:'request failed'},new URLSearchParams(),()=>{});assert(!incomplete.textContent.includes('+2.24%'));assert.match(incomplete.textContent,/Capture failed/);
 console.log('Market renderer passed: exact headline, focused offers, same-pull references, alternates, history, captured export and failed-state null.');
})().catch(error=>{console.error(error);process.exitCode=1;});

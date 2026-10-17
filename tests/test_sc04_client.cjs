// Protocol, cancellation, paging and native-identity regression checks.
const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
const source=fs.readFileSync('app/dashboard/opportunity_static/current/scanner-client.js','utf8');
const {scannerDefaults,scannerQuery,checkScannerPage,scannerSelection,ScannerReader}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const copy=x=>JSON.parse(JSON.stringify(x)),fixture=JSON.parse(fs.readFileSync('tests/fixtures/sc04/workload.json')),v=fixture.page,f=scannerDefaults();
checkScannerPage(v,f,0);const selected=scannerSelection(v,v.rows[0]);assert.equal(selected.row_id,v.rows[0].id);assert(!('rank' in selected));
let u={...copy(v),mode:'unchanged',rows:[]};assert.equal(checkScannerPage(u,f,0,v).rows.length,100);
assert.throws(()=>checkScannerPage({...u,ranked_ids:[]},f,0,v));
let r={...copy(v),mode:'replace_page',publication_revision:2,rows:copy(v.rows).slice(5),ranked_ids:v.ranked_ids.slice(5)};assert.equal(checkScannerPage(r,f,0,v).rows.length,95);
let resync={...copy(v),mode:'resync',epoch:'new',server_id:'restart',publication_revision:0};checkScannerPage(resync,f,0,v);
for(const change of [x=>x.rows[0].category='conditional_hedge',x=>x.rows[0].settlement_complete=false,x=>x.rows[0].current=false,x=>x.rows[0].positions[1].native_key[0]='pinnacle',x=>x.rows[0].id='wrong',x=>x.epoch='crossed',x=>x.publication_revision=-1,x=>x.offset=100,x=>x.filters.minimum_edge='10',x=>x.total_matching=4097]){const x=copy(v);change(x);assert.throws(()=>checkScannerPage(x,f,0,v));}
assert.equal(scannerQuery(f,100,v).get('expected_revision'),'1');assert.equal(scannerQuery(f,0,v).get('since'),'1');assert(!scannerQuery(f).has('amount'));
const published=[],states=[],requests=[];let compatibilityCalls=0;
const reader=new ScannerReader({assetRevision:'assets',onPage:p=>published.push(p),onState:s=>states.push(s),onCompatibility:()=>states.push('incompatible'),fetcher:async url=>{if(url==='/api/scanner/client'){compatibilityCalls++;return new Response(JSON.stringify({protocol:v.version,asset_revision:'assets',assets_valid:true}));}return new Promise(resolve=>requests.push({url,resolve}));}});
reader.configure(f);await new Promise(setImmediate);assert.equal(requests.length,1);
reader.configure({...f,minimum_edge:'2'});await new Promise(setImmediate);assert.equal(requests.length,2);
requests[1].resolve(new Response(JSON.stringify({...v,filters:{...f,minimum_edge:'2'}})));await new Promise(setImmediate);assert.equal(published.length,1);
requests[0].resolve(new Response(JSON.stringify(v)));await new Promise(setImmediate);assert.equal(published.length,1,'delayed superseded filter must not publish');
reader.close();assert.equal(reader.controller,null);
const bound=new ScannerReader({assetRevision:'x',onPage:()=>{},onState:()=>{},onCompatibility:()=>{},fetcher:async()=>new Response(' '.repeat(2097153))});await assert.rejects(bound.json('/',new AbortController().signal),/bound/);bound.close();
let count=0;const conflict=new ScannerReader({assetRevision:'assets',onPage:()=>{},onState:s=>states.push(s),onCompatibility:()=>{},fetcher:async url=>new Response(JSON.stringify(url==='/api/scanner/client'?{protocol:v.version,asset_revision:'assets',assets_valid:true}:{error:'scanner_page_revision_changed'}),{status:url==='/api/scanner/client'?200:409})});conflict.page=v;conflict.configure(f,100);await new Promise(setImmediate);assert.equal(conflict.page,null);assert.equal(conflict.offset,0);conflict.close();
const incompatible=new ScannerReader({assetRevision:'assets',onPage:()=>count++,onState:()=>{},onCompatibility:()=>states.push('incompatible'),fetcher:async()=>new Response(JSON.stringify({protocol:v.version,asset_revision:'different',assets_valid:true}))});await incompatible.read();assert.equal(count,0);assert(incompatible.incompatible);incompatible.close();assert(compatibilityCalls>=2);
console.log('PASS SC04 snapshot/unchanged/replace/resync, crossed identity/category/native venues, bounds, exact selection, delayed filters, paging409 and asset incompatibility');
})().catch(e=>{console.error(e);process.exitCode=1;});

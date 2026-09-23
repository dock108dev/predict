const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('app/dashboard/opportunity_static/dashboard.js','utf8');
const ctx={};vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('function rememberDetails'),source.indexOf('function render')),ctx);
const detail=(key,open=false)=>({dataset:{detailKey:key},open});
const root=nodes=>({querySelectorAll:selector=>selector.endsWith('[open]')?nodes.filter(d=>d.open):nodes});
const old=[detail('references',true),detail('reference-a',true),detail('markets')];
const remembered=ctx.rememberDetails(root(old));
// Poll changes reference count/order; preserve exact identity, not array index.
const refreshed=[detail('markets'),detail('references'),detail('reference-new'),detail('reference-a')];
ctx.restoreDetails(root(refreshed),remembered);
assert.deepEqual(refreshed.map(d=>d.open),[false,true,false,true]);
// Closed groups stay closed and vanished records are not resurrected.
ctx.restoreDetails(root([detail('reference-other',true)]),remembered);
const other=detail('reference-other',true);ctx.restoreDetails(root([other]),remembered);assert.equal(other.open,false);
console.log('PASS: source and reference details survive refresh by stable identity');

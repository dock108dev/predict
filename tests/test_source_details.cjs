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

// A replacement control keeps focus by identity, never by row position or label.
const body={},search={};
ctx.document={activeElement:body,body};
let owners=[];
ctx.$=()=>({querySelectorAll:()=>owners});
const control=(owner,{key,tag='SUMMARY',href=null,visible=true}={})=>({
 dataset:key?{focusKey:key}:{},tagName:tag,
 closest:()=>owner,getAttribute:()=>href,getClientRects:()=>visible?[{}]:[],
 focus(options){assert.equal(options.preventScroll,true);ctx.document.activeElement=this;}
});
const owner=(id,reference=false)=>({dataset:reference?{detailKey:id}:{id},controls:[],querySelectorAll(){return this.controls;}});
const original=owner('native"[odd-id]');
ctx.document.activeElement=control(original,{key:'game-details',tag:'A',href:'/game?cutoff=old'});
const savedFocus=ctx.rememberFocus();
const replacement=owner(original.dataset.id),otherRow=owner('another-row');
replacement.controls=[control(replacement,{key:'game',tag:'A'}),control(replacement,{key:'game-details',tag:'A',href:'/game?cutoff=new'})];
owners=[otherRow,replacement];ctx.document.activeElement=body;ctx.restoreFocus(savedFocus);
assert.equal(ctx.document.activeElement,replacement.controls[1]);
ctx.document.activeElement=search;ctx.restoreFocus(savedFocus);assert.equal(ctx.document.activeElement,search);
owners=[otherRow];ctx.document.activeElement=body;ctx.restoreFocus(savedFocus);assert.equal(ctx.document.activeElement,body);
const refOwner=owner('reference-a',true),refSummary=control(refOwner);
ctx.document.activeElement=refSummary;const refFocus=ctx.rememberFocus();
const newRef=owner('reference-a',true);newRef.controls=[control(newRef)];
owners=[newRef];ctx.document.activeElement=body;ctx.restoreFocus(refFocus);assert.equal(ctx.document.activeElement,newRef.controls[0]);
newRef.controls=[control(newRef,{visible:false})];ctx.document.activeElement=body;ctx.restoreFocus(refFocus);assert.equal(ctx.document.activeElement,body);
console.log('PASS: keyed focus survives changed links and reordering; missing/hidden controls and deliberate focus changes are respected');

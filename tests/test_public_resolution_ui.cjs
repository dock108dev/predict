'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const bundle=JSON.parse(fs.readFileSync('evidence/public-contract-integration-20261001-v1/synthetic-lifecycle/selected-reopening-result.json'));
const data=bundle.responses.find(x=>x.view);assert(data);
data.view.local_observation_lineage.basis='<script>SYNTHETIC</script> local receipt only';
const elements={};const document={getElementById:id=>elements[id]??=( {innerHTML:'',value:'',hidden:false,textContent:'',replaceChildren(){this.innerHTML='';}})};
const context={window:{},document,URLSearchParams,fetch:async()=>({ok:true,json:async()=>data}),location:{search:''},history:{replaceState(){}}};
vm.runInNewContext(fs.readFileSync('app/dashboard/opportunity_static/resolution.js','utf8'),context);
(async()=>{await context.window.PredictResolution.load(new URLSearchParams());const html=elements['resolution-output'].innerHTML;assert(html.includes('Local observations and remediation links'));assert(html.includes('&lt;script&gt;SYNTHETIC&lt;/script&gt;'));assert(!html.includes('<script>'));assert(html.includes('published_at'));assert(html.includes('Venue-reported settlement'));console.log('Public resolution Details preserve local lineage, missing clocks and escaping.');})().catch(e=>{console.error(e);process.exitCode=1;});

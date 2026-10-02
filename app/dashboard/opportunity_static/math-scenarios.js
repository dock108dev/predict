'use strict';
const PredictMath=(()=>{
 const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function example(){
  const fee={basis:'notional',rate:'0',grid:'.01',rounding:'half_even',aggregation:'per_fill'};
  return {states:['A wins','B wins','Refund'],complete:true,ceiling:'10',probabilities:{'A wins':'.45','B wins':'.45',Refund:'.10'},legs:[['A','.4'],['B','.5']].map(([id,price],i)=>({id,minimum:'.5',increment:'.5',partial_final:true,levels:[{price,quantity:'3',liquidity_id:id}],fee_policy:fee,payouts:Object.fromEntries(['A wins','B wins','Refund'].map((s,j)=>[s,{kind:j===2?'refund':'fraction',value:j===2?'1':i===j?'1':'0',settlement_fee_per_unit:'0'}]))}))};
 }
 function controls(row){
  const binding={session:row.session,hash:row.hash,cutoff:row.cutoff};
  return '<details class="math-panel" data-math-binding="'+esc(JSON.stringify(binding))+'"><summary>Settlement & allocation What-if</summary><p>Separate hypothetical analysis. Entered assumptions never qualify native execution, fees or settlement.</p><details><summary>Odds and stake conversion</summary><label>Odds format<select class="math-odds-format"><option value="decimal_odds">Decimal</option><option value="american_odds">American</option><option value="fractional_odds">Fractional</option><option value="probability">Implied probability</option><option value="percent">Implied percentage</option></select></label><label>Odds value<input class="math-odds-value" value="2.5"></label><label>Stake ($)<input class="math-stake" value="12"></label><button type="button" class="math-convert">Convert odds and stake</button></details><button type="button" class="math-references">Inspect complete reference sets</button><button type="button" class="math-example">Load hypothetical example</button><label>Import a saved scenario<input type="file" class="math-import" accept="application/json,.json"></label><label>Probability basis<select class="math-reference-choice"><option value="">Manual What-if</option></select></label><label><input type="checkbox" class="math-conditioning">Use only the quoted reference outcomes; exceptional probabilities remain unknown</label><label>Scenario assumptions<textarea class="math-spec" rows="6" aria-label="Scenario assumptions"></textarea></label><label>Explicit quantities, comma separated (blank searches the supplied grid)<input class="math-quantities" placeholder="e.g. 1, 1.5"></label><button type="button" class="math-evaluate">Calculate What-if</button><button type="button" class="math-save">Save this result</button><label>Saved scenarios at this cutoff<select class="math-history"><option value="">Most recently saved</option></select></label><button type="button" class="math-restore">Reopen saved result</button><button type="button" class="math-download">Download exact result</button><div class="math-result" aria-live="polite"></div></details>';
 }
 function render(r){
  let html='<p>'+esc(r.label)+'</p><p>'+esc(r.original_outputs)+'</p>';
  for(const ref of r.references?.estimates||[])html+='<p><b>Reference-derived estimate · '+esc(ref.provenance.book)+'</b><br>'+esc(ref.method)+' · '+Object.entries(ref.probabilities).map(([k,v])=>esc(k)+': '+esc((Number(v)*100).toFixed(4))+'%').join(' · ')+'<br>'+esc(ref.assumptions)+'<br>'+esc(ref.conditioning)+'<br>Receipt '+esc(ref.freshness.received_at)+'; provider delay unknown</p>';
  for(const ex of r.references?.exclusions||[])html+='<p>Reference excluded: '+esc(ex.book)+' · '+esc(ex.reason)+'</p>';
  if(r.conversion){const x=r.conversion;html+='<p>Decimal odds '+esc(x.decimal_odds)+' · American odds '+esc(x.american_odds)+' · implied probability '+esc(x.implied_probability)+'<br>Stake $'+esc(x.stake)+' · gross winning payout $'+esc(x.gross_win_payout)+' · winning profit $'+esc(x.win_profit)+' · losing profit $'+esc(x.loss_profit)+'<br>'+esc(x.interpretation)+'</p>';}
  const c=r.calculation, v=c?.best??(c?.states?c:null);
  if(c?.search)html+='<p>'+esc(c.search.optimality)+' · '+esc(c.search.evaluated)+' / '+esc(c.search.total_grid_allocations)+' allocations evaluated</p>';
  if(v)html+='<p>Quantities: '+esc(v.quantities.join(', '))+' · committed cash $'+esc(v.committed_cash??'unknown')+'<br>Worst state net $'+esc(v.worst_case_return??'unavailable')+' · return '+esc(v.return_pct??'unavailable')+'%<br>'+esc(v.ev_label)+': $'+esc(v.expected_net??'unavailable')+' · '+esc(v.ev_pct??'unavailable')+'%</p><table><thead><tr><th>Joint settlement state</th><th>Net cashflow</th></tr></thead><tbody>'+Object.entries(v.states).map(([k,x])=>'<tr><td>'+esc(k)+'</td><td>'+esc(x??'unknown')+'</td></tr>').join('')+'</tbody></table><p>'+v.reasons.map(esc).join('<br>')+'</p>';
  if(c?.partial_fill_exposure)html+='<details><summary>Partial-fill exposure</summary><p>'+esc(c.limitation)+'</p>'+c.partial_fill_exposure.map(x=>'<p>'+esc(x.quantities.join(', '))+' units: worst net $'+esc(x.worst_case_return??'unknown')+'</p>').join('')+'</details>';
  if(c?.curve)html+='<details><summary>Ranked evaluated sizes</summary><p>Objective: '+esc(c.objective)+'; up to 64 evaluated candidates.</p>'+c.curve.map(x=>'<p>'+esc(x.quantities.join(', '))+' units · cash $'+esc(x.committed_cash??'unknown')+' · worst net $'+esc(x.worst_case_return??'unknown')+' · EV '+esc(x.ev_pct??'unavailable')+'%</p>').join('')+'</details>';
  return html;
 }
 async function request(body){const response=await fetch('/api/math-scenario',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const r=await response.json();if(!response.ok)throw Error(r.error);return r;}
 function key(root){return 'predict-math-1:'+root.dataset.mathBinding;}
 function history(root){const prefix=key(root)+':';const entries=Object.keys(localStorage).filter(k=>k.startsWith(prefix));root.querySelector('.math-history').innerHTML='<option value="">Most recently saved</option>'+entries.map(k=>'<option value="'+esc(k)+'">Scenario '+esc(k.slice(-12))+'</option>').join('');}
 if(typeof document!=='undefined'){
  document.addEventListener('change',async e=>{
   if(!e.target.classList.contains('math-import'))return;
   const root=e.target.closest('.math-panel');try{const file=e.target.files[0];if(file.size>262144)throw Error('Scenario file too large');const v=JSON.parse(await file.text());root.querySelector('.math-spec').value=JSON.stringify(v.spec||v,null,2);}catch(err){root.querySelector('.math-result').textContent=err.message;}
  });
  document.addEventListener('click',async e=>{
   if(!e.target.className?.startsWith?.('math-'))return;
   const root=e.target.closest('.math-panel');if(!root)return;const out=root.querySelector('.math-result');
   try{
    if(e.target.classList.contains('math-example')){root.querySelector('.math-spec').value=JSON.stringify(example(),null,2);return;}
    if(e.target.classList.contains('math-save')){if(!root.mathResult)throw Error('Calculate a result first');localStorage.setItem(key(root)+':'+root.mathResult.sha256,JSON.stringify(root.mathResult));localStorage.setItem(key(root),JSON.stringify(root.mathResult));history(root);out.insertAdjacentHTML('beforeend','<p>Saved separately at this exact cutoff.</p>');return;}
    if(e.target.classList.contains('math-download')){if(!root.mathResult)throw Error('Calculate a result first');const a=document.createElement('a');a.href='/api/math-scenario-download?sha256='+encodeURIComponent(root.mathResult.sha256);a.download='predict-math-1.json';a.textContent='Download prepared calculation';out.appendChild(a);a.click();return;}
    let r;
    if(e.target.classList.contains('math-restore')){const saved=localStorage.getItem(root.querySelector('.math-history').value||key(root));if(!saved)throw Error('No saved result for this cutoff');r=await request({replay:JSON.parse(saved)});}
    else if(e.target.classList.contains('math-convert'))r=await request({...JSON.parse(root.dataset.mathBinding),conversion:{value:root.querySelector('.math-odds-value').value,convention:root.querySelector('.math-odds-format').value,stake:root.querySelector('.math-stake').value}});
    else if(e.target.classList.contains('math-references'))r=await request(JSON.parse(root.dataset.mathBinding));
    else if(e.target.classList.contains('math-evaluate')){const body={...JSON.parse(root.dataset.mathBinding),spec:JSON.parse(root.querySelector('.math-spec').value)};const q=root.querySelector('.math-quantities').value.trim();if(q)body.quantities=q.split(',').map(x=>x.trim());const reference=root.querySelector('.math-reference-choice').value;if(reference!==''){body.reference_estimate=Number(reference);body.reference_conditioning_acknowledged=root.querySelector('.math-conditioning').checked;}r=await request(body);}
    else return;
    root.mathResult=r;out.innerHTML=render(r);history(root);
    if(r.spec){root.querySelector('.math-spec').value=JSON.stringify(r.spec,null,2);root.querySelector('.math-quantities').value=(r.quantities||[]).join(', ');}
    const choice=root.querySelector('.math-reference-choice'),selected=choice.value;choice.innerHTML='<option value="">Manual What-if</option>'+(r.references?.estimates||[]).map((x,i)=>'<option value="'+i+'">'+esc(x.provenance.book)+' · '+esc(x.method)+' · conditional reference</option>').join('');if([...choice.options].some(x=>x.value===selected))choice.value=selected;
   }catch(err){out.textContent=err.message;}
  });
 }
 return {controls,render,example};
})();
if(typeof module!=='undefined')module.exports=PredictMath;

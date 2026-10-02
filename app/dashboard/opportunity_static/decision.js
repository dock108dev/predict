'use strict';
const PredictDecision=(()=>{
 function summary(d,esc){
  if(!d)return '';
  return '<section aria-label="Decision summary"><strong>'+esc(d.conclusion)+'</strong>'+['settlement','costs','freshness','quantity','net_reason'].map(k=>(d[k]||[]).length?'<p><b>'+esc(({settlement:'Settlement',costs:'Costs',freshness:'Freshness',quantity:'Quantity',net_reason:'Why net is unavailable'})[k])+'</b><br>'+d[k].map(esc).join('<br>')+'</p>':'').join('')+'</section>';
 }
 function controls(row,esc){
  const math=typeof PredictMath==='undefined'?'':PredictMath.controls(row);
  if(row.aggregated)return math+ '<p>Contract sizing unavailable: aggregate quantity, execution and fees unknown.</p>';
  const data=JSON.stringify({session:row.session,hash:row.hash,cutoff:row.cutoff,contract:row.contract||row.legs[0].id,reference:row.reference_id||'',probability:typeof row.probability==='string'?row.probability:null});
  return math+'<div class="size-explorer" data-size-binding="'+esc(data)+'"><label>Compare contract sizes<input class="size-values" value="1, 10, 100" aria-label="Explicit contract sizes"></label><label>Spending ceiling ($, optional)<input class="size-ceiling" type="number" min="0.01" step="0.01"></label><button type="button" class="size-evaluate">Compare sizes at this cutoff</button><div class="size-result" aria-live="polite"></div></div>';
 }
 function sizeHtml(r,esc){
  const pct=x=>x==null?'unavailable':Number(x).toFixed(4);
  return '<p>'+esc(r.original_outputs)+' · '+esc(r.at)+'</p>'+r.sizes.map(s=>'<h4>'+esc(s.requested)+' contracts requested per leg</h4><p>Native acquisitions (alternative contracts; quantities are not additive)</p>'+s.acquisitions.map(l=>'<p>'+esc(l.venue)+' · '+esc(l.contract)+' · supplied depth '+esc(l.visible_size??'unknown')+'<br>Raw acquisition $'+esc(l.entry.notional??'unknown')+' · provisional entry '+(l.entry.upper==null?esc(l.entry.reason):'$'+esc(l.entry.lower)+'–$'+esc(l.entry.upper))+'</p>').join('')+'<p>Complementary contract combinations below use the shared conditional-return engine.</p>'+(s.limitation?'<p>'+esc(s.limitation)+'</p>'+s.fractional_entries.map(l=>'<p>'+esc(l.venue)+' · '+esc(l.contract)+': '+(l.entry.upper==null?esc(l.entry.reason)+'; raw acquisition $'+esc(l.entry.notional??'unknown'):'$'+esc(l.entry.lower)+'–$'+esc(l.entry.upper)+' provisional entry')+'</p>').join(''):'<p>Conditional EV: $'+esc(s.ev?.expected_profit??'unavailable')+' · '+esc(pct(s.ev?.return_pct))+'%. '+esc(s.ev?.reference_limitation||s.ev?.conditional_on||'Supported probability and complete costs required.')+'</p>'+s.candidates.map(c=>'<p><b>'+esc(c.title)+'</b> · '+esc(c.modeled_quantity)+' modeled'+(c.depth_limited?' · depth limited':'')+'<br>'+c.legs.map(l=>esc(l.label)+': notional $'+esc(l.notional??'unknown')+', fee $'+esc(l.fee??'unknown')+', committed $'+esc(l.cash??'unknown')+'; supplied depth '+esc(l.visible_size??'unknown')).join('<br>')+'<br>Combined cash $'+esc(c.cash??'unknown')+' · conditional net $'+esc(c.profit??'unavailable')+' · return '+esc(pct(c.return_pct))+'%'+(r.ceiling?' · ceiling '+(c.within_ceiling==null?'cannot be verified':c.within_ceiling?'met':'exceeded'):'')+'</p>'+summary(c.decision,esc)).join(''))).join('')+'<p>'+esc(r.search)+'</p><p>'+(r.best?'Best evaluated conditional net: $'+esc(r.best.profit)+' at '+esc(r.best.quantity)+' contracts.':'No supported conditional result among these sizes.')+'</p>';
 }
 return {summary,controls,sizeHtml};
})();
if(typeof document!=='undefined')document.addEventListener('click',async e=>{
 if(!e.target.classList.contains('size-evaluate'))return;
 const root=e.target.closest('.size-explorer'),out=root.querySelector('.size-result');
 e.target.disabled=true;out.textContent='Calculating retained inputs…';
 try{
  const body={...JSON.parse(root.dataset.sizeBinding),sizes:root.querySelector('.size-values').value.split(',').map(x=>x.trim()),ceiling:root.querySelector('.size-ceiling').value,scenario:document.getElementById('scenario')?.value||'unknown'};
  const response=await fetch('/api/decision-sizes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),r=await response.json();
  if(!response.ok)throw Error(r.error);
  out.innerHTML=PredictDecision.sizeHtml(r,x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])));
 }catch(err){out.textContent=err.message;}finally{e.target.disabled=false;}
});
if(typeof module!=='undefined')module.exports=PredictDecision;

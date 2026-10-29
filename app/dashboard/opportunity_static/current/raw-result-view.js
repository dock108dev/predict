// Captured overlays never grant current eligibility, even if the saved row did.
import { numeric, percent } from './board-values.js';
const words = value => String(value || 'Unknown').replaceAll('_', ' ');
const venue = value => ({kalshi:'Kalshi',polymarket_us:'Polymarket US',novig:'Novig',prophetx:'ProphetX',pinnacle:'Pinnacle'}[value] || value);
const gap = reason => ({
  exact_pinnacle_opposition_unavailable:'No complete Pinnacle pair for this exact event, outcome and line.',
  exact_native_reference_pair_absent:'No complete Pinnacle pair for this native outcome and exact line.',
  estimate_source_clock_unknown:'The source has not supplied a usable price timestamp.',
  modeled_winner_basis_expired_or_not_effective:'The captured outcome model is outside its applicability interval.',
  conditional_fee_review_expired_or_not_effective:'The captured fee review is outside its applicability interval.',
  kalshi_instrument_fee_schedule_unbound:'The effective instrument fee schedule and multiplier are not bound.',
  prophetx_account_fee_model_and_rate_unbound:'The account-specific fee model and rate are not bound.',
}[reason] || words(reason));
function node(tag, text){const n=document.createElement(tag);n.textContent=text;return n;}
export function capturedCalculation(record) {
  const result=record.result || {}, root=document.createElement('details');
  root.append(node('summary',`${record.view==='odds'?'Equivalent outcome prices':record.view==='ev'?'Captured financial comparison':'Captured modeled margin'} · ${record.calculated_at || result.read_at || 'time unknown'}`));
  root.append(node('p','Last-known captured evidence · Current eligibility is not established. These calculation inputs may differ from the price opened above.'));
  if(record.view==='odds') root.append(node('p',`${result.display_value} · ${result.meaning} · before fees`));
  else {
    for(const [key,label] of [['gross_decisive_benchmark','Gross decisive return'],['conditional_trade_benchmark','Conditional trade-fee return']]) {
      const metric=result[key];
      if(metric?.available && numeric(metric.return_percent)!==null) {
        root.append(node('p',`${label} · last-known: ${numeric(metric.return_percent)>0?'+':''}${percent(metric.return_percent)}`));
        root.append(node('p',key==='gross_decisive_benchmark'?'Per normal acquisition, before fees; decisive outcomes only. Ties, pushes and exceptional settlement excluded.':`${metric.normalization_label || 'Per modeled risk'}. ${metric.condition || 'Conditional scenario only.'}`));
      } else root.append(node('p',`${label} unavailable: ${gap(metric?.reason || 'not_evaluated')}`));
    }
    const metrics=result.financial_metrics || {};
    const fields=record.view==='ev'?[['buffered_ev_usd','buffered_return_percent','Modeled net return'],['conditional_buffered_ev_usd','conditional_buffered_return_percent','Conditional net return · decisive outcomes only']]:[['buffered_complete_modeled_minimum_usd','buffered_complete_minimum_return_percent','Complete modeled minimum'],['buffered_decisive_opposing_margin_usd','buffered_decisive_return_percent','Decisive opposing margin']];
    let supported=false;
    for(const [amount,rate,label] of fields) if(result.availability?.numeric_metrics?.includes(amount) && numeric(metrics[rate])!==null) {
      root.append(node('p',`${label} · last-known: ${percent(metrics[rate])}${result.modeled_basis?' · uncalibrated assumptions':''}`));supported=true;
    }
    if(!supported) root.append(node('p',`${record.view==='ev'?'Complete modeled EV':'Complete modeled margin'} unavailable: ${(result.reasons?.length?result.reasons:result.availability?.reason_codes || ['not_evaluated']).map(gap).join(' ')}`));
    root.append(node('p','Missing evaluation is not zero return. Gross and conditional benchmarks do not establish qualified net EV or executable arbitrage.'));
  }
  for(const p of record.captured_inputs || []) root.append(node('p',`${venue(p.venue)} original · ${p.selection?.label || p.selection?.participant || p.source?.native_outcome_id || 'Outcome'}${p.selection?.signed_line==null?'':' · line '+p.selection.signed_line} · ${words(p.native_side)} · ${p.original?.value ?? 'Unknown'} ${words(p.original?.units)} · Source ${p.times?.source_at || 'unknown'}`));
  const gross=result.gross_decisive_benchmark;
  for(const ref of gross?.reference_originals || []) {
    const s=ref.selection || {};
    root.append(node('p',`Pinnacle reference · ${s.label || s.native?.original_wording || s.participant || s.predicate || 'Outcome'}${s.signed_line==null?'':' · line '+s.signed_line} · ${ref.decimal_odds} decimal odds · Source ${ref.source_at || ref.market_at || ref.book_at || 'unknown'}`));
  }
  if(gross?.available) root.append(node('p',`Selected decisive probability: ${gross.selected_decisive_probability ?? 'Unknown'} · Cost per $1 normal claim: ${gross.acquisition_usd_per_normal_claim ?? 'Unknown'} USD`));
  const evidence=document.createElement('details'), original=node('pre',JSON.stringify(record,null,2));original.className='raw-detail';evidence.append(node('summary','Calculation basis and exact inputs'),original);root.append(evidence);
  return root;
}

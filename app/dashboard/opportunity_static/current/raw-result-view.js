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
  root.append(node('summary',`${record.view==='ev'?'Captured financial comparison':'Captured modeled margin'} · ${record.calculated_at || record.captured_at || 'time unknown'}`));
  root.append(node('p','Last-known captured evidence · Current eligibility is not established. These calculation inputs may differ from the price opened above.'));
  if(record.view==='ev'){
    const metrics = [
      ['Gross decisive return', result.gross_return_percent, result.probability_missing],
      ['Sportsbook estimate before fees', result.sportsbook_baseline?.return_percent, result.probability_missing],
      ['Conditional trade-fee return', result.conditional_return_percent, result.conditional_trade_benchmark?.reason],
      ['Conservative trade-fee return', result.conservative_return_percent, result.conservative_trade_benchmark?.reason],
      ['Assumed net return', result.net_return_percent, result.math?.missing?.join(', ')],
    ];
    for(const [label, value, reason] of metrics){
      root.append(node('p', numeric(value) === null
        ? `${label} unavailable: ${gap(reason || 'not_evaluated')}`
        : `${label} · last-known: ${numeric(value) > 0 ? '+' : ''}${percent(value)}`));
    }
  } else {
    const value = result.minimum_return_percent;
    root.append(node('p', numeric(value) === null
      ? `Assumed scenario minimum unavailable: ${gap(result.math?.missing?.join(', ') || 'not_evaluated')}`
      : `Assumed scenario minimum · last-known: ${percent(value)}`));
  }
  for(const p of record.captured_inputs || []) root.append(node('p',`${venue(p.venue)} original · ${p.selection?.label || p.selection?.participant || p.source?.native_outcome_id || 'Outcome'}${p.selection?.signed_line==null?'':' · line '+p.selection.signed_line} · ${words(p.native_side)} · ${p.original?.value ?? 'Unknown'} ${words(p.original?.units)} · Source ${p.times?.source_at || 'unknown'}`));
  const evidence=document.createElement('details'), original=node('pre',JSON.stringify(record,null,2));original.className='raw-detail';evidence.append(node('summary','Calculation basis and exact inputs'),original);root.append(evidence);
  return root;
}

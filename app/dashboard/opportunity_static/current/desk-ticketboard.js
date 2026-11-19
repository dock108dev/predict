const {el} = window.PredictUI;
const dollars = new Intl.NumberFormat('en-US', {style:'currency', currency:'USD'});
const wholeDollars = new Intl.NumberFormat('en-US', {style:'currency', currency:'USD', maximumFractionDigits:0});
export function unitLabel(value) {
  const amount = Number(value);
  return (Number.isInteger(amount) ? wholeDollars : dollars).format(amount);
}
export const conditioningLabel = value => ({if_no_draw:'if no draw', if_no_push:'if no push',
  if_decisive_completed_game:'for a decisive completed game'})[value];

export function ticketFacts(entries, className) {
  const list = el('dl', null, className);
  for (const [label, value] of entries) {
    const cell = el('div');
    const detail = el('dd');
    detail.append(value ?? 'Unavailable');
    cell.append(el('dt', label), detail);
    list.append(cell);
  }
  return list;
}

export function modeledOdds(display = {}, raw = {}, blended = false) {
  const american = blended ? display.blended_offer : display.after_fee_odds;
  const decimal = blended ? raw.blended_decimal : raw.after_fee_decimal;
  return american || decimal ? odd({american:american ?? display.after_fee_decimal, decimal}) : 'Unavailable';
}

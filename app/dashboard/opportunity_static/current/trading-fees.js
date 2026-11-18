import './ui-common.js';

const {el, num} = window.PredictUI;
const dollars = value => new Intl.NumberFormat('en-US', {
  style:'currency', currency:'USD', notation:'standard'
}).format(num(value));
const date = value => value && new Intl.DateTimeFormat('en-US', {
  timeZone:'America/New_York', dateStyle:'medium'
}).format(new Date(value));

try {
  const response = await fetch('/api/trading-fees');
  if (!response.ok) throw Error('Unavailable');
  const guide = await response.json();
  for (const [venue, terms] of Object.entries(guide)) {
    const section = document.getElementById(`guide-${venue}`);
    const source = section.querySelector('a');
    if (terms.document_url || terms.source_url) source.href = terms.document_url || terms.source_url;
    const effective = terms.published_effective_from || terms.effective_from;
    if (terms.available) {
      for (const rule of terms.configured_rules || []) {
        const now = Date.now();
        if (Date.parse(rule.effective_from) > now || rule.effective_to && Date.parse(rule.effective_to) <= now) continue;
        source.before(el('p', `${rule.league || 'Default'} · coefficient ${rule.rate} · multiplier ${rule.multiplier} · ${rule.profile === 'account' ? 'Account schedule' : 'Conservative public schedule'}.`));
      }
      const modeled = terms.current_example;
      if (modeled) source.before(el('p', `Current ${modeled.league} example · ${modeled.game}. At ${modeled.posted_odds}, the internal $100 comparison basis commits ${dollars(modeled.upfront_usd)}, including ${dollars(modeled.entry_usd)} at entry. A win returns ${dollars(modeled.winning_receipt_usd)} after total winning fees of ${dollars(modeled.winning_fee_usd)}. After fees: ${modeled.after_fees}.`));
      if (venue === 'prophetx' && terms.nhl_taker_coefficient) {
        source.before(el('p', `NHL taker base coefficient ${terms.nhl_taker_coefficient}. Other supported straight markets use ${num(terms.fee_rate) * 100}% of positive net gains.`));
      }
    } else {
      source.before(el('p', 'Predict is awaiting applicable fee terms for this schedule.', 'desk-meta'));
    }
    const times = [effective && `Applies from ${date(effective)}`, terms.reviewed_at && `Reviewed ${date(terms.reviewed_at)}`]
      .filter(Boolean);
    if (times.length) section.append(el('p', times.join(' · '), 'desk-meta'));
  }
} catch {
  document.getElementById('fee-guide-status').textContent = 'The reviewed schedule details are temporarily unavailable.';
}

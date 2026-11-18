import './ui-common.js';

const {el, num} = window.PredictUI;
const dollars = value => new Intl.NumberFormat('en-US', {
  style:'currency', currency:'USD', notation:'standard'
}).format(num(value));
const examples = {
  kalshi: terms => `Example at the base multiplier. Buying 100 contracts at 50¢ costs $50 before the ${dollars(terms.example_fee)} estimated exchange fee.`,
  polymarket_us: terms => `Example at Predict’s ${terms.rate} coefficient. Buying 100 contracts at 50¢ costs $50 before the ${dollars(terms.example_fee)} estimated fee.`,
  novig: () => 'Example. A confirmed eligible pregame straight has a $0.00 trading fee at entry.',
  prophetx: terms => `Example outside NHL. A $10 standalone stake at +104 has a ${dollars(terms.example_fee)} estimated commission if it wins.`
};
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
      const modeled = terms.hundred_dollar_example;
      if (modeled) source.before(el('p', `$100 maximum upfront example at ${modeled.posted_odds}. Stake ${dollars(modeled.stake)}, entry fee ${dollars(modeled.entry_fee)}, upfront ${dollars(modeled.upfront)}. A win returns ${dollars(modeled.winning_return)} after the ${dollars(modeled.win_fee)} winning fee. ${modeled.basis}.`));
      if (venue === 'novig' || terms.example_fee != null) source.before(el('p', examples[venue](terms)));
      if (venue === 'prophetx' && terms.nhl_taker_coefficient) {
        source.before(el('p', `NHL taker base coefficient ${terms.nhl_taker_coefficient}. Other supported straight markets use ${num(terms.rate) * 100}% of positive net gains.`));
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

function rowKey(row) {
  return `${row.game_key}\u001f${row.id}`;
}

export function displayRows(page) {
  return (page?.rows || []).filter(row => !row.withdrawn);
}

export function holdDeskPage(previous, next) {
  // Keep the scroll order of surviving rows, but take both membership
  // and prices from the latest read. An omitted quote cannot be revived.
  const order = new Map(displayRows(previous).map((row, i) => [rowKey(row), i]));
  const ranked = displayRows(next);
  if (ranked.some(row => !order.has(rowKey(row)) && row.score != null)) {
    // A newly eligible result must be visible at its rank, even after a
    // preceding update removed it or temporarily left the board empty.
    return {page:{...next, rows:ranked}, changed:false};
  }
  const rows = [...ranked].sort((a, b) =>
    (order.get(rowKey(a)) ?? Infinity) - (order.get(rowKey(b)) ?? Infinity));
  return {page:{...next, rows}, changed:rows.some((row, i) => row !== ranked[i])};
}

function expired(timestamp, now) {
  return timestamp && Date.parse(timestamp) <= now;
}

function sportsbookDeadline(price) {
  return Date.parse(price.source_at) + 15_000;
}

export function nextDeskDeadline(page, now, {live}) {
  let next = Infinity;
  const consider = timestamp => {
    if (timestamp > now && timestamp < next) next = timestamp;
  };
  for (const row of displayRows(page)) {
    for (const pair of row.pairs || []) {
      if (pair.retail_payoff?.available) consider(Date.parse(pair.calculation_current_until));
    }
    if (!live) {
      consider(Date.parse(row.start_at));
      continue;
    }
    consider(Date.parse(row.sportsbook_reference?.current_until));
    for (const offer of row.offers) {
      consider(Date.parse(offer.current_until));
      if (offer.value != null) consider(Date.parse(offer.calculation_current_until));
    }
    for (const prices of Object.values(row.sportsbook_quotes || {})) {
      for (const price of prices) consider(sportsbookDeadline(price));
    }
  }
  return next;
}

export function expirePage(page, now, {ranked, live, netFilter}) {
  let changed = false;
  const rows = displayRows(page).flatMap(row => {
    const offers = row.offers.flatMap(offer => {
      if (offer.current === false || (!live && expired(row.start_at, now)) || (live && expired(offer.current_until, now))
) {
        changed = true;
        return [];
      }
      if (live && offer.value != null && expired(offer.calculation_current_until, now)) {
        changed = true;
        return [{...offer, value:null, before_fee:null, after_fee:null, conservative:null, fair_odds:null,
          fair_reference:null, sportsbook:null, reference_current:false, reason:offer.calculation_expiry_reason || 'reference_price_stale'}];
      }
      return [offer];
    });
    if (!offers.length) return [];
    const pairs = row.pairs?.filter(pair => pair.legs.every(id => offers.some(offer => offer.id === id)))
      .flatMap(pair => {
        if (!expired(pair.calculation_current_until, now) || !pair.retail_payoff?.available) return [pair];
        changed = true;
        if (netFilter) return [];
        const {acquisition_usd, minimum_gross_payout_usd, minimum_gross_profit_usd, sizing} = pair.retail_payoff;
        const legs = pair.retail_payoff.legs?.map(({quantity, acquisition_usd, depth_status, depth_evidence, quantity_increment}) =>
          ({quantity, acquisition_usd, depth_status, depth_evidence, quantity_increment,
            available:false, reason:'conditional_fee_review_expired_or_not_effective'}));
        return [{...pair, score:null, display_allocations:pair.before_fee_allocations,
          retail_payoff:{available:false, reason:'conditional_fee_review_expired_or_not_effective',
            acquisition_usd, minimum_gross_payout_usd, minimum_gross_profit_usd, sizing, legs}}];
      });
    if (pairs && !pairs.length) return [];
    const lead = offers.find(offer => offer.value != null);
    if (live && ranked && !lead) return [];
    const score = pairs ? pairs[0].score : lead?.value ?? null;
    const reference = row.sportsbook_reference;
    const referenceExpired = live && expired(reference?.current_until, now);
    changed ||= Boolean(referenceExpired);
    const books = Object.fromEntries(Object.entries(row.sportsbook_quotes || {}).map(([book, prices]) => {
      const current = prices.filter(price => price.current !== false && (!live || !price.source_at || sportsbookDeadline(price) > now));
      changed ||= current.length !== prices.length;
      return [book, current];
    }));
    return [{...row, offers, ...(pairs && {pairs}), score,
      score_source:lead && {...row.score_source, id:lead.id},
      sportsbook_reference:referenceExpired ? null : reference, sportsbook_quotes:books}];
  });
  if (!changed) return page;
  return {...page, rows, page_count:page.row_kind === 'games' ? new Set(rows.map(row => row.game_key)).size : rows.length};
}

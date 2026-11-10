// Price and authority can change independently between projection and retention.
export function selectionIdentity(offer) {
  return JSON.stringify([offer.id, offer.price_revision, offer.economic_revision, offer.odds,
    offer.current, offer.trade_fee, offer.reference_current, offer.reference,
    offer.reference_current ? offer.reference_calculation?.probability : null,
    offer.before_fee, offer.after_fee, offer.conservative]);
}

export async function pinLatestSelection({read, pin, release, isActive}) {
  const offer = await read();
  if (!isActive()) return {state:'closed'};
  if (!offer?.current) return {state:'unavailable'};
  const pinned = await pin(offer);
  let accepted = false;
  try {
    if (!isActive()) return {state:'closed'};
    const current = await read();
    if (!isActive()) return {state:'closed'};
    if (!current?.current || selectionIdentity(current) !== selectionIdentity(offer)) return {state:'changed'};
    accepted = true;
    return {state:'ready', offer, ...pinned};
  } finally {
    if (!accepted) release(pinned.lease);
  }
}

export function pinnedInspection(offer, captured) {
  if (!offer.current) {
    return {...captured, fair_reference: {available:false, reason:'source_expired'},
      before_fees: {...captured.before_fees, expected_profit_usd:null, return_percent:null},
      reviewed: {available:false, reason:'source_expired'},
      conservative: {available:false, reason:'source_expired'}};
  }
  const hasReference = offer.reference_current && captured.fair_reference?.available;
  const withoutAuthority = (model, value) => model?.available && value == null
    ? {available:false, reason:hasReference ? offer.trade_fee?.reason || 'fee_outcome_not_published' : 'reference_withdrawn'} : model;
  return {...captured,
    fair_reference: hasReference ? captured.fair_reference :
      {available:false, reason:captured.fair_reference?.reason || 'reference_withdrawn'},
    before_fees: {...captured.before_fees,
      expected_profit_usd: offer.before_fee == null ? null : captured.before_fees.expected_profit_usd,
      return_percent: offer.before_fee == null ? null : captured.before_fees.return_percent},
    reviewed: withoutAuthority(captured.reviewed, offer.after_fee),
    conservative: withoutAuthority(captured.conservative, offer.conservative)};
}

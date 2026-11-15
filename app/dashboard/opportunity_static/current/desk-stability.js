function rowKey(row) {
  return `${row.game_key}\u001f${row.id}`;
}

function quoteKey(offer) {
  return offer.desk_quote_key || offer.id;
}

function staleOffer(offer) {
  return {
    ...offer, current:false, value:null, fair_odds:null, fair_reference:null,
    reference_current:false, sportsbook:null, current_reasons:['input_replaced_or_removed']
  };
}

function staleBooks(books = {}) {
  return Object.fromEntries(Object.entries(books).map(([book, prices]) =>
    [book, prices.map(price => ({...price, current:false}))]));
}

function holdRow(row, current) {
  const nextOffers = new Map((current?.offers || []).map(offer => [quoteKey(offer), offer]));
  const offers = row.offers.map(offer => nextOffers.get(quoteKey(offer)) || staleOffer(offer));
  const updatedIds = new Map(row.offers.map((offer, index) => [offer.id, offers[index].id]));
  const lead = offers.find(offer => offer.id === updatedIds.get(row.score_source?.id)) || offers[0];
  const nextPairs = new Map((current?.pairs || []).map(pair => [pair.id, pair]));
  const pairs = row.pairs?.map(pair => nextPairs.get(pair.id) || {
    ...pair, legs:pair.legs.map(id => updatedIds.get(id) || id), score:null,
    retail_payoff:{available:false, reason:'pair_leg_stale_or_replaced'}
  });
  return {
    ...row, ...current, offers,
    ...(pairs ? {pairs} : {}),
    matrix_order:row.matrix_order,
    score_source:row.score_source && {...row.score_source, id:lead.id},
    score:pairs ? pairs[0]?.score ?? null : lead?.current ? lead.value : null,
    sportsbook_quotes:{...staleBooks(row.sportsbook_quotes), ...current?.sportsbook_quotes},
    sportsbook_reference:current?.sportsbook_reference
  };
}

export function displayRows(page) {
  return (page?.rows || []).filter(row => !row.withdrawn);
}

function order(rows) {
  return JSON.stringify(rows.map(row => {
    const lead = row.offers.find(offer => offer.id === row.score_source?.id);
    return [rowKey(row), lead && quoteKey(lead), row.offers.map(quoteKey), row.pairs?.map(pair => pair.id)];
  }));
}

export function holdDeskPage(previous, next) {
  const oldRows = displayRows(previous);
  const nextRows = displayRows(next);
  const updates = new Map(nextRows.map(row => [rowKey(row), row]));
  const keep = rows => (rows || []).map(row =>
    row.withdrawn ? row : holdRow(row, updates.get(rowKey(row))));
  const changed = order(oldRows) !== order(nextRows)
    || previous.total !== next.total;
  return {
    changed,
    page: {
      ...next, browse_id:previous.browse_id, offset:previous.offset, total:previous.total,
      page_count:previous.page_count, row_kind:previous.row_kind, games:previous.games,
      retained_game:previous.retained_game, selected_game_key:previous.selected_game_key,
      selected_line_id:previous.selected_line_id, rows:keep(previous.rows)
    }
  };
}

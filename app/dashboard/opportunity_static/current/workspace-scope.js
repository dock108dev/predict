// Numeric trading calculations retain the four supported market integrations.
// Known historical exchanges remain trading context with unavailable math.
const tradingVenues=new Set(['kalshi','polymarket_us','polymarket','novig','prophetx','prophetexchange']);
const historicalTradingVenues=new Set(['betfairexchange','matchbook','sporttrade']);
const venue=row=>typeof row==='string'?row:row.represented_venue||row.venue||row.book||row.identity?.book;
export const isTradingVenue=value=>tradingVenues.has(value);
export const tradingContext=row=>historicalTradingVenues.has(venue(row))||row.trading_role==='trading_context';
export const referenceOnly=row=>!tradingContext(row)&&(row.trading_role==='reference_only'||!isTradingVenue(venue(row)));

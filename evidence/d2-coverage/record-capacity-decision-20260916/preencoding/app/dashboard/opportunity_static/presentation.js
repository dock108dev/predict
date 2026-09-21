/* Presentation only: the calculation API retains every candidate. */
'use strict';
const BoardView = {
 crossVenue: c => new Set(c.legs.map(l=>l.venue)).size > 1,
 reasons(c) {
  const reasons=[...(c.reasons||[]),...(c.legs||[c.leg]).filter(Boolean).flatMap(l=>l.reasons||[])];
  return [...new Set(reasons)].map(r=>r === 'Books more than 5 seconds apart at cutoff' ? 'Books >5s apart' : r === 'No supported purchasable ask' ? 'Purchase ask unsupported' : r);
 },
 status(c, profit) { return profit != null ? 'Conditional' : c.status==='Assumption needed' ? 'Enter probability + basis' : 'Unavailable'; }
};
if(typeof module!=='undefined')module.exports=BoardView;

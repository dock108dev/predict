/* Presentation only: the calculation API retains every candidate. */
'use strict';
const BoardView = {
 crossVenue: c => new Set(c.legs.map(l=>l.venue)).size > 1,
 // Translate display text only; saved identities and calculation inputs stay intact.
 words(value) {
  const labels={moneyline:'Winner',full_game:'Full game',first_half:'First half',second_half:'Second half',first_3:'First 3 innings',first_5:'First 5 innings',first_6:'First 6 innings',regulation_9:'Regulation 9 innings',period_1:'Period 1',period_2:'Period 2',period_3:'Period 3',league_champion:'League champion',conference_champion:'Conference champion'};
  return String(value??'Unknown').replace(/\b(moneyline|full_game|first_half|second_half|first_3|first_5|first_6|regulation_9|period_1|period_2|period_3|league_champion|conference_champion)\b/g,key=>labels[key]);
 },
 title(value) { const [name,...context]=String(value??'Game').split(' · ');return {name,context:this.words(context.join(' · '))}; },
 date(value) { const date=new Date(value);return Number.isNaN(date.valueOf())?String(value??'Unknown'):date.toLocaleString(undefined,{timeZoneName:'short'}); },
 captureLabel(value) {
  const match=/^(synthetic|real) · (saved|current|incomplete) · (.+)$/.exec(value);
  return match?this.mode(match[1],match[2]==='current')+(match[2]==='incomplete'?' · incomplete':'')+' · '+this.date(match[3]):value;
 },
 mode(value,live=false,state='') {
  const demo=['mock','synthetic'].includes(value);
  if(state==='saving')return demo?'Saving demo…':'Saving observations…';
  if(state==='incomplete')return demo?'Incomplete demo':'Incomplete saved observations';
  return demo?(live?'Demo scan':'Saved demo'):value==='real'?(live?'Live observations':'Saved observations'):(value||'Saved observations');
 },
 sourceState(value) { return ({configured:'Configured',enabled:'Enabled',stopped:'Stopped',connected:'Connected',receiving:'Receiving',disconnected:'Disconnected',failed:'Failed',unconfigured:'Setup needed',selected:'Selected',resynchronization_required:'Needs resync',unavailable:'Unavailable'})[value]||String(value||'Status unknown').replaceAll('_',' '); },
 scanStatus(s) {
  if(s.cleanup_errors?.length)return 'Cleanup failed. Resource closure is unconfirmed; a new scan is unavailable.';
  if(s.active)return ['stopping','saving','finalizing'].includes(s.state)?'Stopping and saving observations…':'Scanning. Stop saves the observations collected so far.';
  if(s.state==='failed'||s.error)return 'Scan ended with an error. Saved data may be incomplete; review the error and use Refresh.';
  if(!s.start_available)return s.operating_mode==='product-session'?'Start unavailable: no valid run approval is configured. You can still review saved scans.':'Start unavailable: this scan allowance has been used. You can still review saved scans.';
  return s.state==='stopped'?'Scan stopped. Observations saved.':'Choose a saved scan or start a new scan.';
 },
 reasons(c) {
  const reasons=[...(c.reasons||[]),...(c.legs||[c.leg]).filter(Boolean).flatMap(l=>l.reasons||[])];
  const labels={'Books more than 5 seconds apart at cutoff':'Prices were recorded more than 5 seconds apart','No supported purchasable ask':'No supported purchase price','Venue resynchronization_required at cutoff':'Source data was not synchronized at the saved time','Source-time progress: missing':'Source timestamp progress is unknown','Market is not active at cutoff':'Market was not active at the saved time'};
  return [...new Set(reasons)].map(r=>labels[r]||r);
 },
 status(c, profit) { return profit != null ? 'Conditional' : c.status==='Assumption needed' ? 'Enter a probability and basis' : 'Unavailable'; }
};
if(typeof module!=='undefined')module.exports=BoardView;

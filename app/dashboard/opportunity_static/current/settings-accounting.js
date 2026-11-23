// Keep each provider's durable reservation exposure separate from uncertain charges.
const reported=value=>value===null||value===undefined?'Not reported':String(value);
export function accountingFacts(status,clock){
 const q=status.quota||{},source=(status.sources||[]).find(p=>p.provider==='sportsgameodds');
 const objects=source?.metrics?.objects,healthy=status.data_runtime?.healthy!==false;
 const activeSGO=status.config?.aggregate_provider==='sportsgameodds';
 const rows=activeSGO||objects?[
  [healthy?'SportsGameOdds available objects':'SportsGameOdds last reported available objects',objects?.available==null?'Not reported':reported(objects.available)+' above reserve'],
  ['Collector report',clock(status.data_runtime?.heartbeat_at)],
  ['SportsGameOdds held objects',reported(objects?.held)],
  ['SportsGameOdds interrupted objects budgeted',reported(objects?.interrupted)],
 ]:[['The Odds API last reported available credits',reported(q.available??q.remaining)],['The Odds API balance observed at',clock(q.observation?.at)]];
 if(status.quota){
  rows.push(['The Odds API reserved exposure (includes uncertain)',reported(q.reserved)],
            ['The Odds API uncertain held credits',reported(q.held_uncertain_credits)]);
 }
 return rows;
}
export function accountingEvidence(status){
 const q=status.quota||{},metrics=(status.sources||[]).find(p=>p.provider==='sportsgameodds')?.metrics||{};
 return {sportsgameodds:{object_holds:metrics.object_holds||[],interrupted_scans:metrics.object_interruptions||[]},
  the_odds_api:{reserved_exposure:q.reserved??null,uncertain_held_credits:q.held_uncertain_credits??null,
   recovery_incident:q.recovery_incident??null,balance_observed_at:q.observation?.at??null}};
}

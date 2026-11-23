"""Do not label normal reservations as uncertain charges or swap providers."""
from pathlib import Path
import subprocess


def test_provider_accounting_distinguishes_reservations_uncertainty_and_unknown():
    root=Path(__file__).resolve().parents[1]
    script=r"""
import assert from 'node:assert/strict';
import {accountingFacts,accountingEvidence} from './app/dashboard/opportunity_static/current/settings-accounting.js';
const source={provider:'sportsgameodds',metrics:{objects:{available:123,held:4,interrupted:9},object_holds:[{reserved:4}]}};
const status={config:{aggregate_provider:'sportsgameodds'},data_runtime:{healthy:true,heartbeat_at:'report-time'},sources:[source],quota:{reserved:12,held_uncertain_credits:5,available:987,observation:{at:'old-odds-api-balance'}}};
const rows=new Map(accountingFacts(status,x=>x||'Not reported'));
assert.equal(rows.get('SportsGameOdds available objects'),'123 above reserve');
assert.equal(rows.get('The Odds API reserved exposure (includes uncertain)'),'12');
assert.equal(rows.get('The Odds API uncertain held credits'),'5');
const missing=structuredClone(status);delete missing.quota.held_uncertain_credits;missing.sources=[];
const unknown=new Map(accountingFacts(missing,x=>x||'Not reported'));
assert.equal(unknown.get('SportsGameOdds available objects'),'Not reported','never replace missing active SGO balance with legacy provider credits');
assert.equal(unknown.get('The Odds API uncertain held credits'),'Not reported','a reservation is not evidence of an uncertain charge');
const zero=structuredClone(status);zero.quota.held_uncertain_credits=0;zero.sources[0].metrics.objects.held=0;
const knownZero=new Map(accountingFacts(zero,x=>x));assert.equal(knownZero.get('The Odds API uncertain held credits'),'0');assert.equal(knownZero.get('SportsGameOdds held objects'),'0');
const evidence=accountingEvidence(status);assert.equal(evidence.the_odds_api.uncertain_held_credits,5);assert.equal(evidence.the_odds_api.reserved_exposure,12);assert.equal(evidence.sportsgameodds.object_holds[0].reserved,4);
"""
    result=subprocess.run(['node','--input-type=module','-e',script],cwd=root,
                          text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr

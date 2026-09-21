"""Actual capture regressions and explicitly synthetic material settlement cases."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from app.adapters.kalshi import parse_market as parse_k, Response as KR
from app.adapters.polymarket_us import parse_market as parse_p, Response as PR
from app.matching import Matcher, digest, packed
from app.matching_example import synthetic
from app.models.core import Venue, Market, MarketType, Outcome
from app.moneyline import MoneylineMatcher, observe
from app.moneyline_captures import captured_inputs, listing_profile
from app.moneyline_example import synthetic_reports
from app.settlement import (DIMENSIONS, SCENARIOS, fact, profile, compare_profiles,
                            relationships, payout)

TEXT='Wholly synthetic settlement policy: all exceptional cases settle one half.'
H=sha256(TEXT.encode()).hexdigest()
SRC={'url':'synthetic:test','text':TEXT,'sha256':H}


def rules(change=None, payouts=None, equivalent=False):
    dims={k:fact('synthetic-same',evidence=H,certainty='equivalent' if equivalent else 'exact') for k in DIMENSIONS}
    dims.update(change or {})
    ps={k:{'kind':'fraction','value':'0.5','evidence':H} for k in SCENARIOS}
    ps.update(payouts or {})
    return profile(sources=[SRC],dimensions=dims,payouts=ps,actor='synthetic-test')


def rehash(row):
    row=deepcopy(row); row['hash']=digest({k:v for k,v in row.items() if k!='hash'}); return row


def synthetic_pair():
    names=('Atlanta Falcons','Pittsburgh Steelers')
    k=synthetic('ka',Venue.KALSHI,names=names,league='NFL')
    p=synthetic('pm',Venue.POLYMARKET_US,names=names,league='NFL')
    parents=Matcher(); parents.ingest([k,p])
    kn={'ticker':'contract','event_ticker':'ka','market_type':'binary','title':'Untrusted ignored title',
        'yes_sub_title':'Atlanta','rules_primary':'If Atlanta wins the Atlanta vs Pittsburgh professional football game originally scheduled for Sep 13, 2026, then the market resolves to Yes.'}
    pn={'id':'market','title':'Ignored','marketType':'moneyline','sportsMarketType':'football_team_full_game_winner',
        'marketSides':[{'id':'a','marketId':'market','long':True,'teamId':49,'team':{'id':49,'name':'Atlanta Falcons'}},
                       {'id':'b','marketId':'market','long':False,'teamId':74,'team':{'id':74,'name':'Pittsburgh Steelers'}}]}
    kr=KR(json.dumps(kn),'synthetic:test',datetime(2026,9,12,tzinfo=timezone.utc),k['normalized_observation']['observation']['raw']['kind'])
    # Response expects EvidenceKind, not a serialized enum.
    from app.models.core import EvidenceKind
    kr=replace(kr,kind=EvidenceKind.SYNTHETIC)
    pr=PR(json.dumps(pn),'synthetic:test',kr.received_at,EvidenceKind.SYNTHETIC)
    km=parse_k(kr,kn,'ka','KXNFLGAME'); pm=parse_p(pr,pn,'pm')
    kc={'series_ticker':'KXNFLGAME','product_metadata':{'competition_scope':'Game'}}
    pc={'id':'pm'}
    a=observe(km,k,rules(),native=kn,context=kc,artifact='synthetic:test')
    b=observe(pm,p,rules(),native=pn,context=pc,artifact='synthetic:test')
    return parents,a,b,(km,k,kn,kc),(pm,p,pn,pc)


class MoneylineTests(unittest.TestCase):
    def setUp(self): self.parents,self.a,self.b,self.ka,self.pm=synthetic_pair()

    def ingest(self,*rows):
        m=MoneylineMatcher(); r=m.update(self.parents,rows or (self.a,self.b)); return m,r

    def first(self,result): return next(iter(result['pairs'].values()))

    def remap(self, bundle, native=None, context=None, market=None):
        m,p,n,c=deepcopy(bundle)
        m=market or m; n=native or n
        m=replace(m,raw=replace(m.raw,json_text=json.dumps(n)))
        return observe(m,p,rules(),native=n,context=context or c,artifact='synthetic:test')

    def test_native_yes_no_vs_long_short(self):
        self.assertEqual([(s['native_id'],s['predicate']) for s in self.a['sides']],[('no','not_win'),('yes','win')])
        self.assertEqual([s['representation'] for s in self.b['sides']],['long','short'])
        row=self.first(self.ingest()[1]); self.assertTrue(row['structural_match'])
        self.assertTrue(row['qualification']['eligible_for_fee_arb_evaluation'])
        self.assertEqual(row['settlement']['status'],'EXACT')

    def test_side_array_order_price_and_title_do_not_determine_identity(self):
        n=deepcopy(self.pm[2]); n['marketSides'].reverse(); n['outcomes']='["WRONG","ORDER"]'; n['title']='Pittsburgh wins'
        for s in n['marketSides']: s['price']='0.999'
        self.assertEqual(self.remap(self.pm,native=n)['sides'],self.b['sides'])

    def test_kalshi_no_subtitle_and_suffix_do_not_map_no_to_other_team(self):
        n=deepcopy(self.ka[2]); n['no_sub_title']='Pittsburgh'; n['title']='Pittsburgh wins'
        r=self.remap(self.ka,native=n)
        self.assertEqual(r['sides'],self.a['sides'])
        self.assertEqual(r['sides'][0]['participant'],r['sides'][1]['participant'])

    def test_conflicting_authoritative_team_fields_block(self):
        n=deepcopy(self.pm[2]); n['marketSides'][0]['teamId']=74
        self.assertTrue(self.remap(self.pm,native=n)['reasons'])
        n=deepcopy(self.ka[2]); n['yes_sub_title']='Pittsburgh'
        self.assertIn('YES-label-rule-conflict',self.remap(self.ka,native=n)['reasons'])

    def test_wrong_rule_game_and_unresolved_participant_block(self):
        n=deepcopy(self.ka[2]); n['rules_primary']=n['rules_primary'].replace('Atlanta vs Pittsburgh','Atlanta vs Baltimore')
        self.assertTrue(self.remap(self.ka,native=n)['reasons'])
        n=deepcopy(self.pm[2]); n['marketSides'][0]['team']['name']='Unknown team'
        self.assertTrue(self.remap(self.pm,native=n)['reasons'])

    def test_missing_long_flag_or_duplicate_side_identity_block(self):
        for alteration in ('missing','duplicate','wrong-market'):
            n=deepcopy(self.pm[2])
            if alteration=='missing': del n['marketSides'][0]['long']
            if alteration=='duplicate': n['marketSides'][1]['long']=True
            if alteration=='wrong-market': n['marketSides'][0]['marketId']='other'
            self.assertTrue(self.remap(self.pm,native=n)['reasons'])

    def test_missing_side_is_not_invented(self):
        m,p,n,c=deepcopy(self.pm); n['marketSides']=n['marketSides'][:1]
        row=self.remap(self.pm,native=n,market=replace(m,outcomes=m.outcomes[:1]))
        self.assertEqual(len(row['sides']),1)
        self.assertFalse(row['reasons'])

    def test_non_moneyline_rejection(self):
        for typ in ('spreads','totals','player_prop','unknown'):
            n=deepcopy(self.pm[2]); n['marketType']=typ
            self.assertIn('non-moneyline-market:'+typ,self.remap(self.pm,native=n)['reasons'])

    def test_period_rejection(self):
        for typ in ('football_team_first_half_winner','football_team_first_quarter_winner','unknown'):
            n=deepcopy(self.pm[2]); n['sportsMarketType']=typ
            self.assertTrue(self.remap(self.pm,native=n)['reasons'])
        c=deepcopy(self.ka[3]); c['strike_period']='first_half'
        self.assertTrue(self.remap(self.ka,context=c)['reasons'])
        n=deepcopy(self.ka[2]); n['rules_primary']=n['rules_primary'].replace('Atlanta vs Pittsburgh','first half of Atlanta vs Pittsburgh')
        self.assertTrue(self.remap(self.ka,native=n)['reasons'])

    def test_same_exposure_opposing_outcome_and_complement_are_separate(self):
        rel=self.first(self.ingest()[1])['relationships']
        same=next(r for r in rel if r['left_side']=='yes' and r['right_side']=='a')
        self.assertTrue(same['same_exposure']); self.assertEqual(same['complementary_payoffs'],'NO')
        opposing=next(r for r in rel if r['left_side']=='yes' and r['right_side']=='b')
        self.assertTrue(opposing['opposing_sporting_outcomes']); self.assertEqual(opposing['complementary_payoffs'],'YES')
        no=next(r for r in rel if r['left_side']=='no' and r['right_side']=='b')
        self.assertFalse(no['same_exposure']); self.assertFalse(no['opposing_sporting_outcomes'])

    def test_unmatched_parent_cannot_match_via_historical_id(self):
        m,r=self.ingest()
        p=synthetic('pm',Venue.POLYMARKET_US,names=('Atlanta Falcons','Pittsburgh Steelers'),league='NFL',start='2026-09-15T17:00:00+00:00')
        self.parents.ingest([p]); row=self.first(m.report(self.parents))
        self.assertFalse(row['structural_match']); self.assertFalse(row['qualification']['eligible_for_fee_arb_evaluation'])
        self.assertEqual(row['revision'],2)
        self.assertIn('conflicting',' '.join(row['structural_reasons']))
        self.assertTrue(m.snapshot['revisions'][0]['after']['qualification']['eligible_for_fee_arb_evaluation'])

    def test_candidate_and_ambiguous_parents_block(self):
        for status in ('candidate','ambiguous'):
            parents=Matcher()
            if status=='candidate':
                other=synthetic('pm',Venue.POLYMARKET_US,names=('Atlanta Falcons','Pittsburgh Steelers'),league='NFL',start=None)
                parents.ingest([self.ka[1],other])
            else:
                other=synthetic('duplicate',Venue.KALSHI,names=('Atlanta Falcons','Pittsburgh Steelers'),league='NFL')
                parents.ingest([self.ka[1],self.pm[1],other])
            m=MoneylineMatcher();r=m.update(parents,[self.a,self.b])
            self.assertTrue(all(x['structural_status']=='rejected' for x in r['markets'].values()))
            self.assertFalse(any(p['qualification']['eligible_for_fee_arb_evaluation'] for p in r['pairs'].values()))

    def test_current_parents_required(self):
        m,_=self.ingest()
        with self.assertRaises(ValueError): m.report({})

    def test_rule_revision_invalidates_without_erasing_evidence(self):
        m,r=self.ingest(); old=len(m.snapshot['observations'])
        b=deepcopy(self.b); b['profile']=rules({'resumption':fact(reason='missing new rule')}); b=rehash(b)
        row=self.first(m.update(self.parents,[self.a,b]))
        self.assertEqual(row['settlement']['status'],'UNKNOWN'); self.assertFalse(row['qualification']['eligible_for_fee_arb_evaluation'])
        self.assertEqual(len(m.snapshot['observations']),old+1)
        self.assertEqual(row['revision'],2)

    def test_duplicate_input_is_one_liquidity_reference(self):
        m,r=self.ingest(self.a,self.a,self.b,self.b)
        self.assertEqual(len(r['pairs']),1); self.assertEqual(len(r['markets']),2)
        self.assertEqual(len({s['liquidity_key'] for s in self.a['sides']}),1)
        state=m.snapshot; m.update(self.parents,[self.b,self.a]); self.assertEqual(m.snapshot,state)

    def test_conflicting_same_native_batch_blocks(self):
        changed=deepcopy(self.a); changed['profile']=rules({'tie':fact('different',evidence=H)})
        row=self.first(self.ingest(self.a,rehash(changed),self.b)[1])
        self.assertFalse(row['structural_match']); self.assertIn('conflicting-native-market-observations',row['structural_reasons'])

    def test_multiple_venue_markets_share_canonical_market_without_same_venue_pairs(self):
        other=deepcopy(self.a); other['native_market_id']='other'; other['key']=packed([*other['scope'],other['venue'],other['native_event_id'],'other'])
        other['id']='native-market-'+digest(other['key'])[:24]; other=rehash(other)
        _,r=self.ingest(self.a,other,self.b)
        self.assertEqual(len(r['pairs']),2)
        self.assertEqual(len({p['canonical_market_id'] for p in r['pairs'].values()}),1)
        self.assertEqual(other['venue_event_liquidity_family'],self.a['venue_event_liquidity_family'])

    def test_scope_mismatch_rejected(self):
        market,parent,native,context=self.ka
        p=deepcopy(parent);p['scope']=['observation','production']
        with self.assertRaises(ValueError): observe(market,p,rules(),native=native,context=context,artifact='synthetic:test')

    def test_environment_isolation(self):
        a=deepcopy(self.a);a['scope']=['synthetic','sandbox'];a['key']=packed([*a['scope'],a['venue'],a['native_event_id'],a['native_market_id']])
        a['parent_key']=packed([*a['scope'],a['venue'],a['native_event_id']]);a['id']='native-market-'+digest(a['key'])[:24]
        self.assertEqual(self.ingest(rehash(a),self.b)[1]['pairs'],{})

    def test_withdrawn_market_invalidates_qualification(self):
        m,_=self.ingest();row=self.first(m.update(self.parents,[self.a]))
        self.assertTrue(row['withdrawn']);self.assertFalse(row['qualification']['eligible_for_fee_arb_evaluation'])
        self.assertTrue(self.first(m.update(self.parents,[self.a,self.b]))['qualification']['eligible_for_fee_arb_evaluation'])

    def test_stable_native_and_canonical_ids_on_revision(self):
        m,r=self.ingest();cid=self.first(r)['canonical_market_id']
        b=deepcopy(self.b); b['profile']=rules({'tie':fact(reason='changed')}); b=rehash(b)
        self.assertEqual(b['id'],self.b['id'])
        self.assertEqual(self.first(m.update(self.parents,[self.a,b]))['canonical_market_id'],cid)

    def test_compatible_needs_pair_bound_explicit_review(self):
        b=deepcopy(self.b);b['profile']=rules(equivalent=True);b=rehash(b)
        m,r=self.ingest(self.a,b);self.assertEqual(self.first(r)['settlement']['status'],'COMPATIBLE')
        self.assertFalse(self.first(r)['qualification']['eligible_for_fee_arb_evaluation'])
        m.approve_compatible(self.a['profile']['hash'],b['profile']['hash'],actor='synthetic-reviewer',reason='synthetic equivalence review',source='synthetic:test',reviewed_at='2026-09-12T00:00:00Z')
        self.assertTrue(self.first(m.report(self.parents))['qualification']['eligible_for_fee_arb_evaluation'])
        b2=deepcopy(b);b2['profile']=rules(equivalent=True);b2['profile']['actor']='synthetic-new-assessor';b2['profile']=rehash(b2['profile']);b2=rehash(b2)
        self.assertFalse(self.first(m.update(self.parents,[self.a,b2]))['qualification']['eligible_for_fee_arb_evaluation'])

    def test_unknown_and_conflict_cannot_be_approved(self):
        for rule in (rules({'tie':fact(reason='missing')}),rules({'tie':fact('refund',evidence=H)})):
            b=deepcopy(self.b); b['profile']=rule;b=rehash(b);m,_=self.ingest(self.a,b)
            with self.assertRaises(ValueError):m.approve_compatible(self.a['profile']['hash'],rule['hash'],actor='synthetic',reason='override',source='synthetic:test',reviewed_at='2026-09-12T00:00:00Z')

    def test_atomic_persistence_restart_and_idempotency(self):
        m,r=self.ingest()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'markets.json';m.save(path)
            loaded=MoneylineMatcher.load(path);self.assertEqual(loaded.report(self.parents),r)
            state=loaded.snapshot;loaded.update(self.parents,[self.b,self.a]);self.assertEqual(state,loaded.snapshot)
            result=subprocess.run([sys.executable,'-c','from app.moneyline import MoneylineMatcher; import sys; m=MoneylineMatcher.load(sys.argv[1]); print(len(m.snapshot["decisions"]))',str(path)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout.strip(),'1')
            before=path.read_bytes()
            with patch('app.matching.os.replace',side_effect=OSError('synthetic write failure')):
                with self.assertRaises(OSError):m.save(path)
            self.assertEqual(path.read_bytes(),before)

    def test_store_corruption_and_history_rejected(self):
        m,_=self.ingest()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'s.json';m.save(path);base=json.loads(path.read_text())
            for change in ('checksum','history','version'):
                data=deepcopy(base)
                if change=='checksum':data['sha256']='bad'
                elif change=='history':data['data']['revisions'][0]['after']['revision']=99;data['sha256']=digest(data['data'])
                else:data['data']['schema_version']=99;data['sha256']=digest(data['data'])
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):MoneylineMatcher.load(path)


class SettlementTests(unittest.TestCase):
    def test_all_material_dimensions_unknown_block_exact(self):
        for dim in DIMENSIONS:
            p=rules({dim:fact(reason='missing '+dim)})
            r=compare_profiles(p,p)
            self.assertEqual(r['status'],'UNKNOWN');self.assertIn(dim,[x['condition'] for x in r['unknown']])

    def test_known_conflicts_preserve_dimension(self):
        for dim in DIMENSIONS:
            p=rules({dim:fact('different',evidence=H)})
            r=compare_profiles(rules(),p)
            self.assertEqual(r['status'],'INCOMPATIBLE');self.assertIn(dim,[x['condition'] for x in r['conflicts']])

    def test_missing_payout_fields_block_exact(self):
        p=rules(payouts={'canceled':{'kind':'unknown'}})
        self.assertEqual(compare_profiles(p,p)['status'],'UNKNOWN')

    def test_refund_fraction_and_discretion_are_distinct(self):
        s={'native_id':'no','participant':'A','predicate':'not_win'}
        refund=rules(payouts={'tie':{'kind':'refund','evidence':H}})
        self.assertEqual(payout(s,'tie',refund)['kind'],'refund')
        self.assertEqual(compare_profiles(rules(),refund)['status'],'INCOMPATIBLE')
        discretion=rules(payouts={'canceled':{'kind':'discretionary','evidence':H}})
        self.assertEqual(compare_profiles(discretion,discretion)['status'],'UNKNOWN')
        self.assertEqual(payout(s,'canceled',discretion)['kind'],'discretionary')

    def test_no_fraction_complement_and_three_way_tie(self):
        p=rules(payouts={'tie':{'kind':'fraction','value':'0','evidence':H}})
        a=[{'native_id':'no','participant':'A','predicate':'not_win'}]
        b=[{'native_id':'b','participant':'B','predicate':'win'}]
        rel=relationships(a,b,p,p,['A','B'],compare_profiles(p,p))[0]
        self.assertEqual(rel['scenarios']['tie']['left']['value'],'1')
        self.assertEqual(rel['scenarios']['tie']['right']['value'],'0')
        self.assertFalse(rel['same_exposure'])
        rel=relationships([{**a[0],'predicate':'win'}],b,p,p,['A','B'],compare_profiles(p,p))[0]
        self.assertEqual(rel['complementary_payoffs'],'NO');self.assertIn('tie',rel['noncomplementary_cases'])

    def test_known_rules_require_retained_evidence(self):
        with self.assertRaises(ValueError):fact('known')
        with self.assertRaises(ValueError):rules({'tie':fact('known',evidence='unretained')})

    def test_synthetic_cases_are_separately_labeled(self):
        r=synthetic_reports()
        self.assertTrue(all(x['evidence_kind']=='synthetic' for x in r.values()))
        self.assertEqual(r['tie-refund-vs-fraction']['settlement']['status'],'INCOMPATIBLE')
        self.assertEqual(r['postponement-conflict']['settlement']['status'],'INCOMPATIBLE')
        self.assertEqual(r['missing-resumption']['settlement']['status'],'UNKNOWN')


class CapturedMoneylineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch('socket.socket.connect',side_effect=AssertionError('offline only')):
            cls.parents,cls.rows,cls.excluded,cls.coverage=captured_inputs()
            cls.matcher=MoneylineMatcher();cls.result=cls.matcher.update(cls.parents,cls.rows)

    def test_actual_five_pairs_and_ten_structural_matches(self):
        self.assertEqual(len(self.rows),15)
        self.assertEqual(len({c['canonical_event_id'] for c in self.coverage}),5)
        self.assertTrue(all(c['captured_full_game_moneylines'] for c in self.coverage))
        self.assertEqual(len(self.result['pairs']),10)
        self.assertTrue(all(p['structural_match'] for p in self.result['pairs'].values()))
        self.assertEqual({p['settlement']['status'] for p in self.result['pairs'].values()},{'UNKNOWN'})
        self.assertFalse(any(p['qualification']['eligible_for_fee_arb_evaluation'] for p in self.result['pairs'].values()))

    def test_actual_sources_and_native_sides(self):
        self.assertTrue(self.excluded)
        self.assertTrue(all(x['reason'].startswith('non-moneyline') for x in self.excluded))
        for row in self.rows:
            self.assertEqual(row['scope'],['observation','production'])
            self.assertTrue(row['raw']['source_body_sha256']);self.assertTrue(row['profile']['sources'][0]['text'])
            self.assertEqual(len(row['sides']),2)
        self.assertEqual(sum(r['same_exposure'] for p in self.result['pairs'].values() for r in p['relationships']),10)
        self.assertEqual(sum(r['opposing_sporting_outcomes'] for p in self.result['pairs'].values() for r in p['relationships']),10)

    def test_changed_listing_text_not_auto_reinterpreted(self):
        row=self.rows[0];native=deepcopy(row['native']);native['rules_secondary']+=' New rule amendment.'
        s=row['profile']['sources'][0]
        p=listing_profile(native,row['venue'],{'url':s['url'],'artifact':s['artifact'],'sha256':s['capture_sha256'],'captured_at':s['captured_at']})
        self.assertTrue(all(v['value'] is None for v in p['dimensions'].values()))
        self.assertEqual(compare_profiles(row['profile'],p)['status'],'UNKNOWN')

    def test_stale_profile_on_changed_listing_blocks_only_settlement(self):
        row=deepcopy(self.rows[0]); row['native']['rules_secondary']+=' New condition.'
        row['rule_binding']=False; row=rehash(row)
        m=MoneylineMatcher();result=m.update(self.parents,[row,*self.rows[1:]])
        affected=[p for p in result['pairs'].values() if row['key'] in (p['left'],p['right'])]
        self.assertTrue(affected)
        self.assertTrue(all(p['structural_match'] and p['settlement']['status']=='UNKNOWN' for p in affected))
        self.assertTrue(all(p['settlement']['unknown'][0]['condition']=='rule_profile_binding' for p in affected))

    def test_production_replay_input_order_idempotency(self):
        before=self.matcher.snapshot
        self.matcher.update(self.parents,list(reversed(self.rows))+[self.rows[0]])
        self.assertEqual(self.matcher.snapshot,before)

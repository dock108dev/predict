"""Offline, additive public source contracts. Never grants collection authority.

Original catalogs/reviews remain literal. Derived facts have a separate version,
document snapshot and identity checks. Missing exceptions do not erase predicates.
"""
from copy import deepcopy
from decimal import Decimal, ROUND_FLOOR
import json
from pathlib import Path
from functools import lru_cache
from app.dashboard.session_projection import stable, stamp

VERSION = 'public-contract-bindings-1'
PATH = Path(__file__).resolve().parents[1] / 'fixtures/public-contracts-v1.json'


def fraction_input(value):
    from app.fees.engine import number
    if not isinstance(value,str):raise ValueError('Exact decimal fraction string required')
    n=number(value)
    if not 0<=n<=1:raise ValueError('Payout fraction outside face value')
    return n


@lru_cache(maxsize=1)
def _snapshot(signature):
    data = json.loads(PATH.read_text())
    if data['version'] != VERSION or data['collection_authorized'] is not False:
        raise ValueError('Public binding version/authority conflict')
    if data.get('sha256')!=stable({k:v for k,v in data.items() if k!='sha256'}):
        raise ValueError('Public binding snapshot changed')
    return data


def load():
    stat=PATH.stat()
    return deepcopy(_snapshot((stat.st_mtime_ns,stat.st_size)))


def event_identity(*, source, event_id, competition, participants, scheduled_start,
                   provider_season=None, provider_stage=None, provider_label=None):
    """Match exact ID AND participants AND schedule, preserving contradictions."""
    data = load()
    candidates = [x for x in data['events'] if x['competition'] == competition
                  and x['native_ids'].get(source) == event_id]
    original = dict(source=source, event_id=event_id, competition=competition,
                    participants=deepcopy(participants), scheduled_start=scheduled_start,
                    provider_season=provider_season, provider_stage=provider_stage,
                    provider_label=provider_label)
    result = dict(version=VERSION, original=original, status='UNBOUND', enrichment=None,
                  conflicts=[], collection_authorized=False)
    if len(candidates) != 1:
        result['reason'] = 'Exact documented event crosswalk unavailable'; return result
    row = candidates[0]
    if not isinstance(participants,list) or len(participants)!=2 or set(participants) != {row['home'], row['away']} or stamp(scheduled_start) != stamp(row['scheduled_start']):
        result.update(reason='Exact participant or schedule conflict', candidate=deepcopy(row)); return result
    conflicts = list(row['conflicts'])
    for key, value in [('season', provider_season), ('stage', provider_stage)]:
        if value is not None and value != row[key]:
            conflicts.append('Explicit provider ' + key + ' conflicts: ' + str(value))
    if provider_label is not None and provider_label == {'NHL':'nhl-2025','NBA':'nba-2025'}.get(competition):
        conflicts.append('Provider series label '+provider_label+' conflicts with authoritative '+row['season']+' schedule')
    result.update(status='ENRICHED_WITH_CONFLICT' if conflicts else 'ENRICHED', conflicts=conflicts,
                  enrichment=deepcopy(row), sources=[data['sources'][k] for k in row['sources']],
                  qualification='Identity enrichment only; original/rescheduled identity and payout/fees separate')
    result['sha256'] = stable(result)
    return result


def enrich_event(event,source,event_id):
    """Create a new reviewed event; retain the original event alongside it."""
    evidence=event_identity(source=source,event_id=event_id,competition=event['competition'],
        participants=[event['home'],event['away']],scheduled_start=event['scheduled_start'],
        provider_season=event.get('season'),provider_stage=event.get('stage'),provider_label=event.get('seriesSlug'))
    if not evidence.get('enrichment'):raise ValueError(evidence['reason'])
    out=deepcopy(event);out['original_provider_event']=deepcopy(event)
    out.update(season=evidence['enrichment']['season'],stage=evidence['enrichment']['stage'],
               public_binding_version=VERSION,public_identity=evidence)
    return out


def validate_enriched_event(event):
    evidence=event.get('public_identity',{});original=evidence.get('original',{})
    rebuilt=event_identity(**original)
    if rebuilt!=evidence or evidence.get('enrichment') is None:
        raise ValueError('Public identity provenance conflict')
    row=evidence['enrichment']
    if any(event.get(k)!=row[k] for k in ('competition','season','stage','home','away')) or stamp(event['scheduled_start'])!=stamp(row['scheduled_start']):
        raise ValueError('Enriched event changed')


def college_registry():
    """Versioned membership overlay, exact NCAA IDs; no ambiguous short aliases."""
    from app.normalization.college_registry import expanded
    from app.normalization.registry import Registry, name_key
    d=json.loads(expanded().to_json()); membership=load()['ncaab_membership']
    existing={x['id'] for x in d['entities']}
    for m in membership['members']:
        # These source-backed IDs predate the directory expansion. Preserve them.
        if m['org_id'] in (6,8):
            cid={6:'NCAAB:M:D1:AAMU',8:'NCAAB:M:D1:ALA'}[m['org_id']]
            entity=next(x for x in d['entities'] if x['id']==cid)
            entity.update(ncaa_org_id=m['org_id'],academic_year=2027,
                          public_membership_source=load()['sources']['ncaa-mbb-directory-data'])
            continue
        if m['id'] in existing:
            entity=next(x for x in d['entities'] if x['id']==m['id'])
            entity.update(ncaa_org_id=m['org_id'],academic_year=2027,
                          public_membership_source=load()['sources']['ncaa-mbb-directory-data'])
            continue
        source=load()['sources']['ncaa-mbb-directory-data']['url']
        d['entities'].append(dict(id=m['id'],kind='team',name=m['name'],league='NCAAB',source=source,
            school_id='NCAA:'+str(m['org_id']),ncaa_org_id=m['org_id'],academic_year=2027,gender='men',
            basketball_memberships={'2026-2027':dict(division='I',competition_id='NCAA:M:D1',source=source,
                                                   reclassifying=m['reclassification'] is not None)}))
        # Existing ambiguous spellings stay ambiguous; use canonical school names.
        key=('team','NCAAB',None,name_key(m['name']))
        if any((a['kind'],a.get('league'),a.get('venue'),name_key(a['text']))==key for a in d['aliases']):
            raise ValueError('Canonical membership alias conflict')
        d['aliases'].append(dict(kind='team',league='NCAAB',text=m['name'],targets=[m['id']],source=source))
    d['version'] += '+'+VERSION
    return Registry(d)


def membership_field(competition,conference=None):
    """Membership is independent of an award's eligible or revised field."""
    data=load()
    if competition=='NCAAB':
        if conference is not None:raise ValueError('NCAAB conference award membership not bound')
        field=deepcopy(data['ncaab_membership'])
        field['members']=[{'6':'NCAAB:M:D1:AAMU','8':'NCAAB:M:D1:ALA'}.get(str(m['org_id']),m['id']) for m in field['members']]
        source=data['sources']['ncaa-mbb-directory-data']
    else:
        field=deepcopy(data['fields'][competition]);source=data['sources'][field['source']]
        if conference is not None:
            if conference not in field.get('conferences',{}):raise ValueError('Exact conference membership not established')
            field['members']=field['conferences'][conference]
    return dict(version=VERSION,competition=competition,conference=conference,field=field,source=source,
                status='DOCUMENTED_MEMBERSHIP',award_eligibility_established=False,collection_authorized=False)


def us_type(native, *, competition):
    """Registered family locator only; does not invent line sign or settlement."""
    metadata=native.get('metadata',{})
    key=metadata.get('market_sport_type',native.get('sportsMarketType'))
    row=load()['us_types'].get(key)
    result=dict(version=VERSION,native_type=key,status='UNBOUND',original=deepcopy(native),
                collection_authorized=False)
    expected_sport={'NFL':'FOOTBALL','NCAAF':'FOOTBALL','NBA':'BASKETBALL','NCAAB':'BASKETBALL','MLB':'BASEBALL'}.get(competition)
    if expected_sport is not None and metadata.get('event_subcategory') is not None and metadata['event_subcategory']!=expected_sport:
        result['reason']='Explicit provider sport conflicts with requested competition';return result
    if not row or competition not in row['competitions']:
        structure={'moneyline':'moneyline','spreads':'spread','totals':'total',
                   'drawable_outcome':'three_way_winner','futures':'futures'}.get(key)
        if structure:
            result['documented_structure']=structure
            result['source']=load()['sources']['us-schema']
            result['missing_scope']=['Exact sport/league, period or award horizon, category and season']
        result['reason']='No documented requested sport/period type; generic types require separate period evidence'
        return result
    result.update(status='DOCUMENTED_LOCATOR',competition=competition,period=row['period'],family=row['family'],
        total_scope=row['total_scope'],strike_magnitude=metadata.get('outcome_strike'),
        long_participant_id=metadata.get('long_participant_id'),source=load()['sources']['us-schema'],
        missing=['Exact game/season/stage', 'Signed line and native payout predicate', 'Effective settlement/fees'])
    return result


def us_selector(game_id, family):
    if not isinstance(game_id,str) or not game_id or family not in ('moneyline','spread','total','futures'):
        raise ValueError('Exact game ID and documented family required')
    return dict(version=VERSION,path='/v1/markets',query=dict(gameId=game_id,sportsMarketTypes=[{
        'moneyline':'SPORTS_MARKET_TYPE_MONEYLINE','spread':'SPORTS_MARKET_TYPE_SPREAD',
        'total':'SPORTS_MARKET_TYPE_TOTAL','futures':'SPORTS_MARKET_TYPE_FUTURE'}[family]]),
        collection_authorized=False,source=load()['sources']['us-markets'],
        note='Coarse filter; inspect returned typed metadata. No period inferred from filter.')


def odds_outright(native, competition):
    keys=dict(NFL='americanfootball_nfl_super_bowl_winner',NCAAF='americanfootball_ncaaf_championship_winner',
              NBA='basketball_nba_championship_winner',NCAAB='basketball_ncaab_championship_winner',
              MLB='baseball_mlb_world_series_winner',NHL='icehockey_nhl_championship_winner')
    if native.get('sport_key') != keys.get(competition): raise ValueError('Exact documented outright sport key required')
    outcomes=[]
    for b in native.get('bookmakers',[]):
        for m in b.get('markets',[]):
            if m.get('key') != 'outrights': continue
            for o in m.get('outcomes',[]):
                if not isinstance(o.get('name'),str) or type(o.get('price')) not in (int,float,str):
                    raise ValueError('Literal outright outcome/odds required')
                if not Decimal(str(o['price'])).is_finite() or Decimal(str(o['price']))<=1:
                    raise ValueError('Finite decimal odds above one required')
                outcomes.append(dict(bookmaker=b['key'],participant_label=o['name'],decimal_odds=str(o['price']),
                    source_at=m.get('last_update'),payout_basis='bookmaker_contract_unbound'))
    return dict(version=VERSION,competition=competition,category='league_champion',period='season',
        native=deepcopy(native),outcomes=outcomes,source=load()['sources']['odds-sports'],
        missing=['Exact award/season/member field', 'Source contract payout/fee terms'],collection_authorized=False)


def contract(binding):
    """Retained series->exact document association, independently of market title."""
    data=load(); catalog=json.loads(PATH.with_name('native-scope-bindings-v1.json').read_text())
    matches=[x for x in catalog['bindings'] if x['series_ticker']==binding.get('series_ticker')]
    if len(matches)!=1 or any(matches[0][k]!=binding[k] for k in ('sport','period','family')):
        raise ValueError('Exact retained series/scope association required')
    row=matches[0]
    docs=[x for x in data['sources'].values() if x['url']==row['contract_terms_url']]
    if len(docs)!=1: raise ValueError('Linked contract has no complete supported public document')
    return row,docs[0]


def descriptor(native, binding, *, tie_strike_listed=None):
    """Translate complete literal predicates into existing score engines."""
    from app.collection.native_score_binding import bind
    row,doc=contract(binding); fact=bind(native,binding)
    if not fact or fact.get('participant') is None: raise ValueError('Complete explicit native score predicate and canonical participant required')
    period=row['period']; sport=row['sport']; family=row['family']
    if period=='full_game' or family=='futures': raise ValueError('Use separate full-game/award binding')
    d=dict(version='score-lines-1',public_binding_version=VERSION,source='kalshi',family=family,
           period=period,participant=fact['participant'],line=None if family=='moneyline' else fact['line'],
           unit=fact['unit'],offered='pregame',overtime='excluded',overtime_format='not_applicable',
           contract_document=doc['url'],contract_provenance=doc,normal_completion=(
           'first_two_quarters_definitively_completed' if period=='first_half' else period+'_definitively_completed'),
           settlement_score=period+'_only',tied_score='evaluate_actual_score_predicate',
           regulation='first_two_15_minute_quarters' if period=='first_half' else period)
    if sport=='MLB':
        if family=='moneyline':
            # BASEBALLGAMEWIN does not publish the action clause in SPREAD/TOTAL.
            d.update(pitcher_conditions='not_specified_in_linked_winner_contract',completion_scope='specified_segment_only',
                     extra_innings='excluded',segment_start=1,segment_end=int(period.split('_')[1]))
        else:d.update(pitcher_conditions='action',completion_scope='specified_segment_only',extra_innings='excluded',
                      segment_start=1,segment_end=int(period.split('_')[1]))
    equality='predicate'; structure=None
    if family=='moneyline':
        if tie_strike_listed is not None and type(tie_strike_listed) is not bool:
            raise ValueError('Explicit Tie-strike presence or unknown required')
        if fact['participant']=='tie':structure='binary_tie_not_tie'
        elif tie_strike_listed is True:structure='binary_team_win_not_win'
        elif tie_strike_listed is False and sport=='MLB':structure='shared_winner';equality='fraction'
        else:structure='binary_team_win_unresolved_tie';equality='unknown'
        d['winner_structure']=structure
    d['outcomes']=[dict(s,native_label=s['native_id'].title(),equality=equality,refund_fees='unknown') for s in fact['outcomes']]
    if equality=='fraction':
        for side in d['outcomes']:side['equality_payout']='0.5'
    return dict(version=VERSION,descriptor=d,predicate=fact,source=doc,
                status='IMPLEMENTED_DOCUMENTED_DESCRIPTOR',missing=['Exact original/rescheduled event',
                'Source fair-value decision on unresolved exception branch','Account charges and actual fill history'],
                collection_authorized=False)


def period_decision(binding, *, completed, predicate_determined=False, late_game_official=False,
                    resumption_within_window=None, venue_fraction=None):
    """Completion exception is independent of unknown venue fair-value amount."""
    row,doc=contract(binding)
    if row['period'] not in ('first_half','first_3','first_5') or row['family']=='futures':
        raise ValueError('Documented selected football/baseball segment required')
    if type(completed) is not bool or type(predicate_determined) is not bool or type(late_game_official) is not bool:
        raise ValueError('Explicit completion facts required')
    if completed or predicate_determined:
        return dict(version=VERSION,basis='completed_period_actual_predicate',source=doc,payout_basis='existing_score_predicate')
    if resumption_within_window is True:
        return dict(version=VERSION,basis='await_original_or_evidenced_rescheduled_game',source=doc,payout_basis=None)
    if resumption_within_window is None:
        return dict(version=VERSION,basis='resumption_window_unknown',source=doc,payout_basis=None)
    # Full-game official-result exceptions never manufacture an unfinished period score.
    value=None if venue_fraction is None else fraction_input(venue_fraction)
    return dict(version=VERSION,basis='venue_last_fair_value_decision_required',source=doc,
                payout_basis=None if value is None else str(value),late_game_official=late_game_official,
                input_kind='explicit_venue_decision_or_hypothetical_scenario',window_hours=48)


def settlement_profile(binding):
    """Bind public dimensions to the existing independent settlement comparator."""
    from app.settlement import profile,fact
    row,doc=contract(binding);sport=row['sport'];period=row['period'];family=row['family']
    period_docs={'kalshi-football-win','kalshi-football-spread','kalshi-football-total',
                 'kalshi-baseball-win','kalshi-baseball-spread','kalshi-baseball-total',
                 'kalshi-hockey-spread','kalshi-hockey-total'}
    if family!='futures' and doc['id'] not in period_docs:
        raise ValueError('Linked contract class has no reviewed period profile; no sibling-rule inheritance')
    evidence=doc['sha256'];known={}
    def put(key,value):known[key]=fact(value,evidence=evidence)
    if family=='futures' and doc.get('contract_class')=='ENTITYOUTCOME':
        put('tie','literal_achievement; comparative_ties_1_over_N_rounding_precision_or_tie_strike_separate')
        put('cancellation','achieved_or_structurally_impossible -> official_standings -> explicit_venue_last_fair_decision')
        put('postponement','within_listed_time_period_or_overarching_competition_six_months')
        put('result_corrections','vacatur_before_expiration_applies; post_achievement_disqualification_alone_does_not_erase_achievement')
        put('forfeit','opponent_forfeit_achievement_counts; own_withdrawal_before_achievement_NO')
        put('overtime','all_official_tiebreaking_extensions_included')
    elif family=='futures':
        if doc.get('contract_class') not in ('TITLE','ACHIEVEMENTS'):raise ValueError('Unsupported exact award class')
        put('tie','shared_award_cent_floor_complementary_binary_sides')
        put('cancellation','TITLE_remaining_eligible_listed_field_cent_floor' if doc['id']=='kalshi-title' else 'ACHIEVEMENTS_last_fair_committee_eligible_field_waterfall')
        put('result_corrections','before_expiration_only; reinstatement_creates_new_market_original_NO_stands')
        put('forfeit','forfeiting_team_NO')
        put('shortened_game','official_declared_award_winner_or_shared_winners')
        put('postponement','TITLE_two_year_cap' if doc['id']=='kalshi-title' else 'known_final_date_two_weeks_unknown_date_two_years; suspension_two_years')
    else:
        put('overtime','specified_segment_only_later_periods_excluded' if period!='full_game' else 'included_unless_source_time_period_says_otherwise')
        put('tie','literal_score_inequality; equality_NO_for_strict_greater' if family in ('spread','total') else 'requires_exact_listed_tie_strike_or_documented_shared_winner_branch')
        put('shortened_game','completed_period_or_irrevocably_determined_predicate_stands; incomplete_period_venue_fair_value')
        put('abandonment','completed_period_stands; 55_minute_or_league_official_exception_separate' if sport in ('NFL','NHL') else 'completed_period_stands; unfinished_venue_fair_value')
        put('fair_value','explicit_venue_last_fair_decision_required_no_quote_substitution')
        put('result_corrections','official_revisions_before_expiration; later_revisions_excluded; discretionary_review_separate')
        put('postponement','48_hours_from_original_schedule; exact_source_reschedule_identity_required')
        put('resumption','48_hour_window; specified_completed_period_exception')
        put('cancellation','venue_last_fair_value; completed_predicate_exception')
        if sport=='MLB' and family in ('spread','total'):
            put('listed_pitchers','action_all_starting_pitcher_changes_valid')
            put('venue_change','venue_changed_game_played_contracts_valid; original_designated_reschedule_or_chronological_makeup_identity_separate')
        elif sport=='NFL':put('venue_change','same_home_away_within48hours_official_result; reversal_or_outside_scheduling_week_last_fair_value')
    source=dict(url=doc['url'],sha256=evidence,text=doc['clause'],retained_path=doc['path'])
    return profile(sources=[source],dimensions=known,effective_date=doc.get('effective_date'),actor=VERSION)


def championship_payout(binding, *, participant, field, winners=None, eligible=None,
                        cancellation=False, last_fair=None, committee=None, earlier_steps_unavailable=False,
                        entity_decision=None):
    """Template precedence + explicit award state; never prices as resolutions."""
    row,doc=contract(binding)
    if row['family']!='futures' or not isinstance(field,list) or len(field)<2 or len(set(field))!=len(field) or participant not in field:
        raise ValueError('Exact complete championship field/participant required')
    winners=[] if winners is None else winners
    if len(set(winners))!=len(winners) or set(winners)-set(field):raise ValueError('Winner field conflict')
    if doc.get('contract_class')=='ENTITYOUTCOME':
        options=deepcopy(entity_decision or {})
        if winners and not cancellation:options['achieved']=participant in winners
        options['cancelled']=cancellation
        return entity_outcome(binding,**options)
    if doc.get('contract_class') not in ('TITLE','ACHIEVEMENTS'):raise ValueError('Exact award class not bound')
    def pair(yes,basis):
        return dict(version=VERSION,yes=None if yes is None else str(yes),no=None if yes is None else str(1-yes),
                    source=doc,basis=basis,original_field=deepcopy(field),winners=deepcopy(winners))
    if winners and not cancellation:
        value=(Decimal(1)/len(winners)).quantize(Decimal('.01'),rounding=ROUND_FLOOR) if participant in winners else Decimal(0)
        return pair(value,'official_award_shared_winner_cent_floor')
    if not cancellation:return pair(None,'award_not_declared_or_no_winner_rule_unestablished')
    if eligible is None:return pair(None,'cancellation_requires_current_listed_remaining_eligible_field')
    if not isinstance(eligible,list) or not eligible or len(set(eligible))!=len(eligible) or set(eligible)-set(field):
        raise ValueError('Exact current listed eligible field required')
    if participant not in eligible:return pair(Decimal(0),'previously_eliminated_or_disqualified_original_NO_stands')
    if doc['id']!='kalshi-title':
        if last_fair is not None or committee is not None:
            allocation=last_fair if last_fair is not None else committee
            if set(allocation)!=set(eligible):
                raise ValueError('Complete explicit venue allocation required')
            for v in allocation.values():fraction_input(v)
            return pair(fraction_input(allocation[participant]),'explicit_last_fair_decision' if last_fair is not None else 'explicit_committee_decision')
        # Absence of inputs does not prove preceding discretionary steps failed.
        if earlier_steps_unavailable is not True:
            return pair(None,'ACHIEVEMENTS last fair -> committee -> eligible field fallback requires explicit venue decision')
    if not isinstance(eligible,list) or not eligible or len(set(eligible))!=len(eligible) or set(eligible)-set(field):
        return pair(None,'TITLE cancellation needs current listed remaining eligible field')
    value=(Decimal(1)/len(eligible)).quantize(Decimal('.01'),rounding=ROUND_FLOOR) if participant in eligible else Decimal(0)
    return pair(value,('TITLE' if doc['id']=='kalshi-title' else 'ACHIEVEMENTS explicit_failed_prior_steps')+' canceled_award_remaining_field_cent_floor')


def entity_outcome(binding,*,achieved=None,structurally_impossible=False,cancelled=False,
                   official_standings_achievement=None,venue_fraction=None,vacated_before_expiration=False,
                   format_changed=False,methodology_established=False,comparative_tied_count=None,
                   comparison_tie_strike=None,achievement_components=None,logic=None):
    """Exact ENTITYOUTCOME predicates; comparative ties do not become award shares."""
    row,doc=contract(binding)
    if doc.get('contract_class')!='ENTITYOUTCOME':raise ValueError('Exact ENTITYOUTCOME class required')
    if achievement_components is not None:
        if logic not in ('AND','OR') or not isinstance(achievement_components,list) or not 1<=len(achievement_components)<=512 or any(v is not None and type(v) is not bool for v in achievement_components):
            raise ValueError('Explicit listed AND/OR scope and boolean/unknown achievements required')
        derived=(False if False in achievement_components else True if all(v is True for v in achievement_components) else None) if logic=='AND' else (True if True in achievement_components else False if all(v is False for v in achievement_components) else None)
        if achieved is not None and achieved!=derived:raise ValueError('Literal and logical achievement conflict')
        achieved=derived
    elif logic is not None:raise ValueError('Logical scope needs explicit components')
    for value in (achieved,official_standings_achievement):
        if value is not None and type(value) is not bool:raise ValueError('Explicit literal achievement fact required')
    for value in (structurally_impossible,cancelled,vacated_before_expiration,format_changed,methodology_established):
        if type(value) is not bool:raise ValueError('Explicit source decision flags required')
    value=None;raw=None;basis='literal_achievement_not_established'
    if format_changed and not methodology_established:basis='exchange_methodology_required_no_natural_interpretation_inference'
    elif vacated_before_expiration or structurally_impossible:value=Decimal(0);basis='official_vacatur_or_structural_impossibility'
    elif comparative_tied_count is not None:
        if type(comparative_tied_count) is not int or not 2<=comparative_tied_count<=512:raise ValueError('Exact comparative tied entity count required')
        if comparison_tie_strike is not False:basis='comparative_tie_strike_presence_and_decision_required'
        else:
            raw=str(Decimal(1)/comparative_tied_count);basis='comparative_1_over_N_rounded_down_precision_not_published'
            if venue_fraction is not None:
                value=fraction_input(venue_fraction)
                if not 0<=value<=Decimal(raw):raise ValueError('Comparative rounded payout exceeds1/N')
    elif achieved is True:value=Decimal(1);basis='official_literal_achievement'
    elif cancelled:
        if official_standings_achievement is not None:value=Decimal(int(official_standings_achievement));basis='explicit_last_official_standings_achievement'
        elif venue_fraction is not None:value=fraction_input(venue_fraction);basis='explicit_venue_last_fair_decision'
        else:basis='cancellation_requires_official_standings_or_venue_fair_decision'
    elif achieved is False:value=Decimal(0);basis='official_literal_nonachievement'
    if value is not None and (not value.is_finite() or not 0<=value<=1):raise ValueError('Bounded venue payout required')
    return dict(version=VERSION,yes=None if value is None else str(value),no=None if value is None else str(1-value),
                source=doc,basis=basis,unrounded_comparative_fraction=raw)


def award_identity(native,binding):
    from app.collection.native_score_binding import championship
    row,doc=contract(binding);predicate=championship(native,binding)
    if predicate is None:raise ValueError('Complete literal award predicate required')
    data=load();field=None;season=predicate['season'];members=None
    matches=[x for x in data['award_crosswalks'] if x['native_metadata_sha256']==stable(native)
             and x['series_ticker']==row['series_ticker'] and x['category']==row['category']]
    association=matches[0] if len(matches)==1 else None
    participant=predicate['participant']
    if association:
        field=data['fields'][association['field_key']];season=association['season']
        members=field['members']
        if row['sport']=='NFL' and row['category']=='conference_champion':members=field['conferences'][row['conference_id']]
        if association['field_key']=='AAC':members=[m['id'] for m in members]
        participant=association.get('participant_enrichment') or participant
    return dict(version=VERSION,predicate=predicate,participant=participant,association=deepcopy(association),
        official_award_source=data['sources'][association['official_award_source']] if association else None,
        season=season,category=row['category'],
        conference_id=row['conference_id'],field=members,field_provenance=field,contract_provenance=doc,
        status='DOCUMENTED_IDENTITY' if field else 'PARTIAL_AWARD_IDENTITY',
        missing=['Exact selected award deadline and field revision/eligibility','Venue exception decisions and effective amendments'],
        collection_authorized=False)


def championship_descriptor(event,binding,participant,*,scenario_allocations=None):
    """Feed source-specific state payouts into the existing futures engine."""
    from app.normalization import futures
    row,doc=contract(binding);futures.event_key(event)
    if row['family']!='futures' or row['sport']!=event['competition'] or row['category']!=event['category'] or row.get('conference_id')!=event.get('conference_id'):
        raise ValueError('Championship category/competition conflict')
    payouts={'yes':{},'no':{}}
    for state in event['states']:
        options=(scenario_allocations or {}).get(state['id'],{})
        p=championship_payout(binding,participant=participant,field=event['field'],winners=state['winners'],**options)
        for side in payouts:payouts[side][state['id']]=p[side]
    d=dict(version='score-lines-1',public_binding_version=VERSION,source='kalshi',family='futures',period='season',
        participant=participant,line=None,category=event['category'],horizon=event['horizon'],state_space='explicit_exhaustive',
        contract_document=doc['url'],contract_provenance=doc,settlement_model='explicit_source_state_table',
        outcomes=[dict(native_id=side,native_label=side.title(),role='achievement' if side=='yes' else 'not_achievement',
                       payouts=payouts[side]) for side in payouts])
    futures.descriptor(event,d)
    return d


def novig_h1_descriptor(*,participant,yes_id,no_id,association=None):
    """Documented NFL-004 template; listing association is a separate gate."""
    doc=load()['sources']['novig-nfl004']
    if not participant or not yes_id or not no_id or yes_id==no_id:raise ValueError('Exact participant/outcome IDs required')
    d=dict(version='score-lines-1',public_binding_version=VERSION,source='novig',family='moneyline',period='first_half',
        participant=participant,line=None,unit='points',offered='pregame',regulation='first_two_15_minute_quarters',
        overtime='excluded',overtime_format='not_applicable',normal_completion='first_two_quarters_definitively_completed',
        settlement_score='first_half_only',tied_score='evaluate_actual_score_predicate',winner_structure='shared_winner',
        contract_document=doc['url'],contract_provenance=doc,
        outcomes=[dict(native_id=id,native_label=label,operator=op,equality='fraction',equality_payout='0.5',refund_fees='unknown')
                  for id,label,op in [(yes_id,'Selected team','gt'),(no_id,'Other team','le')]])
    if association is not None and (association.get('class_id')!='NFL-004' or association.get('period')!='first_half' or not association.get('market_id') or not association.get('source')):
        raise ValueError('Exact effective listing-to-class/period association required')
    return dict(version=VERSION,descriptor=d,status='IMPLEMENTED_AWAITING_REAL_SOURCE_EVIDENCE' if association is None else 'DOCUMENTED_TEMPLATE_WITH_CALLER_ASSOCIATION',
        association=deepcopy(association),missing=['Effective NFL-004 listing association; dollar class face/v3 one-cent unit applicability'],
        collection_authorized=False)


def prophetx_h1_descriptor(*,participant,selected_id,other_id):
    """Non-tied H1 winner predicate; ambiguous tie clause gates equality only."""
    doc=load()['sources']['prophetx-nfl-spec']
    if not participant or not selected_id or not other_id or selected_id==other_id:raise ValueError('Exact outcomes required')
    d=dict(version='score-lines-1',public_binding_version=VERSION,source='prophetx',family='moneyline',period='first_half',
        participant=participant,line=None,unit='points',offered='pregame',regulation='first_two_15_minute_quarters',
        overtime='excluded',overtime_format='not_applicable',normal_completion='first_two_quarters_definitively_completed',
        settlement_score='first_half_only',tied_score='evaluate_actual_score_predicate',winner_structure='binary_team_win_unresolved_tie',
        contract_document=doc['url'],contract_provenance=doc,
        outcomes=[dict(native_id=id,native_label=label,operator=op,equality='unknown',refund_fees='unknown') for id,label,op in
                  [(selected_id,'Selected team','gt'),(other_id,'Other team','le')]])
    return dict(version=VERSION,descriptor=d,status='IMPLEMENTED_AWAITING_REAL_SOURCE_EVIDENCE',
                missing=['Selected listing/class association','H1 tie clause does not expressly replace after-overtime moneyline tie wording',
                         'Native stake/contract quantity conversion and fee return'],collection_authorized=False)


def award_revision(binding,*,expired,eliminated=False,reinstated=False,official_winner_change=False):
    """Apply documented revision boundary; never fabricate a successor market."""
    row,doc=contract(binding)
    if row['family']!='futures' or any(type(v) is not bool for v in (expired,eliminated,reinstated,official_winner_change)):
        raise ValueError('Explicit award revision facts required')
    if expired:return dict(version=VERSION,source=doc,effect='original_expiration_value_unchanged',original_market_preserved=True)
    if doc.get('contract_class')=='ENTITYOUTCOME':
        if eliminated or reinstated:raise ValueError('ENTITYOUTCOME literal achievement/vacatur, not ACHIEVEMENTS eliminated-market inheritance')
        return dict(version=VERSION,source=doc,effect='official_pre_expiration_vacatur_or_affirmation_requires_literal_achievement_decision',original_market_preserved=True)
    if reinstated:
        if not eliminated:raise ValueError('Reinstatement needs earlier eliminated/original_NO state')
        return dict(version=VERSION,source=doc,effect='original_market_remains_NO; new_market_may_be_created',
                    original_yes='0',original_no='1',successor_market_id=None,correction_edge=False)
    return dict(version=VERSION,source=doc,effect='source_reported_elimination_NO' if eliminated else 'pre_expiration_official_award_revision_applies' if official_winner_change else 'no_revision_fact',
                original_market_preserved=True)


def hockey_period_template(*,family,period,participant,line=None,association=None):
    """Documented class mechanics; does not invent one of the nine selectors."""
    from app.normalization.score_periods import PERIODS
    if family not in ('moneyline','spread','total') or period not in PERIODS['NHL']:
        raise ValueError('Requested individual regulation period required')
    key={'moneyline':'kalshi-hockey-winner-amendment','spread':'kalshi-hockey-spread','total':'kalshi-hockey-total'}[family]
    doc=load()['sources'][key];start,end=PERIODS['NHL'][period]
    if family=='moneyline' and line is not None:raise ValueError('Unlined period winner required')
    if family=='total' and participant!='combined':raise ValueError('Combined period goal total required')
    if family!='moneyline':
        from app.normalization.score_lines import decimal
        decimal(line)
    if association is not None and (association.get('contract_document')!=doc['url'] or association.get('period')!=period or not association.get('market_id') or not association.get('source')):
        raise ValueError('Exact period and amended class association required')
    d=dict(version='score-lines-1',public_binding_version=VERSION,source='kalshi',family=family,period=period,
        participant=participant,line=line,unit='goals',offered='pregame',regulation=period,overtime='excluded',
        overtime_format='not_applicable',normal_completion=period+'_definitively_completed',settlement_score=period+'_only',
        segment_start=start,segment_end=end,tied_score='evaluate_actual_score_predicate',
        contract_document=doc['url'],contract_provenance=doc,
        outcomes=[dict(native_id=id,native_label=id.title(),operator=op,equality='unknown' if family=='moneyline' else 'predicate',refund_fees='unknown')
                  for id,op in [('yes','gt'),('no','le')]])
    if family=='moneyline':d['winner_structure']='binary_team_win_unresolved_tie'
    return dict(version=VERSION,descriptor=d,status='IMPLEMENTED_AWAITING_REAL_SOURCE_EVIDENCE',association=deepcopy(association),
        missing=['Exact native locator/period predicate/line direction and effective listing association',
                 'Tie may-clause or actual tied-period decision' if family=='moneyline' else 'Record-specific inequality',
                 'Exceptional venue fair-value decisions'],collection_authorized=False)


def details(game, snapshot=None):
    """Ordinary Details additive annotation; historical calculations untouched."""
    data=load(); i=game.get('product_identity',{}); annotations=[]
    for source,native in game.get('sources',{}).items():
        participants=i.get('participants') or []
        if game.get('native_review'):
            event=game['native_review'].get('record',{}).get('event')
            if event and isinstance(event,list) and len(event)==2: participants=event[1]
        reviewed=game.get('native_review',{}).get('record',{}).get('sources',{}).get(source,{})
        metadata=reviewed.get('catalog_evidence',{}).get('event',{}).get('native_metadata',{})
        label=metadata.get('seriesSlug')
        annotations.append(event_identity(source=source,event_id=native['event_id'],competition=i.get('competition'),
            participants=participants,scheduled_start=game['scheduled_start'],provider_season=i.get('season'),provider_stage=i.get('stage'),provider_label=label))
    catalog=json.loads(PATH.with_name('native-scope-bindings-v1.json').read_text())
    templates=[]
    for binding in catalog['bindings']:
        if (binding['sport'],binding['period'],binding['family'])!=(i.get('competition'),i.get('period'),i.get('family')):continue
        try:
            row,doc=contract(binding)
            profile=settlement_profile(binding)
        except ValueError:continue
        templates.append(dict(series=row['series_ticker'],document=doc,settlement=profile,
            association='Documented retained series class; exact selected predicate/effective amendment and exception decision checked separately'))
    membership=None
    if i.get('competition') in ('NFL','NBA','NHL','MLB','NCAAF','NCAAB'):
        membership=membership_field(i['competition'])
    fee_rules={source:data['sources'][{'kalshi':'kalshi-rounding','polymarket_us':'us-fees',
        'novig':'novig-v3-fees','prophetx':'prophetx-fees'}[source]] for source in game.get('sources',{})
        if source in ('kalshi','polymarket_us','novig','prophetx')}
    return dict(version=VERSION,identity=annotations,offerings=data['offerings'],contract_templates=templates,
                membership=membership,fee_rules=fee_rules,collection_authorized=False,
                summary='Public contract bindings are additive. Original interpretation and calculation are retained.',
                optional_inputs=['Independent probability model for EV only; deterministic payoff needs no model'],
                scenario_inputs=['Hypothetical fills/allocations, explicit fees or exception decisions, quantities and portfolio states'])

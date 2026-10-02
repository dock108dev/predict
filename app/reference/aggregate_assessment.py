"""Versioned later research over four exact retained H1 observations.

This never alters journals, source identities, native joins, fees or payouts.
Public template assessments are kept apart from effective listing assessments.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from app.dashboard.session_projection import stable
from app.settlement import profile, fact, compare_profiles

VERSION = 'aggregate-h1-rules-20260929-v1'
DATA = Path(__file__).resolve().parents[1] / 'fixtures' / (VERSION + '.json')
DATA_SHA256 = '515a59c24a9fb3a96f4173381df5c5f47ccc3125f2a58d7474f4afc8f5738c3d'
ROOT = Path(__file__).resolve().parents[2]


def reviewed_data():
    body = DATA.read_bytes()
    if sha256(body).hexdigest() != DATA_SHA256:
        raise ValueError('Reviewed assessment changed')
    data = json.loads(body)
    if data['version'] != VERSION:
        raise ValueError('Unknown assessment version')
    for source in data['sources']:
        for field, digest in (('retained_path', 'sha256'), ('text_path', 'text_sha256')):
            recorded = Path(source[field])
            # Preserve the sealed record's bytes while relocating its exact repository paths.
            relative = Path(*recorded.parts[recorded.parts.index('evidence'):]) if recorded.is_absolute() else recorded
            path = ROOT / relative
            if not path.is_relative_to(ROOT) or sha256(path.read_bytes()).hexdigest() != source[digest]:
                raise ValueError('Reviewed public source changed or unavailable')
    return data


def profiles(data, book, *, documented):
    """Use the shared settlement comparator without promoting a template to a listing."""
    name = 'novig-nfl-winner' if book == 'novig' else 'prophetx-nfl-mainline'
    source = next(s for s in data['sources'] if s['id'] == name)
    evidence = source['sha256']
    sources = [dict(url=source['url'], sha256=evidence,
                    text='Retained public contract template: ' + source['text_path'])]
    dimensions = {}
    payouts = {}
    if documented:
        dimensions['overtime'] = fact('first_half_excludes_overtime', evidence=evidence)
        if book == 'novig':
            dimensions['tie'] = fact('half_settlement_value_each_side', evidence=evidence)
            dimensions['result_corrections'] = fact('exclude_revisions_after_expiration', evidence=evidence)
            payouts['tie'] = dict(kind='fraction', value='0.5', evidence=evidence)
            dimensions['shortened_game'] = fact('completed_recorded_segment_stands_without_full_game', evidence=evidence)
            dimensions['postponement'] = fact('scheduling_week_with_formal_reschedule_or_48h_exceptions', evidence=evidence)
            dimensions['resumption'] = fact('48h_suspension_window_separate_postseason_rules', evidence=evidence)
            dimensions['fair_value'] = fact('reference_time_composite_30m_waterfall_then_at_risk_funds_fallback', evidence=evidence)
            dimensions['settlement_sources'] = fact('NFL_official_hierarchy_then_two_concordant_independent_sources', evidence=evidence)
        else:
            dimensions['tie'] = fact(reason='Post-overtime tie clause does not unambiguously establish H1 treatment')
            dimensions['result_corrections'] = fact('resettlement_on_additional_official_information', evidence=evidence)
            dimensions['shortened_game'] = fact('period_complete_unless_outcome_unequivocally_determined', evidence=evidence)
            dimensions['settlement_sources'] = fact('NFL_primary_ESPN_AP_secondary_then_rule_5_2', evidence=evidence)
            # The general 55-minute rule is documented, but H1 precedence is
            # unresolved; it must not become an effective period deadline.
            dimensions['postponement'] = fact(reason='General NFL weekly/55-minute rule; H1 precedence and pre-start treatment unresolved')
    return profile(sources=sources, dimensions=dimensions, payouts=payouts,
                   effective_date=None, actor=VERSION + (':documented-template' if documented else ':unbound-listing'))


def enrich(row, version=VERSION):
    if version == 'original':
        return row
    if version != VERSION:
        raise ValueError('Unsupported aggregate rule analysis version')
    # Restrict applicability before disk reads. Another event, period, or venue
    # never inherits a reviewed fact through a name/ID resemblance.
    if (row['identity'].get('competition'), row['identity'].get('period'),
            row['identity'].get('family')) != ('NFL', 'first_half', 'moneyline'):
        return row
    if {l['venue'] for l in row['legs']} != {'novig', 'prophetx'}:
        return row
    try:
        data = reviewed_data()
    except (OSError, ValueError, KeyError):
        row['rule_analysis'] = dict(version=VERSION, status='unavailable',
            summary='Reviewed rule evidence unavailable or changed; raw observations preserved.',
            blockers=['Verified versioned rule evidence is unavailable.'], books={})
        return row
    bindings = {b['record_sha256']: b for b in data['bindings']}
    selected = {}
    for leg in row['legs']:
        original = leg['provenance']['original']
        digest = stable(original)
        binding = bindings.get(digest)
        if (not binding or original.get('receipt_sha256') != data['response_sha256']
                or leg['id'] != digest or binding['book'] != leg['venue']):
            return row
        selected[leg['venue']] = deepcopy(binding)
    template_profiles = {b: profiles(data, b, documented=True) for b in selected}
    listing_profiles = {b: profiles(data, b, documented=False) for b in selected}
    audit = compare_profiles(listing_profiles['novig'], listing_profiles['prophetx'])
    audit['reason'] = 'No effective listing-to-rule binding; documented templates are separate research'
    analysis = dict(version=VERSION, assessment_sha256=DATA_SHA256,
        status='documented_unbound', reviewed_at=data['reviewed_at'],
        basis='Later public-document research over exact saved records; not knowledge established at acquisition',
        summary=data['summary'], response_sha256=data['response_sha256'],
        books={b: dict(facts=data['books'][b], crosswalk=selected[b]) for b in selected},
        sources=data['sources'], blockers=data['blockers'], native_lookup=data['native_lookup'],
        documented_profiles=template_profiles,
        documented_comparison=compare_profiles(template_profiles['novig'], template_profiles['prophetx']),
        documented_comparison_scope='Template differences only; not an actual observed-market settlement conflict',
        effective_profiles=listing_profiles)
    analysis['hash'] = stable(analysis)
    row['rule_analysis'] = analysis
    row['settlement_audit'] = audit
    # Raw prices, identities and all monetary outputs remain unchanged. There is
    # no qualified fee, payout or execution input to pass into monetary engines.
    return row

"""Reusable source/type scoring applicability, without acquisition.

Shared governing evidence is stored once; observations supply their own exact
identity, native predicate, complete terms and exceptions. Historical event
registry validators remain available for replay, outside ordinary admission.
Attachments never replace source predicates, prices, descriptions or clocks.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from app.comparison.current_dependencies import digest, encoded, instant

VERSION = 'predict-native-scoring-scope-3'
REGISTRY_VERSION = 'predict-native-scoring-registry-1'
ROOT = Path(__file__).resolve().parents[2]
REGISTRY = 'app/fixtures/native-scoring-scope/nfl-full-game-registry.json'
MAX_REGISTRY_BYTES = 128 * 1024
MAX_TARGETS = 32
STATES = ('included', 'excluded', 'unknown')


def _hash(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('Scope registry content digest required')


def _text(value):
    if not isinstance(value, str) or not value or len(value) > 8192:
        raise ValueError('Scope registry bounded text required')


def _key(value):
    if not isinstance(value, list) or len(value) != 5:
        raise ValueError('Scope registry exact native key required')
    for part in value:
        _text(part)
    if value[0] not in ('kalshi', 'polymarket_us'):
        raise ValueError('Scope registry native venue required')
    return tuple(value)


def _envelope(value):
    if (not isinstance(value, dict) or set(value) != {'version', 'governing_rules', 'targets'}
            or value['version'] != REGISTRY_VERSION or len(encoded(value)) > MAX_REGISTRY_BYTES
            or not isinstance(value['targets'], list) or not 1 <= len(value['targets']) <= MAX_TARGETS
            or not isinstance(value['governing_rules'], dict) or len(value['governing_rules']) > 8):
        raise ValueError('Scope registry bounded versioned envelope required')
    return value


def _rule(value):
    required = {'series_id', 'contract_terms_url', 'path', 'sha256', 'period', 'overtime',
                'reviewed_at', 'pointer_evidence', 'default'}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError('Scope governing rule envelope required')
    for name in ('series_id', 'contract_terms_url', 'path', 'default'):
        _text(value[name])
    if value['period'] != 'full_game' or value['overtime'] not in ('included', 'excluded'):
        raise ValueError('Scope governing full-game declaration required')
    _hash(value['sha256']);instant(value['reviewed_at'])
    pointer = value['pointer_evidence']
    if not isinstance(pointer, dict) or set(pointer) != {'path', 'sha256'}:
        raise ValueError('Scope governing pointer required')
    _text(pointer['path']);_hash(pointer['sha256'])
    for path in (value['path'], pointer['path']):
        if not path.startswith('app/fixtures/native-scoring-scope/') or '..' in Path(path).parts:
            raise ValueError('Scope evidence must be packaged locally')
    return value


def _target(value, rules):
    if not isinstance(value, dict) or set(value) != {'id', 'game', 'selection', 'family', 'period', 'bindings'}:
        raise ValueError('Scope target envelope required')
    _text(value['id'])
    game = value['game'];selection = value['selection']
    if (not isinstance(game, dict) or set(game) != {'sport', 'competition', 'season', 'stage', 'home', 'away', 'scheduled_start'}
            or game['sport'] != 'american_football' or game['competition'] != 'NFL'
            or game['stage'] != 'regular_season' or game['home'] == game['away']
            or not isinstance(selection, dict) or set(selection) != {'participant', 'predicate', 'signed_line'}
            or selection['participant'] not in (game['home'], game['away'])
            or selection['predicate'] != 'win' or selection['signed_line'] is not None
            or value['family'] != 'moneyline' or value['period'] != 'full_game'):
        raise ValueError('Scope target own NFL full-game winner facts required')
    for part in game.values():
        _text(part)
    instant(game['scheduled_start'])
    bindings = value['bindings']
    if not isinstance(bindings, list) or not 1 <= len(bindings) <= 4:
        raise ValueError('Scope target bounded native bindings required')
    keys = []
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) != {'native_key', 'series_id', 'governing_rule', 'reviewed_at', 'terms', 'wording', 'market_exceptions'}:
            raise ValueError('Scope native binding envelope required')
        key = _key(binding['native_key']);keys.append(key)
        if (key[0] == 'kalshi' and key[3:] != ('yes', 'yes')
                or key[0] == 'polymarket_us' and key[4] not in ('Long', 'Short')):
            raise ValueError('Scope registry native winner side conflict')
        instant(binding['reviewed_at']);_text(binding['market_exceptions'])
        rule_id = binding['governing_rule']
        if rule_id is not None:
            rule = _rule(rules[rule_id])
            if binding['series_id'] != rule['series_id']:
                raise ValueError('Scope native governing series conflict')
        elif binding['series_id'] is not None:
            _text(binding['series_id'])
        for name in ('terms', 'wording'):
            attachment = binding[name]
            if not isinstance(attachment, dict) or set(attachment) != {'sha256', 'text'}:
                raise ValueError('Scope exact complete wording required')
            _hash(attachment['sha256'])
            if not isinstance(attachment['text'], dict) or not 1 <= len(attachment['text']) <= 8:
                raise ValueError('Scope bounded native wording required')
            for field, text in attachment['text'].items():
                _text(field);_text(text)
            if digest(attachment['text']) != attachment['sha256']:
                raise ValueError('Scope original wording digest conflict')
    if len(keys) != len(set(keys)):
        raise ValueError('Scope duplicate native binding')
    return value


def validate_registry(value):
    """Strict authoring validation; runtime bad targets are isolated by native key."""
    _envelope(value)
    for rule in value['governing_rules'].values():
        _rule(rule)
    ids = [];keys = []
    for target in value['targets']:
        _target(target, value['governing_rules']);ids.append(target['id'])
        keys.extend(_key(binding['native_key']) for binding in target['bindings'])
    if len(ids) != len(set(ids)) or len(keys) != len(set(keys)):
        raise ValueError('Scope registry unique target and native binding required')
    return value


def registry():
    """Read current bytes every time; a changed file cannot reuse cached approval."""
    try:
        raw = (ROOT / REGISTRY).read_bytes()
        if len(raw) > MAX_REGISTRY_BYTES:
            return None
        return _envelope(json.loads(raw))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def publication_dependencies(keys, contexts=None):
    """Invalidate by reusable source/type rules, never by example event lists."""
    if len(keys) > 32768:
        raise ValueError('Scope publication dependency capacity')
    rules = source_rules()
    result = []
    if contexts is not None and len(contexts) != len(keys):
        raise ValueError('Scope dependency contexts must match native keys')
    for index, key in enumerate(keys):
        provider, event_id, market_id, *_ = key
        series = str(event_id or market_id or '').split('-', 1)[0]
        selected = [r for r in rules if r['provider'] == provider and
            (provider != 'kalshi' or r['native_type'] == series)]
        if contexts is not None:
            context = contexts[index] or {}
            meta = context.get('comparison_source_metadata',context)
            market = context.get('market_identity',context)
            league = market.get('competition',context.get('league'))
            native_type = meta.get('native_market_type') if provider == 'polymarket_us' else meta.get('series_id')
            selected = [r for r in selected if (league is None or r['league'] == league)
                and (market.get('family') is None or r['family'] == market['family'])
                and (market.get('period') is None or r['period'] == market['period'])
                and (native_type is None or r['native_type'] == native_type)]
        result.append(digest(dict(version=VERSION, provider=provider, rules=selected)))
    return result


_SOURCE_RULE_CACHE = None


def source_rules(*, detached=True):
    """Cache verified common evidence until one relevant file changes."""
    global _SOURCE_RULE_CACHE
    roots = [ROOT / 'app/fixtures/native-scope-bindings-v1.json',
        ROOT / 'app/fixtures/native-scoring-scope/full-game-source-rules.json',
        ROOT / 'app/fixtures/public-contracts-v1.json']
    paths = roots if _SOURCE_RULE_CACHE is None or _SOURCE_RULE_CACHE[0] != str(ROOT) else _SOURCE_RULE_CACHE[2]
    def signature(files):
        values = []
        for path in files:
            try:
                s = path.stat();values.append((str(path),s.st_mtime_ns,s.st_size))
            except OSError:
                values.append((str(path),None,None))
        return tuple(values)
    current = signature(paths)
    if _SOURCE_RULE_CACHE is not None and _SOURCE_RULE_CACHE[0] == str(ROOT) and current == _SOURCE_RULE_CACHE[1]:
        return deepcopy(_SOURCE_RULE_CACHE[3]) if detached else _SOURCE_RULE_CACHE[3]
    result = _build_source_rules()
    paths = list(roots)
    for rule in result:
        evidence = rule.get('evidence') or {}
        for item in (evidence,evidence.get('pointer_evidence') or {},*evidence.get('supporting_evidence',[])):
            if item.get('path'):
                path = ROOT / item['path']
                if path not in paths:
                    paths.append(path)
    _SOURCE_RULE_CACHE = (str(ROOT),signature(paths),paths,deepcopy(result))
    return result


def _build_source_rules():
    """Reusable exact venue/series/type contracts, independent of game identity.

    The retained source catalogs establish the supported class. Each observation
    still supplies its own participants, native side, period and exceptions.
    """
    from app.collection.public_contracts import load
    from .sporting_scope import supported
    path = ROOT / 'app/fixtures/native-scope-bindings-v1.json'
    try:
        raw = path.read_bytes()
        if len(raw) > 256 * 1024:
            return []
        catalog = json.loads(raw)
        if catalog.get('sha256') != digest({k:v for k,v in catalog.items() if k != 'sha256'}):
            return []
        public = load()
        authored_raw = (ROOT / 'app/fixtures/native-scoring-scope/full-game-source-rules.json').read_bytes()
        if len(authored_raw) > 128 * 1024:
            return []
        authored = json.loads(authored_raw)
        if authored.get('version') != 'predict-native-source-type-rules-1':
            return []
    except (OSError, ValueError, TypeError, KeyError):
        return []
    rules = []
    for row in catalog['bindings']:
        if not supported(row['sport'],row['family'],row['period']):
            continue
        rule = dict(provider='kalshi', native_type=row['series_ticker'], league=row['sport'],
            family=row['family'], period=row['period'], overtime='unknown',
            contract_terms_url=row['contract_terms_url'], source_sha256=row['source_record_sha256'])
        selected = [r for r in authored['rules'] if all(r.get(k) == rule[k]
            for k in ('provider','native_type','league','family','period'))]
        if len(selected) == 1:
            shared = selected[0];evidence = shared.get('evidence')
            available = False
            if isinstance(evidence, dict) and evidence.get('contract_terms_url') == row['contract_terms_url']:
                try:
                    path = Path(evidence['path'])
                    if path.is_absolute() or '..' in path.parts:
                        raise ValueError('Local source evidence required')
                    body = (ROOT / path).read_bytes()
                    available = len(body) <= 256 * 1024 and sha256(body).hexdigest() == evidence['sha256']
                    for support in evidence.get('supporting_evidence',[]):
                        support_path=Path(support['path'])
                        if support_path.is_absolute() or '..' in support_path.parts:
                            raise ValueError('Local scoring support required')
                        support_body=(ROOT/support_path).read_bytes()
                        available &= len(support_body)<=256*1024 and sha256(support_body).hexdigest()==support['sha256']
                    pointer = evidence.get('pointer_evidence')
                    if pointer:
                        pointer_path = Path(pointer['path'])
                        if pointer_path.is_absolute() or '..' in pointer_path.parts:
                            raise ValueError('Local source pointer required')
                        pointer_body = (ROOT / pointer_path).read_bytes()
                        if len(pointer_body) > 16 * 1024:
                            raise ValueError('Bounded source pointer required')
                        governing = json.loads(pointer_body)['governing_terms']
                        available &= (sha256(pointer_body).hexdigest() == pointer['sha256'] and
                            governing['current_series_id'] == row['series_ticker'] and
                            governing['contract_terms_url'] == row['contract_terms_url'] and
                            governing['sha256'] == evidence['sha256'])
                except (OSError, ValueError, KeyError, TypeError):
                    available = False
            rule.update(evidence=deepcopy(evidence),evidence_available=available)
            if available:
                rule.update(shared['defaults'])
        rules.append(rule)
    us_defaults = authored.get('polymarket_us_game_defaults', {})
    us_evidence = us_defaults.get('evidence', {})
    us_available = False
    try:
        path = Path(us_evidence['path'])
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('Local source evidence required')
        body = (ROOT / path).read_bytes()
        us_available = len(body) <= 256 * 1024 and sha256(body).hexdigest() == us_evidence['sha256']
    except (OSError, ValueError, KeyError, TypeError):
        pass
    for native_type, row in public['us_types'].items():
        for league in row['competitions']:
            if not supported(league,row['family'],row['period']):continue
            rule = dict(provider='polymarket_us', native_type=native_type, league=league,
                family=row['family'], period=row['period'], overtime='unknown',
                source_sha256=digest(dict(native_type=row,schema={k:public['sources']['us-schema'].get(k)
                    for k in ('url','sha256')})))
            if row['period'] == 'full_game' and row['family'] in ('moneyline','spread','total'):
                rule.update(evidence=deepcopy(us_evidence), evidence_available=us_available)
                if us_available:
                    rule.update({k:us_defaults[k] for k in ('overtime','extra_innings','shootout')})
            rules.append(rule)
    return rules


def _rule_for(record):
    q = record['quote'];e = record['event'];m = record['market_identity']
    meta = record.get('comparison_source_metadata', {})
    native_type = meta.get('series_id') if q['venue'] == 'kalshi' else meta.get('native_market_type')
    candidates = [r for r in source_rules(detached=False) if r['provider'] == q['venue'] and
        r['league'] == e.get('competition') and r['family'] == m.get('family') and r['period'] == m.get('period')]
    if native_type is not None:
        candidates = [r for r in candidates if r['native_type'] == native_type]
    # Old SQL winner observations already carry the exact admitted family/period
    # and original full-game source literal. They reproject through this class.
    if q['venue'] == 'polymarket_us' and native_type is None and len(candidates) == 1:
        return candidates[0]
    return candidates[0] if len(candidates) == 1 else None


def resolve(record, *, at):
    """Resolve reusable source rules plus this observation's structured facts."""
    instant(at)
    q = record['quote'];event = record['event'];market = record['market_identity']
    meta = record.get('comparison_source_metadata', {})
    terms = (meta.get('combined_native_binding') or {}).get('original_terms')
    if terms is None:
        terms = meta.get('native_terms')
    wording = meta.get('original_wording')
    previous = meta.get('scoring_scope', {})
    observed = previous.get('observed_overtime', (record.get('comparison_scope') or {}).get('overtime', 'unknown'))
    facts = [];conflicts = [];missing = []
    key = [q['venue'], *[q.get('source', {}).get(k) for k in
        ('native_event_id','native_market_id','native_outcome_id','native_side')]]
    if any(v is None for v in key) or 'native_key' not in meta:
        missing.append('native_key')
    elif meta['native_key'] != key or q['source'].get('provider') != q['venue'] or key[1] != event.get('id'):
        conflicts.append('scope_rules_identity_conflict')
    if q['venue'] == 'kalshi' and (key[-1] not in ('yes','no') or key[-2] != key[-1]):
        conflicts.append('scope_rules_native_side_conflict')
    retail = meta.get('public_retail_observation') or {}
    if q['venue'] == 'polymarket_us' and isinstance(retail.get('long'),bool):
        if (key[-1] != ('Long' if retail['long'] else 'Short') or
                retail.get('instrument_id',key[-2]) != key[-2] or
                retail.get('market_id',key[2]) != key[2]):
            conflicts.append('scope_rules_native_side_conflict')
    for field in ('competition','season','stage','home','away','scheduled_start'):
        if not event.get(field):
            missing.append(field)
    roles = event.get('source_participant_roles', {})
    if (event.get('conflicting_duplicate') or event.get('occurrence_conflict') or
            event.get('home') == event.get('away') or
            any(event.get(k) is not None and roles.get(k, event.get(k)) != event.get(k) for k in ('home','away')) or
            any(market.get(k) is not None and market.get(k) != event.get(k) for k in ('competition','season','stage')) or
            event.get('stage') not in (None,'regular_season','preseason','playoffs','postseason','tournament')):
        conflicts.append('scope_rules_identity_conflict')
    if event.get('home') and event.get('away') and set(event.get('participants', {}).values()) != {event.get('home'), event.get('away')}:
        conflicts.append('scope_rules_participant_conflict')
    original_roles = (meta.get('combined_native_binding') or {}).get('original_roles', {})
    if any(event.get(k) is not None and original_roles.get(k,event[k]) != event[k] for k in ('home','away')):
        conflicts.append('scope_rules_participant_conflict')
    selection = record.get('selection', {})
    if market.get('family') in ('moneyline','spread') and selection.get('participant') not in set(event.get('participants', {}).values()):
        conflicts.append('scope_rules_participant_conflict')
    if market.get('scheduled_start') is not None and event.get('scheduled_start') is not None:
        try:
            if instant(market['scheduled_start']) != instant(event['scheduled_start']):
                conflicts.append('scope_rules_schedule_conflict')
        except (ValueError,TypeError):
            conflicts.append('scope_rules_schedule_conflict')
    if market.get('period') is None:
        missing.append('period')
    rule = _rule_for(record)
    if rule is None:
        if market.get('period') is None or meta.get('series_id') is None and q['venue'] == 'kalshi':
            missing.append('source_type_rule')
        else:
            conflicts.append('scope_rules_type_conflict')
    if not isinstance(terms, dict) or not terms or not isinstance(wording, dict) or not wording:
        missing.append('original_terms')
    else:
        semantic = ('description','rules_primary','rules_secondary')
        if any(terms.get(k) != wording.get(k) for k in semantic):
            conflicts.append('scope_rules_terms_conflict')
        if any(meta.get(k) is not None and meta[k] != v for k,v in terms.items()):
            conflicts.append('scope_rules_terms_conflict')
        if q['venue'] == 'kalshi' and market.get('family') == 'moneyline':
            label = wording.get('yes_sub_title')
            if label:
                from app.collection.admission_enrichment import repair_registry
                resolved = repair_registry().resolve('team',label,league=event.get('competition'),venue='kalshi')
                if resolved.status == 'resolved' and resolved.canonical_id != selection.get('participant'):
                    conflicts.append('scope_rules_participant_conflict')
            expected = 'win' if key[-1] == 'yes' else 'not_win' if key[-1] == 'no' else None
            if selection.get('predicate') != expected:
                conflicts.append('scope_rules_native_side_conflict')
        if (q['venue'] == 'polymarket_us' and market.get('family') == 'moneyline'
                and market.get('period')=='full_game' and selection.get('predicate') != 'win'):
            conflicts.append('scope_rules_native_side_conflict')
    if observed not in STATES:
        conflicts.append('scoring_overtime_value_invalid')
    elif observed != 'unknown':
        facts.append(dict(overtime=observed, basis='stored_native_scope'))
    text = '\n'.join(str(v) for values in (terms, wording) if isinstance(values,dict) for v in values.values()).lower()
    declarations = {'overtime is included': 'included', 'including overtime': 'included', 'includes overtime': 'included',
        'overtime is excluded': 'excluded', 'overtime is not included': 'excluded',
        'excluding overtime': 'excluded', 'regulation time only': 'excluded'}
    explicit = set()
    for literal, value in declarations.items():
        if literal in text:
            explicit.add(value)
            facts.append(dict(overtime=value,basis='selected_source_description',text=literal))
    if event.get('competition') == 'MLB' and any(literal in text for literal in
            ('includes extra innings','including extra innings','extra innings are included')):
        explicit.add('included')
        facts.append(dict(overtime='included',basis='selected_source_description',text='extra innings included'))
    scoring = dict(overtime='unknown', extra_innings='not_applicable', shootout='not_applicable', score_domain='integer')
    if rule:
        # A source period exception overrides the class default, and conflicting
        # own declarations remain visible instead of silently choosing one.
        if not explicit and rule['overtime'] != 'unknown':
            facts.append(dict(overtime=rule['overtime'],basis='source_type_rule',rule_id=rule['native_type'],rule_sha256=digest(rule)))
        elif not explicit and rule.get('evidence') and not rule.get('evidence_available'):
            missing.append('source_rule_evidence')
        if event.get('competition') == 'MLB':
            scoring['extra_innings'] = ('excluded' if 'extra innings are excluded' in text or 'excluding extra innings' in text
                else 'included' if 'extra innings' in text and any(word in text for word in ('included','including','includes'))
                else rule.get('extra_innings','unknown'))
        if event.get('competition') == 'NHL':
            scoring['shootout'] = ('excluded' if 'shootout is excluded' in text or 'excluding shootout' in text
                else ('official_final_score' if rule.get('shootout')=='official_final_score' else 'included')
                    if 'shootout' in text and any(word in text for word in ('included','including','includes'))
                else rule.get('shootout','unknown'))
    values = {f['overtime'] for f in facts}
    if len(values) > 1:
        conflicts.append('scoring_overtime_facts_conflict')
    if len(values) == 1:
        scoring['overtime'] = next(iter(values))
    if scoring['overtime'] == 'unknown':
        missing.append('overtime')
    if market.get('period')!='full_game' and scoring['overtime']=='included':
        conflicts.append('scoring_partial_period_includes_overtime')
    if market.get('period')!='full_game' and event.get('competition')=='MLB' and scoring['extra_innings']=='included':
        conflicts.append('scoring_partial_period_includes_extra_innings')
    for field in ('extra_innings','shootout'):
        if scoring[field] == 'unknown':
            missing.append(field)
    status = 'contradictory' if conflicts else 'unknown' if missing else 'supported'
    overtime = scoring['overtime'] if status == 'supported' else 'unknown'
    reason = (conflicts[0] if conflicts else 'scope_rules_evidence_unavailable' if 'source_rule_evidence' in missing
        else 'scope_rules_fields_missing' if missing and missing != ['overtime']
        else 'scoring_overtime_missing' if missing else 'selected_scoring_scope_supported')
    return dict(version=VERSION,status=status,overtime=overtime,reason=reason,
        missing_fields=sorted(set(missing)), observed_overtime=observed, conflicts=sorted(set(conflicts)),
        evidence=facts,scoring=dict(scoring,overtime=overtime),rule_id=None if rule is None else rule['native_type'])


def attach(record, *, at):
    """Detach modified shells; read callers cannot mutate stored original inputs."""
    value = dict(record)
    if record['quote']['venue'] not in ('kalshi', 'polymarket_us'):
        return value
    if record['event'].get('competition') not in ('NFL','NCAAF','NBA','NCAAB','MLB','NHL'):
        return value
    scope = resolve(record, at=at)
    value['comparison_scope'] = dict(overtime=scope['overtime'])
    value['comparison_source_metadata'] = dict(record.get('comparison_source_metadata', {}),
        overtime=scope['overtime'], scoring_scope=deepcopy(scope))
    from .same_outcome import descriptor
    value['comparison_source_metadata']['same_outcome'] = descriptor(value, scoring=scope['scoring'])
    return value

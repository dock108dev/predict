"""Versioned finite native wire/parse policy; no transport or credentials here."""
import json
import math
import re
import sys

POLICY = 'bounded-open-catalog-v4'
KIB = 1024
MIB = 1024 * KIB
# Complete r3 US page fits 256 KiB; both truncated 256 KiB bodies are lower
# bounds only. 2 MiB is a tested engineering envelope, not a provider maximum.
BODY_LIMITS = {'discovery': 2*MIB, 'metadata': MIB, 'account': 64*KIB}
PAGE_CAPS = {'kalshi': 3, 'polymarket_us': 30}
PAGE_SIZES = {'kalshi': 200, 'polymarket_us': 5}
DISCOVERY_SESSION_BYTES = 6*MIB  # preserve 2 MiB of the shared 8 MiB for books
MARKET_PAGES = 3
MARKET_SIZE = 50
REQUEST_CAPS = {'kalshi': 2*2 + 3*(3 + 6*MARKET_PAGES)*2,
                'polymarket_us': 3*(30 + 6*MARKET_PAGES)*2}

# This is an engineering envelope, not an observed provider maximum. Selection
# must appear in a newly sealed spec; absence preserves every legacy limit.
TRANSPORT_POLICY = 'native-http-v2'
RESPONSE_CAP_REASONS = frozenset(('native_response_byte_cap', 'native_wire_byte_cap',
                                 'native_entity_byte_cap', 'native_decoded_byte_cap'))
TRANSPORT_CONTRACT = dict(policy=TRANSPORT_POLICY,
    response_wire_bytes=4*MIB, response_entity_bytes=2*MIB,
    response_decoded_bytes=2*MIB, parse_expansion_bytes=16*MIB,
    json_depth=32, json_structural_tokens=100000,
    discovery_wire_bytes=6*MIB, discovery_decoded_bytes=6*MIB,
    ingress_callback_bytes=256*KIB, source_inventory_bytes=2*MIB)


def exact_transport(value):
    """Equality alone accepts floats/bools in integer fields; seals require types."""
    return (isinstance(value, dict) and value == TRANSPORT_CONTRACT and
            all(type(value[k]) is type(v) for k, v in TRANSPORT_CONTRACT.items()))


def ordinary_collection(spec):
    sources = spec.get('native_sources', {})
    settings = spec.get('source_session')
    from .source_session import VERSION as UNIFIED
    ordinary_settings = (settings is None or isinstance(settings,dict) and
                         settings.get('version') == UNIFIED and not settings.get('native_discovery'))
    return (isinstance(sources, dict) and
            any(isinstance(sources.get(v), dict) and sources[v].get('state') == 'enabled'
                for v in ('kalshi', 'polymarket_us')) and
            not spec.get('native_discovery') and ordinary_settings)


def validate_transport(spec):
    """An explicit, exact contract cannot change the budget of an old seal."""
    if 'native_transport' not in spec:
        return None
    value = spec['native_transport']
    if not exact_transport(value):
        raise ValueError('Exact native HTTP transport contract required')
    transport_timeout(spec)
    # Selection remains explicit and therefore changes the specification hash.
    # The transport is shared by ordinary bounded listing and detail requests;
    # transport completion neither reviews terms nor admits identities/books.
    # Retained target-v1 and qualification profiles cannot be extended in place.
    scope = spec.get('native_discovery', {})
    if (spec.get('two_source_qualification') or spec.get('supervised_profile') or
        scope.get('slice') == 'native-reviewed-target-v1' or
        not (enabled(spec) or ordinary_collection(spec))):
        raise ValueError('Revised transport requires supported bounded native collection')
    return dict(value)


def configure_transport(client, spec):
    client.transport_policy = validate_transport(spec)
    client.revised_parse_accounting = spec.get("v1_comparison_policy")=="manual-comparison-2"


def transport_timeout(spec):
    http = spec.get('http', {})
    value = http.get('timeout', 5) if isinstance(http, dict) else None
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 30:
        raise ValueError('Native HTTP timeout must be finite, positive and at most 30 seconds')
    return value


def enabled(spec):
    from .native_selectors import policy, POLICY as DIRECTED
    return (policy(spec) in ('bounded-open-catalog-v3',POLICY,DIRECTED,'polymarket-us-metadata-delivery-v1') or
            exact_transport(spec.get('native_transport')) and ordinary_collection(spec))


def event_detail_id(path):
    match = re.fullmatch(r'/(?:v1/events|trade-api/v2/events)/([A-Za-z0-9_-]{1,160})', path)
    return match.group(1) if match else None


def market_detail_id(path):
    match = re.fullmatch(r'/v1/market/id/([A-Za-z0-9_-]{1,160})', path)
    return match.group(1) if match else None


def envelope(path):
    """Documented native response shape; independent of any selected event."""
    if event_detail_id(path) is not None:return 'event'
    if market_detail_id(path) is not None:return 'market'
    if path == '/trade-api/v2/series/fee_changes':return 'series_fee_change_arr'
    if path == '/trade-api/v2/events/fee_changes':return 'event_fee_changes'
    if re.fullmatch(r'/trade-api/v2/series/[A-Za-z0-9_-]{1,160}',path):return 'series'
    if path in ('/trade-api/v2/events', '/v1/events') or re.fullmatch(r'/v2/leagues/[A-Za-z0-9_-]{1,160}/events', path):return 'events'
    if path in ('/trade-api/v2/markets', '/v1/markets'):return 'markets'
    if path == '/trade-api/v2/milestones':return 'milestones'
    if path == '/v2/leagues':return 'leagues'
    if path in ('/trade-api/v2/account/limits', '/trade-api/v2/account/endpoint_costs'):return 'account'
    return None


def category(path):
    kind = envelope(path)
    return 'discovery' if kind in ('events', 'event', 'leagues','milestones') else 'metadata' if kind in ('markets', 'market','series','series_fee_change_arr','event_fee_changes') else 'account'


def parse(raw, *, limits=None, metrics=None, revised=False):
    """Bound structural expansion before allocation by the JSON decoder.

    No decompression is performed. A byte cap alone permits huge object counts
    or recursion depth. Count structural tokens outside strings before decoding.
    Duplicate object keys and nonfinite numbers cannot supply identities.
    """
    if limits is not None:
        if len(raw) > limits['response_decoded_bytes']:
            raise ValueError('native_decoded_byte_cap')
        try: decoded = raw.decode('utf-8-sig')
        except UnicodeDecodeError: raise ValueError('native_invalid_utf8') from None
    depth = tokens = peak = 0
    depth_cap = 32 if limits is None else limits['json_depth']
    token_cap = 100000 if limits is None else limits['json_structural_tokens']
    quoted = escaped = False
    for c in raw:
        if quoted:
            if escaped: escaped = False
            elif c == 92: escaped = True
            elif c == 34: quoted = False
        elif c == 34: quoted = True
        elif c in (123, 91):
            depth += 1; tokens += 1
            peak = max(peak, depth)
            if depth > depth_cap:
                if metrics is not None: metrics.update(json_structural_tokens=tokens, json_depth_peak=peak)
                raise ValueError('native_json_depth_cap')
        elif c in (125, 93): depth -= 1
        elif c in (44, 58): tokens += 1
        if tokens > token_cap:
            if metrics is not None: metrics.update(json_structural_tokens=tokens, json_depth_peak=peak)
            raise ValueError('native_json_structure_cap')
    # A conservative admission charge complements the independent token/depth
    # caps. It is an accounting estimate, not a claimed allocator/RSS limit.
    # Each separator is not an allocated object. Charge two adjacent
    # separators per typical member at 128 bytes each, plus four raw-byte
    # equivalents for decoding/string storage. Independent token/depth caps
    # and the measured deep-object cap still enforce the unchanged envelope.
    estimate = 4*len(raw) + (128 if revised else 256)*tokens
    if metrics is not None:
        metrics.update(json_structural_tokens=tokens, json_depth_peak=peak,
                       parse_estimated_expansion_bytes=estimate, parse_estimator="structural-charge-2" if revised else "structural-charge-1")
    if limits is not None and estimate > limits['parse_expansion_bytes']:
        raise ValueError('native_parse_expansion_cap')
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result: raise ValueError('native_json_duplicate_key')
            result[k] = v
        return result
    def constant(value): raise ValueError('native_json_nonfinite')
    data = json.loads(raw if limits is None else decoded,
                      object_pairs_hook=pairs, parse_constant=constant)
    if limits is not None:
        # No recursion or unbounded auxiliary traversal queue. JSON has no
        # cycles; repeated scalar objects are charged conservatively each time.
        size = 0
        stack = [iter((data,))]
        while stack:
            try: obj = next(stack[-1])
            except StopIteration:
                stack.pop()
                continue
            size += sys.getsizeof(obj)
            if size > limits['parse_expansion_bytes']:
                raise ValueError('native_parse_expansion_cap')
            if isinstance(obj, dict):
                # Keys are part of the parsed expansion, not only values.
                size += sum(sys.getsizeof(k) for k in obj)
                if size > limits['parse_expansion_bytes']:
                    raise ValueError('native_parse_expansion_cap')
                stack.append(iter(obj.values()))
            elif isinstance(obj, list): stack.append(iter(obj))
        if metrics is not None: metrics['parse_object_bytes'] = size
    return data


def validate_envelope(data, path):
    """Envelope validation never asserts the selected identity or eligibility."""
    if not isinstance(data, dict):
        raise ValueError('native_unexpected_envelope')
    kind = envelope(path)
    if kind is None:raise ValueError('native_unsupported_metadata_route')
    if kind in ('event', 'market','series'):
        if not isinstance(data.get(kind), dict):raise ValueError('native_unexpected_envelope')
    elif kind in ('events', 'markets', 'leagues','milestones','series_fee_change_arr','event_fee_changes'):
        rows = data.get(kind)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError('native_unexpected_envelope')


def query_cap_reasons(spec):
    """Entity/query bounds are local; resident/session/storage bounds are not."""
    return RESPONSE_CAP_REASONS | (frozenset(('native_parse_expansion_cap',
        'native_json_depth_cap','native_json_structure_cap'))
        if spec.get('v1_comparison_policy')=='manual-comparison-2' else frozenset())

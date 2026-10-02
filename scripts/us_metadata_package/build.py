"""Build an inert independently sealed metadata-only package, without any transport."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
TEMPLATES = Path(__file__).resolve().parent
from app.collection.native_approval import digest, implementation
from app.collection.native_payload import TRANSPORT_CONTRACT
from app.collection.continuous import LIMITS
from app.collection.control_binding import validate_identity
from app.collection.us_metadata_diagnostic import (CONTRACT, POLICY, TARGET, REQUEST,
                                                   WINDOW_BASIS, baseline_from_review)
from app.collection.run_spec import preflight

SOURCE = dict(credential_reference='none:public-metadata-no-credential-access',
              entitlement_reference='docs/us-metadata-delivery-repair.md; retained official event-by-ID documentation')
PREDICTION = dict(messages=0, connections=0, frame_bytes=0, session_bytes=8388608,
                  discovery_requests=1, dollar_cap_per_source='0',
                  dollars_per_discovery_request='0', dollars_per_connection='0',
                  plan_evidence='docs/us-metadata-delivery-repair.md')


def encoded(value):
    return (json.dumps(value, indent=2)+'\n').encode()


def authorization(identity, expires):
    """The destination and all exact candidate references derive from one identity."""
    latest_start=(datetime.fromisoformat(expires)-timedelta(seconds=32)).isoformat()
    return (f"I approve exactly one metadata-only Polymarket US public GET to https://gateway.polymarket.us/v1/events/127804, "
            f"with no query parameters, for implementation {identity['implementation_sha256']}, "
            f"specification {identity['spec_sha256']}, attempt {identity['attempt_id']}, "
            f"and destination {identity['output']}. "
            f"The independent diagnostic approval expires at {expires}; activate and dispatch no later than {latest_start}. "
            "Execute only this sealed owned-server/control package once, within its native-http-v2 limits: "
            "2 MiB retained body and decoded input, 4 MiB HTTP plaintext, 16 MiB parse expansion, "
            "and the separately sealed intake, catalog, queue, journal, storage and 256 MiB RSS limits; "
            "15 seconds collection and 32 seconds total supervision including forced cleanup. "
            "No Kalshi request, credentials, books, market sockets, aggregate request, redirects, retries, "
            "pagination, fallback, substitution, budget increase, credits, purchases or trading. "
            "Preserve complete or failed delivery with safe headers, framing, measured bytes, raw provenance and exact reasons. "
            "Admit metadata only after complete framing and whole-document validation. "
            "Assess delivery, JSON, exact identity, material terms, current state and pregame eligibility separately. "
            "A started or closed event may answer delivery without pregame eligibility. "
            "This authorization does not authorize paired books, comparisons, economics, owner validation or commercial validation. "
            "Dispatch consumes this attempt on success, failure, interruption or uncertainty; do not repeat it.\n").encode()


def build(folder, attempt_id=None, *, offline=False, validity_seconds=7200, now=None):
    folder = Path(folder).resolve()
    if folder.exists():
        raise ValueError('Package destination exists; preserve it and choose a fresh destination')
    if type(validity_seconds) is not int or not 33 <= validity_seconds <= 86400:
        raise ValueError('Independent finite diagnostic validity required')
    attempt_id = attempt_id or str(uuid.uuid4())
    if str(uuid.UUID(attempt_id)) != attempt_id:
        raise ValueError('Canonical fresh UUID required')
    prefix = 'OFFLINE-us-metadata-diagnostic-session-' if offline else 'us-metadata-diagnostic-attempt-'
    output = ROOT/'evidence'/(prefix+attempt_id)
    if output.exists():
        raise ValueError('Attempt destination exists; never reuse')
    now = now or datetime.now(timezone.utc)
    if now.utcoffset() != timedelta(0):
        raise ValueError('UTC sealing time required')
    start = now.isoformat()
    expires = (now+timedelta(seconds=validity_seconds)).isoformat()
    latest_start = (now+timedelta(seconds=validity_seconds-32)).isoformat()
    baseline = baseline_from_review(ROOT/'evidence/native-nyi-tor-20260930-v3/review-templates.json')
    spec = dict(mode='real', reference_enabled=False, start_after=start, start_before=latest_start,
                duration=15, discovery_cadence=60, stale_seconds=10,
                sources={'polymarket_us':deepcopy(SOURCE)},
                mapping_revision='native-semantic-review-v1; exact US event-by-ID metadata diagnostic',
                assessment_revisions=dict(pairing=None,lineage=None,fees=None,settlement=None),
                prediction=deepcopy(PREDICTION),
                cleanup='close only owned diagnostic transports; retain bounded journals and safe controls',
                capture_authorization='UNAPPROVED independently sealed metadata-only diagnostic; exact approval required',
                native_sources={v:(dict(state='enabled',environment='production',poll_seconds=60,event_cap=1,market_cap=1)
                                   if v=='polymarket_us' else dict(state='disabled',selected=False))
                                for v in ('kalshi','polymarket_us','novig','prophetx')},
                native_discovery=deepcopy(CONTRACT), native_transport=deepcopy(TRANSPORT_CONTRACT),
                us_metadata_diagnostic=dict(policy=POLICY,target=deepcopy(TARGET),request=deepcopy(REQUEST),
                    historical_baseline=baseline,
                    validity_window=dict(start=start,expires=expires,basis=WINDOW_BASIS)))
    checked = preflight(spec, now=now)
    if not checked['valid']:
        raise ValueError('Diagnostic preflight refused: '+str(checked['errors']))
    impl = implementation()
    core = dict(implementation_sha256=digest(impl), spec_sha256=digest(spec),
                attempt_id=attempt_id, output=str(output))
    limits = dict(duration_seconds=15, overall_wall_seconds=32, operation_wall_seconds=30,
        http_timeout_seconds=5, control_ready_seconds=3, control_start_seconds=6,
        control_get_seconds=1, control_stop_seconds=2, finalization_seconds=5,
        forced_cleanup_seconds=2, http_attempts={'kalshi':0,'polymarket_us':1},
        http_retries=0, redirects=False, pagination=0, fallback=0, automatic_budget_increases=0,
        books=0, market_sockets=0,websocket_connections=0,provider_http_connections=1,
        metadata_http_requests=1,concurrent_http_connections=1,book_sockets=0,
        credential_access=0, aggregate_requests=0, credits=0,purchases=0,trading=0,
        discovery_generations=1, source_body_bytes=8388608,
        native_http_v2=deepcopy(TRANSPORT_CONTRACT),
        overflow_entity_lookahead_bytes=1, overflow_plaintext_callback_bytes=262144,
        fixed_ingress_callback_buffer_bytes=262144, aiohttp_read_buffer_bytes=4096,
        http_header_lines=64,http_header_line_bytes=8190,http_header_field_bytes=8190,
        content_encoding='identity', automatic_decompression=False,
        physical_tls_and_tcp_bytes='outside HTTP-plaintext accounting; no physical-wire claim',
        shared=deepcopy(LIMITS),effective_ingress_bytes=16777216,effective_ingress_records=2048,
        per_source_catalog_retained_bytes=2097152,normalization_inventory_retained_bytes=4128768,
        journal_expanded_bytes=33554432,journal_terminal_reserve_bytes=65536,
        journal_terminal_reserve_records=64,ordinary_journal_records=4032,
        journal_record_estimation_headroom_bytes=2048,
        output_reservation_soft_guard_bytes=125829120,output_journal_estimation_multiplier=3,
        control_input_bytes=65536,control_overflow_lookahead_bytes=1,control_record_bytes=131072,
        extra_control_output_bytes=2097152,owned_server_log_bytes=65536,startup_locations_bytes=65536,
        supervisor_watchdog_seconds=31.5,supervisor_unconditional_exit_seconds=32,
        watchdog_failure_record_reserve_seconds=.5,
        control_log_read_bytes=4096,control_logs_are_sanitized=True)
    values = {'run-spec.json':spec,'attempt.json':dict(**core,status='OFFLINE_REHEARSAL' if offline else 'UNUSED_UNAPPROVED'),
              'limits.json':limits,'implementation.json':impl,
              'request-plan.json':dict(**REQUEST,requests=1,headers={'Accept':'application/json','Accept-Encoding':'identity','Connection':'close'},
                    approval_required=True,no_credentials=True,no_books=True,no_kalshi=True),
              'review-baseline.json':baseline,
              'field-policy.json':dict(policy='native-semantic-review-v1',complete_document_required=True,
                    truncation=False,partial_identity=False,required_fields_discarded=False,
                    delivery_identity_terms_state_and_pregame_are_separate=True,
                    raw_provenance='whole-response hash and retained bytes in durable journal',
                    synthetic_controls='engineering only; no provider evidence'),
              'window.json':dict(prepared_at=start,sealed_at=start,expires_at=expires,latest_activation_and_dispatch=latest_start,
                                validity_seconds=validity_seconds,basis=WINDOW_BASIS,
                                expired_paired_spec_extended=False),
              'authority.json':dict(tracker='/Users/michaelfuscoletti/Desktop/prediction_arb_next_steps.md',
                    tracker_sha256=sha256(Path('/Users/michaelfuscoletti/Desktop/prediction_arb_next_steps.md').read_bytes()).hexdigest(),
                    completed_repair='evidence/us-metadata-delivery-repair-20260930-v1/engineering-seal.json',
                    repair_seal_sha256=sha256((ROOT/'evidence/us-metadata-delivery-repair-20260930-v1/engineering-seal.json').read_bytes()).hexdigest())}
    folder.mkdir(parents=True,exist_ok=False)
    for name,value in values.items():
        (folder/name).write_bytes(encoded(value))
    for name in ('launch.py','control.py','supervise.py','build.py'):
        (folder/name).write_bytes((TEMPLATES/name).read_bytes())
    (folder/'binding-schema.json').write_bytes((ROOT/'scripts/native_package/binding-schema.json').read_bytes())
    (folder/'AUTHORIZATION.txt').write_bytes(authorization(core,expires))
    specification = f"""# Polymarket US metadata-only delivery diagnostic

Status: **UNAPPROVED, UNUSED, UNACTIVATED**. The final destination does not exist.

Implementation: `{core['implementation_sha256']}`. Specification: `{core['spec_sha256']}`.
Attempt: `{attempt_id}`. Destination: `{output}`.
Independent validity: `{start}` through `{expires}` UTC. Latest activation and dispatch: `{latest_start}` UTC, reserving the full 32-second path before expiration. This does not extend the expired paired-book specification.

Exactly one public `GET https://gateway.polymarket.us/v1/events/127804`, no parameters. No Kalshi, credentials, books, market sockets, aggregate, credits, purchases or trading. No redirects, retries, pagination, fallback, substitution or automatic increase. Native-http-v2 explicitly limits retained body and decoded input to 2 MiB, HTTP plaintext to 4 MiB, structural tokens to 100,000, nesting to 32 and conservative parse expansion to 16 MiB. The fixed callback buffer is 256 KiB; a violating callback is separately charged and refused, and entity overflow uses one charged lookahead byte. HTTP plaintext excludes physical TLS/TCP overhead. All other exact finite limits are sealed in limits.json.

Collection lasts at most 15 seconds, including the existing 5-second HTTP timeout. Overall owned-server supervision is at most 32 seconds: 30 seconds of readiness, dispatch, collection, terminal persistence and status handling, plus 2 seconds of forced cleanup. Readiness is 3 seconds, Start's whole-request deadline 6 seconds, control GETs 1 second and Stop 2 seconds. Finalization/settled-state waiting is separately bounded at 5 seconds. Control reads are at most 64 KiB, records at most 128 KiB, sanitized server logs at most 64 KiB. Failure to complete cleanup is retained as failure and prohibits qualification.

Transport completion, whole-document JSON validity, target identity, material-term agreement, current state and pregame eligibility are independent findings. Complete started/closed event metadata can answer delivery while failing pregame eligibility. No incomplete body establishes absence, identity, availability or eligibility. Admission requires complete HTTP framing, peer closure, identity encoding, bounded whole-document parsing, expected singular event envelope and bounded catalog retention. Required fields are never silently removed. The complete retained source is provenance; a prefix is only failure evidence.

Historical review material is a sealed comparison baseline, not current state or current review applicability. Synthetic local responses are engineering controls. A successful live diagnostic leaves fresh paired native books, current review applicability, ordinary paired product verification, economics and owner/commercial validation outstanding.

Run `launch.py` or `control.py --check` for inert checks. Execution requires a separate exact approval.json matching identity.json and approved=true; no approval is created in this final package. Execute only supervise.py after approval. native-control-binding-v1 compares every public identity value and package file hash byte-for-byte before ordinary Start. Activation is durable and distinct from dispatch. Dispatch consumes the allowance before the single Start, including failure/interruption; never reset or reuse. Earlier attempts and seals remain intact.
"""
    (folder/'SPECIFICATION.md').write_text(specification)
    names = [*values,'launch.py','control.py','supervise.py','build.py','binding-schema.json','AUTHORIZATION.txt','SPECIFICATION.md']
    identity = dict(**core,file_hashes={name:sha256((folder/name).read_bytes()).hexdigest() for name in names})
    validate_identity(identity)
    (folder/'identity.json').write_bytes(encoded(identity))
    (folder/'package-seal.json').write_bytes(encoded(dict(package_sha256=digest(identity),identity=identity)))
    (folder/'approval-template.json').write_bytes(encoded(dict(approved=False,**identity)))
    if offline:
        (folder/'approval.json').write_bytes(encoded(dict(approved=True,**identity,
            classification='OFFLINE ISOLATED OWNED-SERVER REHEARSAL ONLY; declared loopback substitution; no provider or credential authority')))
    match = (folder/'AUTHORIZATION.txt').read_bytes() == authorization(identity,expires)
    destination_match = json.loads((folder/'attempt.json').read_text())['output'] == identity['output']
    if not match or not destination_match:
        raise ValueError('Authorization/destination binding mismatch')
    (folder/'binding-verification.json').write_bytes(encoded(dict(authorization_bytes_match=match,
        destination_bytes_match=destination_match,approved=offline,activated=False,dispatched=False,
        destination_exists=output.exists(),package_sha256=digest(identity))))
    return identity


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder')
    parser.add_argument('--offline',action='store_true')
    args=parser.parse_args()
    print(json.dumps(build(args.folder,offline=args.offline),indent=2))

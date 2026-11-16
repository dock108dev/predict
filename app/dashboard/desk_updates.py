"""Change witnesses for the public desk without replaying a publication."""
from datetime import timedelta

from app.comparison.game_phase import LIVE_SECONDS, ODDSLINK_LIVE_SECONDS, PREGAME_SPORTSBOOK_SECONDS
from app.comparison.source_clock import NATIVE_BOOK_MAX_AGE_SECONDS
from app.fees.schedule_lifecycle import revision as fee_revision
from app.storage.store import exact_time, hashed, stamp


def cursor(db, *, at, phase, head, owner, provider, states, settings, epoch, live_enabled):
    """Watch displayed inputs, leaving routine book confirmations to expiry."""
    pregame = phase == 'pregame'
    latest = exact_time(at.isoformat())
    native_since = exact_time((at - timedelta(seconds=NATIVE_BOOK_MAX_AGE_SECONDS)).isoformat())
    aggregate_age = PREGAME_SPORTSBOOK_SECONDS if pregame else max(LIVE_SECONDS, ODDSLINK_LIVE_SECONDS)
    aggregate_since = exact_time((at - timedelta(seconds=aggregate_age)).isoformat())

    if pregame and provider == 'sportsgameodds' and (owner.get('config') or {}).get('direct_novig_enabled') is False:
        # The direct reader revisits committed offers on every list request.
        # Watch the indexed receipt watermarks and the much smaller sporting
        # closure set, rather than joining and decoding the entire slate just
        # to decide whether the browser should read it again.
        witness = db.execute("""
            SELECT (SELECT max(received_order) FROM current_offer_storage
                    WHERE native_book_id IS NOT NULL AND received_order BETWEEN %s AND %s) native,
                   (SELECT max(source_order) FROM current_offer_storage
                    WHERE native_book_id IS NULL AND source_order BETWEEN %s AND %s) aggregate,
                   (SELECT max(received_order) FROM sgo_event_evidence
                    WHERE kind='frame' AND received_order BETWEEN %s AND %s) references,
                   (SELECT md5(string_agg(concat_ws(':',id,revision), ',' ORDER BY id))
                    FROM current_event WHERE scheduled_start::timestamptz BETWEEN %s AND %s
                      AND (facts#>>'{status,status}' IN ('cancelled','canceled','postponed','delayed','suspended')
                           OR facts#>>'{status,ended}'='true')) closures
            """, (native_since, latest, aggregate_since, latest, aggregate_since, latest, at, at + timedelta(hours=72))
        ).fetchone()
    else:
        witness = db.execute(
            """WITH recent AS (
                   SELECT contract_id,price_dependency,revision,native_book_id
                   FROM current_offer_storage
                   WHERE native_book_id IS NOT NULL AND received_order BETWEEN %s AND %s
                   UNION ALL
                   SELECT contract_id,price_dependency,revision,native_book_id
                   FROM current_offer_storage
                   WHERE native_book_id IS NULL AND source_order BETWEEN %s AND %s
               )
               SELECT (
                   SELECT md5(string_agg(concat_ws(':',o.contract_id,o.price_dependency,o.revision,c.revision,e.revision,b.depth_revision),
                       ',' ORDER BY o.contract_id))
                   FROM recent o
                   JOIN current_contract_storage c ON c.id=o.contract_id
                   JOIN current_event e ON e.id=c.event_id
                   LEFT JOIN native_book_revision b ON b.id=o.native_book_id AND b.is_current
                   WHERE (o.native_book_id IS NULL OR (
                       b.state='active' AND b.sync='synchronized'
                       AND greatest(b.source_order, extract(epoch FROM (b.confirmation->>'confirmed_at')::timestamptz))
                            BETWEEN %s AND %s))
                     AND (e.scheduled_start::timestamptz > %s) = %s
                     AND e.scheduled_start::timestamptz <= %s
               ) offers, (
                   SELECT md5(string_agg(concat_ws(':',event_id,received_order), ',' ORDER BY event_id))
                   FROM sgo_event_evidence
                   WHERE kind='frame' AND received_order BETWEEN %s AND %s
               ) references""",
            (native_since, latest, aggregate_since, latest, native_since, latest, at, pregame, at + timedelta(hours=72),
             aggregate_since, latest),
        ).fetchone()
    return hashed([
        head['generation'], phase, live_enabled, epoch, settings['revision'], {key: str(value) for key, value in witness.items()},
        fee_revision(owner.get('fee_lifecycle')), owner.get('fee_products'),
        owner.get('active'), owner.get('healthy'), owner.get('global_stopped'), owner.get('paused_sources'),
        owner.get('calculations', {}).get('board'), provider,
        {key: [state.get('state'), state.get('reason_code'), state.get('observed_sports')]
         for key, state in states.items()},
    ])


def refresh_at(page, at):
    """First visible pricing, calculation, or kickoff boundary."""
    deadlines = []
    for row in page.get('rows', []):
        if row.get('withdrawn'):
            continue
        deadlines.append(row.get('start_at'))
        for offer in row.get('offers', []):
            if offer.get('current'):
                deadlines.extend((offer.get('current_until'), offer.get('calculation_current_until')))
        deadlines.extend(pair.get('calculation_current_until') for pair in row.get('pairs', ()))
        if page.get('phase') == 'pregame':
            reference = row.get('sportsbook_reference') or {}
            deadlines.append(reference.get('current_until'))
    future = [stamp(deadline) for deadline in deadlines if deadline and stamp(deadline) > at]
    return min(future).isoformat() if future else None

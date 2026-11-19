"""Fingerprint only public authority that can invalidate a frozen cohort."""

from .pregame_known_withdrawals import phase_closed


def authority_state(db, at):
    # Positive public prices are never borrowed by a cohort. Hash negative set
    # membership (including its removal), not every public calculation revision.
    # The sparse SGO indexes avoid fetching all available quote bodies.
    return db.execute(
        """WITH event_scope AS MATERIALIZED (
          SELECT id FROM current_event
          UNION SELECT known.id FROM public.current_event known
            JOIN (SELECT DISTINCT event_id FROM current_sgo_reference) frozen
              ON known.provider='sportsgameodds' AND known.native_event_id=frozen.event_id
        ), reference_scope AS MATERIALIZED (
          SELECT id FROM current_sgo_reference
          UNION SELECT sgo_quote_id FROM current_offer_storage WHERE sgo_quote_id IS NOT NULL
        ), known_events AS MATERIALIZED (
          SELECT known.id,known.scheduled_start::timestamptz AS start_at,"""
        + phase_closed("known")
        + """ AS closed FROM public.current_event known JOIN event_scope frozen USING(id)
        ), negatives AS (
          SELECT jsonb_build_array('contract',known.id)::text AS token
            FROM public.current_contract_storage known JOIN current_contract frozen USING(id)
            WHERE known.active=false
          UNION ALL SELECT jsonb_build_array('offer',known.contract_id)::text
            FROM public.current_offer_storage known JOIN current_contract frozen
              ON frozen.id=known.contract_id WHERE known.facts->>'state'='unavailable'
          UNION ALL SELECT jsonb_build_array('reference',known.id)::text
            FROM public.sgo_quote_revision known JOIN reference_scope frozen USING(id)
            WHERE known.is_current
              AND (known.facts->'available'='false'::jsonb
                OR known.facts->'provider_available'='false'::jsonb)
          UNION ALL SELECT jsonb_build_array('line',quote_id)::text
            FROM public.sgo_line_presence known JOIN reference_scope frozen
              ON frozen.id=known.quote_id WHERE known.expired
          UNION ALL SELECT jsonb_build_array('event',id)::text FROM known_events
            WHERE closed OR start_at<=%s
          UNION ALL SELECT jsonb_build_array('work',provider,native_event_id)::text
            FROM current_pregame_work
        ) SELECT encode(sha256(convert_to(COALESCE((
            SELECT string_agg(token,E'\\n' ORDER BY token) FROM negatives),''),'UTF8')),'hex')
            AS fingerprint,
          (SELECT min(start_at) FROM known_events WHERE start_at>%s) AS next
        """,
        (at, at),
    ).fetchone()

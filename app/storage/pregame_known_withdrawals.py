"""Negative current authority can invalidate a retained cohort, never replace it.

Missing public rows supply no new authority. These checks preserve the cohort's
original prices and clocks while refusing known withdrawal or sporting closure.
"""


def phase_closed(alias):
    return f"""({alias}.facts->'status' @> '{{"live":true}}'::jsonb
      OR {alias}.facts->'status' @> '{{"started":true}}'::jsonb
      OR {alias}.facts->'status' @> '{{"ended":true}}'::jsonb
      OR {alias}.facts->'status' @> '{{"completed":true}}'::jsonb
      OR {alias}.facts->'status' @> '{{"finalized":true}}'::jsonb
      OR {alias}.facts->'status' @> '{{"cancelled":true}}'::jsonb
      OR {alias}.facts->'status' @> '{{"suspended":true}}'::jsonb
      OR {alias}.facts->'status' @> '{{"delayed":true}}'::jsonb
      OR COALESCE({alias}.facts#>>'{{status,status}}','') IN
        ('cancelled','final','suspended','started','delayed'))"""


def reference_known_unavailable(identity):
    return f"""(EXISTS(SELECT 1
        FROM public.sgo_quote_revision known_ref
        WHERE known_ref.id={identity} AND known_ref.is_current
          AND (known_ref.facts->'available'='false'::jsonb
            OR known_ref.facts->'provider_available'='false'::jsonb))
      OR EXISTS(SELECT 1 FROM public.sgo_line_presence known_line
        WHERE known_line.quote_id={identity} AND known_line.expired))"""


# Both readers name their frozen price/contract/offer aliases p/c/o.
ROW_GUARDS = (
    """NOT EXISTS(SELECT 1 FROM public.current_contract_storage known_contract
      WHERE known_contract.id=c.id AND known_contract.active=false)""",
    """NOT EXISTS(SELECT 1 FROM public.current_offer_storage known_offer
      WHERE known_offer.contract_id=c.id AND known_offer.facts->>'state'='unavailable')""",
    """NOT EXISTS(SELECT 1 FROM public.sgo_line_presence known_line
      WHERE known_line.quote_id=o.sgo_quote_id AND known_line.expired)""",
    "NOT COALESCE((SELECT known_event.scheduled_start::timestamptz<=%s OR "
    + phase_closed("known_event")
    + " FROM public.current_event known_event WHERE known_event.id=c.event_id LIMIT 1),false)",
    "NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p.payload#>'{reference,prices}') frozen_ref WHERE "
    + reference_known_unavailable("frozen_ref->>'input_id'")
    + ")",
)

BOOK_GUARD = (
    "NOT "
    + reference_known_unavailable("q.id")
    + " AND NOT COALESCE((SELECT "
    + phase_closed("known_book_event")
    + " FROM public.current_event known_book_event WHERE known_book_event.provider='sportsgameodds' AND known_book_event.native_event_id=q.event_id LIMIT 1),false)"
)

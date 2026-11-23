"""Durable opt-in fee calculations, with an explicit captured zero-fee model.

Missing settings mean fees are excluded. Missing markers on historical fee
inputs mean the original fee calculation remains enabled for reproduction.
"""

from copy import deepcopy
from fractions import Fraction

from psycopg import sql
from psycopg.types.json import Jsonb

from app.storage.store import hashed

VERSION = 'predict-fee-mode-1'
KEY = 'predict:fee_mode'
SCHEMAS = ('public', 'pregame_monitor', 'pregame_live', 'pregame_combined')


def state(enabled=False, generation=0):
    if type(enabled) is not bool or type(generation) is not int or generation < 0:
        raise ValueError('fee_mode_state_invalid')
    return dict(version=VERSION, enabled=enabled,
        revision=hashed([VERSION, enabled, generation]),
        assumption='Fees included using the existing fee model.' if enabled else
            'Fees excluded: calculations assume $0 fees.')


def read(db):
    row = db.execute('SELECT state FROM public.public_fee_schedule WHERE venue=%s', (KEY,)).fetchone()
    if not row:
        return state()
    saved = row['state'].get('fee_mode')
    if not isinstance(saved, dict) or set(saved) != {'enabled', 'generation'}:
        raise ValueError('fee_mode_state_invalid')
    return state(saved['enabled'], saved['generation'])


def set_enabled(db, enabled):
    """Persist and invalidate generated reads atomically; never acquire prices."""
    if type(enabled) is not bool:
        raise ValueError('fee_mode_enabled_must_be_boolean')
    from app.storage.current_rows import LOCK

    with db.transaction():
        db.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
        row = db.execute('SELECT state FROM public.public_fee_schedule WHERE venue=%s FOR UPDATE', (KEY,)).fetchone()
        previous = read(db)
        if previous['enabled'] == enabled:
            return dict(previous, queued_events=0)
        generation = row['state']['fee_mode']['generation']+1 if row else 1
        db.execute('''INSERT INTO public.public_fee_schedule(venue,state) VALUES(%s,%s)
            ON CONFLICT(venue) DO UPDATE SET state=excluded.state''',
            (KEY, Jsonb(dict(fee_mode=dict(enabled=enabled, generation=generation)))))
        queued = db.execute('''INSERT INTO public.current_pregame_work(provider,native_event_id)
            SELECT DISTINCT provider,native_event_id FROM public.current_event
            ON CONFLICT(provider,native_event_id) DO UPDATE SET
                revision=current_pregame_work.revision+1,admitted_at=clock_timestamp(),error=NULL
            RETURNING provider''').fetchall()
        # These are bounded working projections, not immutable research records.
        # Cohort queues have no recovery consumer; their next captured projection
        # must replace this expired result rather than inherit a stuck queue row.
        for schema in SCHEMAS:
            for table in ('current_pregame_calculation', 'current_pregame_price'):
                db.execute(sql.SQL('UPDATE {}.{} SET valid_until=LEAST(valid_until,clock_timestamp())').format(
                    sql.Identifier(schema), sql.Identifier(table)))
            db.execute(sql.SQL('''UPDATE {}.current_pregame_revision
                SET revision=revision+1,committed_at=clock_timestamp() WHERE singleton''').format(sql.Identifier(schema)))
        return dict(state(enabled, generation), queued_events=len(queued))


def mode_for_fee(fee):
    captured = fee.get('fee_mode') or (fee.get('evidence') or {}).get('fee_mode')
    if captured is None:
        return dict(version='legacy-fee-calculation', enabled=True,
            revision='legacy-fees-included', assumption='Fees included in the original captured calculation.')
    if not isinstance(captured, dict) or type(captured.get('enabled')) is not bool:
        raise ValueError('fee_mode_input_invalid')
    return deepcopy(captured)


def assumed_zero(value):
    return mode_for_fee(value)['enabled'] is False


def zero_fee(record, mode):
    if mode.get('enabled') is not False:
        raise ValueError('zero_fee_requires_disabled_mode')
    return dict(available=True, classification='assumed_zero', reason=None,
        fee_mode=deepcopy(mode), evidence=dict(version=VERSION, fee_mode=deepcopy(mode),
            basis='owner_selected_zero_fee_assumption'),
        profile='fees_disabled', liquidity_role='taker', fill_count=1,
        quantity='1', quantity_unit='normalized_claim', trade_fee_usd='0',
        fee_payment='at_fill', fee_cashflows=dict(at_fill_usd='0'),
        assumptions=[mode['assumption']], venue=record['quote']['venue'])


def zero_order(fee):
    """The normal price/quantity owner still determines purchased cashflows."""
    if not assumed_zero(fee):
        raise ValueError('zero_fee_requires_disabled_mode')
    mode = mode_for_fee(fee)
    trace = [dict(operation='fees_excluded', version=VERSION, revision=mode['revision'])]
    def evaluated(_levels, _stake):
        return Fraction(0), Fraction(0), {}, deepcopy(trace)
    return evaluated, deepcopy(fee.get('evidence') or {}), Fraction(0)

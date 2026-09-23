"""Documented two-grid sensitivity for known complete Kalshi fills, not net profit."""
from copy import deepcopy
from decimal import Decimal, localcontext
from .engine import calculate

def calculate_envelope(context,registry=None,*,execution_split_known=False):
    base=dict(available=False,kind='conditional_entry_fee_precision_envelope',lower=None,upper=None,
              qualification='Only documented exchange entry fees for supplied complete fills; excludes unverified account/settlement charges. Not historical applicability or net qualification.')
    if context.get('venue')!='kalshi' or not execution_split_known or context.get('complete_order_history') is not True:
        return dict(base,reason='Exact complete fill allocation required; aggregated book depth is insufficient')
    values=[];audits=[]
    for precision in ('0.0001','0.01'):
        c=deepcopy(context);c['balance_precision']=precision
        result=calculate(c,registry)
        if result['unsupported'] or result['entry_fees'] is None:
            return dict(base,reason='Other fee inputs unsupported',unsupported=result['unsupported'])
        # Deduct the engine's separately retained rounding refunds via balance debit.
        with localcontext() as arithmetic:
            arithmetic.prec=100
            values.append(Decimal(result['entry_balance_debit'])-Decimal(result['entry_notional']))
        audits.append(result)
    return dict(base,available=True,lower=str(min(values)),upper=str(max(values)),scenarios=audits,
                reason='Envelope over both documented balance grids; account precision may remain unknown only for this conditional entry-fee bound')

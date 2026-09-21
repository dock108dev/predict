"""Session availability is separate from unchanged E3/E4 arithmetic."""
from datetime import datetime


def validate_context(context,cutoff):
    if context is None:return False # Older engineering attempts lack this evidence.
    if context['policy']!='e6-session-health-1' or context['cutoff']!=cutoff:raise ValueError('session health cutoff mismatch')
    if set(context['health'])!={'kalshi','polymarket_us','reference','discovery'}:raise ValueError('session source scope mismatch')
    for source,h in context['health'].items():
        if h.get('detected_at') and datetime.fromisoformat(h['detected_at'])>datetime.fromisoformat(cutoff):raise ValueError('future source health knowledge')
        if h['state']=='connected':
            at=h.get('last_success_at')
            if not at or not 0<=(datetime.fromisoformat(cutoff)-datetime.fromisoformat(at)).total_seconds()<=(60 if source=='discovery' else 30):
                raise ValueError('connected source health lacks fresh receipt evidence')
    eligible=all(h['state']=='connected' for h in context['health'].values())
    if eligible!=context['eligible']:raise ValueError('session eligibility differs from retained source health')
    return eligible

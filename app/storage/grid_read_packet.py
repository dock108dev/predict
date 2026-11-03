"""Lossless publication-time encoding for the existing immutable grid capture."""
from .store import encoded
from .slate_reads import CapturedReads


def pack(row, grid):
    # An Odds lease selects observation Originals only. Financial unit copies
    # have independent immutable packets/leases and must not be duplicated for
    # every source-price refresh. Keep the parent selected frame exact.
    omitted={'boards','result_units','result_unit_inventory','result_unit_attempts',
        'result_inventory_dependencies','result_inventory_accounting','dashboard_boards'}
    facts={k:v for k,v in row['facts'].items() if k not in omitted}
    value={k:row[k] for k in ('game_key','dependency_revision','economic_revision','calculated_at')}
    value.update(_facts_text=encoded(facts).decode(),_board_text=encoded(grid).decode())
    return CapturedReads.freeze(encoded(value))

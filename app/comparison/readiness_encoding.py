"""Lossless readiness transport; logical identities never depend on this encoding."""
from copy import deepcopy
from .current_dependencies import encoded, encoded_size

ENCODING = 'readiness-shared-fields-1'
TABLES = ('instruments', 'pairs', 'scopes')


def compact(frame):
    if frame is None:
        return None
    if 'field_encoding' in frame:
        raise ValueError('readiness_encoding_already_compact')
    counts, values = {}, {}
    for name in TABLES:
        for row in frame.get(name, []):
            for value in row.values():
                body = encoded(value)
                if len(body) >= 32:
                    counts[body] = counts.get(body, 0) + 1
                    values[body] = value
    pool = [values[body] for body in sorted(counts) if counts[body] > 1]
    indexes = {encoded(value): i for i, value in enumerate(pool)}
    out = {key: value for key, value in frame.items() if key not in TABLES}
    out.update(field_encoding=ENCODING, field_pool=pool)
    for name in TABLES:
        keys = sorted({key for row in frame.get(name, []) for key in row})
        key_ids = {key: i for i, key in enumerate(keys)}
        rows = []
        for row in frame.get(name, []):
            literals, refs = [], []
            for key, value in row.items():
                index = indexes.get(encoded(value))
                if index is None:
                    literals.append([key_ids[key], value])
                else:
                    refs.append([key_ids[key], index])
            rows.append([literals, refs])
        out[name] = dict(keys=keys, rows=rows)
    return out


def expand(frame):
    if frame is None or 'field_encoding' not in frame:
        return frame
    if frame['field_encoding'] != ENCODING or not isinstance(frame.get('field_pool'), list):
        raise ValueError('readiness_field_reference_invalid')
    pool = frame['field_pool']
    out = {key: value for key, value in frame.items() if key not in (*TABLES, 'field_encoding', 'field_pool')}
    for name in TABLES:
        table = frame[name]; keys = table['keys']
        if len(set(keys)) != len(keys) or any(not isinstance(k, str) for k in keys):
            raise ValueError('readiness_field_reference_invalid')
        rows = []
        for literals, refs in table['rows']:
            row = {}
            for is_ref, items in ((False, literals), (True, refs)):
                for key, value in items:
                    if type(key) is not int or not 0 <= key < len(keys) or keys[key] in row:
                        raise ValueError('readiness_field_reference_invalid')
                    if is_ref:
                        if type(value) is not int or not 0 <= value < len(pool):
                            raise ValueError('readiness_field_reference_invalid')
                        value = pool[value]
                    row[keys[key]] = deepcopy(value)
            rows.append(row)
        out[name] = rows
    return out


def transport_size(frame):
    return encoded_size(compact(frame))

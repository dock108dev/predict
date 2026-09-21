"""Conservative text keys: never strip digits, accents, or join word boundaries."""
import re
import unicodedata


def name_key(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError('name must be text')
    value = unicodedata.normalize('NFC', value).casefold()
    # Periods in abbreviations and apostrophe typography are insignificant.
    value = value.replace('.', '').replace('’', "'")
    value = re.sub(r'[-‐‑–—]', ' ', value)
    return ' '.join(value.split())

"""Personal appearance contract shared by persistence and generated browser metadata.

Palette identity remains a bounded label: saved/custom colors are authoritative,
so older labels need no owner-data migration when the starter catalog changes.
"""

from copy import deepcopy
import re

PALETTES = (
    {"id": "prism", "name": "Prism", "primary": "#b69ae8", "secondary": "#edb8dc"},
    {
        "id": "midnight",
        "name": "Midnight",
        "primary": "#8299d7",
        "secondary": "#c7d5f6",
    },
    {"id": "cobalt", "name": "Cobalt", "primary": "#4779eb", "secondary": "#d4e3ff"},
    {"id": "slate", "name": "Slate", "primary": "#849bab", "secondary": "#d9e1e5"},
    {"id": "teal", "name": "Teal", "primary": "#3ca5a7", "secondary": "#b7e3d5"},
    {"id": "emerald", "name": "Emerald", "primary": "#3c9a70", "secondary": "#d7e9ad"},
    {"id": "pine", "name": "Pine", "primary": "#568170", "secondary": "#ded2a6"},
    {
        "id": "burgundy",
        "name": "Burgundy",
        "primary": "#a04468",
        "secondary": "#e7c6a4",
    },
    {"id": "rose", "name": "Rose", "primary": "#d37d9d", "secondary": "#e8d0f2"},
    {"id": "coral", "name": "Coral", "primary": "#dc846c", "secondary": "#f5dfb2"},
    {"id": "amber", "name": "Amber", "primary": "#c68b38", "secondary": "#ece1c6"},
    {"id": "gold", "name": "Gold", "primary": "#c4ad46", "secondary": "#e8e0a6"},
    {"id": "crimson", "name": "Crimson", "primary": "#c84b55", "secondary": "#f0d0c2"},
    {"id": "ice", "name": "Ice", "primary": "#79b7d7", "secondary": "#c6e5e9"},
    {"id": "mono", "name": "Monochrome", "primary": "#b5b2bd", "secondary": "#e4e0e9"},
)
MODES = ("dark", "light", "system")
COLOR_PATTERN = r"#[a-fA-F0-9]{6}"
PALETTE_PATTERN = r"[a-z]{1,20}"
DEFAULT = dict(
    palette=PALETTES[0]["id"],
    primary=PALETTES[0]["primary"],
    secondary=PALETTES[0]["secondary"],
    appearance="dark",
)


def catalog():
    return deepcopy(
        dict(
            default=DEFAULT,
            palettes=PALETTES,
            modes=MODES,
            color_pattern=COLOR_PATTERN,
            palette_pattern=PALETTE_PATTERN,
        )
    )


def validate(value):
    if (
        not isinstance(value, dict)
        or set(value) != set(DEFAULT)
        or value.get("appearance") not in MODES
        or not isinstance(value.get("palette"), str)
        or not re.fullmatch(PALETTE_PATTERN, value["palette"])
        or any(
            not isinstance(value.get(key), str)
            or not re.fullmatch(COLOR_PATTERN, value[key])
            for key in ("primary", "secondary")
        )
    ):
        raise ValueError("Choose an appearance and two six-digit colors")

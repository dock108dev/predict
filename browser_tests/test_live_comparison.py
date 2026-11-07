"""Run the actual L03/L04 bundles without network, owner SQL or provider traffic."""

import asyncio
from browser_tests.l03_current import main as controller_journey
from browser_tests.l04_interface import main as presentation_journey


def test_live_controller(tmp_path):
    asyncio.run(controller_journey(tmp_path))


def test_compact_drawer(tmp_path):
    asyncio.run(presentation_journey(tmp_path))

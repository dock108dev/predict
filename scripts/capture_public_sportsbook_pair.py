"""Capture one public pregame board for the running sportsbook estimate."""
import argparse
import asyncio

from aiohttp import ClientSession, ClientTimeout

from app.collection.public_sportsbook_worker import fetch_board, store_capture
from app.collection.runtime_status import read_runtime
from app.comparison.public_sportsbook_estimate import SPORTS, allowed
from app.storage.store import ROOT, connect


def collection_active():
    with connect() as db:
        return allowed(read_runtime(db))


async def capture(league):
    async with ClientSession(timeout=ClientTimeout(total=8), trust_env=True) as client:
        wire, reason, _ = await fetch_board(client, league)
    if wire is None:
        raise ValueError(reason)
    if not collection_active():
        raise ValueError('Collection authority changed before capture')
    store_capture(ROOT, league, wire)
    print(f'{league}: {len(wire["fixtures"])} board fixtures captured at {wire["received_at"]}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('league', choices=SPORTS)
    args = parser.parse_args()
    if not collection_active():
        parser.error('Current collection must be active with the aggregate source enabled')
    asyncio.run(capture(args.league))


if __name__ == '__main__':
    main()

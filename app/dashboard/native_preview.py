"""Idle ordinary Predict product with explicit B3 spec/approval; never auto-Start."""
import argparse
import json
from pathlib import Path
from aiohttp import web
from app.dashboard.coverage_owner import CoverageOwner
from app.dashboard.multi_game_server import create_app
from app.collection.venue_access import ENDPOINTS


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spec',type=Path,required=True);p.add_argument('--approval',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--port',type=int,default=8795)
    a=p.parse_args()
    owner=CoverageOwner(a.output/'legacy',pilot_output=a.output,endpoints=ENDPOINTS,product_mode=True,
        native_approval_path=a.approval,spec_factory=lambda:json.loads(a.spec.read_text()))
    web.run_app(create_app(owner=owner,sessions={}),host='127.0.0.1',port=a.port)

if __name__=='__main__':main()

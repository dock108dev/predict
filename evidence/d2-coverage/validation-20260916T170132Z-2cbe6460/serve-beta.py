"""Explicit repaired-validation-attempt configuration; unchanged D2 collector, idle startup."""
import sys
from pathlib import Path
sys.path.insert(0, '/Users/michaelfuscoletti/Desktop/prediction-arb')
import psycopg
from aiohttp import web
from app.dashboard.opportunity_board import create_app
from app.dashboard.coverage_owner import CoverageOwner
from app.dashboard.multi_game import OUTPUT

def deny(*args, **kwargs):
    raise PermissionError('File-only board forbids database connections')
psycopg.connect = psycopg.Connection.connect = psycopg.AsyncConnection.connect = deny
owner = CoverageOwner(OUTPUT, pilot_output=Path('/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/d2-coverage/validation-20260916T170132Z-2cbe6460'))
web.run_app(create_app(owner=owner), host='127.0.0.1', port=8783, access_log=None)

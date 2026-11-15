"""Load repository CI tools without invoking their command-line entry points."""

import importlib.util
from pathlib import Path
import sys


def load(name):
    scripts = Path(__file__).resolve().parents[1] / "scripts/ci"
    spec = importlib.util.spec_from_file_location(name, scripts / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(scripts))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(scripts))
    return module

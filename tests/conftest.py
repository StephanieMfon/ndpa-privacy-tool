"""Shared test setup: lets any test import the helper modules that live in tests/unit (web_seed, builders)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "unit"))

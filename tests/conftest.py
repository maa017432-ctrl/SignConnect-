"""Shared pytest configuration for SignConnect tests.

Each test module that needs a Flask test client should define its own ``app``
/ ``client`` fixture.  This module only ensures the project root is on
``sys.path`` so that ``from core.xxx import ...`` works in every test.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

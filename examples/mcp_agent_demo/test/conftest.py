"""Test configuration for the standalone demo."""

import sys
from pathlib import Path


DEMO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = DEMO_ROOT / "tools"

for path in (DEMO_ROOT, TOOLS_ROOT):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)

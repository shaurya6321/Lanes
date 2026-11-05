"""Re-export of lanes.hooks.adapters, kept here to match the brief's layout.

The adapter normalizes Claude Code (and later Codex) hook payloads and outputs.
Edit lanes/hooks/adapters.py, not this file.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lanes.hooks.adapters import *  # noqa: E402,F401,F403

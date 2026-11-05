"""Hook wrapper for lanes.hooks.pre_tool_guard; the logic lives in lanes/hooks/pre_tool_guard.py.

Runs as `uv run --project <repo> python hooks/pre_tool_guard.py` inside the Lanes repo.
Repos that adopt Lanes call `lanes hook <name>` instead (see lanes init).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lanes.hooks.pre_tool_guard import main  # noqa: E402

raise SystemExit(main())

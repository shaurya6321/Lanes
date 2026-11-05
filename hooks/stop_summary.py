"""Hook wrapper for lanes.hooks.stop_summary; the logic lives in lanes/hooks/stop_summary.py.

Runs as `uv run --project <repo> python hooks/stop_summary.py` inside the Lanes repo.
Repos that adopt Lanes call `lanes hook <name>` instead (see lanes init).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lanes.hooks.stop_summary import main  # noqa: E402

raise SystemExit(main())

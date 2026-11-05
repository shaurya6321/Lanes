"""Hook wrapper for lanes.hooks.session_start; the logic lives in lanes/hooks/session_start.py.

Runs as `uv run --project <repo> python hooks/session_start.py` inside the Lanes repo.
Repos that adopt Lanes call `lanes hook <name>` instead (see lanes init).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lanes.hooks.session_start import main  # noqa: E402

raise SystemExit(main())

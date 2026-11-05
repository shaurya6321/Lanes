"""Hook wrapper for lanes.hooks.post_tool_notice; the logic lives in lanes/hooks/post_tool_notice.py.

Runs as `uv run --project <repo> python hooks/post_tool_notice.py` inside the Lanes repo.
Repos that adopt Lanes call `lanes hook <name>` instead (see lanes init).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lanes.hooks.post_tool_notice import main  # noqa: E402

raise SystemExit(main())

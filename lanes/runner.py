"""How Lanes is installed in a repo, and how to spell the `lanes` command in messages.

- global ("lanes"):   `uv tool install git+...`; hooks run `lanes hook <name>`.
- local ("uv-local"): Lanes is a dev dependency of the repo; hooks run
                      `uv run --project <repo> lanes hook <name>` and nothing is on PATH,
                      so every command Claude or a person is told to run says `uv run lanes ...`.
- dev ("uv-dev"):     only for the Lanes repo itself; hooks run the in-repo wrappers.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

GLOBAL, LOCAL, DEV = "lanes", "uv-local", "uv-dev"
RUNNERS = (GLOBAL, LOCAL, DEV)


def prefix_for(runner: str) -> str:
    return "uv run lanes" if runner == LOCAL else "lanes"


def lanes_cmd(root: Path | str | None = None) -> str:
    """`uv run lanes` when this process runs from the repo's own environment, else `lanes`.

    `LANES_CMD` overrides the detection (used by tests, or to force a spelling).
    """
    override = os.environ.get("LANES_CMD", "").strip()
    if override:
        return override
    if root is not None:
        try:
            prefix, repo = Path(sys.prefix).resolve(), Path(root).resolve()
            if prefix == repo or repo in prefix.parents:
                return "uv run lanes"
        except OSError:
            pass
    return "lanes"

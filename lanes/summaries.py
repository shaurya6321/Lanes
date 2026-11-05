"""Session summaries: `.lanes/summaries/<member>-<YYYY-MM-DD>.md`, one section per session.

    ## 2026-11-05 14:22 UTC · shaurya · T1
    <!-- lanes-session:<session-id> updated:2026-11-05T14:22:33Z -->
    - Why: Added cart totals and documented them in cart-api.
    - Files: src/api/cart/total.py, .lanes/contracts/cart-api.md
    - Open: Should totals include tax?

Claude Code fires Stop after every turn, so the section for a session is
rewritten in place (upsert) instead of appended each time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .redact import redact

SUMMARIES_DIR = Path(".lanes") / "summaries"
_MARKER = re.compile(r"<!-- lanes-session:(?P<sid>\S+) updated:(?P<ts>\S+) -->")
MAX_FILES_SHOWN = 6


@dataclass
class Section:
    member: str
    session_id: str
    updated: datetime
    lines: list[str]  # heading first, marker excluded


def parse_ts(text: str) -> datetime | None:
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _split_sections(text: str) -> list[list[str]]:
    sections: list[list[str]] = []
    for line in text.splitlines():
        if line.startswith("## "):
            sections.append([line])
        elif sections:
            sections[-1].append(line)
    return sections


def read_sections(root: Path) -> list[Section]:
    folder = root / SUMMARIES_DIR
    if not folder.is_dir():
        return []
    out: list[Section] = []
    for path in folder.glob("*.md"):
        member = path.stem.rsplit("-", 3)[0] if re.search(r"-\d{4}-\d{2}-\d{2}$", path.stem) else path.stem
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for block in _split_sections(text):
            marker = next((m for m in map(_MARKER.search, block) if m), None)
            ts = parse_ts(marker.group("ts")) if marker else None
            if not marker or not ts:
                continue
            lines = [ln for ln in block if not _MARKER.search(ln) and ln.strip()]
            out.append(Section(member, marker.group("sid"), ts, lines))
    return sorted(out, key=lambda s: s.updated)


def render_section(member: str, session_id: str, task: str | None, why: str, files: list[str], open_q: str, now: datetime) -> str:
    shown = files[:MAX_FILES_SHOWN]
    more = f" (+{len(files) - len(shown)} more)" if len(files) > len(shown) else ""
    lines = [
        f"## {now.strftime('%Y-%m-%d %H:%M')} UTC · {member} · {task or '-'}",
        f"<!-- lanes-session:{session_id} updated:{now.strftime('%Y-%m-%dT%H:%M:%SZ')} -->",
        f"- Why: {why or '(no summary given)'}",
        f"- Files: {', '.join(shown) + more if shown else 'none'}",
        f"- Open: {open_q or 'none'}",
    ]
    return redact("\n".join(lines)) + "\n"


def _content(block: list[str]) -> list[str]:
    """A section without its heading time and `updated:` marker, for 'did anything change?'."""
    heading = block[0].split(" UTC · ", 1)[-1] if block else ""
    return [heading] + [ln for ln in block[1:] if not _MARKER.search(ln) and ln.strip()]


def upsert(root: Path, member: str, session_id: str, section: str, now: datetime) -> Path:
    """Insert or replace this session's section. Writes nothing if only the timestamp would change."""
    path = root / SUMMARIES_DIR / f"{member}-{now.strftime('%Y-%m-%d')}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.exists() else f"# Session summaries · {member} · {now.strftime('%Y-%m-%d')}\n"
    header, blocks = _header_and_blocks(text)
    marker = f"<!-- lanes-session:{session_id} "
    new_block = section.rstrip("\n").splitlines()
    replaced = False
    for i, block in enumerate(blocks):
        if any(marker in ln for ln in block):
            if _content(block) == _content(new_block):
                return path  # unchanged apart from the time: don't dirty the file
            if " UTC · " in block[0]:  # keep the section's original start time in its heading
                new_block = [block[0].split(" UTC · ", 1)[0] + " UTC · " + new_block[0].split(" UTC · ", 1)[-1], *new_block[1:]]
            blocks[i] = new_block
            replaced = True
    if not replaced:
        blocks.append(new_block)
    body = "\n\n".join("\n".join(b).rstrip() for b in blocks)
    path.write_text(header.rstrip() + "\n\n" + body + "\n", encoding="utf-8", newline="\n")
    return path


def has_section(root: Path, session_id: str) -> bool:
    return any(s.session_id == session_id for s in read_sections(root))


def _header_and_blocks(text: str) -> tuple[str, list[list[str]]]:
    lines = text.splitlines()
    first = next((i for i, ln in enumerate(lines) if ln.startswith("## ")), len(lines))
    return "\n".join(lines[:first]), _split_sections("\n".join(lines[first:]))


# ---- deriving the "why" and open questions from Claude's last message --------------------

_CODE_FENCE = re.compile(r"```.*?```", re.S)
_LINE_PREFIX = re.compile(r"^(?:>\s*)+")  # block quotes, only at line start
_EMPHASIS = re.compile(r"\*\*|__(?=\S)|(?<=\S)__|`")  # bold markers and backticks; keeps snake_case


def _plain_lines(message: str) -> list[str]:
    text = _CODE_FENCE.sub(" ", message or "")
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("|", "<!--", "#")) or set(line) <= set("-=|: "):
            continue  # tables, comments, headings and rules never carry the "why"
        line = _LINE_PREFIX.sub("", line)
        line = re.sub(r"^([-*+]|\d+[.)])\s+", "", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)  # markdown links -> text
        line = _EMPHASIS.sub("", line).strip()
        if line:
            lines.append(line)
    return lines


def derive_why(message: str | None, limit: int = 220) -> str:
    lines = _plain_lines(message or "")
    if not lines:
        return ""
    text = lines[0]
    if len(text) < 80 and len(lines) > 1:
        text = f"{text} {lines[1]}"
    sentences = re.split(r"(?<=[.!])\s+", text)
    out = " ".join(sentences[:2]).strip()
    return redact(out if len(out) <= limit else out[: limit - 3].rstrip() + "...")


def derive_open(message: str | None, limit: int = 200) -> str:
    qs = [ln for ln in _plain_lines(message or "") if ln.endswith("?")][:2]
    out = "; ".join(qs)
    return redact(out if len(out) <= limit else out[: limit - 3].rstrip() + "...")

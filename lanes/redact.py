"""Redact secrets before anything is written to a notice, summary or handoff.

This is a best-effort filter. It errs toward over-redacting, because notices
are committed to git and shared with every teammate.
"""

from __future__ import annotations

import re

MASK = "[REDACTED]"

# (pattern, replacement). Replacements may keep a non-secret prefix via \1.
_RULES: list[tuple[re.Pattern[str], str]] = [
    # PEM private keys (whole block)
    (re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)", re.S), MASK),
    # Provider-specific token shapes
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}"), MASK),  # Anthropic
    (re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{20,}"), MASK),  # OpenAI
    (re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}"), MASK),  # Stripe
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"), MASK),  # GitHub
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), MASK),
    (re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}"), MASK),  # GitLab
    (re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"), MASK),  # Slack
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), MASK),  # AWS access key id
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}"), MASK),  # Google API key
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), MASK),  # JWT
    # Authorization headers
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/\-]{16,}=*"), r"\1 " + MASK),
    # Credentials inside URLs: scheme://user:password@host
    (re.compile(r"([a-z][a-z0-9+.\-]*://[^\s:/@]+:)[^\s@/]+@", re.I), r"\1" + MASK + "@"),
    # .env-style lines: UPPER_CASE=value
    (re.compile(r"(?m)^(\s*(?:export\s+)?[A-Z][A-Z0-9_]*\s*=\s*)\S.*$"), r"\1" + MASK),
    # Secret-looking assignments: api_key = "...", password: '...'
    (
        re.compile(
            r"(?i)\b([A-Z0-9_\-]*(?:secret|token|passw(?:or)?d|pwd|api[_\-]?key|private[_\-]?key|access[_\-]?key|auth)"
            r"[A-Z0-9_\-]*[\"']?\s*[:=]\s*)(\"[^\"\n]{6,}\"|'[^'\n]{6,}'|(?=[A-Za-z0-9_\-+/=.]*\d)[A-Za-z0-9_\-+/=.]{12,})"
        ),
        r"\1" + MASK,
    ),
]


def redact(text: str) -> str:
    if not text:
        return text
    for pattern, repl in _RULES:
        text = pattern.sub(repl, text)
    return text


def is_env_file(rel_path: str) -> bool:
    """True for .env, .env.local, prod.env, etc. Lanes never reads these."""
    name = rel_path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return (name == ".env" or name.startswith(".env.") or name.endswith(".env")) and name != ".env.example"

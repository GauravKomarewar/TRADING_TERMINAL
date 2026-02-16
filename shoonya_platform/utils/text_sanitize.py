#!/usr/bin/env python3
"""Utilities to normalize and sanitize log/notification text."""

from __future__ import annotations

import re
import unicodedata

_ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
_MOJIBAKE_HINTS = ("Ã", "Â", "â", "ðŸ", "ï¸", "Å", "¢")

_SYMBOL_MAP = {
    "₹": "INR ",
    "→": "->",
    "←": "<-",
    "↔": "<->",
    "•": "-",
    "⚠": "WARNING",
    "✅": "OK",
    "❌": "ERROR",
}


def _repair_mojibake(text: str) -> str:
    """Best-effort repair for UTF-8 text decoded as latin-1/cp1252."""
    if not text:
        return text
    if not any(h in text for h in _MOJIBAKE_HINTS):
        return text

    repaired = text
    for _ in range(2):
        try:
            candidate = repaired.encode("latin-1", errors="ignore").decode("utf-8", errors="ignore")
            if candidate and candidate != repaired:
                repaired = candidate
            else:
                break
        except Exception:
            break
    return repaired


def sanitize_text(text: str, ascii_only: bool = True) -> str:
    """Return cleaned text suitable for logs/Telegram payloads."""
    if text is None:
        return ""

    cleaned = str(text).replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _ANSI_RE.sub("", cleaned)
    cleaned = _repair_mojibake(cleaned)

    for src, dst in _SYMBOL_MAP.items():
        cleaned = cleaned.replace(src, dst)

    if ascii_only:
        cleaned = unicodedata.normalize("NFKD", cleaned)
        cleaned = cleaned.encode("ascii", errors="ignore").decode("ascii")

    # Keep formatting readable, remove accidental trailing spaces.
    cleaned = "\n".join(line.rstrip() for line in cleaned.split("\n"))
    return cleaned


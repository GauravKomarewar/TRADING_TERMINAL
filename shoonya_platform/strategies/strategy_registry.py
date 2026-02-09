#!/usr/bin/env python3
"""
Strategy registry (folder-based discovery)

Rules:
- Each strategy lives in its own folder under strategies/
- Each folder contains one or more .py files (excluding __init__.py)
- legacy/, universal_config/, __pycache__ are excluded
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Dict


_STRATEGIES_DIR = Path(__file__).resolve().parent
_EXCLUDED_FOLDERS = {"legacy", "universal_config", "__pycache__"}


def _label_for(folder: str, stem: str) -> str:
    if folder == stem:
        return folder.replace("_", " ").title()
    return f"{folder.replace('_', ' ').title()} - {stem.replace('_', ' ').title()}"


def list_strategy_templates() -> List[Dict[str, str]]:
    templates: List[Dict[str, str]] = []

    for entry in sorted(_STRATEGIES_DIR.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name in _EXCLUDED_FOLDERS:
            continue

        py_files = sorted(
            [p for p in entry.glob("*.py") if p.name != "__init__.py"]
        )
        for py_file in py_files:
            templates.append(
                {
                    "id": f"{entry.name}/{py_file.stem}",
                    "folder": entry.name,
                    "file": py_file.name,
                    "module": f"shoonya_platform.strategies.{entry.name}.{py_file.stem}",
                    "label": _label_for(entry.name, py_file.stem),
                    "slug": py_file.stem,
                }
            )

    return templates

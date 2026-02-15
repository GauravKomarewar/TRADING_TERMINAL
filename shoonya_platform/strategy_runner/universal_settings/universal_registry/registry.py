#!/usr/bin/env python3
"""
STRATEGY REGISTRY
================
Folder-based discovery of all strategies

Works with BOTH market types:
- live_feed_market adapters
- database_market adapters

RULES:
- Each strategy lives in its own folder under strategies/
- Each folder contains one or more .py files (excluding __init__.py)
- legacy/, universal_config/, universal_settings/, __pycache__ are excluded
- Works regardless of how market data is provided (adapter-agnostic)
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Dict


def _label_for(folder: str, stem: str) -> str:
    """Generate human-readable label for strategy"""
    if folder == stem:
        return folder.replace("_", " ").title()
    return f"{folder.replace('_', ' ').title()} - {stem.replace('_', ' ').title()}"


def list_strategy_templates() -> List[Dict[str, str]]:
    """
    Discover all available strategy templates in the codebase
    
    Returns:
        List of strategy template metadata dicts
        
    Each dict contains:
        - id: unique identifier (folder/file)
        - folder: strategy folder name
        - file: strategy file name
        - module: fully qualified module path
        - label: human-readable name
        - slug: file stem (base name)
    """
    _STRATEGIES_DIR = Path(__file__).resolve().parent.parent.parent
    _EXCLUDED_FOLDERS = {
        "legacy",
        "universal_config",
        "universal_settings",
        "universal_registry",
        "universal_strategy_reporter",
        "writer",
        "database_market",
        "live_feed_market",
        "market_adapter_factory",
        "engine",
        "saved_configs",
        "__pycache__",
    }

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

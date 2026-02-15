#!/usr/bin/env python3
"""
Tests for strategy_runner execution primitives.
"""

import tempfile
from pathlib import Path

from shoonya_platform.strategy_runner.strategy_executor_service import (
    ExecutionState,
    StateManager,
)


def test_state_manager_save_load_delete_roundtrip():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name
    try:
        mgr = StateManager(db_path)
        state = ExecutionState(strategy_name="nifty_test", run_id="run_1", has_position=True)

        mgr.save(state)
        loaded = mgr.load("nifty_test")
        assert loaded is not None
        assert loaded.strategy_name == "nifty_test"
        assert loaded.run_id == "run_1"
        assert loaded.has_position is True

        assert "nifty_test" in mgr.list_all()

        mgr.delete("nifty_test")
        assert mgr.load("nifty_test") is None
    finally:
        Path(db_path).unlink(missing_ok=True)

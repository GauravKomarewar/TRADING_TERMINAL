"""
Strategy Execution Engines
==========================

Universal execution engines handling:
- Strategy lifecycle (init, run, exit)
- Intent execution
- Time-based exit enforcement
- Error handling and recovery

Available Engines:
- Engine: Full-featured with recovery handling
- Engine (NoRecovery): Simplified without recovery logic

Consolidated from execution/ to keep all strategy code in strategies/ folder
"""

from .engine import Engine as EngineWithRecovery
from .engine_no_recovery import Engine as EngineNoRecovery

# Main export
Engine = EngineNoRecovery

__all__ = [
    "Engine",
    "EngineWithRecovery",
    "EngineNoRecovery",
]

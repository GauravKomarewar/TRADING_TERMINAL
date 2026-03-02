import unittest
from pathlib import Path


class TestHardeningCriticalPaths(unittest.TestCase):
    def test_no_bare_except_in_critical_files(self):
        # Bare except in runtime-critical paths can hide trading failures.
        critical_files = [
            Path("shoonya_platform/strategy_runner/strategy_executor_service.py"),
            Path("shoonya_platform/execution/trading_bot.py"),
            Path("shoonya_platform/execution/bot_alert_processing.py"),
            Path("shoonya_platform/execution/bot_execution.py"),
            Path("shoonya_platform/execution/bot_status_scheduling.py"),
        ]
        for p in critical_files:
            text = p.read_text(encoding="utf-8", errors="replace")
            self.assertNotIn("except:\n", text, f"Bare except found in {p}")
            self.assertNotIn("except:\r\n", text, f"Bare except found in {p}")

    def test_adjustment_cooldown_guard_uses_injected_time(self):
        text = Path("shoonya_platform/strategy_runner/adjustment_engine.py").read_text(
            encoding="utf-8", errors="replace"
        )
        self.assertIn("def _check_guards(self, rule: Dict[str, Any], current_time: Optional[datetime] = None)", text)
        self.assertIn("now = current_time or datetime.now()", text)
        # Per-rule cooldown: uses _rule_last_fired dict instead of global state.last_adjustment_time
        self.assertIn("(now - self._rule_last_fired[rule_name]).total_seconds()", text)

    def test_test_mode_exit_uses_executor_state(self):
        # MOCK mode now runs full pipeline using executor state (no broker skip)
        text = Path("shoonya_platform/execution/bot_execution.py").read_text(
            encoding="utf-8", errors="replace"
        )
        # MOCK builds virtual positions from executor state
        self.assertIn("_build_mock_exit_positions", text)
        # validate_and_prepare runs for both MOCK and LIVE
        self.assertIn("guarded = self.execution_guard.validate_and_prepare(", text)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""
test_v3_builder_compat.py
=========================
Integration tests for the v3 strategy_builder → strategy_runner compatibility layer.

Tests every fix made in the compatibility pass:
  1. config_schema: simple_close_open_new accepted, empty rules → warning, tag.X.Y allowed
  2. condition_engine: tag.LEG@1.delta resolves via tag_map to ce_delta
  3. strategy_executor_service: _inject_pnl_exit_conditions injects TP/SL conditions
  4. strategy_executor_service: per-leg condition gating skips failed legs
  5. strategy_executor_service: _execute_simple_close_open_new close+reopen logic

Run:
    python3 -m pytest strategy_runner/test_v3_builder_compat.py -v
    # or without pytest:
    python3 strategy_runner/test_v3_builder_compat.py
"""

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call
# Allow running from project root or from strategy_runner/ directly
_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
sys.path.insert(0, str(_PROJECT))

# ── Shoonya platform module shims ────────────────────────────────────────────
# strategy_executor_service imports from shoonya_platform.* (the production package
# path). In the test environment that package isn't installed, so we inject shims
# pointing at the real source files via sys.modules before importing the executor.

import types as _types

def _make_shim(real_module):
    """Return a module shim whose attributes proxy a real module."""
    shim = _types.ModuleType(real_module.__name__)
    shim.__dict__.update(real_module.__dict__)
    return shim

# Import real modules directly from the project directory
import importlib.util as _ilu

def _load_local(name, path):
    spec = _ilu.spec_from_file_location(name, path)
    mod = _ilu.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

# 1. Load condition_engine and expose under both the local and shoonya_platform names
_ce = _load_local("strategy_runner.condition_engine",
                   _PROJECT / "strategy_runner" / "condition_engine.py")
sys.modules["shoonya_platform"] = _types.ModuleType("shoonya_platform")
sys.modules["shoonya_platform.strategy_runner"] = _types.ModuleType("shoonya_platform.strategy_runner")
sys.modules["shoonya_platform.strategy_runner.condition_engine"] = _ce

# 2. config_schema
_cs = _load_local("strategy_runner.config_schema",
                   _PROJECT / "strategy_runner" / "config_schema.py")
sys.modules["shoonya_platform.strategy_runner.config_schema"] = _cs

# 3. Stub market_reader
_mr_stub = _types.ModuleType("shoonya_platform.strategy_runner.market_reader")
_mr_stub.MarketReader = MagicMock  # replaced per-test anyway
sys.modules["shoonya_platform.strategy_runner.market_reader"] = _mr_stub

# 4. Stub market_data.feeds
_mdf = _types.ModuleType("shoonya_platform.market_data")
_mdf_feeds = _types.ModuleType("shoonya_platform.market_data.feeds")
_mdf_feeds.index_tokens_subscriber = MagicMock()
sys.modules["shoonya_platform.market_data"] = _mdf
sys.modules["shoonya_platform.market_data.feeds"] = _mdf_feeds

# 5. Stub scripts.scriptmaster
_scripts = _types.ModuleType("scripts")
_scripts_sm = _types.ModuleType("scripts.scriptmaster")
_scripts_sm.requires_limit_order = lambda *a, **kw: False
sys.modules["scripts"] = _scripts
sys.modules["scripts.scriptmaster"] = _scripts_sm

# Now safe to import the executor
import strategy_runner.strategy_executor_service as _svc

# ── Imports under test ───────────────────────────────────────────────────────
from strategy_runner.config_schema import (
    validate_config,
    ValidationError,
    VALID_ADJUSTMENT_ACTIONS,
)
from strategy_runner.condition_engine import (
    StrategyState,
    evaluate_condition,
    evaluate_adjustment_rules,
)

_inject_pnl_exit_conditions = _svc._inject_pnl_exit_conditions

# ─────────────────────────────────────────────────────────────────────────────
# Helpers / fixtures
# ─────────────────────────────────────────────────────────────────────────────

SAMPLE_V3_PATH = Path(__file__).resolve().parent / "saved_configs" / "builder_v3_nifty_strangle.json"


def load_sample() -> dict:
    """Load the canonical builder v3 sample config."""
    with open(SAMPLE_V3_PATH) as f:
        return json.load(f)


def _make_state(**kwargs) -> StrategyState:
    """
    Create a StrategyState with convenient attribute overrides.

    Handles computed properties by mapping convenience shortcuts to their
    underlying plain fields:
      combined_pnl=X  →  ce_pnl=X  (all attributed to CE leg for simplicity)
    """
    # Map convenience aliases → real settable fields
    _aliases = {
        "combined_pnl": "ce_pnl",   # combined_pnl is @property = ce_pnl + pe_pnl
    }
    st = StrategyState()
    for k, v in kwargs.items():
        real_k = _aliases.get(k, k)
        setattr(st, real_k, v)
    return st


# ═════════════════════════════════════════════════════════════════════════════
# 1. Config schema validation
# ═════════════════════════════════════════════════════════════════════════════

class TestConfigSchemaV3Compat(unittest.TestCase):
    """validate_config must accept builder v3 output without hard errors."""

    def setUp(self):
        self.cfg = load_sample()

    # ── 1a. simple_close_open_new in allowlist ────────────────────────────
    def test_simple_close_open_new_in_valid_actions(self):
        self.assertIn(
            "simple_close_open_new",
            VALID_ADJUSTMENT_ACTIONS,
            "simple_close_open_new must be in VALID_ADJUSTMENT_ACTIONS",
        )

    # ── 1b. Full v3 config passes validation (no errors) ─────────────────
    def test_full_v3_config_validates_without_errors(self):
        is_valid, errors = validate_config(self.cfg)
        hard_errors = [e for e in errors if e.severity == "error"]
        self.assertTrue(
            is_valid,
            f"Expected v3 config to be valid. Hard errors:\n"
            + "\n".join(f"  {e.path}: {e.message}" for e in hard_errors),
        )

    # ── 1c. Empty entry.conditions.rules → warning not error ─────────────
    def test_empty_entry_conditions_is_warning_not_error(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["entry"]["conditions"] = {"operator": "AND", "rules": []}
        is_valid, errors = validate_config(cfg)
        hard_errors = [e for e in errors if e.severity == "error" and "rules" in e.path]
        self.assertEqual(
            hard_errors, [],
            f"Empty rules should be a warning, not an error. Got: {hard_errors}",
        )
        warnings = [e for e in errors if e.severity == "warning" and "rules" in e.path.lower()]
        self.assertTrue(
            len(warnings) > 0 or is_valid,
            "Empty rules: expected either a warning or valid=True",
        )

    # ── 1d. tag.X.Y parameters pass validation ───────────────────────────
    def test_tag_parameter_passes_validation(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["adjustment"]["rules"][0]["conditions"] = {
            "operator": "AND",
            "rules": [
                {"parameter": "tag.LEG@1.delta", "comparator": ">=", "value": 0.50}
            ],
        }
        is_valid, errors = validate_config(cfg)
        param_errors = [
            e for e in errors
            if e.severity == "error" and "tag.LEG@1.delta" in e.message
        ]
        self.assertEqual(
            param_errors, [],
            f"tag.LEG@1.delta should not cause a hard error. Got: {param_errors}",
        )

    # ── 1e. simple_close_open_new in adj action doesn't cause schema error ─
    def test_simple_close_open_new_action_type_accepted(self):
        cfg = copy.deepcopy(self.cfg)
        is_valid, errors = validate_config(cfg)
        action_errors = [
            e for e in errors
            if e.severity == "error" and "simple_close_open_new" in e.message
        ]
        self.assertEqual(
            action_errors, [],
            f"simple_close_open_new in action.type should not cause an error. Got: {action_errors}",
        )


# ═════════════════════════════════════════════════════════════════════════════
# 2. Tag parameter resolution in condition_engine
# ═════════════════════════════════════════════════════════════════════════════

class TestTagParameterResolution(unittest.TestCase):
    """tag.LEG@N.metric must resolve to ce_/pe_ metric via tag_map."""

    def setUp(self):
        self.state = _make_state(
            ce_delta=0.42,
            pe_delta=0.31,
            ce_ltp=85.5,
            pe_ltp=72.0,
            combined_pnl=1250.0,
        )
        self.state.tag_map = {
            "LEG@1": "CE",
            "LEG@2": "PE",
        }

    # ── 2a. tag.LEG@1.delta → ce_delta ───────────────────────────────────
    def test_leg1_delta_resolves_to_ce_delta(self):
        val = self.state.get_param("tag.LEG@1.delta")
        self.assertAlmostEqual(val, 0.42, places=5, msg="tag.LEG@1.delta must equal ce_delta")

    # ── 2b. tag.LEG@2.delta → pe_delta ───────────────────────────────────
    def test_leg2_delta_resolves_to_pe_delta(self):
        val = self.state.get_param("tag.LEG@2.delta")
        self.assertAlmostEqual(val, 0.31, places=5, msg="tag.LEG@2.delta must equal pe_delta")

    # ── 2c. tag.LEG@1.ltp → ce_ltp ──────────────────────────────────────
    def test_leg1_ltp_resolves_to_ce_ltp(self):
        val = self.state.get_param("tag.LEG@1.ltp")
        self.assertAlmostEqual(val, 85.5, places=5, msg="tag.LEG@1.ltp must equal ce_ltp")

    # ── 2d. Unknown tag returns None (not crash) ──────────────────────────
    def test_unknown_tag_returns_none(self):
        val = self.state.get_param("tag.LEG@99.delta")
        self.assertIsNone(val, "Unknown tag should return None")

    # ── 2e. Malformed tag returns None ───────────────────────────────────
    def test_malformed_tag_does_not_crash(self):
        val = self.state.get_param("tag.nodot")
        self.assertIsNone(val, "Malformed tag (no metric part) should return None")

    # ── 2f. tag_map in StrategyState initialises to empty dict ───────────
    def test_tag_map_initialised_empty(self):
        fresh = StrategyState()
        self.assertIsInstance(fresh.tag_map, dict)
        self.assertEqual(fresh.tag_map, {})

    # ── 2g. Condition evaluation with tag parameter (full flow) ───────────
    def test_evaluate_condition_with_tag_param_passes(self):
        """CE delta is 0.42 ≥ 0.40 → condition True."""
        cond = {"parameter": "tag.LEG@1.delta", "comparator": ">=", "value": 0.40}
        result = evaluate_condition(cond, self.state)
        self.assertTrue(result, "Condition tag.LEG@1.delta >= 0.40 should be True (ce_delta=0.42)")

    def test_evaluate_condition_with_tag_param_fails(self):
        """CE delta 0.42 < 0.50 threshold → condition False."""
        cond = {"parameter": "tag.LEG@1.delta", "comparator": ">=", "value": 0.50}
        result = evaluate_condition(cond, self.state)
        self.assertFalse(result, "Condition tag.LEG@1.delta >= 0.50 should be False (ce_delta=0.42)")

    # ── 2h. Full adjustment rule evaluation using tag params ──────────────
    def test_adjustment_rule_triggers_via_tag_param(self):
        """Simulate: CE drifted to 0.55 → adjustment rule 1 should trigger."""
        state = copy.deepcopy(self.state)
        state.ce_delta = 0.55  # drifted above 0.50 threshold
        state.pe_delta = 0.28  # PE still OK

        cfg = load_sample()
        triggered = evaluate_adjustment_rules(cfg, state)

        self.assertTrue(len(triggered) >= 1, "At least 1 adjustment rule should trigger")
        self.assertEqual(
            triggered[0].action.get("type"),
            "simple_close_open_new",
            "Triggered rule action type should be simple_close_open_new",
        )

    def test_adjustment_rule_does_not_trigger_when_delta_ok(self):
        """Both deltas within range → no adjustments triggered."""
        state = _make_state(ce_delta=0.32, pe_delta=0.29)
        state.tag_map = {"LEG@1": "CE", "LEG@2": "PE"}

        cfg = load_sample()
        triggered = evaluate_adjustment_rules(cfg, state)
        self.assertEqual(triggered, [], "No adjustments should trigger when deltas are normal")


# ═════════════════════════════════════════════════════════════════════════════
# 3. P&L exit condition injection
# ═════════════════════════════════════════════════════════════════════════════

class TestPnLExitInjection(unittest.TestCase):
    """_inject_pnl_exit_conditions must turn target_profit/stop_loss into
    exit.conditions.rules entries."""

    def _base_config(self, tp=2000, sl=3000):
        return {
            "basic": {"exchange": "NFO", "underlying": "NIFTY", "lots": 1},
            "timing": {"entry_time": "09:20", "exit_time": "15:28"},
            "entry": {"conditions": {"operator": "AND", "rules": []}},
            "exit": {
                "target_profit": {"amount": tp, "pct": None},
                "stop_loss": {"amount": sl, "pct": None},
                "conditions": {
                    "operator": "OR",
                    "rules": [
                        {"parameter": "time_current", "comparator": ">=", "value": "15:28"}
                    ],
                },
            },
        }

    # ── 3a. Target profit injected as combined_pnl >= amount ─────────────
    def test_target_profit_injected(self):
        cfg = _inject_pnl_exit_conditions(self._base_config(tp=2000, sl=None))
        rules = cfg["exit"]["conditions"]["rules"]
        tp_rules = [r for r in rules if r.get("parameter") == "combined_pnl" and r.get("comparator") == ">="]
        self.assertEqual(len(tp_rules), 1, "Exactly one combined_pnl >= rule must be injected")
        self.assertEqual(tp_rules[0]["value"], 2000.0)

    # ── 3b. Stop loss injected as combined_pnl <= -amount ────────────────
    def test_stop_loss_injected_as_negative(self):
        cfg = _inject_pnl_exit_conditions(self._base_config(tp=None, sl=3000))
        rules = cfg["exit"]["conditions"]["rules"]
        sl_rules = [r for r in rules if r.get("parameter") == "combined_pnl" and r.get("comparator") == "<="]
        self.assertEqual(len(sl_rules), 1, "Exactly one combined_pnl <= rule must be injected")
        self.assertEqual(sl_rules[0]["value"], -3000.0, "SL value must be negated")

    # ── 3c. Both injected when both present ──────────────────────────────
    def test_both_tp_and_sl_injected(self):
        cfg = _inject_pnl_exit_conditions(self._base_config(tp=2000, sl=3000))
        rules = cfg["exit"]["conditions"]["rules"]
        tp_rules = [r for r in rules if r.get("comparator") == ">="]
        sl_rules = [r for r in rules if r.get("comparator") == "<="]
        self.assertGreater(len(tp_rules), 0, "TP rule must be injected")
        self.assertGreater(len(sl_rules), 0, "SL rule must be injected")

    # ── 3d. None amount → not injected ───────────────────────────────────
    def test_none_amount_not_injected(self):
        cfg = _inject_pnl_exit_conditions(self._base_config(tp=None, sl=None))
        rules = cfg["exit"]["conditions"]["rules"]
        pnl_rules = [r for r in rules if r.get("parameter") == "combined_pnl"]
        self.assertEqual(pnl_rules, [], "None amounts must not inject conditions")

    # ── 3e. Original scheduled-exit condition preserved ──────────────────
    def test_existing_conditions_preserved(self):
        cfg = _inject_pnl_exit_conditions(self._base_config(tp=2000, sl=3000))
        rules = cfg["exit"]["conditions"]["rules"]
        time_rules = [r for r in rules if r.get("parameter") == "time_current"]
        self.assertEqual(len(time_rules), 1, "Original time_current exit rule must be preserved")

    # ── 3f. Idempotent: re-running doesn't duplicate ──────────────────────
    def test_idempotent_double_injection(self):
        cfg = self._base_config(tp=2000, sl=3000)
        cfg = _inject_pnl_exit_conditions(cfg)
        cfg = _inject_pnl_exit_conditions(cfg)  # run again
        rules = cfg["exit"]["conditions"]["rules"]
        # Filter specifically for P&L rules, not the time_current rule that also uses >=
        tp_rules = [r for r in rules if r.get("parameter") == "combined_pnl" and r.get("comparator") == ">="]
        sl_rules = [r for r in rules if r.get("parameter") == "combined_pnl" and r.get("comparator") == "<="]
        self.assertLessEqual(len(tp_rules), 1, "TP must not be duplicated on second injection")
        self.assertLessEqual(len(sl_rules), 1, "SL must not be duplicated on second injection")

    # ── 3g. Full sample config injected correctly ─────────────────────────
    def test_full_sample_config_injection(self):
        cfg = load_sample()
        cfg = _inject_pnl_exit_conditions(cfg)
        rules = cfg["exit"]["conditions"]["rules"]
        pnl_rules = [r for r in rules if r.get("parameter") == "combined_pnl"]
        self.assertEqual(len(pnl_rules), 2, "Sample config should inject exactly 2 P&L rules (TP + SL)")
        values = {r["comparator"]: r["value"] for r in pnl_rules}
        self.assertEqual(values.get(">="), 2000.0, "TP should be ₹2000")
        self.assertEqual(values.get("<="), -3000.0, "SL should be -₹3000")


# ═════════════════════════════════════════════════════════════════════════════
# 4. Per-leg condition gating  (tested via helper extracted from executor)
# ═════════════════════════════════════════════════════════════════════════════

def _leg_conditions_met(leg_cfg: dict, state: StrategyState) -> bool:
    """
    Standalone replica of the _leg_conditions_met helper in _check_entry().
    The executor embeds this as a closure; we replicate it here to test the logic.
    """
    cond_block = leg_cfg.get("conditions_block")
    if not cond_block or not isinstance(cond_block, dict):
        return True
    rules = cond_block.get("rules", [])
    if not rules:
        return True
    result = evaluate_condition(cond_block, state)
    if not result:
        mode = leg_cfg.get("condition_mode", "if_then")
        if mode == "if_then_else":
            else_block = leg_cfg.get("else_conditions_block")
            if else_block and isinstance(else_block, dict) and else_block.get("rules"):
                return evaluate_condition(else_block, state)
    return result


class TestPerLegConditionGating(unittest.TestCase):
    """Each entry leg's conditions_block gates whether the leg is executed."""

    def _make_leg(self, option_type, delta_cond, mode="if_then", else_block=None):
        return {
            "tag": f"LEG@{'1' if option_type=='CE' else '2'}",
            "option_type": option_type,
            "condition_mode": mode,
            "conditions_block": {
                "operator": "AND",
                "rules": [{"parameter": f"{option_type.lower()}_delta", **delta_cond}],
            },
            "else_conditions_block": else_block,
        }

    # ── 4a. No conditions_block → always executes ─────────────────────────
    def test_no_conditions_block_always_true(self):
        leg = {"option_type": "CE", "condition_mode": "if_then"}
        state = _make_state(ce_delta=0.99)
        self.assertTrue(_leg_conditions_met(leg, state))

    # ── 4b. Empty rules → always executes ────────────────────────────────
    def test_empty_rules_always_true(self):
        leg = {
            "option_type": "CE",
            "condition_mode": "if_then",
            "conditions_block": {"operator": "AND", "rules": []},
        }
        state = _make_state(ce_delta=0.99)
        self.assertTrue(_leg_conditions_met(leg, state))

    # ── 4c. Passing IF condition → executes ───────────────────────────────
    def test_passing_if_condition_executes(self):
        leg = self._make_leg("CE", {"comparator": "between", "value": [0.15, 0.50]})
        state = _make_state(ce_delta=0.32)  # in range
        self.assertTrue(_leg_conditions_met(leg, state))

    # ── 4d. Failing IF (if_then mode) → skipped ───────────────────────────
    def test_failing_if_condition_skips_leg(self):
        leg = self._make_leg("CE", {"comparator": "between", "value": [0.15, 0.50]})
        state = _make_state(ce_delta=0.05)  # out of range
        self.assertFalse(_leg_conditions_met(leg, state), "Leg should be skipped when IF fails in if_then mode")

    # ── 4e. Failing IF, passing ELSE (if_then_else) → executes via ELSE ──
    def test_else_branch_executes_when_if_fails(self):
        else_block = {
            "operator": "AND",
            "rules": [{"parameter": "ce_delta", "comparator": ">=", "value": 0.0}],
        }
        leg = self._make_leg("CE", {"comparator": ">=", "value": 0.90}, mode="if_then_else", else_block=else_block)
        state = _make_state(ce_delta=0.32)  # fails IF (>=0.90), passes ELSE (>=0.0)
        self.assertTrue(_leg_conditions_met(leg, state), "ELSE branch should activate when IF fails")

    # ── 4f. Both IF and ELSE fail (if_then_else) → skipped ───────────────
    def test_both_if_and_else_fail_skips_leg(self):
        else_block = {
            "operator": "AND",
            "rules": [{"parameter": "ce_delta", "comparator": ">=", "value": 0.95}],
        }
        leg = self._make_leg("CE", {"comparator": ">=", "value": 0.90}, mode="if_then_else", else_block=else_block)
        state = _make_state(ce_delta=0.32)  # fails both
        self.assertFalse(_leg_conditions_met(leg, state))

    # ── 4g. Sample config leg-1 CE condition passes in normal state ───────
    def test_sample_config_ce_leg_passes_in_normal_state(self):
        cfg = load_sample()
        ce_leg = cfg["entry"]["action"]["legs"][0]
        state = _make_state(ce_delta=0.30)  # in [0.15, 0.50]
        self.assertTrue(_leg_conditions_met(ce_leg, state))

    # ── 4h. Sample config leg-1 CE condition fails when delta is extreme ──
    def test_sample_config_ce_leg_fails_extreme_delta(self):
        cfg = load_sample()
        ce_leg = cfg["entry"]["action"]["legs"][0]
        state = _make_state(ce_delta=0.05)  # below 0.15 → out of range
        self.assertFalse(_leg_conditions_met(ce_leg, state))


# ═════════════════════════════════════════════════════════════════════════════
# 5. simple_close_open_new execution
# ═════════════════════════════════════════════════════════════════════════════

def _make_mock_executor():
    """Build a lightweight mock of StrategyExecutorService for testing _execute_simple_close_open_new."""
    svc = MagicMock(spec=_svc.StrategyExecutorService)
    # Re-bind the real method to our mock
    svc._execute_simple_close_open_new = _svc.StrategyExecutorService._execute_simple_close_open_new.__get__(svc)

    # Helpers the method calls
    svc._adjustment_close_leg.return_value = True
    svc._open_monitored_leg.return_value = None
    svc._resolve_order_contract.return_value = ("MARKET", 0.0)
    svc._resolve_webhook_secret.return_value = "TEST_SECRET"
    svc._resolve_intent_test_mode.return_value = None
    svc.state_mgr = MagicMock()
    svc.state_mgr.save.return_value = None

    # bot.process_alert returns a success dict
    svc.bot = MagicMock()
    svc.bot.process_alert.return_value = {"status": "SUCCESS"}

    return svc


def _make_mock_reader(new_option: dict = None):
    reader = MagicMock()
    reader.get_lot_size.return_value = 50
    reader.get_atm_strike.return_value = 22500.0
    reader.get_spot_price.return_value = 22500.0
    default_opt = new_option or {
        "trading_symbol": "NIFTY25FEB22600CE",
        "ltp": 95.5,
        "strike": 22600.0,
    }
    reader.find_option_by_delta.return_value = default_opt
    reader.find_option_by_premium.return_value = default_opt
    reader.get_option_at_strike.return_value = default_opt
    reader.get_full_chain.return_value = [
        {"strike": float(22000 + i * 50)} for i in range(20)
    ]
    return reader


class TestSimpleCloseOpenNew(unittest.TestCase):
    """Unit tests for _execute_simple_close_open_new."""

    def _base_exec_state(self):
        state = _svc.ExecutionState(strategy_name="TEST", run_id="R1")
        state.has_position = True
        state.ce_symbol = "NIFTY25FEB22550CE"
        state.ce_strike = 22550.0
        state.ce_qty = 50
        state.ce_side = "SELL"
        state.ce_entry_price = 110.0
        state.pe_symbol = "NIFTY25FEB22400PE"
        state.pe_strike = 22400.0
        state.pe_qty = 50
        state.pe_side = "SELL"
        state.pe_entry_price = 95.0
        return state

    def _base_engine_state(self):
        st = StrategyState()
        st.tag_map = {"LEG@1": "CE", "LEG@2": "PE"}
        return st

    def _base_config(self):
        return {
            "basic": {"exchange": "NFO", "underlying": "NIFTY", "lots": 1},
            "identity": {"exchange": "NFO", "product_type": "NRML", "order_type": "MARKET"},
        }

    def _make_action(self, close_tag, new_option_type="CE", strike_sel="delta", strike_val=0.30):
        return {
            "type": "simple_close_open_new",
            "details": {
                "leg_swaps": [
                    {
                        "close_tag": close_tag,
                        "new_leg": {
                            "side": "SELL",
                            "instrument": "OPTION",
                            "option_type": new_option_type,
                            "strike_selection": strike_sel,
                            "strike_value": strike_val,
                            "lots": 1,
                            "order_type": "MARKET",
                        },
                    }
                ],
                "target_leg_tags": [close_tag],
            },
        }

    # ── 5a. Empty leg_swaps → returns False ───────────────────────────────
    def test_empty_leg_swaps_returns_false(self):
        svc = _make_mock_executor()
        action = {"type": "simple_close_open_new", "details": {"leg_swaps": []}}
        result = svc._execute_simple_close_open_new(
            name="TEST",
            exec_state=self._base_exec_state(),
            engine_state=self._base_engine_state(),
            config=self._base_config(),
            action=action,
            reader=_make_mock_reader(),
        )
        self.assertFalse(result)

    # ── 5b. Unknown close_tag → returns False ────────────────────────────
    def test_unknown_close_tag_returns_false(self):
        svc = _make_mock_executor()
        action = self._make_action(close_tag="LEG@99")
        engine_state = self._base_engine_state()
        engine_state.tag_map = {}  # empty map
        result = svc._execute_simple_close_open_new(
            name="TEST",
            exec_state=self._base_exec_state(),
            engine_state=engine_state,
            config=self._base_config(),
            action=action,
            reader=_make_mock_reader(),
        )
        self.assertFalse(result)

    # ── 5c. CE tag resolved: _adjustment_close_leg called with "CE" ───────
    def test_ce_close_tag_calls_close_leg_with_ce(self):
        svc = _make_mock_executor()
        reader = _make_mock_reader({
            "trading_symbol": "NIFTY25FEB22600CE",
            "ltp": 95.0,
            "strike": 22600.0,
        })
        action = self._make_action(close_tag="LEG@1", new_option_type="CE")
        result = svc._execute_simple_close_open_new(
            name="TEST",
            exec_state=self._base_exec_state(),
            engine_state=self._base_engine_state(),
            config=self._base_config(),
            action=action,
            reader=reader,
        )
        self.assertTrue(result)
        close_call = svc._adjustment_close_leg.call_args
        self.assertEqual(close_call.kwargs.get("leg") or close_call[1].get("leg"), "CE")

    # ── 5d. PE tag resolved: _adjustment_close_leg called with "PE" ───────
    def test_pe_close_tag_calls_close_leg_with_pe(self):
        svc = _make_mock_executor()
        reader = _make_mock_reader({
            "trading_symbol": "NIFTY25FEB22400PE",
            "ltp": 88.0,
            "strike": 22400.0,
        })
        action = self._make_action(close_tag="LEG@2", new_option_type="PE")
        result = svc._execute_simple_close_open_new(
            name="TEST",
            exec_state=self._base_exec_state(),
            engine_state=self._base_engine_state(),
            config=self._base_config(),
            action=action,
            reader=reader,
        )
        self.assertTrue(result)
        close_call = svc._adjustment_close_leg.call_args
        self.assertEqual(close_call.kwargs.get("leg") or close_call[1].get("leg"), "PE")

    # ── 5e. New option placed via bot.process_alert ───────────────────────
    def test_new_leg_placed_via_bot(self):
        svc = _make_mock_executor()
        reader = _make_mock_reader({
            "trading_symbol": "NIFTY25FEB22600CE",
            "ltp": 95.0,
            "strike": 22600.0,
        })
        action = self._make_action(close_tag="LEG@1", new_option_type="CE")
        svc._execute_simple_close_open_new(
            name="TEST",
            exec_state=self._base_exec_state(),
            engine_state=self._base_engine_state(),
            config=self._base_config(),
            action=action,
            reader=reader,
        )
        svc.bot.process_alert.assert_called_once()
        alert = svc.bot.process_alert.call_args[0][0]
        self.assertEqual(alert["execution_type"], "ADJUSTMENT")
        legs = alert.get("legs", [])
        self.assertEqual(len(legs), 1)
        self.assertIn("NIFTY25FEB22600CE", legs[0]["tradingsymbol"])

    # ── 5f. exec_state updated with new symbol ───────────────────────────
    def test_exec_state_updated_after_swap(self):
        svc = _make_mock_executor()
        new_symbol = "NIFTY25FEB22650CE"
        reader = _make_mock_reader({
            "trading_symbol": new_symbol,
            "ltp": 80.0,
            "strike": 22650.0,
        })
        exec_state = self._base_exec_state()
        action = self._make_action(close_tag="LEG@1", new_option_type="CE")
        svc._execute_simple_close_open_new(
            name="TEST",
            exec_state=exec_state,
            engine_state=self._base_engine_state(),
            config=self._base_config(),
            action=action,
            reader=reader,
        )
        self.assertEqual(exec_state.ce_symbol, new_symbol)
        self.assertEqual(exec_state.ce_strike, 22650.0)

    # ── 5g. Close failure → returns False ────────────────────────────────
    def test_close_failure_returns_false(self):
        svc = _make_mock_executor()
        svc._adjustment_close_leg.return_value = False  # simulate close failure
        action = self._make_action(close_tag="LEG@1", new_option_type="CE")
        result = svc._execute_simple_close_open_new(
            name="TEST",
            exec_state=self._base_exec_state(),
            engine_state=self._base_engine_state(),
            config=self._base_config(),
            action=action,
            reader=_make_mock_reader(),
        )
        self.assertFalse(result)
        svc.bot.process_alert.assert_not_called()

    # ── 5h. No option found → returns False ──────────────────────────────
    def test_no_option_found_returns_false(self):
        svc = _make_mock_executor()
        reader = _make_mock_reader()
        reader.find_option_by_delta.return_value = None
        action = self._make_action(close_tag="LEG@1", strike_sel="delta", strike_val=0.30)
        result = svc._execute_simple_close_open_new(
            name="TEST",
            exec_state=self._base_exec_state(),
            engine_state=self._base_engine_state(),
            config=self._base_config(),
            action=action,
            reader=reader,
        )
        self.assertFalse(result)

    # ── 5i. strike_selection: "atm" uses get_option_at_strike ────────────
    def test_atm_strike_selection(self):
        svc = _make_mock_executor()
        reader = _make_mock_reader({
            "trading_symbol": "NIFTY25FEB22500CE",
            "ltp": 105.0,
            "strike": 22500.0,
        })
        action = self._make_action(close_tag="LEG@1", strike_sel="atm", strike_val=None)
        svc._execute_simple_close_open_new(
            name="TEST",
            exec_state=self._base_exec_state(),
            engine_state=self._base_engine_state(),
            config=self._base_config(),
            action=action,
            reader=reader,
        )
        reader.get_option_at_strike.assert_called_once()

    # ── 5j. Multi-swap: two leg_swaps in one action ───────────────────────
    def test_multi_swap_calls_close_twice(self):
        svc = _make_mock_executor()
        reader = _make_mock_reader({
            "trading_symbol": "NIFTY25FEB22600CE",
            "ltp": 90.0,
            "strike": 22600.0,
        })
        action = {
            "type": "simple_close_open_new",
            "details": {
                "leg_swaps": [
                    {
                        "close_tag": "LEG@1",
                        "new_leg": {"side": "SELL", "instrument": "OPTION", "option_type": "CE",
                                    "strike_selection": "delta", "strike_value": 0.30, "lots": 1, "order_type": "MARKET"},
                    },
                    {
                        "close_tag": "LEG@2",
                        "new_leg": {"side": "SELL", "instrument": "OPTION", "option_type": "PE",
                                    "strike_selection": "delta", "strike_value": 0.30, "lots": 1, "order_type": "MARKET"},
                    },
                ],
                "target_leg_tags": ["LEG@1", "LEG@2"],
            },
        }
        result = svc._execute_simple_close_open_new(
            name="TEST",
            exec_state=self._base_exec_state(),
            engine_state=self._base_engine_state(),
            config=self._base_config(),
            action=action,
            reader=reader,
        )
        self.assertTrue(result)
        self.assertEqual(svc._adjustment_close_leg.call_count, 2, "Should close both legs")
        self.assertEqual(svc.bot.process_alert.call_count, 2, "Should open two new legs")


# ═════════════════════════════════════════════════════════════════════════════
# 6. End-to-end: sample config survives validate → inject → evaluate pipeline
# ═════════════════════════════════════════════════════════════════════════════

class TestEndToEndSampleConfig(unittest.TestCase):
    """Smoke test: sample builder config through the full compatibility pipeline."""

    def test_validate_then_inject_then_evaluate_exit(self):
        from strategy_runner.condition_engine import evaluate_exit_rules

        cfg = load_sample()

        # Step 1: validate
        is_valid, errors = validate_config(cfg)
        hard = [e for e in errors if e.severity == "error"]
        self.assertTrue(is_valid, f"Config must pass validation. Errors: {hard}")

        # Step 2: inject P&L conditions
        cfg = _inject_pnl_exit_conditions(cfg)
        exit_rules = cfg["exit"]["conditions"]["rules"]
        pnl_rules = [r for r in exit_rules if r.get("parameter") == "combined_pnl"]
        self.assertEqual(len(pnl_rules), 2)

        # Step 3: evaluate exit — profit hit
        state = _make_state(combined_pnl=2500.0)  # above ₹2000 target
        state.tag_map = {"LEG@1": "CE", "LEG@2": "PE"}
        result = evaluate_exit_rules(cfg, state)
        self.assertTrue(result.triggered, "Exit should trigger when combined_pnl=2500 > target=2000")

    def test_validate_then_inject_then_evaluate_exit_sl(self):
        from strategy_runner.condition_engine import evaluate_exit_rules

        cfg = load_sample()
        cfg = _inject_pnl_exit_conditions(cfg)

        state = _make_state(combined_pnl=-3200.0)  # breached ₹3000 SL
        state.tag_map = {"LEG@1": "CE", "LEG@2": "PE"}
        result = evaluate_exit_rules(cfg, state)
        self.assertTrue(result.triggered, "Exit should trigger when combined_pnl=-3200 < SL=-3000")

    def test_adjustment_pipeline_ce_drift(self):
        """Full pipeline: CE delta drifts, tag resolves, rule triggers."""
        cfg = load_sample()
        cfg = _inject_pnl_exit_conditions(cfg)

        state = _make_state(ce_delta=0.55, pe_delta=0.28, combined_pnl=300.0)
        state.tag_map = {"LEG@1": "CE", "LEG@2": "PE"}

        triggered = evaluate_adjustment_rules(cfg, state)
        self.assertTrue(len(triggered) >= 1)
        self.assertEqual(triggered[0].action.get("type"), "simple_close_open_new")
        # Should be CE rule (priority 1)
        leg_swaps = triggered[0].action.get("details", {}).get("leg_swaps", [])
        self.assertEqual(leg_swaps[0]["close_tag"], "LEG@1")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Run in logical order matching the fix areas
    for cls in [
        TestConfigSchemaV3Compat,
        TestTagParameterResolution,
        TestPnLExitInjection,
        TestPerLegConditionGating,
        TestSimpleCloseOpenNew,
        TestEndToEndSampleConfig,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)

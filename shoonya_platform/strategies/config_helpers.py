#!/usr/bin/env python3
"""
Strategy Config Helpers
=======================
Handles v2.0 schema format, ensures all fields present,
and converts between config formats for strategy factory.

Functions:
- ensure_complete_config: Fills in ALL schema fields (even None) for saving
- convert_v2_to_factory_format: Converts v2.0 nested → flat factory format
- normalize_for_validation: Prepares config for validator (adds market_config from identity)

Status: PRODUCTION
Date: 2026-02-13
"""

import copy
import logging
from typing import Dict, Any

logger = logging.getLogger("STRATEGY.CONFIG_HELPERS")

# ==========================================================================
# COMPLETE v2.0 CONFIG TEMPLATE — Every possible field with default/None
# ==========================================================================
COMPLETE_CONFIG_TEMPLATE: Dict[str, Any] = {
    "schema_version": "2.0",
    "name": None,
    "id": None,
    "enabled": False,
    "description": None,
    "tags": [],
    "status": "IDLE",
    "strategy_type": None,
    "created_at": None,
    "updated_at": None,
    "status_updated_at": None,
    "identity": {
        "strategy_type": None,
        "exchange": None,
        "underlying": None,
        "instrument_type": None,
        "expiry_mode": None,
        "expiry_custom": None,
        "product_type": None,
        "order_type": None,
    },
    "market_config": {
        "market_type": "database_market",
        "exchange": None,
        "symbol": None,
        "db_path": None,
    },
    "entry": {
        "timing": {
            "entry_time": None,
            "entry_end_time": None,
            "entry_delay_seconds": 0,
            "active_days": ["mon", "tue", "wed", "thu", "fri"],
            "skip_expiry_day": False,
        },
        "condition": {
            "type": "time_based",
            "price_above": None,
            "price_below": None,
            "iv_above": None,
            "iv_below": None,
            "vix_min": None,
            "vix_max": None,
            "oi_min_lakhs": None,
            "pcr_min": None,
            "pcr_max": None,
            "premium_min": None,
            "indicator": None,
            "indicator_period": 14,
            "indicator_threshold": None,
        },
        "position": {
            "lots": 1,
            "max_open_positions": 1,
            "lot_size_override": None,
            "scale_in_enabled": False,
            "scale_in_lots": 1,
            "scale_in_trigger_pct": None,
        },
        "hedging": {
            "hedge_on_entry": False,
            "hedge_type": "far_otm_buy",
            "hedge_offset": 500,
            "hedge_lots": 1,
        },
        "execution": {
            "auto_confirm": True,
            "retry_on_reject": True,
            "retry_count": 2,
            "slippage_points": 2,
        },
        "legs": {
            "leg_type": "strangle",
            "target_entry_delta": 0.30,
            "atm_offset": 0,
            "ce_offset": 100,
            "pe_offset": 100,
            "strike_selection": "delta",
            "premium_target": None,
        },
    },
    "adjustment": {
        "general": {
            "enabled": True,
            "check_interval_min": 5,
            "max_adj_per_day": 5,
            "max_adj_per_session": 10,
            "cooldown_seconds": 60,
        },
        "delta": {
            "trigger": 0.50,
            "target": 0.20,
            "emergency_trigger": 0.65,
            "mode": "shift",
        },
        "gamma_theta": {
            "max_gamma": None,
            "min_theta": None,
            "gamma_hedge_trigger": None,
            "theta_rebalance_time": None,
        },
        "pnl": {
            "profit_lock_trigger": None,
            "loss_repair_trigger": None,
            "trailing_adj_start": None,
            "trailing_adj_step": None,
            "pnl_action": "roll_strike",
        },
        "iv": {
            "iv_spike_threshold": None,
            "iv_spike_action": "wait",
            "iv_crush_action": "none",
        },
        "roll": {
            "roll_when_itm_by": None,
            "roll_to_atm_offset": 0,
            "roll_only_after": None,
            "auto_roll_before_expiry": False,
        },
        "leg_level": {
            "per_leg_sl": None,
            "per_leg_target": None,
            "per_leg_delta_max": 0.65,
            "rebalance_individual": False,
        },
    },
    "exit": {
        "time": {
            "exit_time": None,
            "force_exit_before_expiry_min": 10,
            "exit_on_expiry_day": True,
            "early_exit_if_profitable_after": None,
        },
        "profit": {
            "target_rupees": None,
            "target_pct": None,
            "target_per_lot": None,
            "target_premium_pct": None,
            "min_profit_to_book": None,
        },
        "stop_loss": {
            "sl_rupees": None,
            "sl_pct": None,
            "sl_per_lot": None,
            "sl_premium_pct": None,
        },
        "trailing": {
            "type": "none",
            "value": None,
            "step": None,
            "activate_at": None,
        },
        "per_leg": {
            "leg_sl": None,
            "leg_sl_pct": None,
            "leg_target": None,
            "leg_target_pct": None,
            "exit_all_on_breach": True,
        },
        "combined": {
            "combined_sl": None,
            "combined_target": None,
        },
        "partial": {
            "enabled": False,
            "partial_at_pct": 50,
            "exit_pct": 50,
        },
        "re_entry": {
            "enabled": False,
            "cooldown_min": 15,
            "max_count": 1,
            "profit_only": False,
        },
        "emergency": {
            "vix_above": None,
            "gap_pct": None,
            "mtm_below": None,
        },
    },
    "rms": {
        "position": {
            "max_value": None,
            "max_lots": 10,
            "max_margin_pct": 70,
            "max_notional": None,
        },
        "daily": {
            "loss_limit": None,
            "profit_target": None,
            "max_trades": 10,
            "max_adjustments": 5,
        },
        "weekly": {
            "loss_limit": None,
            "profit_target": None,
        },
        "monthly": {
            "loss_limit": None,
            "max_drawdown_pct": None,
        },
        "greeks": {
            "max_delta": None,
            "max_gamma": None,
            "max_vega": None,
            "max_theta": None,
        },
        "circuit": {
            "amount": None,
            "pct": None,
            "cooldown_min": 30,
            "kill_switch": False,
        },
        "margin": {
            "buffer_pct": 20,
            "block_above_pct": 85,
        },
        "combined": {
            "track": True,
            "sl": None,
            "target": None,
        },
        "auto": {
            "square_off_on_breach": True,
            "auto_reduce": False,
            "reduce_to_lots": 0,
        },
        "notifications": {
            "telegram": True,
            "email": False,
            "webhook": None,
            "on_entry": True,
            "on_exit": True,
            "on_adjustment": True,
            "on_risk_breach": True,
        },
    },
}


def _deep_merge(template: dict, data: dict) -> dict:
    """
    Deep merge data into template.
    
    - Template provides the complete key structure with defaults
    - Data values override template defaults where present
    - Keys in data but not in template are preserved
    - Nested dicts are merged recursively
    """
    result = {}
    for key, default_val in template.items():
        if key in data:
            if isinstance(default_val, dict) and isinstance(data[key], dict):
                result[key] = _deep_merge(default_val, data[key])
            else:
                result[key] = data[key]
        else:
            # Use template default (deep copy to avoid shared references)
            if isinstance(default_val, (dict, list)):
                result[key] = copy.deepcopy(default_val)
            else:
                result[key] = default_val
    # Preserve keys in data that are NOT in template
    for key in data:
        if key not in template:
            result[key] = data[key]
    return result


def ensure_complete_config(config: dict) -> dict:
    """
    Ensure a strategy config has ALL fields from the v2.0 schema.
    Missing fields are set to None/default values.
    Also syncs market_config from identity for backward compatibility.
    
    This is THE function to call before saving any config to disk.
    Guarantees: Every possible field exists in the output, even if None.
    """
    result = _deep_merge(COMPLETE_CONFIG_TEMPLATE, config)

    # --- Sync identity ↔ market_config ---
    identity = result.get("identity", {})
    mc = result.get("market_config", {})

    # identity → market_config
    if identity.get("exchange") and not mc.get("exchange"):
        mc["exchange"] = identity["exchange"]
    if identity.get("underlying") and not mc.get("symbol"):
        mc["symbol"] = identity["underlying"]
    result["market_config"] = mc

    # market_config → identity (reverse sync)
    if mc.get("exchange") and not identity.get("exchange"):
        identity["exchange"] = mc["exchange"]
    if mc.get("symbol") and not identity.get("underlying"):
        identity["underlying"] = mc["symbol"]
    result["identity"] = identity

    # --- Sync strategy_type at root ↔ identity ---
    if identity.get("strategy_type") and not result.get("strategy_type"):
        result["strategy_type"] = identity["strategy_type"]
    elif result.get("strategy_type") and not identity.get("strategy_type"):
        result["identity"]["strategy_type"] = result["strategy_type"]

    # --- Derive id from name if missing ---
    name = result.get("name")
    if name and not result.get("id"):
        result["id"] = name.upper().replace(" ", "_").strip("_")

    return result


def convert_v2_to_factory_format(config: dict) -> dict:
    """
    Convert v2.0 schema config to flat format expected by strategy_factory.create_strategy().
    
    The factory expects flat keys like:
      strategy_type, strategy_name, exchange, symbol, instrument_type,
      entry_time, exit_time, order_type, product, lot_qty, params, etc.
    
    This function extracts values from v2.0 nested structure and builds
    a flat dict the factory can consume.
    """
    identity = config.get("identity", {}) or {}
    entry = config.get("entry", {}) or {}
    exit_cfg = config.get("exit", {}) or {}
    adjustment = config.get("adjustment", {}) or {}
    mc = config.get("market_config", {}) or {}

    # Determine values: try v2.0 nested first, then flat fallback
    exchange = identity.get("exchange") or mc.get("exchange") or config.get("exchange", "")
    symbol = identity.get("underlying") or mc.get("symbol") or config.get("symbol", "")
    strategy_type = identity.get("strategy_type") or config.get("strategy_type", "")
    instrument_type = identity.get("instrument_type") or config.get("instrument_type", "OPTIDX")
    order_type = identity.get("order_type") or config.get("order_type", "MARKET")
    product_type = identity.get("product_type") or config.get("product", "NRML")

    # Timing
    timing = entry.get("timing", {}) or {}
    time_cfg = exit_cfg.get("time", {}) or {}
    entry_time = timing.get("entry_time") or config.get("entry_time", "09:20")
    exit_time = time_cfg.get("exit_time") or config.get("exit_time", "15:20")

    # Position
    position = entry.get("position", {}) or {}
    lots = position.get("lots") or config.get("lot_qty", 1)

    # Build params dict for strategy-specific parameters
    delta_cfg = adjustment.get("delta", {}) or {}
    legs_cfg = entry.get("legs", {}) or {}
    general_adj = adjustment.get("general", {}) or {}
    pnl_cfg = adjustment.get("pnl", {}) or {}
    leg_level = adjustment.get("leg_level", {}) or {}

    # Start with existing params if any (for flat-format configs)
    params = dict(config.get("params", {}) or {})

    # Overlay v2.0 nested values into params (only if key not already set)
    if legs_cfg.get("target_entry_delta") is not None:
        params.setdefault("target_entry_delta", legs_cfg["target_entry_delta"])
    if delta_cfg.get("trigger") is not None:
        params.setdefault("delta_adjust_trigger", delta_cfg["trigger"])
    if delta_cfg.get("emergency_trigger") is not None:
        params.setdefault("max_leg_delta", delta_cfg["emergency_trigger"])
    elif leg_level.get("per_leg_delta_max") is not None:
        params.setdefault("max_leg_delta", leg_level["per_leg_delta_max"])
    if pnl_cfg.get("profit_lock_trigger") is not None:
        params.setdefault("profit_step", pnl_cfg["profit_lock_trigger"])
    params.setdefault(
        "cooldown_seconds",
        general_adj.get("cooldown_seconds") or config.get("cooldown_seconds", 300),
    )
    params.setdefault("instrument_type", instrument_type)
    params.setdefault(
        "expiry_mode",
        identity.get("expiry_mode") or "weekly_current",
    )

    flat = {
        "strategy_type": strategy_type,
        "strategy_name": config.get("name") or config.get("strategy_name", ""),
        "strategy_version": config.get("schema_version", "1.0"),
        "exchange": exchange,
        "symbol": symbol,
        "instrument_type": instrument_type,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "order_type": order_type,
        "product": product_type,
        "lot_qty": int(lots) if lots else 1,
        "enabled": config.get("enabled", False),
        "params": params,
        "max_positions": position.get("max_open_positions") or config.get("max_positions", 1),
        "poll_interval": float(config.get("poll_interval", 2.0)),
        "cooldown_seconds": int(
            general_adj.get("cooldown_seconds") or config.get("cooldown_seconds", 300)
        ),
        # Preserve market_config for runner registration
        "market_config": {
            "market_type": mc.get("market_type", "database_market"),
            "exchange": exchange,
            "symbol": symbol,
            "db_path": mc.get("db_path"),
        },
    }

    logger.info(
        f"Converted v2.0 config to factory format: {flat.get('strategy_name')} "
        f"({flat.get('strategy_type')}) | {exchange}:{symbol}"
    )
    return flat


def is_v2_config(config: dict) -> bool:
    """Check if a config dict is in v2.0 nested format."""
    return (
        config.get("schema_version") == "2.0"
        or "identity" in config
        or isinstance(config.get("entry", {}).get("timing"), dict)
    )


def get_factory_config(config: dict) -> dict:
    """
    Get factory-ready config from any format.
    
    Auto-detects v2.0 vs flat format and converts if needed.
    """
    if is_v2_config(config):
        return convert_v2_to_factory_format(config)
    return config

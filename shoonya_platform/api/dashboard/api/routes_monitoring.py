# ======================================================================
# ROUTES: Monitoring Positions, Leg Greeks, Live Positions Overview,
#         Index Tokens
# Extracted from router.py during modularisation.
# ======================================================================
from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional, Any
from datetime import datetime
import time
import logging

from shoonya_platform.api.dashboard.deps import require_dashboard_auth
from shoonya_platform.market_data.feeds import index_tokens_subscriber
from shoonya_platform.api.dashboard.api._shared import (
    logger,
    get_broker,
    get_system,
    _mode_from_saved_file,
)

sub_router = APIRouter()

# ==================================================
# ADVANCED MONITORING - LEG-WISE & STRATEGY GREEKS
# ==================================================

@sub_router.get("/monitoring/strategy-positions")
def get_strategy_positions_detailed(
    strategy_name: Optional[str] = Query(None, description="Filter by strategy name"),
    ctx=Depends(require_dashboard_auth),
    broker=Depends(get_broker),
    system=Depends(get_system),
):
    """Get detailed position monitoring with leg-wise greeks."""
    try:
        positions = broker.get_positions() or []
        orders = system.get_orders(500) or []

        legs_by_symbol = {}
        strategy_positions = {}

        for pos in positions:
            symbol = pos.get("tsym", "")
            netqty = int(pos.get("netqty", 0))

            if netqty == 0 or not symbol:
                continue

            order_detail = next((o for o in orders if getattr(o, "symbol", None) == symbol), None)

            leg_data = {
                "symbol": symbol,
                "exchange": pos.get("exch"),
                "qty": abs(netqty),
                "side": "BUY" if netqty > 0 else "SELL",
                "entry_price": float(getattr(order_detail, "price", 0) or 0) if order_detail else 0.0,
                "ltp": float(pos.get("ltp", 0) or 0),
                "avg_price": float(pos.get("avgprc", 0) or 0),

                "delta": float(getattr(order_detail, "delta", 0) or 0) if order_detail else 0.0,
                "gamma": float(getattr(order_detail, "gamma", 0) or 0) if order_detail else 0.0,
                "theta": float(getattr(order_detail, "theta", 0) or 0) if order_detail else 0.0,
                "vega": float(getattr(order_detail, "vega", 0) or 0) if order_detail else 0.0,

                "realized_pnl": float(pos.get("rpnl", 0) or 0),
                "unrealized_pnl": float(pos.get("upnl", 0) or 0),
                "total_pnl": float(pos.get("upnl", 0) or 0) + float(pos.get("rpnl", 0) or 0),
            }

            legs_by_symbol[symbol] = leg_data

            strat = (getattr(order_detail, "strategy_name", None) if order_detail else None) or strategy_name or "UNKNOWN"

            if strat not in strategy_positions:
                strategy_positions[strat] = {
                    "strategy_name": strat,
                    "legs": [],
                    "combined_delta": 0.0,
                    "combined_gamma": 0.0,
                    "combined_theta": 0.0,
                    "combined_vega": 0.0,
                    "total_unrealized_pnl": 0.0,
                    "total_realized_pnl": 0.0,
                    "leg_count": 0,
                }

            strategy_positions[strat]["legs"].append(leg_data)
            strategy_positions[strat]["combined_delta"] += leg_data["delta"]
            strategy_positions[strat]["combined_gamma"] += leg_data["gamma"]
            strategy_positions[strat]["combined_theta"] += leg_data["theta"]
            strategy_positions[strat]["combined_vega"] += leg_data["vega"]
            strategy_positions[strat]["total_unrealized_pnl"] += leg_data["unrealized_pnl"]
            strategy_positions[strat]["total_realized_pnl"] += leg_data["realized_pnl"]
            strategy_positions[strat]["leg_count"] += 1

        if strategy_name and strategy_name in strategy_positions:
            filtered_strategies = {strategy_name: strategy_positions[strategy_name]}
        elif strategy_name:
            filtered_strategies = {}  # requested strategy not found — return empty
        else:
            filtered_strategies = strategy_positions

        return {
            "timestamp": datetime.now().isoformat(),
            "total_symbols": len(legs_by_symbol),
            "total_strategies": len(filtered_strategies),
            "legs_detailed": list(legs_by_symbol.values()),
            "strategy_positions": list(filtered_strategies.values()),
            "summary": {
                "total_unrealized_pnl": sum(s["total_unrealized_pnl"] for s in filtered_strategies.values()),
                "total_realized_pnl": sum(s["total_realized_pnl"] for s in filtered_strategies.values()),
                "portfolio_delta": sum(s["combined_delta"] for s in filtered_strategies.values()),
                "portfolio_gamma": sum(s["combined_gamma"] for s in filtered_strategies.values()),
                "portfolio_theta": sum(s["combined_theta"] for s in filtered_strategies.values()),
                "portfolio_vega": sum(s["combined_vega"] for s in filtered_strategies.values()),
            }
        }

    except Exception as e:
        logger.exception("Failed to get strategy positions")
        raise HTTPException(status_code=500, detail=str(e))


@sub_router.get("/monitoring/leg-greeks/{symbol}")
def get_leg_greeks(
    symbol: str,
    ctx=Depends(require_dashboard_auth),
    broker=Depends(get_broker),
    system=Depends(get_system),
):
    """Get detailed greeks and monitoring data for a specific leg/symbol."""
    try:
        positions = broker.get_positions() or []
        orders = system.get_orders(500) or []

        position = next((p for p in positions if p.get("tsym") == symbol), None)
        if not position:
            raise HTTPException(status_code=404, detail=f"Position not found: {symbol}")

        order = next((o for o in orders if getattr(o, "symbol", None) == symbol), None)
        netqty = int(position.get("netqty", 0))

        return {
            "symbol": symbol,
            "exchange": position.get("exch"),
            "position": {
                "qty": abs(netqty),
                "side": "BUY" if netqty > 0 else "SELL",
                "entry_price": float(getattr(order, "price", 0) or 0) if order else 0.0,
                "avg_price": float(position.get("avgprc", 0) or 0),
                "ltp": float(position.get("ltp", 0) or 0),
            },
            "pnl": {
                "realized": float(position.get("rpnl", 0) or 0),
                "unrealized": float(position.get("upnl", 0) or 0),
                "total": float(position.get("upnl", 0) or 0) + float(position.get("rpnl", 0) or 0),
            },
            "greeks": {
                "delta": float(getattr(order, "delta", 0) or 0) if order else 0.0,
                "gamma": float(getattr(order, "gamma", 0) or 0) if order else 0.0,
                "theta": float(getattr(order, "theta", 0) or 0) if order else 0.0,
                "vega": float(getattr(order, "vega", 0) or 0) if order else 0.0,
                "rho": float(getattr(order, "rho", 0) or 0) if order else 0.0,
            },
            "metadata": {
                "strategy": getattr(order, "strategy_name", "UNKNOWN") if order else "UNKNOWN",
                "order_count": len([o for o in orders if getattr(o, "symbol", None) == symbol]),
                "updated_at": position.get("upl_time", ""),
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get leg greeks for {symbol}")
        raise HTTPException(status_code=500, detail=str(e))


@sub_router.get("/monitoring/live-positions-overview")
def get_live_positions_overview(
    ctx=Depends(require_dashboard_auth),
    broker=Depends(get_broker),
    system=Depends(get_system),
):
    """
    Live monitoring view for strategy page.

    Classifies each open broker position into:
    - strategy_active: linked to a strategy currently running in executor
    - strategy_inactive: linked to strategy orders, but strategy not running now
    - orphan: no strategy linkage (manual/external/orphan rule flow)
    """
    try:
        bot = ctx["bot"]
        positions = broker.get_positions() or []
        orders = system.get_orders(2000) or []

        # Active strategy names in-memory (executor/live registry).
        with bot._live_strategies_lock:
            active_strategies = set(bot._live_strategies.keys())

        def _order_ts(order_obj: Any) -> float:
            for attr in ("updated_at", "created_at"):
                value = getattr(order_obj, attr, None)
                if value is None:
                    continue
                if isinstance(value, datetime):
                    return value.timestamp()
                if isinstance(value, (int, float)):
                    return float(value)
                try:
                    return datetime.fromisoformat(str(value)).timestamp()
                except Exception:
                    continue
            return 0.0

        def _is_strategy_name(name: str) -> bool:
            if not name:
                return False
            clean = str(name).strip()
            if not clean:
                return False
            upper = clean.upper()
            if upper in {"UNKNOWN", "N/A", "NONE"}:
                return False
            if upper.startswith("ORPHAN_RULE_"):
                return False
            return True

        def _as_float(value: Any, default: float = 0.0) -> float:
            try:
                return float(value or 0)
            except Exception:
                return default

        # Keep latest known order metadata by symbol.
        latest_by_symbol: dict[str, tuple[float, str, Any]] = {}
        for order in orders:
            symbol = str(getattr(order, "symbol", "") or "").strip()
            if not symbol:
                continue
            strategy_name = str(getattr(order, "strategy_name", "") or "").strip()
            ts = _order_ts(order)
            prev = latest_by_symbol.get(symbol)
            if prev is None or ts >= prev[0]:
                latest_by_symbol[symbol] = (ts, strategy_name, order)

        classified: list[dict[str, Any]] = []
        seen_symbol_owner: set[tuple[str, str]] = set()
        for pos in positions:
            netqty = int(pos.get("netqty", 0) or 0)
            if netqty == 0:
                continue

            symbol = str(pos.get("tsym", "") or "").strip()
            if not symbol:
                continue

            mapped_strategy = ""
            order_detail = None
            if symbol in latest_by_symbol:
                mapped_strategy = latest_by_symbol[symbol][1]
                order_detail = latest_by_symbol[symbol][2]

            strategy_generated = _is_strategy_name(mapped_strategy)
            is_active = strategy_generated and mapped_strategy in active_strategies
            if is_active:
                owner_type = "strategy_active"
            elif strategy_generated:
                owner_type = "strategy_inactive"
            else:
                owner_type = "orphan"

            qty = abs(netqty)
            side = "BUY" if netqty > 0 else "SELL"
            ltp = float(pos.get("ltp", pos.get("lp", 0)) or 0)
            avg = float(pos.get("avgprc", pos.get("avg_price", 0)) or 0)
            rpnl = float(pos.get("rpnl", pos.get("realized_pnl", 0)) or 0)
            upnl = float(pos.get("upnl", pos.get("urmtom", 0)) or 0)
            total_pnl = rpnl + upnl

            item = {
                "symbol": symbol,
                "exchange": pos.get("exch"),
                "qty": qty,
                "side": side,
                "netqty": netqty,
                "position_source": "BROKER",
                "avg_price": avg,
                "ltp": ltp,
                "realized_pnl": rpnl,
                "unrealized_pnl": upnl,
                "total_pnl": total_pnl,
                "delta": _as_float(getattr(order_detail, "delta", 0) if order_detail else 0),
                "gamma": _as_float(getattr(order_detail, "gamma", 0) if order_detail else 0),
                "theta": _as_float(getattr(order_detail, "theta", 0) if order_detail else 0),
                "vega": _as_float(getattr(order_detail, "vega", 0) if order_detail else 0),
                "strategy_name": mapped_strategy if strategy_generated else None,
                "owner_type": owner_type,
                "updated_at": pos.get("upl_time") or "",
            }
            classified.append(item)
            seen_symbol_owner.add((symbol, owner_type))

        # Add virtual executor-state positions.
        svc = getattr(bot, "strategy_executor_service", None)
        if svc is not None:
            exec_states = dict(getattr(svc, "_exec_states", {}) or {})
            strategy_cfgs = dict(getattr(svc, "_strategies", {}) or {})

            for strat_name, state in exec_states.items():
                try:
                    if not bool(getattr(state, "any_leg_active", False)):
                        continue
                    cfg = strategy_cfgs.get(strat_name, {})
                    mode = "LIVE"
                    try:
                        mode = "MOCK" if bool(getattr(svc, "_is_paper_mode")(cfg)) else "LIVE"
                    except Exception:
                        identity_cfg = cfg.get("identity", {}) or {}
                        mode = "MOCK" if bool(identity_cfg.get("paper_mode") or identity_cfg.get("test_mode")) else "LIVE"

                    owner_type = "strategy_active" if strat_name in active_strategies else "strategy_inactive"
                    now_iso = datetime.now().isoformat()
                    for leg in (getattr(state, "legs", {}) or {}).values():
                        if not bool(getattr(leg, "is_active", False)):
                            continue
                        symbol = str(
                            getattr(leg, "trading_symbol", None)
                            or getattr(leg, "symbol", "")
                        ).strip()
                        lots_qty = int(getattr(leg, "qty", 0) or 0)
                        qty = lots_qty
                        try:
                            exec_obj = (getattr(svc, "_executors", {}) or {}).get(strat_name)
                            if exec_obj is not None and hasattr(exec_obj, "_lots_to_order_qty"):
                                qty = int(exec_obj._lots_to_order_qty(lots_qty, leg))
                        except Exception:
                            qty = lots_qty
                        if not symbol or lots_qty <= 0:
                            continue
                        key = (symbol, owner_type)
                        if key in seen_symbol_owner:
                            continue
                        seen_symbol_owner.add(key)

                        side_val = getattr(getattr(leg, "side", None), "value", getattr(leg, "side", ""))
                        side_s = str(side_val or "").upper()
                        delta = float(getattr(leg, "delta", 0) or 0)
                        gamma = float(getattr(leg, "gamma", 0) or 0)
                        theta = float(getattr(leg, "theta", 0) or 0)
                        vega = float(getattr(leg, "vega", 0) or 0)
                        upnl = float(getattr(leg, "pnl", 0) or 0)

                        classified.append({
                            "symbol": symbol,
                            "exchange": (cfg.get("identity", {}) or {}).get("exchange", ""),
                            "qty": qty,
                            "side": side_s,
                            "netqty": int(qty if side_s == "BUY" else -qty),
                            "position_source": "PAPER" if mode == "MOCK" else "EXECUTOR_STATE",
                            "avg_price": float(getattr(leg, "entry_price", 0) or 0),
                            "ltp": float(getattr(leg, "ltp", 0) or 0),
                            "realized_pnl": 0.0,
                            "unrealized_pnl": upnl,
                            "total_pnl": upnl,
                            "delta": delta,
                            "gamma": gamma,
                            "theta": theta,
                            "vega": vega,
                            "strategy_name": strat_name,
                            "owner_type": owner_type,
                            "updated_at": now_iso,
                        })
                except Exception as leg_err:
                    logger.debug("Skipping paper leg mapping for %s: %s", strat_name, leg_err)

        strategy_positions = [p for p in classified if p["owner_type"] != "orphan"]
        orphan_positions = [p for p in classified if p["owner_type"] == "orphan"]
        leg_snapshot: dict[str, Any] = {}
        strategy_modes: dict[str, str] = {}
        completed_strategy_groups: list[dict[str, Any]] = []
        if svc is not None:
            try:
                getter = getattr(svc, "get_strategy_leg_monitor_snapshot", None)
                if callable(getter):
                    result = getter()
                    if isinstance(result, dict):
                        leg_snapshot = result
                    else:
                        logger.debug("Leg monitor snapshot returned non-dict, ignoring")
            except Exception as snap_err:
                logger.debug("Could not fetch strategy leg monitor snapshot: %s", snap_err)
            try:
                mode_getter = getattr(svc, "get_strategy_mode", None)
                if callable(mode_getter):
                    for strat in set(list(getattr(svc, "_strategies", {}).keys()) + list((leg_snapshot or {}).keys())):
                        strategy_modes[strat] = str(mode_getter(strat) or "LIVE").upper()
            except Exception as mode_err:
                logger.debug("Could not fetch strategy modes for monitor: %s", mode_err)
            try:
                completed_getter = getattr(svc, "get_completed_strategy_monitor_history", None)
                if callable(completed_getter):
                    result = completed_getter(limit=50)
                    if isinstance(result, list):
                        for row in result:
                            if isinstance(row, dict):
                                strat_name = str(row.get("strategy_name", "") or "")
                                mode_val = str(row.get("mode", "") or "").upper()
                                if mode_val not in {"LIVE", "MOCK"} and strat_name:
                                    row["mode"] = _mode_from_saved_file(strat_name)
                        completed_strategy_groups = result
            except Exception as history_err:
                logger.debug("Could not fetch completed strategy monitor history: %s", history_err)

        def _group_mode(strategy_name_val: str) -> str:
            known = str(strategy_modes.get(strategy_name_val, "") or "").upper()
            if known in {"LIVE", "MOCK"}:
                return known
            resolved = _mode_from_saved_file(strategy_name_val)
            strategy_modes[strategy_name_val] = resolved
            return resolved

        by_strategy: dict[str, dict[str, Any]] = {}
        for p in strategy_positions:
            strat = p.get("strategy_name") or "UNKNOWN"
            if strat not in by_strategy:
                by_strategy[strat] = {
                    "strategy_name": strat,
                    "mode": _group_mode(strat),
                    "active": strat in active_strategies,
                    "adjustments_today": 0,
                    "lifetime_adjustments": 0,
                    "last_adjustment_time": None,
                    "leg_count": 0,
                    "total_qty": 0,
                    "total_pnl": 0.0,
                    "realized_pnl": 0.0,
                    "unrealized_pnl": 0.0,
                    "combined_delta": 0.0,
                    "combined_gamma": 0.0,
                    "combined_theta": 0.0,
                    "combined_vega": 0.0,
                    "active_legs": 0,
                    "closed_legs": 0,
                    "positions": [],
                    "all_legs": [],
                }
            by_strategy[strat]["leg_count"] += 1
            by_strategy[strat]["total_qty"] += int(p.get("qty", 0) or 0)
            by_strategy[strat]["total_pnl"] += float(p.get("total_pnl", 0) or 0)
            by_strategy[strat]["realized_pnl"] += float(p.get("realized_pnl", 0) or 0)
            by_strategy[strat]["unrealized_pnl"] += float(p.get("unrealized_pnl", 0) or 0)
            by_strategy[strat]["combined_delta"] += float(p.get("delta", 0) or 0)
            by_strategy[strat]["combined_gamma"] += float(p.get("gamma", 0) or 0)
            by_strategy[strat]["combined_theta"] += float(p.get("theta", 0) or 0)
            by_strategy[strat]["combined_vega"] += float(p.get("vega", 0) or 0)
            by_strategy[strat]["active_legs"] += 1
            by_strategy[strat]["positions"].append(p)

        # Merge full strategy leg history from executor snapshot.
        for strat, snap in (leg_snapshot or {}).items():
            if strat not in by_strategy:
                by_strategy[strat] = {
                    "strategy_name": strat,
                    "mode": _group_mode(strat),
                    "active": strat in active_strategies,
                    "adjustments_today": 0,
                    "lifetime_adjustments": 0,
                    "last_adjustment_time": None,
                    "leg_count": 0,
                    "total_qty": 0,
                    "total_pnl": 0.0,
                    "realized_pnl": 0.0,
                    "unrealized_pnl": 0.0,
                    "combined_delta": 0.0,
                    "combined_gamma": 0.0,
                    "combined_theta": 0.0,
                    "combined_vega": 0.0,
                    "active_legs": 0,
                    "closed_legs": 0,
                    "positions": [],
                    "all_legs": [],
                }
            group = by_strategy[strat]
            legs = list((snap or {}).get("legs") or [])
            legs.sort(key=lambda x: str(x.get("updated_at") or x.get("opened_at") or ""), reverse=True)
            group["all_legs"] = legs
            group["active_leg_rows"] = [l for l in legs if str(l.get("status", "")).upper() == "ACTIVE"]
            group["closed_leg_rows"] = [l for l in legs if str(l.get("status", "")).upper() == "CLOSED"]
            group["active_legs"] = int((snap or {}).get("active_legs", group.get("active_legs", 0)) or 0)
            group["closed_legs"] = int((snap or {}).get("closed_legs", 0) or 0)
            group["realized_pnl"] = float((snap or {}).get("realized_pnl", group.get("realized_pnl", 0.0)) or 0.0)
            group["unrealized_pnl"] = float((snap or {}).get("unrealized_pnl", group.get("unrealized_pnl", 0.0)) or 0.0)
            group["adjustments_today"] = int((snap or {}).get("adjustments_today", group.get("adjustments_today", 0)) or 0)
            group["lifetime_adjustments"] = int((snap or {}).get("lifetime_adjustments", group.get("lifetime_adjustments", 0)) or 0)
            group["last_adjustment_time"] = (snap or {}).get("last_adjustment_time", group.get("last_adjustment_time"))
            group["total_pnl"] = float(group["realized_pnl"] + group["unrealized_pnl"])
            active_legs = list(group["active_leg_rows"])
            if active_legs:
                group["combined_delta"] = sum(float(l.get("delta", 0) or 0) for l in active_legs)
                group["combined_gamma"] = sum(float(l.get("gamma", 0) or 0) for l in active_legs)
                group["combined_theta"] = sum(float(l.get("theta", 0) or 0) for l in active_legs)
                group["combined_vega"] = sum(float(l.get("vega", 0) or 0) for l in active_legs)

            opened_ts_all = []
            closed_ts_all = []
            opened_ts_active = []
            for l in legs:
                raw_opened = l.get("opened_at")
                raw_closed = l.get("closed_at")
                status_u = str(l.get("status", "")).upper()
                try:
                    if raw_opened:
                        ts_open = datetime.fromisoformat(str(raw_opened)).timestamp()
                        opened_ts_all.append(ts_open)
                        if status_u == "ACTIVE":
                            opened_ts_active.append(ts_open)
                except Exception:
                    pass
                try:
                    if raw_closed:
                        closed_ts_all.append(datetime.fromisoformat(str(raw_closed)).timestamp())
                except Exception:
                    pass

            if group["active_legs"] > 0 and opened_ts_active:
                runtime_seconds = int(max(0, time.time() - min(opened_ts_active)))
                runtime_state = "RUNNING"
            elif opened_ts_all and closed_ts_all:
                runtime_seconds = int(max(0, max(closed_ts_all) - min(opened_ts_all)))
                runtime_state = "COMPLETED"
            else:
                runtime_seconds = 0
                runtime_state = "IDLE"

            group["runtime_seconds"] = runtime_seconds
            group["runtime_state"] = runtime_state
            group["analytics"] = {
                "win_legs": len([l for l in group["closed_leg_rows"] if float(l.get("realized_pnl", 0) or 0) > 0]),
                "loss_legs": len([l for l in group["closed_leg_rows"] if float(l.get("realized_pnl", 0) or 0) < 0]),
                "flat_legs": len([l for l in group["closed_leg_rows"] if float(l.get("realized_pnl", 0) or 0) == 0]),
                "avg_realized_per_closed_leg": (
                    float(group["realized_pnl"]) / float(group["closed_legs"])
                    if float(group["closed_legs"] or 0) > 0
                    else 0.0
                ),
            }

        # Fallback for strategies without explicit leg snapshot.
        for group in by_strategy.values():
            if group.get("all_legs"):
                continue
            fallback_legs = []
            for p in group.get("positions", []):
                fallback_legs.append({
                    "strategy_name": group.get("strategy_name"),
                    "exchange": p.get("exchange"),
                    "symbol": p.get("symbol"),
                    "side": p.get("side"),
                    "qty": int(p.get("qty", 0) or 0),
                    "entry_price": float(p.get("avg_price", 0) or 0),
                    "exit_price": None,
                    "status": "ACTIVE",
                    "source": p.get("position_source") or "BROKER",
                    "realized_pnl": float(p.get("realized_pnl", 0) or 0),
                    "unrealized_pnl": float(p.get("unrealized_pnl", 0) or 0),
                    "total_pnl": float(p.get("total_pnl", 0) or 0),
                    "delta": float(p.get("delta", 0) or 0),
                    "gamma": float(p.get("gamma", 0) or 0),
                    "theta": float(p.get("theta", 0) or 0),
                    "vega": float(p.get("vega", 0) or 0),
                    "opened_at": p.get("updated_at") or "",
                    "closed_at": None,
                    "updated_at": p.get("updated_at") or "",
                })
            group["all_legs"] = fallback_legs
            if not str(group.get("mode", "")).strip():
                group["mode"] = _group_mode(group.get("strategy_name") or "")
            group["active_leg_rows"] = [l for l in fallback_legs if str(l.get("status", "")).upper() == "ACTIVE"]
            group["closed_leg_rows"] = [l for l in fallback_legs if str(l.get("status", "")).upper() == "CLOSED"]
            group["runtime_seconds"] = 0
            group["runtime_state"] = "IDLE"
            group["analytics"] = {
                "win_legs": 0,
                "loss_legs": 0,
                "flat_legs": 0,
                "avg_realized_per_closed_leg": 0.0,
            }

        orphan_aggregate = {
            "leg_count": len(orphan_positions),
            "total_pnl": sum(float(p.get("total_pnl", 0) or 0) for p in orphan_positions),
            "realized_pnl": sum(float(p.get("realized_pnl", 0) or 0) for p in orphan_positions),
            "unrealized_pnl": sum(float(p.get("unrealized_pnl", 0) or 0) for p in orphan_positions),
            "combined_delta": sum(float(p.get("delta", 0) or 0) for p in orphan_positions),
            "combined_gamma": sum(float(p.get("gamma", 0) or 0) for p in orphan_positions),
            "combined_theta": sum(float(p.get("theta", 0) or 0) for p in orphan_positions),
            "combined_vega": sum(float(p.get("vega", 0) or 0) for p in orphan_positions),
        }

        strategy_realized = sum(float(g.get("realized_pnl", 0) or 0) for g in by_strategy.values())
        strategy_unrealized = sum(float(g.get("unrealized_pnl", 0) or 0) for g in by_strategy.values())
        portfolio_realized = strategy_realized + float(orphan_aggregate.get("realized_pnl", 0) or 0)
        portfolio_unrealized = strategy_unrealized + float(orphan_aggregate.get("unrealized_pnl", 0) or 0)

        return {
            "timestamp": datetime.now().isoformat(),
            "active_strategy_names": sorted(active_strategies),
            "summary": {
                "total_open_positions": len(classified),
                "strategy_linked_positions": len(strategy_positions),
                "orphan_positions": len(orphan_positions),
                "strategy_active_positions": len([p for p in classified if p["owner_type"] == "strategy_active"]),
                "strategy_inactive_positions": len([p for p in classified if p["owner_type"] == "strategy_inactive"]),
                "portfolio_total_pnl": float(portfolio_realized + portfolio_unrealized),
                "portfolio_realized_pnl": float(portfolio_realized),
                "portfolio_unrealized_pnl": float(portfolio_unrealized),
                "strategy_realized_pnl": float(strategy_realized),
                "strategy_unrealized_pnl": float(strategy_unrealized),
                "total_strategy_legs_tracked": sum(len(g.get("all_legs") or []) for g in by_strategy.values()),
                "total_closed_strategy_legs": sum(int(g.get("closed_legs", 0) or 0) for g in by_strategy.values()),
                "completed_strategy_runs": len(completed_strategy_groups),
                "portfolio_combined_delta": sum(float(p.get("delta", 0) or 0) for p in classified),
                "portfolio_combined_gamma": sum(float(p.get("gamma", 0) or 0) for p in classified),
                "portfolio_combined_theta": sum(float(p.get("theta", 0) or 0) for p in classified),
                "portfolio_combined_vega": sum(float(p.get("vega", 0) or 0) for p in classified),
            },
            "strategy_groups": list(by_strategy.values()),
            "completed_strategy_groups": completed_strategy_groups,
            "orphan_aggregate": orphan_aggregate,
            "orphan_positions": orphan_positions,
            "all_positions": classified,
        }
    except Exception as e:
        logger.exception("Failed to build live positions overview")
        raise HTTPException(status_code=500, detail=str(e))


# ======================================================================
# INDEX TOKENS API
# ======================================================================

@sub_router.get("/index-tokens/prices")
def get_index_tokens_prices(
    symbols: Optional[str] = Query(
        None,
        description="Comma-separated list (e.g., 'NIFTY,BANKNIFTY,SENSEX'). If None, returns all subscribed."
    ),
    ctx=Depends(require_dashboard_auth),
):
    """Get live index token prices from the live feed."""
    try:
        requested = []
        if symbols:
            requested = [s.strip().upper() for s in symbols.split(",")]

        subscribed = index_tokens_subscriber.get_subscribed_indices()

        indices_data = index_tokens_subscriber.get_index_prices(
            indices=requested if requested else None,
            include_missing=False
        )

        result = {}
        for symbol, data in indices_data.items():
            if data:
                result[symbol] = {
                    "ltp": data.get("ltp"),
                    "pc": data.get("pc"),
                    "v": data.get("v"),
                    "o": data.get("o"),
                    "h": data.get("h"),
                    "l": data.get("l"),
                    "c": data.get("c"),
                    "ap": data.get("ap"),
                    "oi": data.get("oi"),
                    "tt": data.get("tt"),
                    "exchange": data.get("exchange"),
                    "token": data.get("token"),
                }

        return {
            "subscribed": subscribed,
            "indices": result,
            "timestamp": time.time(),
        }

    except Exception as e:
        logger.error(f"Error fetching index tokens: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching index prices: {str(e)}"
        )


@sub_router.get("/index-tokens/list")
def list_available_indices(ctx=Depends(require_dashboard_auth)):
    """Get list of all available index tokens."""
    try:
        all_indices = index_tokens_subscriber.get_all_available_indices()
        subscribed = index_tokens_subscriber.get_subscribed_indices()
        major = index_tokens_subscriber.MAJOR_INDICES

        enriched = {}
        for symbol, friendly_name in all_indices.items():
            meta = index_tokens_subscriber.get_index_metadata(symbol)
            if meta:
                enriched[symbol] = meta

        return {
            "all": enriched,
            "subscribed": subscribed,
            "major": major,
        }

    except Exception as e:
        logger.error(f"Error listing indices: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error listing indices: {str(e)}"
        )


# ==================================================
# DELETE COMPLETED STRATEGY HISTORY
# ==================================================

@sub_router.delete("/monitoring/completed-history")
def delete_completed_history(
    strategy_name: Optional[str] = Query(None, description="Delete only entries for this strategy"),
    archived_at: Optional[str] = Query(None, description="Delete specific entry by archived_at timestamp"),
    ctx=Depends(require_dashboard_auth),
):
    """Delete completed strategy monitor history entries."""
    bot = ctx.get("bot")
    svc = getattr(bot, "strategy_executor_service", None) if bot else None
    if not svc:
        raise HTTPException(status_code=503, detail="Strategy executor service not available")
    try:
        count = svc.delete_completed_strategy_monitor_history(
            strategy_name=strategy_name or None,
            archived_at=archived_at or None,
        )
        return {"status": "ok", "deleted": count}
    except Exception as e:
        logger.error(f"Error deleting completed history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

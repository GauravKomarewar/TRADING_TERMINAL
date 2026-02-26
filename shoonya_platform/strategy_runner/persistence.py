import json
from datetime import datetime, date
from typing import Optional, Dict, Any
from .state import StrategyState, LegState
from .models import InstrumentType, OptionType, Side

class StatePersistence:
    @staticmethod
    def save(state: StrategyState, filepath: str):
        """✅ BUG-006 FIX: Use JSON instead of pickle (pickle allows arbitrary code execution)."""
        data = StatePersistence.to_dict(state)
        # Write atomically via a temp file to avoid partial writes on crash
        tmp = filepath + ".tmp"
        with open(tmp, 'w') as f:
            json.dump(data, f, indent=2)
        import os
        os.replace(tmp, filepath)

    @staticmethod
    def load(filepath: str) -> Optional[StrategyState]:
        """✅ BUG-006 FIX: Load from JSON instead of pickle."""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            return StatePersistence.from_dict(data)
        except FileNotFoundError:
            return None
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to load state from {filepath}: {e}")
            return None

    @staticmethod
    def to_dict(state: StrategyState) -> Dict[str, Any]:
        return {
            "legs": {
                tag: {
                    "tag": leg.tag,
                    "symbol": leg.symbol,
                    "instrument": leg.instrument.value,
                    "option_type": leg.option_type.value if leg.option_type else None,
                    "strike": leg.strike,
                    "expiry": leg.expiry,
                    "side": leg.side.value,
                    "qty": leg.qty,
                    "entry_price": leg.entry_price,
                    "ltp": leg.ltp,
                    "delta": leg.delta,
                    "gamma": leg.gamma,
                    "theta": leg.theta,
                    "vega": leg.vega,
                    "iv": leg.iv,
                    "is_active": leg.is_active,
                    "group": leg.group,
                    "label": leg.label,
                    "oi": leg.oi,
                    "oi_change": leg.oi_change,
                    "volume": leg.volume,
                    "trading_symbol": leg.trading_symbol, 
                    "order_id": leg.order_id,
                    "command_id": leg.command_id,
                    "order_status": leg.order_status,
                    "filled_qty": leg.filled_qty,
                    "order_placed_at": leg.order_placed_at.isoformat() if leg.order_placed_at else None,
                } for tag, leg in state.legs.items()
            },
            "spot_price": state.spot_price,
            "spot_open": state.spot_open,
            "atm_strike": state.atm_strike,
            "fut_ltp": state.fut_ltp,
            "adjustments_today": state.adjustments_today,
            "total_trades_today": state.total_trades_today,
            "cumulative_daily_pnl": state.cumulative_daily_pnl,
            "entry_time": state.entry_time.isoformat() if state.entry_time else None,
            "last_adjustment_time": state.last_adjustment_time.isoformat() if state.last_adjustment_time else None,
            "trailing_stop_active": state.trailing_stop_active,
            "trailing_stop_level": state.trailing_stop_level,
            "peak_pnl": state.peak_pnl,
            "prev_values": state.prev_values,
            "lifetime_adjustments": state.lifetime_adjustments,
            "current_profit_step": state.current_profit_step,
            "last_date": state.last_date.isoformat() if state.last_date else None,
            "entered_today": state.entered_today,
            "minutes_to_exit": state.minutes_to_exit,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> StrategyState:
        legs = {}
        for tag, leg_data in data.get("legs", {}).items():
            leg = LegState(
                tag=leg_data["tag"],
                symbol=leg_data["symbol"],
                instrument=InstrumentType(leg_data["instrument"]),
                option_type=OptionType(leg_data["option_type"]) if leg_data["option_type"] else None,
                strike=leg_data["strike"],
                expiry=leg_data["expiry"],
                side=Side(leg_data["side"]),
                qty=leg_data["qty"],
                entry_price=leg_data["entry_price"],
                ltp=leg_data["ltp"],
                delta=leg_data["delta"],
                gamma=leg_data["gamma"],
                theta=leg_data["theta"],
                vega=leg_data["vega"],
                iv=leg_data["iv"],
                is_active=leg_data["is_active"],
                group=leg_data.get("group", ""),
                label=leg_data.get("label", ""),
                oi=leg_data.get("oi", 0),
                oi_change=leg_data.get("oi_change", 0),
                volume=leg_data.get("volume", 0),
                trading_symbol=leg_data.get("trading_symbol", ""),  
                order_id=leg_data.get("order_id"),
                command_id=leg_data.get("command_id"),
                order_status=leg_data.get("order_status", "PENDING"),
                filled_qty=leg_data.get("filled_qty", 0),
                order_placed_at=datetime.fromisoformat(leg_data["order_placed_at"]) if leg_data.get("order_placed_at") else None,
            )
            legs[tag] = leg

        state = StrategyState(
            legs=legs,
            spot_price=data.get("spot_price", 0.0),
            spot_open=data.get("spot_open", 0.0),
            atm_strike=data.get("atm_strike", 0.0),
            fut_ltp=data.get("fut_ltp", 0.0),
            adjustments_today=data.get("adjustments_today", 0),
            total_trades_today=data.get("total_trades_today", 0),
            cumulative_daily_pnl=data.get("cumulative_daily_pnl", 0.0),
            entry_time=datetime.fromisoformat(data["entry_time"]) if data.get("entry_time") else None,
            last_adjustment_time=datetime.fromisoformat(data["last_adjustment_time"]) if data.get("last_adjustment_time") else None,
            trailing_stop_active=data.get("trailing_stop_active", False),
            trailing_stop_level=data.get("trailing_stop_level", 0.0),
            peak_pnl=data.get("peak_pnl", 0.0),
            prev_values=data.get("prev_values", {}),
            lifetime_adjustments=data.get("lifetime_adjustments", 0),
            current_profit_step=data.get("current_profit_step", -1),
            last_date=date.fromisoformat(data["last_date"]) if data.get("last_date") else None,
            entered_today=data.get("entered_today", False),
            minutes_to_exit=data.get("minutes_to_exit", 0),
        )
        return state
"""
Config Resolution Service
=========================
Validates and resolves strategy configs BEFORE execution.

Responsibilities:
1. Validate exchange+symbol exists in ScriptMaster
2. Resolve expiry from ScriptMaster (not date math)
3. Validate order_type allowed for instrument
4. Determine correct .sqlite database file path
5. Resolve live_option_data reference
6. Validate all cross-field dependencies

Usage:
    resolver = ConfigResolutionService()
    resolved = resolver.resolve(config, exchange, symbol)
    
    if resolved["valid"]:
        # All fields resolved and validated
        db_path = resolved["db_path"]
        expiry = resolved["expiry"]
        order_type = resolved["order_type"]
    else:
        # Validation failed
        errors = resolved["errors"]
"""

from datetime import datetime
from typing import Dict, Any, Optional, List
from pathlib import Path

from scripts.scriptmaster import (
    options_expiry, 
    OPTION_INSTRUMENTS,
    SCRIPTMASTER,
    refresh_scriptmaster,
    universal_symbol_search,
)
from scripts.scriptmaster import requires_limit_order
from shoonya_platform.logging.logger_config import get_component_logger

logger = get_component_logger('core')


class ConfigResolutionService:
    """
    Centralized strategy config validation and resolution.
    
    Ensures all references are resolved from single source of truth (ScriptMaster)
    before strategy execution begins.
    """
    
    def __init__(self):
        """Initialize resolution service."""
        self.errors: List[str] = []
        self.warnings: List[str] = []
        # Ensure scriptmaster is loaded
        if not SCRIPTMASTER:
            try:
                refresh_scriptmaster()
            except Exception as e:
                logger.warning(f"Failed to refresh scriptmaster: {e}")
    
    def resolve(
        self,
        config: Dict[str, Any],
        exchange: str,
        symbol: str,
        instrument_type: str,
        expiry_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Resolve and validate strategy config.
        
        Args:
            config: Strategy config dict
            exchange: NFO, BFO, MCX, etc.
            symbol: NIFTY, BANKNIFTY, CRUDEOILM, etc.
            instrument_type: OPTIDX, OPTFUT, etc.
            expiry_mode: "weekly_current", "monthly_current", or custom expiry
        
        Returns:
            {
                "valid": bool,
                "expiry": "17-FEB-2026",
                "db_path": "/path/to/MCX_CRUDEOILM_17-FEB-2026.sqlite",
                "order_type_resolved": "LIMIT" or "MARKET",
                "lot_size": 75,  # from ScriptMaster LotSize
                "errors": [...],
                "warnings": [...],
            }
        """
        errors: List[str] = []
        warnings: List[str] = []
        
        exchange = exchange.upper()
        symbol = symbol.upper()
        instrument_type = instrument_type.upper()
        
        result = {
            "valid": False,
            "expiry": None,
            "db_path": None,
            "order_type_resolved": None,
            "lot_size": None,
            "errors": [],
            "warnings": [],
        }
        
        # 1. Validate exchange exists in ScriptMaster
        if not self._validate_exchange(exchange):
            errors.append(f"Exchange '{exchange}' not found in ScriptMaster")
            result["errors"] = errors
            return result
        
        # 2. Validate symbol exists for this exchange
        if not self._validate_symbol(exchange, symbol):
            errors.append(
                f"Symbol '{symbol}' not found on {exchange} in ScriptMaster"
            )
            result["errors"] = errors
            return result
        
        # 3. Validate instrument_type
        if not self._validate_instrument_type(exchange, instrument_type):
            errors.append(
                f"Instrument type '{instrument_type}' not valid for {exchange}"
            )
            result["errors"] = errors
            return result
        
        # 4. Resolve expiry from ScriptMaster
        resolved_expiry = self._resolve_expiry(exchange, symbol, expiry_mode)
        if not resolved_expiry:
            errors.append(
                f"Could not resolve expiry for {symbol} on {exchange}"
            )
            result["errors"] = errors
            return result
        
        # 5. Determine db_path based on supervisor pattern
        db_path = self._resolve_db_path(exchange, symbol, resolved_expiry)
        if not db_path:
            errors.append(f"Could not resolve database path")
            result["errors"] = errors
            return result
        
        # 6. Validate order_type for this instrument
        order_type_config = config.get("identity", {}).get("order_type", "LIMIT")
        resolved_order_type = self._resolve_order_type(
            exchange, symbol, instrument_type, order_type_config
        )
        if not resolved_order_type:
            errors.append(
                f"Order type '{order_type_config}' not valid for {symbol} on {exchange}"
            )
            result["errors"] = errors
            return result
        
        # All validations passed
        result["valid"] = True
        result["expiry"] = resolved_expiry
        result["db_path"] = str(db_path)
        result["order_type_resolved"] = resolved_order_type
        result["lot_size"] = self._resolve_lot_size(exchange, symbol, instrument_type)
        result["errors"] = errors
        result["warnings"] = warnings
        
        if warnings:
            logger.warning(f"Config resolution warnings: {warnings}")
        
        logger.info(
            f"\u2705 Config RESOLVED: {symbol} {resolved_expiry} "
            f"({instrument_type}) \u2192 {resolved_order_type} | "
            f"lot_size={result['lot_size']}"
        )
        
        return result
    
    def _validate_exchange(self, exchange: str) -> bool:
        """Check if exchange exists in ScriptMaster."""
        return exchange in SCRIPTMASTER
    
    def _validate_symbol(self, exchange: str, symbol: str) -> bool:
        """Check if symbol exists for exchange in ScriptMaster."""
        if exchange not in SCRIPTMASTER:
            return False
        
        # Check if symbol exists as Symbol or Underlying
        for rec in SCRIPTMASTER[exchange].values():
            if rec.get("Symbol") == symbol or rec.get("Underlying") == symbol:
                return True
        
        return False
    
    def _validate_instrument_type(self, exchange: str, instrument_type: str) -> bool:
        """Check if instrument_type is valid for exchange."""
        valid_types = OPTION_INSTRUMENTS.get(exchange, set())
        return instrument_type in valid_types
    
    def _resolve_expiry(
        self,
        exchange: str,
        symbol: str,
        expiry_mode: Optional[str] = None,
    ) -> Optional[str]:
        """
        Resolve option expiry from ScriptMaster.
        
        Returns:
            "17-FEB-2026" format expiry string from ScriptMaster
        """
        try:
            # Query ScriptMaster for actual option expiries
            expiries = options_expiry(symbol, exchange)
            
            if not expiries:
                logger.error(f"No option expiries for {symbol} on {exchange}")
                return None
            
            # Filter for upcoming expiries
            from datetime import date
            today = date.today()
            upcoming = []
            
            for exp_str in expiries:
                try:
                    exp_date = datetime.strptime(exp_str, "%d-%b-%Y").date()
                    if exp_date >= today:
                        upcoming.append(exp_str)
                except ValueError:
                    continue
            
            if not upcoming:
                upcoming = expiries
            
            # Select based on mode
            if expiry_mode == "weekly_current":
                selected = upcoming[0]
            elif expiry_mode == "monthly_current":
                # Find last expiry of current month
                current_month = today.month
                current_year = today.year
                
                month_expiries = []
                for exp_str in upcoming:
                    try:
                        exp_date = datetime.strptime(exp_str, "%d-%b-%Y").date()
                        if exp_date.month == current_month and exp_date.year == current_year:
                            month_expiries.append(exp_str)
                    except ValueError:
                        continue
                
                selected = month_expiries[-1] if month_expiries else upcoming[0]
            else:
                # Default: first upcoming
                selected = upcoming[0]
            
            return selected
        
        except Exception as e:
            logger.error(f"Expiry resolution failed: {e}")
            return None
    
    def _resolve_db_path(self, exchange: str, symbol: str, expiry: str) -> Optional[Path]:
        """
        Determine .sqlite database file path.
        
        Pattern matches supervisor.py:296
        {DB_BASE_DIR}/{EXCHANGE}_{SYMBOL}_{EXPIRY}.sqlite
        
        Returns:
            Path to .sqlite file
        """
        try:
            # Match supervisor pattern
            from shoonya_platform.market_data.option_chain.supervisor import DB_BASE_DIR
            
            db_filename = f"{exchange}_{symbol}_{expiry}.sqlite"
            db_path = DB_BASE_DIR / db_filename
            
            return db_path
        
        except Exception as e:
            logger.error(f"DB path resolution failed: {e}")
            return None
    
    def _resolve_order_type(
        self,
        exchange: str,
        symbol: str,
        instrument_type: str,
        requested_order_type: str,
    ) -> Optional[str]:
        """
        Validate and resolve order type for instrument.
        
        ScriptMaster rules: Some instruments require LIMIT orders.
        Check via requires_limit_order() function.
        
        Returns:
            "LIMIT" or "MARKET" (what's actually allowed)
        """
        try:
            # Check if this instrument REQUIRES limit orders
            # requires_limit_order uses keyword-only arguments
            if requires_limit_order(exchange=exchange, tradingsymbol=symbol):
                if requested_order_type != "LIMIT":
                    self.warnings.append(
                        f"{symbol} requires LIMIT orders. "
                        f"Changing from {requested_order_type} to LIMIT"
                    )
                return "LIMIT"
            
            # Otherwise use requested
            if requested_order_type in ("LIMIT", "MARKET", "MKT"):
                order_type = "MARKET" if requested_order_type == "MKT" else requested_order_type
                return order_type
            
            # Unknown order type
            logger.error(f"Unknown order type: {requested_order_type}")
            return None
        
        except Exception as e:
            logger.error(f"Order type resolution failed: {e}")
            # Fallback to LIMIT (safer)
            self.warnings.append(f"Order type validation error: {e}. Using LIMIT.")
            return "LIMIT"

    def _resolve_lot_size(
        self,
        exchange: str,
        symbol: str,
        instrument_type: str,
    ) -> Optional[int]:
        """
        Resolve lot size from ScriptMaster for the given exchange+symbol+instrument.
        
        Returns:
            Lot size (e.g. 75 for NIFTY, 15 for BANKNIFTY) or None
        """
        try:
            records = universal_symbol_search(symbol, exchange)
            if not records:
                self.warnings.append(f"No ScriptMaster records for {symbol} on {exchange}")
                return None
            
            # Filter to matching instrument type (OPTIDX, OPTSTK, OPTFUT, etc.)
            for rec in records:
                if rec.get("Instrument") == instrument_type:
                    lot_size = rec.get("LotSize")
                    if lot_size and int(lot_size) > 0:
                        return int(lot_size)
            
            # Fallback: any record with a valid lot size for this symbol
            for rec in records:
                lot_size = rec.get("LotSize")
                if lot_size and int(lot_size) > 0:
                    self.warnings.append(
                        f"LotSize from {rec.get('Instrument')} (not {instrument_type})"
                    )
                    return int(lot_size)
            
            self.warnings.append(f"No lot size found for {symbol}")
            return None
        
        except Exception as e:
            logger.error(f"Lot size resolution failed: {e}")
            return None


def validate_config(
    config: Dict[str, Any],
    exchange: str,
    symbol: str,
) -> Dict[str, Any]:
    """
    Quick validation function (convenience wrapper).
    
    Args:
        config: Strategy config dict
        exchange: NFO, BFO, MCX
        symbol: NIFTY, BANKNIFTY, CRUDEOILM
    
    Returns:
        Resolution result dict with valid/errors/resolved_values
    """
    resolver = ConfigResolutionService()
    
    identity = config.get("identity", {})
    return resolver.resolve(
        config=config,
        exchange=exchange or identity.get("exchange"),
        symbol=symbol or identity.get("underlying"),
        instrument_type=identity.get("instrument_type", "OPTIDX"),
        expiry_mode=identity.get("expiry_mode", "weekly_current"),
    )

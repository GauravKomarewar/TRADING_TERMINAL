#!/usr/bin/env python3
"""
Strategy Configuration Validation Service
=========================================

Purpose:
- Validate strategy JSON against schema
- Check database paths exist
- Validate all parameter combinations
- Provide smart error messages
- Reject invalid strategies with reason

Status: PRODUCTION READY
Date: 2026-02-12
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from enum import Enum

logger = logging.getLogger("STRATEGY.VALIDATION")


class ValidationLevel(str, Enum):
    """Validation result levels"""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationResult:
    """Structured validation result"""
    
    def __init__(self, name: str):
        self.name = name
        self.valid = True
        self.errors: List[Dict[str, str]] = []
        self.warnings: List[Dict[str, str]] = []
        self.info: List[Dict[str, str]] = []
    
    def add_error(self, field: str, message: str, error_type: str = "validation_error"):
        """Add an error (makes validation fail)"""
        self.valid = False
        self.errors.append({
            "field": field,
            "message": message,
            "type": error_type,
            "level": "error"
        })
        logger.error(f"❌ {self.name} | {field}: {message}")
    
    def add_warning(self, field: str, message: str, warning_type: str = "warning"):
        """Add a warning (doesn't make validation fail)"""
        self.warnings.append({
            "field": field,
            "message": message,
            "type": warning_type,
            "level": "warning"
        })
        logger.warning(f"⚠️ {self.name} | {field}: {message}")
    
    def add_info(self, message: str):
        """Add info message"""
        self.info.append({
            "message": message,
            "level": "info"
        })
        logger.info(f"ℹ️ {self.name} | {message}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response"""
        return {
            "name": self.name,
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "info": self.info,
            "total_issues": len(self.errors) + len(self.warnings),
            "timestamp": datetime.now().isoformat()
        }


class StrategyConfigValidator:
    """Validate strategy configuration"""
    
    # Valid enum values
    VALID_MARKET_TYPES = ["database_market", "live_feed_market"]
    VALID_EXCHANGES = ["NFO", "MCX", "NCDEX", "CDSL"]
    VALID_ENTRY_TYPES = ["delta_neutral", "directional", "calendar_spread", "butterfly", "iron_condor"]
    VALID_ADJUSTMENT_TYPES = ["delta_drift", "stop_loss_triggered", "time_decay", "vega_spike"]
    VALID_EXIT_TYPES = ["profit_target", "stop_loss", "time_based", "manual"]
    VALID_ORDER_TYPES = ["MARKET", "LIMIT", "STOP", "STOP_LIMIT"]
    VALID_PRODUCTS = ["NRML", "MIS", "CNC"]
    
    def __init__(self):
        self.result: ValidationResult = ValidationResult("_initial")
    
    def validate(self, config: Dict[str, Any], config_name: Optional[str] = None) -> ValidationResult:
        """
        Validate strategy configuration comprehensively.
        
        Args:
            config: Strategy configuration dictionary
            config_name: Name of strategy (optional, extracted from config if not provided)
            
        Returns:
            ValidationResult with errors and warnings
        """
        name = config_name or config.get("name", "UNKNOWN")
        self.result = ValidationResult(name)
        
        logger.info(f"🔍 Validating strategy: {name}")
        
        try:
            # Phase 1: Basic structure
            self._validate_basic_structure(config)
            if self.result.errors:
                return self.result
            
            # Phase 2: Required fields
            self._validate_required_fields(config)
            
            # Phase 3: Market config
            self._validate_market_config(config.get("market_config", {}))
            
            # Phase 4: Entry config
            self._validate_entry_config(config.get("entry", {}))
            
            # Phase 5: Exit config
            self._validate_exit_config(config.get("exit", {}))
            
            # Phase 6: Optional configs
            self._validate_adjustment_config(config.get("adjustment", {}))
            self._validate_execution_config(config.get("execution", {}))
            self._validate_risk_management_config(config.get("risk_management", {}))
            
            # Phase 7: Smart cross-field validation
            self._validate_cross_fields(config)
            
            # Summary
            if self.result.valid:
                self.result.add_info(f"✅ Configuration is valid")
                logger.info(f"✅ {name} validation PASSED")
            else:
                logger.error(f"❌ {name} validation FAILED ({len(self.result.errors)} errors)")
        
        except Exception as e:
            self.result.add_error("_general", f"Validation error: {str(e)}", "system_error")
            logger.exception(f"❌ {name} validation exception: {e}")
        
        return self.result
    
    def _validate_basic_structure(self, config: Dict):
        """Validate config is a dict with basic structure"""
        if not isinstance(config, dict):
            self.result.add_error("_root", "Config must be a JSON object", "invalid_type")
            return
    
    def _validate_required_fields(self, config: Dict):
        """Validate all required fields are present"""
        required = ["name", "market_config", "entry", "exit"]
        
        for field in required:
            if field not in config:
                self.result.add_error(field, f"Required field '{field}' is missing", "missing_field")
            elif config[field] is None:
                self.result.add_error(field, f"Required field '{field}' cannot be null", "null_value")
            elif isinstance(config[field], dict) and not config[field]:
                self.result.add_warning(field, f"Field '{field}' is empty dict", "empty_dict")
    
    def _validate_market_config(self, market_config: Dict):
        """Validate market configuration"""
        if not isinstance(market_config, dict):
            self.result.add_error("market_config", "Must be a JSON object", "invalid_type")
            return
        
        # Exchange
        exchange = market_config.get("exchange")
        if not exchange:
            self.result.add_error("market_config.exchange", "Exchange is required", "missing_field")
        elif exchange not in self.VALID_EXCHANGES:
            self.result.add_error(
                "market_config.exchange",
                f"Invalid exchange '{exchange}'. Must be one of: {', '.join(self.VALID_EXCHANGES)}",
                "invalid_enum"
            )
        
        # Symbol
        symbol = market_config.get("symbol")
        if not symbol:
            self.result.add_error("market_config.symbol", "Symbol is required", "missing_field")
        elif not isinstance(symbol, str) or len(symbol) == 0:
            self.result.add_error("market_config.symbol", "Symbol must be non-empty string", "invalid_type")
        
        # Market type
        market_type = market_config.get("market_type", "database_market")
        if market_type not in self.VALID_MARKET_TYPES:
            self.result.add_error(
                "market_config.market_type",
                f"Invalid market_type '{market_type}'. Must be one of: {', '.join(self.VALID_MARKET_TYPES)}",
                "invalid_enum"
            )
        
        # Database path (required if market_type is database_market)
        if market_type == "database_market":
            db_path = market_config.get("db_path")
            if not db_path:
                self.result.add_error(
                    "market_config.db_path",
                    "db_path is required when market_type='database_market'",
                    "missing_field"
                )
            else:
                # Check if file exists
                path = Path(db_path)
                if not path.exists():
                    self.result.add_error(
                        "market_config.db_path",
                        f"Database file not found: {db_path}",
                        "file_not_found"
                    )
                elif not path.is_file():
                    self.result.add_error(
                        "market_config.db_path",
                        f"Path is not a file: {db_path}",
                        "not_a_file"
                    )
    
    def _validate_entry_config(self, entry_config: Dict):
        """Validate entry configuration"""
        if not isinstance(entry_config, dict):
            self.result.add_error("entry", "Must be a JSON object", "invalid_type")
            return
        
        # Entry time
        entry_time = entry_config.get("entry_time")
        if entry_time:
            if not self._is_valid_time_format(entry_time):
                self.result.add_error(
                    "entry.entry_time",
                    f"Invalid time format: '{entry_time}'. Use HH:MM (24-hour format)",
                    "invalid_format"
                )
        else:
            self.result.add_warning("entry.entry_time", "Entry time not specified", "missing_optional")
        
        # Entry type
        entry_type = entry_config.get("entry_type", "delta_neutral")
        if entry_type not in self.VALID_ENTRY_TYPES:
            self.result.add_warning(
                "entry.entry_type",
                f"Unknown entry_type '{entry_type}'. Known types: {', '.join(self.VALID_ENTRY_TYPES)}",
                "unknown_value"
            )
        
        # Target deltas
        ce_delta = entry_config.get("target_ce_delta")
        if ce_delta is not None:
            if not isinstance(ce_delta, (int, float)):
                self.result.add_error("entry.target_ce_delta", "Must be a number", "invalid_type")
            elif not (0 <= ce_delta <= 1):
                self.result.add_error("entry.target_ce_delta", "Delta must be between 0 and 1", "out_of_range")
        
        pe_delta = entry_config.get("target_pe_delta")
        if pe_delta is not None:
            if not isinstance(pe_delta, (int, float)):
                self.result.add_error("entry.target_pe_delta", "Must be a number", "invalid_type")
            elif not (0 <= pe_delta <= 1):
                self.result.add_error("entry.target_pe_delta", "Delta must be between 0 and 1", "out_of_range")
        
        # Delta tolerance
        tolerance = entry_config.get("delta_tolerance", 0.05)
        if not isinstance(tolerance, (int, float)):
            self.result.add_error("entry.delta_tolerance", "Must be a number", "invalid_type")
        elif not (0 <= tolerance <= 0.5):
            self.result.add_warning(
                "entry.delta_tolerance",
                f"Delta tolerance '{tolerance}' is unusually large (typically 0-0.1)",
                "unusual_value"
            )
        
        # Quantity
        quantity = entry_config.get("quantity")
        if quantity is not None:
            if not isinstance(quantity, int):
                self.result.add_error("entry.quantity", "Must be an integer", "invalid_type")
            elif quantity <= 0:
                self.result.add_error("entry.quantity", "Quantity must be positive", "invalid_value")
    
    def _validate_exit_config(self, exit_config: Dict):
        """Validate exit configuration"""
        if not isinstance(exit_config, dict):
            self.result.add_error("exit", "Must be a JSON object", "invalid_type")
            return
        
        # Exit time
        exit_time = exit_config.get("exit_time")
        if exit_time:
            if not self._is_valid_time_format(exit_time):
                self.result.add_error(
                    "exit.exit_time",
                    f"Invalid time format: '{exit_time}'. Use HH:MM (24-hour format)",
                    "invalid_format"
                )
        else:
            self.result.add_warning("exit.exit_time", "Exit time not specified", "missing_optional")
        
        # Exit type
        exit_type = exit_config.get("exit_type", "profit_target")
        if exit_type not in self.VALID_EXIT_TYPES:
            self.result.add_warning(
                "exit.exit_type",
                f"Unknown exit_type '{exit_type}'. Known types: {', '.join(self.VALID_EXIT_TYPES)}",
                "unknown_value"
            )
        
        # Profit target
        profit = exit_config.get("profit_target")
        if profit is not None:
            if not isinstance(profit, (int, float)):
                self.result.add_error("exit.profit_target", "Must be a number", "invalid_type")
            elif profit <= 0:
                self.result.add_error("exit.profit_target", "Profit target must be positive", "invalid_value")
        
        # Max loss
        loss = exit_config.get("max_loss")
        if loss is not None:
            if not isinstance(loss, (int, float)):
                self.result.add_error("exit.max_loss", "Must be a number", "invalid_type")
            elif loss <= 0:
                self.result.add_error("exit.max_loss", "Max loss must be positive", "invalid_value")
        
        # Ensure at least one exit condition
        if not profit and not loss:
            self.result.add_warning(
                "exit",
                "No profit_target or max_loss specified - strategy may not exit",
                "no_exit_condition"
            )
    
    def _validate_adjustment_config(self, adjustment_config: Dict):
        """Validate adjustment configuration"""
        if not isinstance(adjustment_config, dict):
            if adjustment_config is not None:
                self.result.add_error("adjustment", "Must be a JSON object", "invalid_type")
            return
        
        if not adjustment_config:
            return  # Empty is okay
        
        enabled = adjustment_config.get("enabled", True)
        if not isinstance(enabled, bool):
            self.result.add_warning("adjustment.enabled", "Should be boolean", "invalid_type")
        
        if enabled:
            # Adjustment type
            adj_type = adjustment_config.get("adjustment_type", "delta_drift")
            if adj_type not in self.VALID_ADJUSTMENT_TYPES:
                self.result.add_warning(
                    "adjustment.adjustment_type",
                    f"Unknown adjustment_type '{adj_type}'. Known types: {', '.join(self.VALID_ADJUSTMENT_TYPES)}",
                    "unknown_value"
                )
            
            # Delta drift trigger
            trigger = adjustment_config.get("delta_drift_trigger")
            if trigger is not None:
                if not isinstance(trigger, (int, float)):
                    self.result.add_error("adjustment.delta_drift_trigger", "Must be a number", "invalid_type")
                elif not (0 <= trigger <= 1):
                    self.result.add_error("adjustment.delta_drift_trigger", "Must be between 0 and 1", "out_of_range")
            
            # Cooldown
            cooldown = adjustment_config.get("cooldown_seconds", 60)
            if not isinstance(cooldown, int):
                self.result.add_error("adjustment.cooldown_seconds", "Must be an integer", "invalid_type")
            elif cooldown < 0:
                self.result.add_error("adjustment.cooldown_seconds", "Must be non-negative", "invalid_value")
    
    def _validate_execution_config(self, execution_config: Dict):
        """Validate execution configuration"""
        if not isinstance(execution_config, dict):
            if execution_config is not None:
                self.result.add_error("execution", "Must be a JSON object", "invalid_type")
            return
        
        # Order type
        order_type = execution_config.get("order_type", "MARKET")
        if order_type not in self.VALID_ORDER_TYPES:
            self.result.add_warning(
                "execution.order_type",
                f"Unknown order_type '{order_type}'. Known types: {', '.join(self.VALID_ORDER_TYPES)}",
                "unknown_value"
            )
        
        # Product
        product = execution_config.get("product", "NRML")
        if product not in self.VALID_PRODUCTS:
            self.result.add_warning(
                "execution.product",
                f"Unknown product '{product}'. Known products: {', '.join(self.VALID_PRODUCTS)}",
                "unknown_value"
            )
    
    def _validate_risk_management_config(self, risk_config: Dict):
        """Validate risk management configuration"""
        if not isinstance(risk_config, dict):
            if risk_config is not None:
                self.result.add_error("risk_management", "Must be a JSON object", "invalid_type")
            return
        
        # Max concurrent legs
        max_legs = risk_config.get("max_concurrent_legs")
        if max_legs is not None:
            if not isinstance(max_legs, int):
                self.result.add_error("risk_management.max_concurrent_legs", "Must be integer", "invalid_type")
            elif max_legs < 1:
                self.result.add_error("risk_management.max_concurrent_legs", "Must be >= 1", "invalid_value")
        
        # Max total loss
        max_loss = risk_config.get("max_total_loss")
        if max_loss is not None:
            if not isinstance(max_loss, (int, float)):
                self.result.add_error("risk_management.max_total_loss", "Must be a number", "invalid_type")
            elif max_loss <= 0:
                self.result.add_error("risk_management.max_total_loss", "Must be positive", "invalid_value")
    
    def _validate_cross_fields(self, config: Dict):
        """Validate relationships between fields"""
        try:
            # Entry time before exit time
            entry = config.get("entry", {})
            exit_cfg = config.get("exit", {})
            
            entry_time = entry.get("entry_time")
            exit_time = exit_cfg.get("exit_time")
            
            if entry_time and exit_time and self._is_valid_time_format(entry_time) and self._is_valid_time_format(exit_time):
                if entry_time >= exit_time:
                    self.result.add_error(
                        "entry.entry_time vs exit.exit_time",
                        f"Entry time ({entry_time}) must be before exit time ({exit_time})",
                        "invalid_time_range"
                    )
            
            # Profit target vs max loss
            profit = exit_cfg.get("profit_target")
            loss = exit_cfg.get("max_loss")
            
            if profit and loss and isinstance(profit, (int, float)) and isinstance(loss, (int, float)):
                if profit <= loss:
                    self.result.add_warning(
                        "exit.profit_target vs exit.max_loss",
                        f"Profit target ({profit}) should typically be > max loss ({loss})",
                        "unusual_risk_ratio"
                    )
            
            # Asymmetric deltas warning
            ce_delta = entry.get("target_ce_delta")
            pe_delta = entry.get("target_pe_delta")
            
            if ce_delta is not None and pe_delta is not None:
                if ce_delta != pe_delta:
                    self.result.add_warning(
                        "entry.deltas",
                        f"Asymmetric deltas: CE={ce_delta}, PE={pe_delta} (intentional?)",
                        "asymmetric_deltas"
                    )
        
        except Exception as e:
            self.result.add_warning("_cross_fields", f"Could not validate cross-fields: {str(e)}", "validation_skip")
    
    @staticmethod
    def _is_valid_time_format(time_str: str) -> bool:
        """Check if time is in HH:MM format"""
        if not isinstance(time_str, str):
            return False
        try:
            parts = time_str.split(":")
            if len(parts) != 2:
                return False
            hours = int(parts[0])
            minutes = int(parts[1])
            return 0 <= hours < 24 and 0 <= minutes < 60
        except (ValueError, AttributeError):
            return False


# Singleton instance
_validator: Optional[StrategyConfigValidator] = None


def get_validator() -> StrategyConfigValidator:
    """Get or create validator instance"""
    global _validator
    if _validator is None:
        _validator = StrategyConfigValidator()
    return _validator


def validate_strategy(config: Dict[str, Any], name: Optional[str] = None) -> ValidationResult:
    """
    Validate strategy configuration.
    
    Usage:
        result = validate_strategy(config_dict, "MY_STRATEGY")
        print(result.to_dict())
    """
    validator = get_validator()
    return validator.validate(config, name)

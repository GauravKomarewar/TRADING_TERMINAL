"""
ORPHAN POSITION MANAGER
=======================

Monitors and manages positions created outside the strategy system:
- Manual trades from UI
- External webhooks (non-strategy)
- System-generated orders

Features:
- Price-based rules (target, stoploss, trailing)
- Greek-based rules (delta, theta, vega, gamma targets)
- Combined position rules (multiple symbols with net greeks)
- Automatic exit/reduce when conditions met
"""

import json
import logging
import time
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

from shoonya_platform.persistence.database import get_connection

logger = logging.getLogger("ORPHAN_POSITION_MANAGER")


class OrphanPositionManager:
    """
    Monitor and manage orphan positions via rules.
    
    Rules can be:
    - PRICE: Exit at target, stoploss, or trailing stop
    - GREEK: Exit when delta/theta/vega/gamma reaches threshold
    - COMBINED: Multiple positions with combined net greek threshold
    """
    
    def __init__(self, bot):
        """
        Args:
            bot: ShoonyaBot instance (for broker API access)
        """
        self.bot = bot
        self.active_rules: Dict[str, dict] = {}
        self.rule_execution_log = []
        
    # ==================================================
    # RULE LOADING
    # ==================================================
    
    def load_active_rules(self) -> int:
        """
        Load all active orphan position rules from DB.
        
        Returns:
            Count of active rules loaded
        """
        try:
            db = get_connection()
            rows = db.execute(
                """
                SELECT id, payload
                FROM control_intents
                WHERE type = 'ORPHAN_POSITION_RULE'
                  AND status NOT IN ('DELETED', 'FAILED')
                """
            ).fetchall()
            
            for row in rows:
                try:
                    rule_id = row["id"]
                    payload = json.loads(row["payload"])
                    self.active_rules[rule_id] = payload
                except Exception as e:
                    logger.warning(f"Failed to load rule {row['id']}: {e}")
            
            logger.info(f"Loaded {len(self.active_rules)} orphan position rules")
            return len(self.active_rules)
            
        except Exception as e:
            logger.exception("Failed to load orphan rules")
            return 0
    
    # ==================================================
    # RULE MONITORING & EXECUTION
    # ==================================================
    
    def monitor_and_execute(self) -> int:
        """
        Monitor all active rules and execute when conditions met.
        
        Returns:
            Count of rules executed
        """
        if not self.active_rules:
            return 0
        
        try:
            # Get current broker positions
            self.bot._ensure_login()
            positions = self.bot.api.get_positions() or []
            
            # Get strategy-owned symbols (exclude from orphan management)
            orders = self.bot.order_repo.get_all_orders() or []
            strategy_symbols = set(
                o.get("symbol") for o in orders 
                if o.get("user") and o.get("user") not in ["", None]
            )
            
            executed_count = 0
            
            for rule_id, rule in list(self.active_rules.items()):
                try:
                    # Skip deleted rules
                    if rule.get("status") == "DELETED":
                        del self.active_rules[rule_id]
                        continue
                    
                    symbols = rule.get("symbols", [])
                    rule_type = rule.get("rule_type", "PRICE")
                    
                    # Get relevant positions (orphan only)
                    relevant_positions = [
                        p for p in positions
                        if p.get("tsym") in symbols and p.get("tsym") not in strategy_symbols
                    ]
                    
                    if not relevant_positions:
                        logger.debug(f"No positions found for rule {rule_id}")
                        continue
                    
                    # Check and execute rule
                    if rule_type == "PRICE":
                        if self._check_price_rule(rule, relevant_positions):
                            executed_count += self._execute_rule(rule, relevant_positions)
                    
                    elif rule_type == "GREEK":
                        if self._check_greek_rule(rule, positions, strategy_symbols):
                            executed_count += self._execute_rule(rule, relevant_positions)
                    
                    elif rule_type == "COMBINED":
                        if self._check_combined_rule(rule, relevant_positions):
                            executed_count += self._execute_rule(rule, relevant_positions)
                
                except Exception as e:
                    logger.exception(f"Error checking rule {rule_id}: {e}")
            
            return executed_count
            
        except Exception as e:
            logger.exception("Error monitoring orphan rules")
            return 0
    
    # ==================================================
    # RULE CONDITION CHECKS
    # ==================================================
    
    def _check_price_rule(self, rule: dict, positions: List) -> bool:
        """
        Check if price-based rule condition is met.
        
        Conditions:
        - target: position LTP >= target price
        - stoploss: position LTP <= stoploss price
        - trailing: position LTP <= (entry_price - trailing_amount)
        """
        condition = rule.get("condition")
        threshold = rule.get("threshold")
        
        for pos in positions:
            ltp = float(pos.get("ltp", 0) or 0)
            
            if condition == "target":
                if ltp >= threshold:
                    logger.warning(
                        f"✅ PRICE RULE TARGET HIT: {pos.get('tsym')} "
                        f"LTP={ltp} >= TARGET={threshold}"
                    )
                    return True
            
            elif condition == "stoploss":
                if ltp <= threshold:
                    logger.warning(
                        f"✅ PRICE RULE STOPLOSS HIT: {pos.get('tsym')} "
                        f"LTP={ltp} <= STOPLOSS={threshold}"
                    )
                    return True
            
            elif condition == "trailing":
                avg_price = float(pos.get("avgprc", 0) or 0)
                trailing_stop = avg_price - threshold
                if ltp <= trailing_stop:
                    logger.warning(
                        f"✅ PRICE RULE TRAILING STOPPED: {pos.get('tsym')} "
                        f"LTP={ltp} <= TRAILING_STOP={trailing_stop}"
                    )
                    return True
        
        return False
    
    def _check_greek_rule(self, rule: dict, all_positions: List, strategy_symbols: set) -> bool:
        """
        Check if greek-based rule condition is met.
        
        Conditions:
        - delta_target: abs(delta) >= threshold
        - theta_target: theta <= threshold (for decay exit)
        - vega_target: abs(vega) >= threshold
        - gamma_target: gamma >= threshold
        """
        condition = rule.get("condition")
        threshold = rule.get("threshold", 0)
        symbols = rule.get("symbols", [])
        
        for pos in all_positions:
            symbol = pos.get("tsym", "")
            if symbol not in symbols or symbol in strategy_symbols:
                continue
            
            # Get greeks from order data
            # (Note: In production, these would come from live feeds or option pricing)
            # For now, we use stub values from positions
            delta = float(pos.get("delta", 0) or 0)
            theta = float(pos.get("theta", 0) or 0)
            vega = float(pos.get("vega", 0) or 0)
            gamma = float(pos.get("gamma", 0) or 0)
            
            if condition == "delta_target":
                if abs(delta) >= threshold:
                    logger.warning(
                        f"✅ GREEK RULE DELTA HIT: {symbol} "
                        f"|DELTA|={abs(delta):.4f} >= TARGET={threshold}"
                    )
                    return True
            
            elif condition == "theta_target":
                # theta_target: exit when theta approaches zero (decay complete)
                if abs(theta) <= threshold:
                    logger.warning(
                        f"✅ GREEK RULE THETA HIT: {symbol} "
                        f"|THETA|={abs(theta):.4f} <= TARGET={threshold}"
                    )
                    return True
            
            elif condition == "vega_target":
                if abs(vega) >= threshold:
                    logger.warning(
                        f"✅ GREEK RULE VEGA HIT: {symbol} "
                        f"|VEGA|={abs(vega):.4f} >= TARGET={threshold}"
                    )
                    return True
            
            elif condition == "gamma_target":
                if gamma >= threshold:
                    logger.warning(
                        f"✅ GREEK RULE GAMMA HIT: {symbol} "
                        f"GAMMA={gamma:.4f} >= TARGET={threshold}"
                    )
                    return True
        
        return False
    
    def _check_combined_rule(self, rule: dict, positions: List) -> bool:
        """
        Check if combined position rule condition is met.
        
        Examples:
        - combined_delta: sum of deltas >= threshold
        - combined_pnl: total PnL >= threshold
        """
        condition = rule.get("condition")
        threshold = rule.get("threshold", 0)
        
        if condition == "combined_delta":
            combined_delta = sum(float(p.get("delta", 0) or 0) for p in positions)
            if abs(combined_delta) >= threshold:
                logger.warning(
                    f"✅ COMBINED RULE DELTA HIT: "
                    f"|COMBINED_DELTA|={abs(combined_delta):.4f} >= TARGET={threshold}"
                )
                return True
        
        elif condition == "combined_pnl":
            combined_pnl = sum(float(p.get("upnl", 0) or 0) for p in positions)
            if combined_pnl >= threshold:
                logger.warning(
                    f"✅ COMBINED RULE PnL HIT: "
                    f"COMBINED_PnL={combined_pnl:.2f} >= TARGET={threshold}"
                )
                return True
        
        return False
    
    # ==================================================
    # RULE EXECUTION
    # ==================================================
    
    def _execute_rule(self, rule: dict, positions: List) -> int:
        """
        Execute the action specified in the rule.
        
        Actions:
        - EXIT: Full exit of all positions
        - REDUCE: Reduce qty by specified amount
        """
        rule_id = rule.get("rule_id")
        action = rule.get("action", "EXIT")
        reduce_qty = rule.get("reduce_qty")
        
        execution_count = 0
        
        for pos in positions:
            symbol = pos.get("tsym")
            netqty = int(pos.get("netqty", 0))
            
            if netqty == 0:
                continue
            
            try:
                # Determine exit side
                side = "SELL" if netqty > 0 else "BUY"
                exit_qty = netqty if action == "EXIT" else reduce_qty
                
                if action == "EXIT":
                    logger.warning(
                        f"🚪 ORPHAN EXIT: rule={rule_id} | {symbol} "
                        f"| {side} {exit_qty} | FULL EXIT"
                    )
                else:
                    logger.warning(
                        f"📉 ORPHAN REDUCE: rule={rule_id} | {symbol} "
                        f"| {side} {exit_qty} | PARTIAL EXIT"
                    )
                
                # Register exit intent
                from shoonya_platform.execution.intent import UniversalOrderCommand
                
                cmd = UniversalOrderCommand.from_order_params(
                    order_params={
                        "exchange": pos.get("exch"),
                        "symbol": symbol,
                        "side": side,
                        "quantity": exit_qty,
                        "product": pos.get("prd", "MIS"),
                        "order_type": "MARKET",
                        "price": None,
                        "strategy_name": f"ORPHAN_RULE_{rule_id}",
                    },
                    source="ORPHAN_POSITION_RULE",
                    user="ORPHAN_MANAGER",
                )
                
                # Submit to command service
                self.bot.command_service.register(cmd)
                
                # Log execution
                self.rule_execution_log.append({
                    "timestamp": datetime.now().isoformat(),
                    "rule_id": rule_id,
                    "symbol": symbol,
                    "action": action,
                    "qty": exit_qty,
                    "status": "EXECUTED",
                })
                
                execution_count += 1
                
                # Mark rule as executed once
                self.active_rules[rule_id]["status"] = "EXECUTED"
                
            except Exception as e:
                logger.exception(f"Failed to execute rule {rule_id} for {symbol}: {e}")
                self.rule_execution_log.append({
                    "timestamp": datetime.now().isoformat(),
                    "rule_id": rule_id,
                    "symbol": symbol,
                    "status": "FAILED",
                    "error": str(e),
                })
        
        return execution_count
    
    # ==================================================
    # STATUS & MONITORING
    # ==================================================
    
    def get_execution_history(self, limit: int = 50) -> List[dict]:
        """Get recent rule execution history"""
        return self.rule_execution_log[-limit:]
    
    def get_active_rule_count(self) -> int:
        """Get count of currently active rules"""
        return sum(
            1 for r in self.active_rules.values()
            if r.get("status") not in ["DELETED", "EXECUTED"]
        )

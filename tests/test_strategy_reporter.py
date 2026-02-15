#!/usr/bin/env python3
"""
Test Universal Strategy Reporter

Tests:
- Report generation for active strategies
- Report generation with database_market adapter
- Report generation with live_feed_market adapter
- Report graceful degradation without adapter
- Telegram-format compliance
"""

import pytest
from typing import Optional
from unittest.mock import Mock, MagicMock
from shoonya_platform.strategy_runner.universal_settings.universal_strategy_reporter import (
    build_strategy_report,
)


class MockLeg:
    """Mock strategy leg"""
    def __init__(self, symbol="NFO_NIFTY_25FEB_23500_CE", delta=0.5):
        self.symbol = symbol
        self.delta = delta
        self.entry_price = 100.0
        self.current_price = 120.0
    
    def unrealized_pnl(self):
        return (self.current_price - self.entry_price) * 100  # qty = 100


class MockState:
    """Mock strategy state"""
    def __init__(self, active=True):
        self.active = active
        self.ce_leg = MockLeg("CE_LEG", delta=0.5) if active else None
        self.pe_leg = MockLeg("PE_LEG", delta=-0.5) if active else None
        self.adjustment_phase: Optional[str] = None
        self.adjustment_target_delta: Optional[float] = None
        self.adjustment_leg_type: Optional[str] = None
        self.realized_pnl = 0.0  # Add realized_pnl attribute
        self.next_profit_target = None  # Add next_profit_target attribute
    
    def total_unrealized_pnl(self):
        return (self.ce_leg.unrealized_pnl() if self.ce_leg else 0) + \
               (self.pe_leg.unrealized_pnl() if self.pe_leg else 0)
    
    def total_delta(self):
        return (self.ce_leg.delta if self.ce_leg else 0) + \
               (self.pe_leg.delta if self.pe_leg else 0)


class MockStrategy:
    """Mock strategy for reporting"""
    def __init__(self, active=True):
        self.state = MockState(active=active)
        self.config = Mock()
        self.config.cooldown_seconds = 30
    
    def set_adjustment_phase(self, phase):
        self.state.adjustment_phase = phase
        self.state.adjustment_leg_type = "CE"
        self.state.adjustment_target_delta = 0.3


class TestStrategyReporter:
    """Test strategy reporting functionality"""
    

    
    def test_report_returns_none_for_inactive_strategy(self):
        """Should return None for inactive strategies"""
        strategy = MockStrategy(active=False)
        
        report = build_strategy_report(strategy)
        
        assert report is None
    
    def test_report_returns_string_for_active_strategy(self):
        """Should return report string for active strategies"""
        strategy = MockStrategy(active=True)
        
        report = build_strategy_report(strategy)
        
        assert report is not None
        assert isinstance(report, str)
        assert len(report) > 0
    
    def test_report_includes_header(self):
        """Report should include header section"""
        strategy = MockStrategy(active=True)
        
        report = build_strategy_report(strategy)
        assert report is not None
        assert "DELTA NEUTRAL" in report
        assert "LIVE STATUS" in report
    
    def test_report_includes_legs_section(self):
        """Report should include legs information"""
        strategy = MockStrategy(active=True)
        
        report = build_strategy_report(strategy)
        assert report is not None
        assert "CALL LEG" in report
        assert "PUT LEG" in report
    
    def test_report_includes_net_delta(self):
        """Report should include net delta"""
        strategy = MockStrategy(active=True)
        
        report = build_strategy_report(strategy)
        assert report is not None
        assert "Net Delta" in report
    
    def test_report_includes_pnl(self):
        """Report should include PnL information"""
        strategy = MockStrategy(active=True)
        
        report = build_strategy_report(strategy)
        assert report is not None
        assert "Unrealized" in report
        assert "Realized" in report
    
    def test_report_with_adjustment_phase(self):
        """Report should show adjustment phase if active"""
        strategy = MockStrategy(active=True)
        strategy.set_adjustment_phase("entry")
        
        report = build_strategy_report(strategy)
        assert report is not None
        assert "Adjustment In Progress" in report
        assert "entry" in report
    
    def test_report_with_adjustment_rules(self):
        """Report should show adjustment rules if not in phase"""
        strategy = MockStrategy(active=True)
        
        report = build_strategy_report(strategy)
        assert report is not None
        assert "Adjustment Rules" in report
        assert "Profit Target" in report
    
    def test_report_works_with_database_market_adapter(self):
        """Report should work with DatabaseMarketAdapter"""
        from unittest.mock import Mock
        
        strategy = MockStrategy(active=True)
        mock_adapter = Mock()
        mock_adapter.get_market_snapshot = Mock(return_value={"spot": 23500.0})
        
        report = build_strategy_report(strategy, market_adapter=mock_adapter)
        
        assert report is not None
        assert "23500" in report
    
    def test_report_works_with_live_feed_adapter(self):
        """Report should work with LiveFeedMarketAdapter"""
        from unittest.mock import Mock
        
        strategy = MockStrategy(active=True)
        mock_adapter = Mock()
        mock_adapter.get_market_snapshot = Mock(return_value={"spot": 23600.0})
        
        report = build_strategy_report(strategy, market_adapter=mock_adapter)
        
        assert report is not None
        assert "23600" in report
    
    def test_report_handles_adapter_error(self):
        """Report should handle adapter errors gracefully"""
        strategy = MockStrategy(active=True)
        mock_adapter = Mock()
        mock_adapter.get_market_snapshot = Mock(side_effect=Exception("Adapter error"))
        
        # Should not raise, should degrade gracefully
        report = build_strategy_report(strategy, market_adapter=mock_adapter)
        
        assert report is not None
        assert isinstance(report, str)
    
    def test_report_works_without_adapter(self):
        """Report should work when adapter is None"""
        strategy = MockStrategy(active=True)
        
        report = build_strategy_report(strategy, market_adapter=None)
        
        assert report is not None
        assert "—" in report  # Spot should be missing
    
    def test_report_is_telegram_formatted(self):
        """Report should use Telegram markdown formatting"""
        strategy = MockStrategy(active=True)
        
        report = build_strategy_report(strategy)
        assert report is not None
        # Check for Telegram formatting
        assert "*" in report  # Bold
        assert "`" in report  # Code blocks
        assert "—" in report  # Separators


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

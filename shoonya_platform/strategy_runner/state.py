from dataclasses import dataclass, field
from typing import Dict, Optional, List, Any
from datetime import datetime, date
from .models import InstrumentType, OptionType, Side

@dataclass
class LegState:
    tag: str
    symbol: str
    instrument: InstrumentType
    option_type: Optional[OptionType]   # None for FUT
    strike: Optional[float]             # None for FUT
    expiry: str                          # YYYY-MM-DD or special code
    side: Side
    qty: int                              # current lots (can be reduced)
    entry_price: float
    ltp: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    iv: float = 0.0
    is_active: bool = True

    # New fields from gap analysis
    group: str = ""               # for group exits
    label: str = ""                # user label
    oi: int = 0
    oi_change: int = 0
    volume: int = 0

    @property
    def pnl(self) -> float:
        if self.side == Side.BUY:
            return (self.ltp - self.entry_price) * self.qty
        else:
            return (self.entry_price - self.ltp) * self.qty

    @property
    def pnl_pct(self) -> float:
        if self.entry_price == 0:
            return 0.0
        return (self.pnl / (self.entry_price * self.qty)) * 100

    @property
    def abs_delta(self) -> float:
        return abs(self.delta)

    @property
    def abs_gamma(self) -> float:
        return abs(self.gamma)

    @property
    def abs_theta(self) -> float:
        return abs(self.theta)

    @property
    def abs_vega(self) -> float:
        return abs(self.vega)

    @property
    def moneyness(self) -> float:
        if self.option_type is None or self.strike is None or self.ltp == 0:
            return 0.0
        if self.option_type == OptionType.CE:
            return (self.strike - self.ltp) / self.ltp
        else:
            return (self.ltp - self.strike) / self.ltp

@dataclass
class StrategyState:
    legs: Dict[str, LegState] = field(default_factory=dict)

    spot_price: float = 0.0
    spot_open: float = 0.0
    atm_strike: float = 0.0
    fut_ltp: float = 0.0
    # index_data: key = symbol (e.g., "INDIAVIX"), value = dict of metrics (ltp, change, etc.)
    index_data: Dict[str, Dict[str, float]] = field(default_factory=dict)

    adjustments_today: int = 0
    total_trades_today: int = 0
    cumulative_daily_pnl: float = 0.0
    minutes_to_exit: int = 0   # minutes until EOD exit
    entry_time: Optional[datetime] = None
    last_adjustment_time: Optional[datetime] = None

    trailing_stop_active: bool = False
    trailing_stop_level: float = 0.0
    peak_pnl: float = 0.0

    # Additional runtime fields
    current_time: Optional[datetime] = None

    # New fields from gap analysis
    prev_values: Dict[str, Any] = field(default_factory=dict)   # for crosses_above/below
    lifetime_adjustments: int = 0
    current_profit_step: int = -1
    last_date: Optional[date] = None
    entered_today: bool = False

    @property
    def net_delta(self) -> float:
        return sum(leg.delta for leg in self.legs.values() if leg.is_active)

    @property
    def combined_pnl(self) -> float:
        return sum(leg.pnl for leg in self.legs.values() if leg.is_active)

    @property
    def total_premium(self) -> float:
        total = 0.0
        for leg in self.legs.values():
            if leg.is_active and leg.instrument == InstrumentType.OPT:
                if leg.side == Side.SELL:
                    total += leg.entry_price * leg.qty
                else:
                    total -= leg.entry_price * leg.qty
        return total

    @property
    def max_leg_delta(self) -> float:
        if not self.legs:
            return 0.0
        return max((leg.abs_delta for leg in self.legs.values() if leg.is_active), default=0.0)

    @property
    def min_leg_delta(self) -> float:
        if not self.legs:
            return 0.0
        return min((leg.abs_delta for leg in self.legs.values() if leg.is_active), default=0.0)

    @property
    def most_profitable_leg(self) -> Optional[str]:
        if not self.legs:
            return None
        active = [leg for leg in self.legs.values() if leg.is_active]
        if not active:
            return None
        return max(active, key=lambda l: l.pnl).tag

    @property
    def least_profitable_leg(self) -> Optional[str]:
        if not self.legs:
            return None
        active = [leg for leg in self.legs.values() if leg.is_active]
        if not active:
            return None
        return min(active, key=lambda l: l.pnl).tag

    # New computed properties
    @property
    def portfolio_gamma(self) -> float:
        return sum(leg.gamma for leg in self.legs.values() if leg.is_active)

    @property
    def portfolio_theta(self) -> float:
        return sum(leg.theta for leg in self.legs.values() if leg.is_active)

    @property
    def portfolio_vega(self) -> float:
        return sum(leg.vega for leg in self.legs.values() if leg.is_active)

    @property
    def combined_pnl_pct(self) -> float:
        if self.total_premium == 0:
            return 0.0
        return (self.combined_pnl / self.total_premium) * 100

    @property
    def active_legs_count(self) -> int:
        return sum(1 for leg in self.legs.values() if leg.is_active)

    @property
    def closed_legs_count(self) -> int:
        return len(self.legs) - self.active_legs_count

    @property
    def any_leg_active(self) -> bool:
        return self.active_legs_count > 0

    @property
    def all_legs_active(self) -> bool:
        return self.active_legs_count == len(self.legs)

    @property
    def time_in_position_sec(self) -> float:
        if self.entry_time is None:
            return 0.0
        delta = (datetime.now() - self.entry_time).total_seconds()
        return max(0.0, delta)

    @property
    def time_since_last_adj_sec(self) -> float:
        if self.last_adjustment_time is None:
            return 999999.0
        return (datetime.now() - self.last_adjustment_time).total_seconds()

    # Breakeven calculations (simplified – assumes short strangle/straddle)
    @property
    def breakeven_upper(self) -> float:
        return self.atm_strike + self.total_premium

    @property
    def breakeven_lower(self) -> float:
        return self.atm_strike - self.total_premium

    @property
    def breakeven_distance(self) -> float:
        return min(abs(self.spot_price - self.breakeven_upper),
                   abs(self.spot_price - self.breakeven_lower))

    @property
    def spot_vs_upper_be(self) -> float:
        return self.spot_price - self.breakeven_upper

    @property
    def spot_vs_lower_be(self) -> float:
        return self.spot_price - self.breakeven_lower

    @property
    def days_to_expiry(self) -> int:
        """Minimum days to expiry among active legs."""
        if not self.legs:
            return 0
        today = datetime.now().date()
        min_days = 999
        for leg in self.legs.values():
            if not leg.is_active:
                continue
            try:
                exp_date = datetime.strptime(leg.expiry, "%d-%b-%Y").date()
                days = (exp_date - today).days
                if days < min_days:
                    min_days = days
            except ValueError:
                continue
        return min_days if min_days != 999 else 0

    @property
    def is_expiry_day(self) -> bool:
        return self.days_to_expiry == 0

    @property
    def session_type(self) -> str:
        """Return 'morning' if before 12:00, else 'afternoon'."""
        now = datetime.now()
        return "morning" if now.hour < 12 else "afternoon"
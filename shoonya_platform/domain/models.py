#!/usr/bin/env python3
"""
Data Models Module
Contains data classes and models used throughout the application
"""

from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from datetime import datetime

@dataclass
class TradeRecord:
    """Data class to store trade information"""
    timestamp: str
    strategy_name: str
    execution_type: str
    symbol: str
    direction: str
    quantity: int
    price: float
    order_id: str
    status: str
    pnl: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert trade record to dictionary"""
        return {
            'timestamp': self.timestamp,
            'strategy_name': self.strategy_name,
            'execution_type': self.execution_type,
            'symbol': self.symbol,
            'direction': self.direction,
            'quantity': self.quantity,
            'price': self.price,
            'order_id': self.order_id,
            'status': self.status,
            'pnl': self.pnl
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TradeRecord':
        """Create trade record from dictionary"""
        return cls(
            timestamp=data['timestamp'],
            strategy_name=data['strategy_name'],
            execution_type=data['execution_type'],
            symbol=data['symbol'],
            direction=data['direction'],
            quantity=data['quantity'],
            price=data['price'],
            order_id=data['order_id'],
            status=data['status'],
            pnl=data.get('pnl', 0.0)
        )

@dataclass
class OrderParams:
    """Data class for order parameters"""
    trantype: str  # B or S (Buy/Sell)
    prd: str       # Product type (M, C, I)
    exch: str      # Exchange (NSE, NFO, etc.)
    tsym: str      # Trading symbol
    qty: int       # Quantity
    prctyp: str    # Price type (MKT, LMT, etc.)
    prc: float     # Price (0 for market orders)
    dscqty: int = 0      # Disclosed quantity
    trgprc: Optional[float] = None  # Trigger price
    ret: str = 'DAY'      # Retention (DAY, IOC, etc.)
    remarks: str = 'TradingView Alert'  # Order remarks
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert order params to dictionary for API call"""
        params = {
            'buy_or_sell': self.trantype,
            'product_type': self.prd,
            'exchange': self.exch,
            'tradingsymbol': self.tsym,
            'quantity': self.qty,
            'discloseqty': self.dscqty,
            'price_type': self.prctyp,
            'price': self.prc,
            'retention': self.ret,
            'remarks': self.remarks
        }
        
        if self.trgprc is not None:
            params['trigger_price'] = self.trgprc
            
        return params

@dataclass
class LegData:
    """Data class for individual strategy leg"""
    tradingsymbol: str
    direction: str      # BUY or SELL
    qty: int
    order_type: str = 'MKT'    # MKT or LMT
    price: float = 0.0
    product_type: str = 'M'    # M, C, I
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LegData':
        """Create leg data from dictionary"""
        # Normalize keys to lowercase
        normalized = {k.lower(): v for k, v in data.items()}
        
        return cls(
            tradingsymbol=normalized['tradingsymbol'],
            direction=normalized['direction'].upper(),
            qty=int(normalized['qty']),
            order_type=normalized.get('order_type', 'MKT').upper(),
            price=float(normalized.get('price', 0.0)),
            product_type=normalized.get('product_type', 'M')
        )
    
    def to_order_params(self, exchange: str) -> OrderParams:
        """Convert leg data to order parameters"""
        buy_or_sell = 'B' if self.direction == 'BUY' else 'S'
        
        if self.order_type == 'MKT':
            price_type = 'MKT'
            price_value = 0.0
        else:
            price_type = 'LMT'
            price_value = self.price
        
        return OrderParams(
            trantype=buy_or_sell,
            prd=self.product_type,
            exch=exchange.upper(),
            tsym=self.tradingsymbol,
            qty=self.qty,
            prctyp=price_type,
            prc=price_value
        )

@dataclass
class AlertData:
    """Data class for parsed alert data"""
    execution_type: str
    strategy_name: str
    exchange: str
    legs: List[LegData]
    test_mode: Optional[str] = None
    underlying: str = ''
    expiry: str = ''
    product_type: str = 'M'
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AlertData':
        """Create alert data from dictionary"""
        # Normalize keys to lowercase
        normalized = {k.lower(): v for k, v in data.items()}
        
        # Parse legs
        legs = [LegData.from_dict(leg) for leg in normalized['legs']]
        
        return cls(
            test_mode=normalized.get('test_mode'),
            execution_type=normalized['execution_type'],
            strategy_name=normalized.get('strategy_name', 'default'),
            exchange=normalized.get('exchange', 'NFO'),
            legs=legs,
            underlying=normalized.get('underlying', ''),
            expiry=normalized.get('expiry', ''),
            product_type=normalized.get('product_type', 'M')
        )


@dataclass
class OrderResult:
    """Data class for order execution result"""
    success: bool
    order_id: str = ''
    status: str = ''
    error_message: str = ''
    response_data: Optional[Dict[str, Any]] = None
    
    @classmethod
    def from_api_response(cls, response: Dict[str, Any]) -> 'OrderResult':
        """Create order result from API response"""
        if response and response.get('stat') == 'Ok':
            return cls(
                success=True,
                order_id=response.get('norenordno', ''),
                status=response.get('stat', ''),
                response_data=response
            )
        else:
            return cls(
                success=False,
                status=response.get('stat', 'Failed') if response else 'No Response',
                error_message=response.get('emsg', 'Unknown error') if response else 'No response from API',
                response_data=response
            )

@dataclass
class LegResult:
    """Data class for leg execution result"""
    leg_data: LegData
    order_result: OrderResult
    order_params: Optional[OrderParams] = None
    execution_time: Optional[str] = None
    
    def __post_init__(self):
        """Set execution time if not provided"""
        if self.execution_time is None:
            self.execution_time = datetime.now().isoformat()

@dataclass
class AccountInfo:
    """Data class for account information"""
    available_cash: float = 0.0
    used_margin: float = 0.0
    positions: List[Dict[str, Any]] = None
    orders: List[Dict[str, Any]] = None
    
    def __post_init__(self):
        """Initialize empty lists if None"""
        if self.positions is None:
            self.positions = []
        if self.orders is None:
            self.orders = []
    
    @classmethod
    def from_api_data(cls, limits_data: Dict[str, Any], 
                      positions_data: List[Dict[str, Any]] = None,
                      orders_data: List[Dict[str, Any]] = None) -> 'AccountInfo':
        """Create account info from API data"""
        available_cash = float(limits_data.get('cash', 0.0)) if limits_data else 0.0
        used_margin = float(limits_data.get('marginused', 0.0)) if limits_data else 0.0
        
        return cls(
            available_cash=available_cash,
            used_margin=used_margin,
            positions=positions_data or [],
            orders=orders_data or []
        )

@dataclass
class BotStats:
    """Data class for bot statistics"""
    total_trades: int = 0
    today_trades: int = 0
    successful_trades: int = 0
    failed_trades: int = 0
    success_rate: float = 0.0
    last_activity: Optional[str] = None
    
    @classmethod
    def from_trade_records(cls, trade_records: List[TradeRecord]) -> 'BotStats':
        """Create bot stats from trade records"""
        total_trades = len(trade_records)
        today = datetime.now().date()
        
        today_trades = [
            t for t in trade_records 
            if datetime.fromisoformat(t.timestamp).date() == today
        ]
        
        successful_trades = len([t for t in trade_records if t.status in ("PLACED", "FILLED", "TRIGGERED")])
        failed_trades = total_trades - successful_trades
        success_rate = (successful_trades / total_trades * 100) if total_trades > 0 else 0.0
        
        last_activity = trade_records[-1].timestamp if trade_records else None
        
        return cls(
            total_trades=total_trades,
            today_trades=len(today_trades),
            successful_trades=successful_trades,
            failed_trades=failed_trades,
            success_rate=success_rate,
            last_activity=last_activity
        )

#!/usr/bin/env python3
"""
Utility Functions Module
Contains helper functions and utilities used throughout the application
"""

import hmac
import hashlib
import logging
import traceback
from datetime import datetime, timedelta, date

from functools import wraps
import time

from typing import Dict, Any, List, Optional, Callable, Tuple

logger = logging.getLogger(__name__)

def setup_logging(log_file: str = 'webhook_bot.log',
                 log_level: str = 'INFO') -> logging.Logger:
    """
    Setup application-wide logging with rotation.

    - Rotates at 10 MB
    - Keeps last 5 log files
    - Logs to both file and stdout
    """

    import sys
    from pathlib import Path
    from logging.handlers import RotatingFileHandler

    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # # Prevent duplicate handlers (important for python -m runs)
    # if root_logger.handlers:
    #     return root_logger

    # Remove existing handlers to enforce our logging config
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)


    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Rotating file handler
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(formatter)

    # Console handler (wrap stdout to ensure UTF-8 with safe error handling)
    try:
        import io
        console_stream = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )
    except Exception:
        console_stream = sys.stdout

    console_handler = logging.StreamHandler(console_stream)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    return root_logger


def validate_webhook_signature(payload: str, signature: str, secret_key: str) -> bool:
    """Validate webhook signature for security"""
    if not signature:
        logger.warning("No signature provided")
        return True  # Allow if no signature verification needed
    
    try:
        expected_signature = hmac.new(
            secret_key.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(signature, expected_signature)
    except Exception as e:
        logger.error(f"Signature validation error: {e}")
        return False

def format_currency(amount: Any) -> str:
    """Format currency for display"""
    try:
        return f"₹{float(amount):,.2f}" if amount else "₹0.00"
    except (ValueError, TypeError):
        return "₹0.00"

def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert value to float"""
    try:
        return float(value) if value is not None else default
    except (ValueError, TypeError):
        return default

def safe_int(value: Any, default: int = 0) -> int:
    """Safely convert value to int"""
    try:
        return int(value) if value is not None else default
    except (ValueError, TypeError):
        return default

def normalize_dict_keys(data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert all dictionary keys to lowercase"""
    if not isinstance(data, dict):
        return data
    
    return {k.lower(): v for k, v in data.items()}

def validate_required_fields(data: Dict[str, Any], required_fields: List[str]) -> List[str]:
    """Validate that all required fields are present in data"""
    missing_fields = []
    for field in required_fields:
        if field not in data or data[field] is None:
            missing_fields.append(field)
    return missing_fields

def retry_on_exception(max_attempts: int = 3, delay: float = 1.0, 
                      exceptions: tuple = (Exception,)):
    """Decorator to retry function on specific exceptions"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    logger.warning(f"Attempt {attempt + 1}/{max_attempts} failed: {e}")
                    
                    if attempt < max_attempts - 1:
                        time.sleep(delay)
                    else:
                        logger.error(f"All {max_attempts} attempts failed")
                        raise last_exception
            
            return None
        return wrapper
    return decorator

def get_date_filter(date_str: Optional[str] = None) -> Optional[date]:
    """Parse date string and return date object"""
    if not date_str:
        return None
    
    try:
        return datetime.fromisoformat(date_str).date()
    except ValueError:
        logger.error(f"Invalid date format: {date_str}")
        return None

def calculate_success_rate(successful: int, total: int) -> float:
    """Calculate success rate percentage"""
    if total == 0:
        return 0.0
    return (successful / total) * 100

def filter_trades_by_date(trade_records: List, target_date: date) -> List:
    """Filter trade records by specific date"""
    return [
        trade for trade in trade_records
        if datetime.fromisoformat(trade.timestamp).date() == target_date
    ]

def get_today_trades(trade_records: List) -> List:
    """Get today's trade records"""
    today = datetime.now().date()
    return filter_trades_by_date(trade_records, today)

def get_yesterday_trades(trade_records: List) -> List:
    """Get yesterday's trade records"""
    yesterday = datetime.now().date() - timedelta(days=1)
    return filter_trades_by_date(trade_records, yesterday)

def format_timestamp(timestamp: str, format_str: str = '%Y-%m-%d %H:%M:%S') -> str:
    """Format ISO timestamp to readable string"""
    try:
        dt = datetime.fromisoformat(timestamp)
        return dt.strftime(format_str)
    except ValueError:
        return timestamp

def log_exception(func_name: str, exception: Exception) -> None:
    """Log exception with traceback"""
    logger.error(f"Exception in {func_name}: {exception}")
    logger.error(f"Traceback: {traceback.format_exc()}")

def create_response_dict(status: str, message: str = '', data: Any = None, 
                        timestamp: Optional[str] = None) -> Dict[str, Any]:
    """Create standardized API response dictionary"""
    response = {
        'status': status,
        'timestamp': timestamp or datetime.now().isoformat()
    }
    
    if message:
        response['message'] = message
    
    if data is not None:
        response['data'] = data
    
    return response

def generate_totp(secret_key: str) -> Optional[str]:
    """Generate TOTP for two-factor authentication"""
    try:
        import pyotp
        totp = pyotp.TOTP(secret_key)
        return totp.now()
    except ImportError:
        logger.error("pyotp library not installed. Install with: pip install pyotp")
        return None
    except Exception as e:
        logger.error(f"Error generating TOTP: {e}")
        return None

def parse_json_safely(payload: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Safely parse JSON payload and return data and error message"""
    try:
        import json
        data = json.loads(payload)
        return data, None
    except json.JSONDecodeError as e:
        error_msg = f"Invalid JSON: {str(e)}"
        logger.error(f"{error_msg}. Payload: {payload[:200]}...")
        return None, error_msg

def truncate_string(text: str, max_length: int = 200) -> str:
    """Truncate string to maximum length with ellipsis"""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."

def validate_order_direction(direction: str) -> str:
    """Validate and normalize order direction"""
    direction = direction.upper().strip()
    if direction in ['BUY', 'B']:
        return 'BUY'
    elif direction in ['SELL', 'S']:
        return 'SELL'
    else:
        raise ValueError(f"Invalid order direction: {direction}")

def validate_order_type(order_type: str) -> str:
    """Validate and normalize order type"""
    order_type = order_type.upper().strip()
    valid_types = ['MKT', 'MARKET', 'LMT', 'LIMIT']
    
    if order_type in ['MKT', 'MARKET']:
        return 'MKT'
    elif order_type in ['LMT', 'LIMIT']:
        return 'LMT'
    else:
        raise ValueError(f"Invalid order type: {order_type}. Valid types: {valid_types}")

def validate_product_type(product_type: str) -> str:
    """Validate and normalize product type"""
    product_type = product_type.upper().strip()
    valid_types = ['M', 'C', 'I', 'MARGIN', 'CNC', 'INTRADAY']
    
    if product_type in ['M', 'MARGIN']:
        return 'M'
    elif product_type in ['C', 'CNC']:
        return 'C'
    elif product_type in ['I', 'INTRADAY']:
        return 'I'
    elif product_type in valid_types:
        return product_type
    else:
        raise ValueError(f"Invalid product type: {product_type}. Valid types: {valid_types}")

def get_market_hours() -> Dict[str, str]:
    """Get market opening and closing hours"""
    return {
        'market_open': '09:15',
        'market_close': '15:30',
        'pre_open': '09:00',
        'post_close': '16:00'
    }

def is_market_open() -> bool:
    """Check if market is currently open"""
    now = datetime.now().time()
    market_hours = get_market_hours()
    
    try:
        market_open = datetime.strptime(market_hours['market_open'], '%H:%M').time()
        market_close = datetime.strptime(market_hours['market_close'], '%H:%M').time()
        
        return market_open <= now <= market_close
    except ValueError:
        return False

def is_weekend() -> bool:
    """Check if today is weekend"""
    return datetime.now().weekday() >= 5  # 5 = Saturday, 6 = Sunday

def should_trade() -> bool:
    """Check if trading should be allowed (market open and not weekend)"""
    return is_market_open() and not is_weekend()

def sanitize_symbol(symbol: str) -> str:
    """Sanitize trading symbol"""
    return symbol.upper().strip()

def validate_quantity(quantity: Any) -> int:
    """Validate and normalize quantity"""
    try:
        qty = int(quantity)
        if qty <= 0:
            raise ValueError("Quantity must be positive")
        return qty
    except (ValueError, TypeError):
        raise ValueError(f"Invalid quantity: {quantity}")

def validate_price(price: Any) -> float:
    """Validate and normalize price"""
    try:
        price_val = float(price)
        if price_val < 0:
            raise ValueError("Price cannot be negative")
        return price_val
    except (ValueError, TypeError):
        raise ValueError(f"Invalid price: {price}")

class Timer:
    """Simple timer context manager"""
    
    def __init__(self, description: str = "Operation"):
        self.description = description
        self.start_time = None
        self.end_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        logger.debug(f"Starting {self.description}...")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
        duration = self.end_time - self.start_time
        logger.debug(f"{self.description} completed in {duration:.3f} seconds")
    
    @property
    def elapsed(self) -> float:
        """Get elapsed time"""
        if self.start_time is None:
            return 0.0
        end = self.end_time or time.time()
        return end - self.start_time
    
def safe_api_call(
    func: Callable[..., Any],
    *args,
    retries: int = 3,
    delay: float = 1.0,
    **kwargs
) -> Optional[Any]:
    """
    ⚠️ IMPORTANT USAGE POLICY ⚠️

    This helper is for NON–TIME-CRITICAL API calls only.

    ❌ STRICTLY FORBIDDEN:
        - get_quotes()
        - get_ltp()
        - any live market data
        - ATM / option-chain resolution
        - strategy execution paths

    ✅ ALLOWED:
        - get_limits
        - get_holdings
        - searchscrip
        - diagnostics / dashboards
        - reference / metadata calls

    Reason:
        Market data APIs may legally return empty or delayed responses.
        Retrying them breaks determinism and causes false failures.
    """

    func_name = getattr(func, "__name__", str(func))

    # 🚨 HARD SAFETY GUARD — DO NOT REMOVE
    if func_name in ("get_quotes", "get_ltp"):
        raise RuntimeError(
            f"❌ safe_api_call MUST NOT be used with {func_name}(). "
            f"Call ShoonyaClient.{func_name}() directly."
        )

    last_exc: Optional[Exception] = None

    for attempt in range(1, retries + 1):
        try:
            response = func(*args, **kwargs)

            if response is None:
                raise RuntimeError("API returned None")

            return response

        except Exception as exc:
            last_exc = exc
            logger.warning(
                "API call failed (%d/%d) [%s]: %s",
                attempt,
                retries,
                func_name,
                exc,
            )

            if attempt < retries:
                time.sleep(delay)

    logger.error(
        "API call permanently failed after %d attempts [%s]",
        retries,
        func_name,
    )

    if last_exc:
        logger.debug("Last exception traceback", exc_info=last_exc)

    return None

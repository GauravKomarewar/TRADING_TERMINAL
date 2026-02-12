#!/usr/bin/env python3
"""
Simple Option Finder

Single function to find options by ANY parameter and return full details.

Usage:
    find_option(field="delta", value=0.3, option_type="CE", exchange="NFO", symbol="NIFTY")
    find_option(field="strike", value=23700, exchange="NFO", symbol="NIFTY")
    find_option(field="ltp", value=200, option_type="CE", exchange="NFO", symbol="NIFTY")
    find_option(field="oi", value=5000000, exchange="NFO", symbol="NIFTY")
    find_option(field="volume", value=100000, exchange="NFO", symbol="NIFTY")
"""

import sqlite3
from typing import Dict, List, Optional, Union
from pathlib import Path


def find_option(
    field: str,
    value: Union[int, float],
    exchange: str = "NFO",
    symbol: str = "NIFTY",
    option_type: Optional[str] = None,
    db_path: Optional[str] = None,
    tolerance: Optional[float] = None,
    use_absolute: bool = False,
) -> Optional[Dict]:
    """
    Find an option by ANY field and return complete details.
    
    Args:
        field: Field to search by (delta, gamma, theta, vega, iv, strike, ltp, oi, volume, etc.)
        value: Target value to match
        exchange: Exchange code (NFO, BSE, NSE, MCX)
        symbol: Symbol (NIFTY, BANKNIFTY, FINNIFTY, etc.)
        option_type: "CE" or "PE" (optional, searches both if not specified)
        db_path: Path to SQLite database (auto-detects if None)
        tolerance: Tolerance for numerical match (if None, finds nearest)
        use_absolute: Use absolute value for comparison (for negative deltas)
    
    Returns:
        Dict with full option details or None if not found
        
    Examples:
        # Find CE with delta ≈ 0.3
        option = find_option(field="delta", value=0.3, option_type="CE", symbol="NIFTY")
        
        # Find any option at strike 23700
        option = find_option(field="strike", value=23700, symbol="NIFTY")
        
        # Find PE with LTP ≈ 200
        option = find_option(field="ltp", value=200, option_type="PE", symbol="NIFTY")
        
        # Find option with OI ≈ 5,000,000
        option = find_option(field="oi", value=5000000, symbol="NIFTY")
        
        # Find option with volume ≈ 100,000
        option = find_option(field="volume", value=100000, symbol="NIFTY")
    """
    
    # Auto-detect database path if not provided
    if db_path is None:
        db_path = _find_database_path()
    
    if not db_path or not Path(db_path).exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    
    # Normalize field name
    field = field.lower().strip()
    
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get all columns to check what's available
        cursor.execute(f"PRAGMA table_info(option_chain)")
        columns = {row[1].lower(): row[1] for row in cursor.fetchall()}
        
        if field not in columns:
            available = ", ".join(sorted(columns.keys()))
            raise ValueError(f"Field '{field}' not found. Available fields: {available}")
        
        # Build base query
        query = "SELECT * FROM option_chain WHERE symbol = ?"
        params = [symbol]
        
        if option_type:
            query += " AND option_type = ?"
            params.append(option_type)
        
        # Execute query
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return None
        
        # Find nearest match to value
        def distance(row_val):
            if row_val is None:
                return float('inf')
            if use_absolute:
                row_val = abs(row_val)
            return abs(row_val - value)
        
        # Get all column names (in lowercase for case-insensitive matching)
        all_columns = [d[0] for d in cursor.description] if cursor.description else []
        
        nearest = None
        min_distance = float('inf')
        
        for row in rows:
            try:
                row_value = row[columns[field]]
                if row_value is None:
                    continue
                
                dist = distance(row_value)
                
                if dist < min_distance:
                    min_distance = dist
                    nearest = dict(row)
            except (IndexError, TypeError):
                continue
        
        return nearest if nearest else None
        
    except sqlite3.Error as e:
        raise RuntimeError(f"Database error: {e}")
    finally:
        if conn is not None:
            conn.close()


def find_options(
    field: str,
    value: Union[int, float],
    exchange: str = "NFO",
    symbol: str = "NIFTY",
    option_type: Optional[str] = None,
    db_path: Optional[str] = None,
    limit: int = 10,
    use_absolute: bool = False,
) -> List[Dict]:
    """
    Find multiple options matching criteria, ordered by proximity to value.
    
    Args:
        field: Field to search by
        value: Target value
        exchange: Exchange code
        symbol: Symbol
        option_type: "CE" or "PE" (optional)
        db_path: Path to database
        limit: Maximum number of results
        use_absolute: Use absolute value for comparison
    
    Returns:
        List of dicts with option details, sorted by distance to value
        
    Examples:
        # Find all options near delta 0.3
        options = find_options(field="delta", value=0.3, limit=5)
        
        # Find top 5 options by volume
        options = find_options(field="volume", value=100000, limit=5)
    """
    
    if db_path is None:
        db_path = _find_database_path()
    
    if not db_path or not Path(db_path).exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    
    field = field.lower().strip()
    
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = "SELECT * FROM option_chain WHERE symbol = ?"
        params = [symbol]
        
        if option_type:
            query += " AND option_type = ?"
            params.append(option_type)
        
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return []
        
        # Convert to dicts and calculate distance
        results = []
        for row in rows:
            try:
                row_value = row[field]
                if row_value is None:
                    continue
                
                if use_absolute:
                    row_value = abs(row_value)
                
                distance = abs(row_value - value)
                row_dict = dict(row)
                row_dict['_distance'] = distance
                results.append(row_dict)
            except (KeyError, TypeError):
                continue
        
        # Sort by distance and limit
        results.sort(key=lambda x: x['_distance'])
        return results[:limit]
        
    except sqlite3.Error as e:
        raise RuntimeError(f"Database error: {e}")
    finally:
        if conn is not None:
            conn.close()


def find_option_by_multiple_criteria(
    criteria: Dict[str, Union[int, float]],
    exchange: str = "NFO",
    symbol: str = "NIFTY",
    option_type: Optional[str] = None,
    db_path: Optional[str] = None,
    weighting: Optional[Dict[str, Union[int, float]]] = None,
) -> Optional[Dict]:
    """
    Find option matching multiple criteria with weighted scoring.
    
    Args:
        criteria: Dict of {field: target_value}
        exchange: Exchange code
        symbol: Symbol
        option_type: "CE" or "PE"
        db_path: Path to database
        weighting: Dict of {field: weight} (default: equal weight)
    
    Returns:
        Best matching option dict or None
        
    Example:
        # Find option close to delta=0.3 AND strike=23700 AND ltp=200
        option = find_option_by_multiple_criteria(
            criteria={"delta": 0.3, "strike": 23700, "ltp": 200},
            weighting={"delta": 2.0, "strike": 1.0, "ltp": 0.5}
        )
    """
    
    if db_path is None:
        db_path = _find_database_path()
    
    if not db_path or not Path(db_path).exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    
    if not criteria:
        raise ValueError("criteria dict cannot be empty")
    
    # Set default weighting (equal)
    if weighting is None:
        weighting = {field: 1.0 for field in criteria}
    
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = "SELECT * FROM option_chain WHERE symbol = ?"
        params = [symbol]
        
        if option_type:
            query += " AND option_type = ?"
            params.append(option_type)
        
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return None
        
        # Calculate weighted score for each option
        best_option = None
        best_score = float('inf')
        
        for row in rows:
            score = 0
            valid = True
            
            for field, target_value in criteria.items():
                try:
                    row_value = row[field.lower()]
                    if row_value is None:
                        valid = False
                        break
                    
                    distance = abs(row_value - target_value)
                    weight = weighting.get(field, 1.0)
                    score += distance * weight
                except (KeyError, TypeError):
                    valid = False
                    break
            
            if valid and score < best_score:
                best_score = score
                best_option = dict(row)
        
        return best_option
        
    except sqlite3.Error as e:
        raise RuntimeError(f"Database error: {e}")
    finally:
        if conn is not None:
            conn.close()


def get_option_details(symbol: Optional[str] = None, token: Optional[int] = None, db_path: Optional[str] = None) -> Optional[Dict]:
    """
    Get complete details by symbol or token.
    
    Args:
        symbol: Trading symbol (e.g., "NIFTY_25FEB_23700_CE")
        token: Option token
        db_path: Path to database
    
    Returns:
        Full option details dict or None
    """
    
    if db_path is None:
        db_path = _find_database_path()
    
    if not db_path or not Path(db_path).exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if symbol:
            cursor.execute("SELECT * FROM option_chain WHERE symbol = ?", (symbol,))
        elif token:
            cursor.execute("SELECT * FROM option_chain WHERE token = ?", (token,))
        else:
            return None
        
        row = cursor.fetchone()
        conn.close()
        
        return dict(row) if row else None
        
    except sqlite3.Error as e:
        raise RuntimeError(f"Database error: {e}")
    finally:
        if conn is not None:
            conn.close()


def _find_database_path() -> Optional[str]:
    """Auto-detect database path from common locations."""
    possible_paths = [
        "market_data.sqlite",
        "market_data.db",
        Path.home() / ".shoonya" / "market_data.sqlite",
        Path(__file__).parent / "market_data.sqlite",
    ]
    
    for path in possible_paths:
        if isinstance(path, str):
            path = Path(path)
        if path.exists():
            return str(path)
    
    return None


# ═════════════════════════════════════════════════════════════════════════
# JSON API (for web pages)
# ═════════════════════════════════════════════════════════════════════════

def find_option_json(request_json: Dict) -> Dict:
    """
    JSON API for web pages to find options.
    
    JSON Input Format:
    {
        "field": "delta",
        "value": 0.3,
        "symbol": "NIFTY",
        "option_type": "CE",
        "exchange": "NFO"
    }
    
    JSON Output:
    {
        "success": true,
        "option": {
            "symbol": "NIFTY_25FEB_23700_CE",
            "token": 12345,
            "strike": 23700,
            "delta": 0.30,
            ... all other fields
        }
    }
    """
    
    try:
        field = request_json.get("field", "").lower()
        value = float(request_json.get("value", 0))
        symbol = request_json.get("symbol", "NIFTY")
        option_type = request_json.get("option_type")
        exchange = request_json.get("exchange", "NFO")
        db_path = request_json.get("db_path")
        use_absolute = request_json.get("use_absolute", False)
        
        if not field:
            return {
                "success": False,
                "error": "field is required"
            }
        
        option = find_option(
            field=field,
            value=value,
            symbol=symbol,
            option_type=option_type,
            exchange=exchange,
            db_path=db_path,
            use_absolute=use_absolute
        )
        
        if option:
            return {
                "success": True,
                "option": option
            }
        else:
            return {
                "success": False,
                "error": f"No option found matching {field}={value}"
            }
    
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def find_options_json(request_json: Dict) -> Dict:
    """
    JSON API to find multiple options.
    
    JSON Input:
    {
        "field": "delta",
        "value": 0.3,
        "symbol": "NIFTY",
        "limit": 5
    }
    
    JSON Output:
    {
        "success": true,
        "options": [
            {"symbol": "...", "delta": 0.30, ...},
            {"symbol": "...", "delta": 0.31, ...},
            ...
        ],
        "count": 5
    }
    """
    
    try:
        field = request_json.get("field", "").lower()
        value_raw = request_json.get("value")
        value = float(value_raw) if value_raw is not None else 0.0
        symbol = request_json.get("symbol", "NIFTY")
        option_type = request_json.get("option_type")
        limit = int(request_json.get("limit", 10))
        db_path = request_json.get("db_path")
        
        if not field:
            return {
                "success": False,
                "error": "field is required"
            }
        
        options = find_options(
            field=field,
            value=value,
            symbol=symbol,
            option_type=option_type,
            db_path=db_path,
            limit=limit
        )
        
        # Remove internal _distance field before returning
        for opt in options:
            opt.pop('_distance', None)
        
        return {
            "success": True,
            "options": options,
            "count": len(options)
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


if __name__ == "__main__":
    # Example usage
    try:
        # Find CE option with delta ≈ 0.3
        print("Example 1: Find CE with delta ≈ 0.3")
        option = find_option(field="delta", value=0.3, option_type="CE")
        if option:
            print(f"  Symbol: {option.get('symbol')}")
            print(f"  Delta: {option.get('delta')}")
            print(f"  Strike: {option.get('strike')}")
        else:
            print("  No option found (database might not exist)")
        
        # Find option at strike 23700
        print("\nExample 2: Find any option at strike 23700")
        option = find_option(field="strike", value=23700)
        if option:
            print(f"  Symbol: {option.get('symbol')}")
            print(f"  Strike: {option.get('strike')}")
        else:
            print("  No option found")
        
        # Find multiple options
        print("\nExample 3: Find top 5 options near delta 0.3")
        options = find_options(field="delta", value=0.3, limit=5)
        for opt in options:
            print(f"  {opt.get('symbol')}: delta={opt.get('delta')}")
        
    except Exception as e:
        print(f"Error: {e}")

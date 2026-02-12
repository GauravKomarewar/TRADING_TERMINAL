#!/usr/bin/env python3
"""
DNSS Database Setup & Initialization
====================================
Creates the SQLite database structure for option chain data if it doesn't exist.
Also provides utilities to populate test data.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime, date, timedelta

def create_database_structure(db_path: str) -> bool:
    """Create option_chain.db with proper schema"""
    
    try:
        db_file = Path(db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Create option_chain table with MultiIndex-like structure
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS option_chain (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            
            -- Identification
            symbol TEXT NOT NULL,
            underlying TEXT NOT NULL,
            expiry TEXT NOT NULL,
            
            -- CE (Call) leg data
            ce_symbol TEXT,
            ce_last_price REAL,
            ce_bid REAL,
            ce_ask REAL,
            ce_delta REAL,
            ce_gamma REAL,
            ce_theta REAL,
            ce_vega REAL,
            ce_iv REAL,
            
            -- PE (Put) leg data
            pe_symbol TEXT,
            pe_last_price REAL,
            pe_bid REAL,
            pe_ask REAL,
            pe_delta REAL,
            pe_gamma REAL,
            pe_theta REAL,
            pe_vega REAL,
            pe_iv REAL,
            
            -- Spot price
            spot_price REAL,
            
            UNIQUE(symbol, expiry, timestamp)
        )
        """)
        
        # Create index for fast lookups
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_symbol_expiry ON option_chain(symbol, expiry)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON option_chain(timestamp DESC)")
        
        conn.commit()
        conn.close()
        
        return True
    except Exception as e:
        print(f"❌ Failed to create database: {e}")
        return False


def add_sample_nifty_data(db_path: str) -> bool:
    """Add sample NIFTY option chain data for testing"""
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get current expiry (next Thursday)
        today = date.today()
        days_until_thursday = (3 - today.weekday()) % 7
        if days_until_thursday == 0:
            expiry_date = today
        else:
            expiry_date = today + timedelta(days=days_until_thursday)
        
        expiry = expiry_date.strftime("%d%b%Y").upper()
        timestamp = datetime.now().isoformat()
        
        # Sample NIFTY strikes
        strikes = [24700, 24750, 24800, 24850, 24900, 24950, 25000]
        spot = 24875
        
        for strike in strikes:
            # Calculate sample greeks (simplified approximation)
            ce_delta = 0.5 + (strike - spot) / 2000  # Delta decreases as OTM
            pe_delta = -0.5 - (strike - spot) / 2000
            
            ce_price = max(10 + (spot - strike) / 2, 0.05)
            pe_price = max(10 + (strike - spot) / 2, 0.05)
            
            cursor.execute("""
            INSERT OR REPLACE INTO option_chain 
            (symbol, underlying, expiry, 
             ce_symbol, ce_last_price, ce_delta, ce_gamma, ce_theta,
             pe_symbol, pe_last_price, pe_delta, pe_gamma, pe_theta,
             spot_price, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                f"NIFTY_{strike}",  # symbol
                "NIFTY",           # underlying
                expiry,            # expiry
                
                # CE data
                f"NIFTY_{strike}CE",      # ce_symbol
                ce_price,                 # ce_last_price
                ce_delta,                 # ce_delta
                0.002,                    # ce_gamma
                -0.05,                    # ce_theta
                
                # PE data
                f"NIFTY_{strike}PE",      # pe_symbol
                pe_price,                 # pe_last_price
                pe_delta,                 # pe_delta
                0.002,                    # pe_gamma
                -0.05,                    # pe_theta
                
                # Spot
                spot,                     # spot_price
                timestamp                 # timestamp
            ))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Added {len(strikes)} sample NIFTY options for {expiry}")
        return True
    
    except Exception as e:
        print(f"❌ Failed to add sample data: {e}")
        return False


def verify_database(db_path: str) -> dict:
    """Verify database structure and content"""
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        
        # Check option count
        cursor.execute("SELECT COUNT(*) FROM option_chain")
        count = cursor.fetchone()[0]
        
        # Check NIFTY data
        cursor.execute("SELECT COUNT(*) FROM option_chain WHERE underlying='NIFTY'")
        nifty_count = cursor.fetchone()[0]
        
        # Get latest timestamp
        cursor.execute("SELECT MAX(timestamp) FROM option_chain")
        latest = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "success": True,
            "tables": tables,
            "total_rows": count,
            "nifty_rows": nifty_count,
            "latest_update": latest,
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def main():
    """Initialize database"""
    print("\n" + "="*70)
    print("DNSS DATABASE INITIALIZATION")
    print("="*70 + "\n")
    
    db_path = "shoonya_platform/market_data/option_chain/data/option_chain.db"
    
    # Create database structure
    print(f"📝 Creating database structure at: {db_path}")
    if not create_database_structure(db_path):
        return 1
    
    print("✅ Database structure created\n")
    
    # Add sample data
    print("📊 Adding sample NIFTY option chain data for testing...")
    if not add_sample_nifty_data(db_path):
        return 1
    
    print("✅ Sample data added\n")
    
    # Verify
    print("🔍 Verifying database...")
    result = verify_database(db_path)
    
    if result["success"]:
        print(f"✅ Database verified:")
        print(f"   Tables: {result['tables']}")
        print(f"   Total rows: {result['total_rows']}")
        print(f"   NIFTY rows: {result['nifty_rows']}")
        print(f"   Latest update: {result['latest_update']}\n")
        
        print("="*70)
        print("✅ DATABASE READY FOR TESTING")
        print("="*70)
        print("\n⚠️  NOTE: This is SAMPLE DATA only for testing!")
        print("For LIVE TRADING, you need a real market data feed updating every 2 seconds.")
        print("\nRun the pre-flight check:")
        print("  python dnss_nifty_precheck.py\n")
        
        return 0
    else:
        print(f"❌ Verification failed: {result['error']}")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())

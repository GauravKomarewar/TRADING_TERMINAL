"""
Disk-backed ScriptMaster Loader (Production Grade) 
=========================================================
#NOTE:
BFO contracts do not expose canonical underlying symbols.
Underlying is derived from TradingSymbol and used for
expiry grouping and symbol resolution.

Design goals:
- Download Shoonya scripmasters ONCE per day
- Normalize & clean data
- Persist to disk (raw + processed)
- Load from disk during runtime
- ZERO network dependency during trading
- Exchange-correct futures & options handling
- Calendar-driven expiry resolution

SAFE TO FREEZE & USE IN PRODUCTION
"""
#============================================
#SCRIPTMASTER v2.0
#OMS ORDER-TYPE RULES
#STATUS: PRODUCTION FROZEN
#============================================
from __future__ import annotations

import io
import zipfile
import json
import logging
import requests
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# =============================================================================
# VERSION (FREEZE CONTRACT)
# =============================================================================

SCRIPTMASTER_VERSION = "2.0"

# =============================================================================
# CONFIG
# =============================================================================

BASE_URL = "https://api.shoonya.com"

SCRIPTMASTER_URLS = {
    "NSE": f"{BASE_URL}/NSE_symbols.txt.zip",
    "NFO": f"{BASE_URL}/NFO_symbols.txt.zip",
    "BSE": f"{BASE_URL}/BSE_symbols.txt.zip",
    "BFO": f"{BASE_URL}/BFO_symbols.txt.zip",
    "MCX": f"{BASE_URL}/MCX_symbols.txt.zip",
}

DATA_DIR = Path(__file__).resolve().parent / "scriptmaster_store"
RAW_DIR = DATA_DIR / "raw"
PROC_DIR = DATA_DIR / "processed"
META_FILE = DATA_DIR / "metadata.json"

for d in (RAW_DIR, PROC_DIR):
    d.mkdir(parents=True, exist_ok=True)

# =============================================================================
# CANONICAL INSTRUMENT GROUPS (BASED ON REAL DATA)
# =============================================================================

FUTURE_INSTRUMENTS = {
    "NFO": {"FUTIDX", "FUTSTK"},
    "BFO": {"FUTIDX", "FUTSTK"},  
    "MCX": {"FUTCOM"},
}

OPTION_INSTRUMENTS = {
    "NFO": {"OPTIDX", "OPTSTK"},
    "BFO": {"OPTIDX", "OPTSTK"}, 
    "MCX": {"OPTFUT"},
}

# =============================================================================
# IN-MEMORY STORES
# =============================================================================

SCRIPTMASTER: Dict[str, Dict[str, Dict[str, Any]]] = {}
SCRIPTMASTER_UNIVERSAL: Dict[str, Dict[str, Any]] = {}
EXPIRY_CALENDAR: Dict[str, Dict[str, Dict[str, list[str]]]] = {}
_LAST_REFRESH_DATE: Optional[str] = None

# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _today_ist() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


def _should_refresh() -> bool:
    if not META_FILE.exists():
        return True

    try:
        meta = json.loads(META_FILE.read_text())
        return meta.get("date") != _today_ist()
    except Exception:
        return True


def _download_zip(exchange: str, url: str) -> Path:
    logger.info(f"⬇️ Downloading {exchange} scripmaster")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    zip_path = RAW_DIR / f"{exchange}.zip"
    zip_path.write_bytes(resp.content)
    return zip_path


def _extract_txt(zip_path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as z:
        txt = next(n for n in z.namelist() if n.lower().endswith(".txt"))
        with z.open(txt) as f:
            return pd.read_csv(f, sep=",", low_memory=False)

def _extract_underlying(tradingsymbol: str, symbol: Optional[str] = None) -> Optional[str]:
    """
    Extract canonical underlying using Symbol as anchor.
    """
    if not tradingsymbol:
        return None

    ts = tradingsymbol.upper()

    # 1️⃣ Trust Symbol column if it is a prefix
    if symbol:
        sym = symbol.upper()
        if ts.startswith(sym):
            return sym

    # 2️⃣ Fallback (rare / defensive)
    ts = re.sub(r"(CE|PE|FUT|F)$", "", ts)
    ts = re.sub(
        r"\d{2}(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{0,2}",
        "",
        ts,
    )
    ts = re.sub(r"\d+$", "", ts)

    return ts or None


def _normalize(df: pd.DataFrame, exchange: str) -> Dict[str, Dict[str, Any]]:
    colmap = {
        "Token": ["Token", "token"],
        "TradingSymbol": ["TradingSymbol", "tsym"],
        "Symbol": ["Symbol", "symname"],
        "LotSize": ["LotSize", "ls"],
        "Expiry": ["Expiry", "expdt"],
        "Instrument": ["Instrument", "instname"],
        "OptionType": ["OptionType", "optt"],
        "StrikePrice": ["StrikePrice", "strprc"],
        "TickSize": ["TickSize", "ti"],
        "PricePrecision": ["pp"],
    }

    norm = pd.DataFrame()
    for out, srcs in colmap.items():
        for s in srcs:
            if s in df.columns:
                norm[out] = df[s]
                break
        else:
            norm[out] = None

    norm["Token"] = norm["Token"].astype(str).str.strip()
    norm["TradingSymbol"] = norm["TradingSymbol"].astype(str).str.strip()
    norm["Symbol"] = norm["Symbol"].astype(str).str.upper()
    norm["Underlying"] = [_extract_underlying(ts, sym)
        for ts, sym in zip(norm["TradingSymbol"], norm["Symbol"])]


    norm = norm[(norm["Token"] != "") & (norm["TradingSymbol"] != "")]

    norm["LotSize"] = pd.to_numeric(norm["LotSize"], errors="coerce").astype("Int64")
    norm["StrikePrice"] = pd.to_numeric(norm["StrikePrice"], errors="coerce")
    norm["TickSize"] = pd.to_numeric(norm["TickSize"], errors="coerce")
    norm["PricePrecision"] = pd.to_numeric(norm["PricePrecision"], errors="coerce").astype("Int64")

    records: Dict[str, Dict[str, Any]] = {}

    for r in norm.itertuples(index=False):
        records[r.Token] = {
            "Exchange": exchange,
            "Token": r.Token,
            "TradingSymbol": r.TradingSymbol,
            "Symbol": r.Symbol,
            "Underlying": r.Underlying,
            "LotSize": int(r.LotSize) if pd.notna(r.LotSize) else None,
            "Expiry": r.Expiry,
            "Instrument": r.Instrument,
            "OptionType": r.OptionType,
            "StrikePrice": float(r.StrikePrice) if pd.notna(r.StrikePrice) else None,
            "TickSize": float(r.TickSize) if pd.notna(r.TickSize) else None,
            "PricePrecision": int(r.PricePrecision) if pd.notna(r.PricePrecision) else None,
        }

    return records


def _build_universal() -> None:
    SCRIPTMASTER_UNIVERSAL.clear()
    for exch, data in SCRIPTMASTER.items():
        for tok, rec in data.items():
            SCRIPTMASTER_UNIVERSAL[f"{exch}|{tok}"] = rec.copy()


def _build_expiry_calendar() -> None:
    EXPIRY_CALENDAR.clear()

    for exchange, data in SCRIPTMASTER.items():
        for rec in data.values():
            expiry = rec["Expiry"]
            if not expiry:
                continue

            inst = rec["Instrument"]
            symbol = rec["Symbol"]
            underlying = rec.get("Underlying")

            key = underlying or symbol

            if inst in FUTURE_INSTRUMENTS.get(exchange, set()):
                bucket = "FUTURE"
            elif inst in OPTION_INSTRUMENTS.get(exchange, set()):
                bucket = "OPTION"
            else:
                continue

            EXPIRY_CALENDAR \
                .setdefault(exchange, {}) \
                .setdefault(key, {"FUTURE": [], "OPTION": []}) \
                [bucket].append(expiry)

    for exch in EXPIRY_CALENDAR:
        for sym in EXPIRY_CALENDAR[exch]:
            for k in ("FUTURE", "OPTION"):
                EXPIRY_CALENDAR[exch][sym][k] = sorted(
                    set(EXPIRY_CALENDAR[exch][sym][k]),
                    key=lambda x: pd.to_datetime(x, errors="coerce")
                )

# =============================================================================
# PUBLIC API
# =============================================================================

def refresh_scriptmaster(force: bool = False) -> None:
    global _LAST_REFRESH_DATE

    if not force and not _should_refresh():
        logger.info("📦 Loading ScriptMaster from disk")
        _load_from_disk()
        return

    SCRIPTMASTER.clear()
    SCRIPTMASTER_UNIVERSAL.clear()
    EXPIRY_CALENDAR.clear()

    for exch, url in SCRIPTMASTER_URLS.items():
        zip_path = _download_zip(exch, url)

        try:
            df = _extract_txt(zip_path)
            SCRIPTMASTER[exch] = _normalize(df, exch)

            pd.DataFrame.from_dict(
                SCRIPTMASTER[exch],
                orient="index"
            ).to_parquet(PROC_DIR / f"{exch}.parquet")

        finally:
            try:
                # 🔥 DELETE ZIP — no longer needed
                zip_path.unlink(missing_ok=True)
                logger.debug(f"🧹 Deleted raw ZIP: {zip_path.name}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to delete {zip_path}: {e}")

    _build_universal()
    _build_expiry_calendar()

    pd.DataFrame.from_dict(
        SCRIPTMASTER_UNIVERSAL,
        orient="index"
    ).to_parquet(PROC_DIR / "universal.parquet")

    (
        pd.DataFrame
        .from_dict(EXPIRY_CALENDAR, orient="index")
        .to_json(PROC_DIR / "expiry_calendar.json", indent=2)
    )

    META_FILE.write_text(json.dumps({
        "date": _today_ist(),
        "version": SCRIPTMASTER_VERSION,
    }, indent=2))

    _LAST_REFRESH_DATE = _today_ist()
    logger.info("🎯 ScriptMaster refreshed & cached")


def _load_from_disk() -> None:
    SCRIPTMASTER.clear()
    SCRIPTMASTER_UNIVERSAL.clear()
    EXPIRY_CALENDAR.clear()

    for p in PROC_DIR.glob("*.parquet"):
        if p.name == "universal.parquet":
            continue
        exch = p.stem
        df = pd.read_parquet(p)
        SCRIPTMASTER[exch] = df.to_dict(orient="index")

    if (PROC_DIR / "universal.parquet").exists():
        df = pd.read_parquet(PROC_DIR / "universal.parquet")
        SCRIPTMASTER_UNIVERSAL.update(df.to_dict(orient="index"))

    # ✅ ALWAYS rebuild calendar from current rules
    _build_expiry_calendar()

# =============================================================================
# QUERY HELPERS 
# =============================================================================
def universal_symbol_search(symbol: str, exchange: str):
    symbol = symbol.upper()
    exchange = exchange.upper()

    # 1️⃣ Direct Symbol match
    rows = [
        r for r in SCRIPTMASTER.get(exchange, {}).values()
        if r["Symbol"] == symbol
    ]
    if rows:
        return rows

    # 2️⃣ Underlying fallback (BFO-safe)
    rows = [
        r for r in SCRIPTMASTER.get(exchange, {}).values()
        if r.get("Underlying") == symbol
    ]
    return rows

def get_expiry_calendar(exchange: str, symbol: str, kind: str) -> list[str]:
    exch = exchange.upper()
    sym = symbol.upper()

    bucket = EXPIRY_CALENDAR.get(exch, {})

    if sym in bucket:
        expiries = bucket[sym].get(kind.upper(), [])
    else:
        # fallback search
        expiries = []
        for k, v in bucket.items():
            if k == sym:
                expiries = v.get(kind.upper(), [])
                break

    return sorted(expiries, key=lambda x: pd.to_datetime(x, errors="coerce"))


def options_expiry(symbol: str, exchange: str, result: Optional[int] = None):
    expiries = get_expiry_calendar(exchange, symbol, "OPTION")
    if not expiries:
        return None if result is not None else []
    return expiries[result] if result is not None else expiries


def fut_expiry(symbol: str, exchange: str, result: Optional[int] = None):
    expiries = get_expiry_calendar(exchange, symbol, "FUTURE")
    if not expiries:
        return None if result is not None else []
    return expiries[result] if result is not None else expiries


def get_future(symbol: str, exchange: str, result: Optional[int] = None):
    symbol, exchange = symbol.upper(), exchange.upper()
    insts = FUTURE_INSTRUMENTS.get(exchange, set())

    rows = [
        r for r in SCRIPTMASTER.get(exchange, {}).values()
        if (
            (r["Symbol"] == symbol or r.get("Underlying") == symbol)
            and r["Instrument"] in insts
            and r["Expiry"]
        )
    ]

    if not rows:
        return {} if result is not None else pd.DataFrame()

    df = pd.DataFrame(rows)
    df["_dt"] = pd.to_datetime(df["Expiry"], format="%d-%b-%Y", errors="coerce")
    df = df.sort_values("_dt").drop(columns="_dt").reset_index(drop=True)

    return df.iloc[result].to_dict() if result is not None else df


def get_stock_detail(symbol: str, exchange: str, instrument_type: str):
    symbol = symbol.upper()
    for r in SCRIPTMASTER.get(exchange, {}).values():
        if (
            (r["Symbol"] == symbol or r.get("Underlying") == symbol)
            and r["Instrument"] == instrument_type
        ):
            return r
    return {}

def get_tokens(
    *,
    exchange: Optional[str] = None,
    tradingsymbol: Optional[str] = None,
    symbol: Optional[str] = None,
    underlying: Optional[str] = None,
    instrument: Optional[str] = None,
    expiry: Optional[str] = None,
    option_type: Optional[str] = None,
    strike_price: float | int | None = None,
) -> list[str]:
    """
    Search ScriptMaster across ALL exchanges and return matching tokens.

    All filters are AND-ed if provided.

    Returns:
        List[str] → matching Token(s)
    """

    results = []

    for key, rec in SCRIPTMASTER_UNIVERSAL.items():
        exch, token = key.split("|", 1)

        if exchange and rec.get("Exchange") != exchange.upper():
            continue

        if tradingsymbol and rec.get("TradingSymbol") != tradingsymbol.upper():
            continue

        if symbol and rec.get("Symbol") != symbol.upper():
            continue

        if underlying and rec.get("Underlying") != underlying.upper():
            continue

        if instrument and rec.get("Instrument") != instrument.upper():
            continue

        if expiry and rec.get("Expiry") != expiry:
            continue

        if option_type and rec.get("OptionType") != option_type.upper():
            continue

        if strike_price is not None:
            try:
                if float(rec.get("StrikePrice") or 0) != float(strike_price):
                    continue
            except Exception:
                continue

        results.append(token)

    return results

def requires_limit_order(
    *,
    exchange: str,
    token: Optional[str] = None,
    tradingsymbol: Optional[str] = None,
) -> bool:
    """
    Canonical Shoonya order-type rule (PRODUCTION FROZEN):

    LIMIT order is REQUIRED ONLY for:
    - Stock Options      (OPTSTK)  [NFO / BFO]
    - MCX Options        (OPTFUT)  [MCX]

    LIMIT or MARKET is ALLOWED for:
    - Index Options      (OPTIDX)
    - All Futures
    - Cash / Equity

    Resolution priority:
    1️⃣ token (authoritative)
    2️⃣ tradingsymbol fallback
    """

    exchange = exchange.upper()
    rec = None

    # -------------------------------------------------
    # 1️⃣ Resolve via token (most reliable)
    # -------------------------------------------------
    if token:
        rec = SCRIPTMASTER_UNIVERSAL.get(f"{exchange}|{token}")

    # -------------------------------------------------
    # 2️⃣ Resolve via tradingsymbol (fallback)
    # -------------------------------------------------
    if rec is None and tradingsymbol:
        ts = tradingsymbol.upper()
        for r in SCRIPTMASTER.get(exchange, {}).values():
            if r.get("TradingSymbol") == ts:
                rec = r
                break

    if not rec:
        # Defensive default → allow MARKET
        return False

    instrument = rec.get("Instrument")

    # 🔒 LIMIT ONLY cases
    if instrument in {"OPTSTK", "OPTFUT"}:
        return True

    return False

# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    refresh_scriptmaster(force=True)
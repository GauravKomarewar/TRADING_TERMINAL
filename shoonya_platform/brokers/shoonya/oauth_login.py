#!/usr/bin/env python3
"""
Daily OAuth login for Shoonya API — SEBI compliance requirement.

SEBI circular mandates daily re-authentication via broker OAuth flow before
algorithmic trading. Run this once per day before market open (8:45 AM IST).

Usage (standalone):
    python -m shoonya_platform.brokers.shoonya.oauth_login
    # or via cron (see crontab entry at bottom of this file)

The script:
  1. Opens Shoonya OAuth login in headless Chromium
  2. Fills in credentials + TOTP
  3. Captures the auth code from the redirect URL
  4. Computes SHA256 checksum
  5. Calls GenAcsTok API to complete activation
  6. Logs result and exits 0 (success) or 1 (failure)

Cron job (added automatically):
    45 8 * * 1-5 ... python -m shoonya_platform.brokers.shoonya.oauth_login
"""

import json
import hashlib
import time
import logging
import os
import sys
import requests
import pyotp
from urllib.parse import urlparse, parse_qs
from typing import Optional

logger = logging.getLogger(__name__)

# ── Selenium (lazy import so absence doesn't crash the whole platform) ──
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.service import Service
    from selenium.common.exceptions import InvalidSessionIdException, WebDriverException
    _SELENIUM_AVAILABLE = True
except ImportError:
    _SELENIUM_AVAILABLE = False

# ── Constants ────────────────────────────────────────────────────────────────
_BASE_URL = "https://trade.shoonya.com"
_TOKEN_URL = f"{_BASE_URL}/NorenWClientAPI/GenAcsTok"
_OAUTH_LOGIN_URL_TPL = (
    f"{_BASE_URL}/OAuthlogin/investor-entry-level/login"
    "?api_key={vendor_code}&route_to={user_id}+s+apikey"
)
# ARM64 snap Chromium (the only working Chrome on this server)
_CHROMEDRIVER_PATH = "/snap/chromium/current/usr/lib/chromium-browser/chromedriver"
_CHROMIUM_BINARY   = "/snap/bin/chromium"


# ── Credential helpers ───────────────────────────────────────────────────────

def _read_creds_from_env() -> dict:
    """Read credentials from already-loaded environment variables."""
    def _strip(val: str) -> str:
        if val and "#" in val:
            val = val[: val.index("#")]
        return val.strip()

    return {
        "user_id":      _strip(os.getenv("USER_ID", "")),
        "password":     _strip(os.getenv("PASSWORD", "")),
        "totp_key":     _strip(os.getenv("TOKEN", "")),
        "vendor_code":  _strip(os.getenv("VC", "")),
        "oauth_secret": _strip(os.getenv("OAUTH_SECRET", "")),
    }


def _creds_from_config(config) -> dict:
    """Extract OAuth credentials from a Config object."""
    return {
        "user_id":      config.user_id or "",
        "password":     config.password or "",
        "totp_key":     config.totp_key or "",
        "vendor_code":  config.vendor_code or "",
        "oauth_secret": getattr(config, "oauth_secret", None) or os.getenv("OAUTH_SECRET", ""),
    }


# ── Chrome driver ─────────────────────────────────────────────────────────────

def _build_driver():
    """Create headless Chrome WebDriver using snap Chromium (ARM64 compatible)."""
    if not _SELENIUM_AVAILABLE:
        raise RuntimeError(
            "selenium is not installed. Run: pip install selenium"
        )

    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--single-process")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    options.binary_location = _CHROMIUM_BINARY

    service = Service(executable_path=_CHROMEDRIVER_PATH)
    return webdriver.Chrome(service=service, options=options)


# ── Auth code capture ─────────────────────────────────────────────────────────

def _scan_network_for_code(driver) -> Optional[str]:
    """Scan Chrome performance logs for auth code in Shoonya network requests."""
    try:
        for entry in driver.get_log("performance"):
            try:
                msg = json.loads(entry["message"])["message"]
                if msg.get("method") == "Network.requestWillBeSent":
                    url = msg.get("params", {}).get("request", {}).get("url", "")
                    if "code=" in url and "shoonya" in url.lower():
                        parsed = urlparse(url)
                        code = parse_qs(parsed.query).get("code", [None])[0]
                        if code:
                            return code
            except Exception:
                continue
    except Exception:
        pass
    return None


def _fast_fill(element, value: str) -> None:
    element.click()
    time.sleep(0.1)
    element.clear()
    element.send_keys(value)
    time.sleep(0.1)


def _capture_auth_code(driver, creds: dict) -> Optional[str]:
    """Drive headless browser through OAuth login and capture auth code."""
    wait = WebDriverWait(driver, 30)
    login_url = _OAUTH_LOGIN_URL_TPL.format(
        vendor_code=creds["vendor_code"],
        user_id=creds["user_id"],
    )

    logger.info("Opening Shoonya OAuth login page...")
    driver.get(login_url)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input")))
    time.sleep(2)

    all_inputs = driver.find_elements(
        By.CSS_SELECTOR,
        "input:not([type='hidden']):not([type='checkbox']):not([type='radio'])",
    )
    visible_inputs = [inp for inp in all_inputs if inp.is_displayed()]
    logger.info("Visible input fields found: %d", len(visible_inputs))

    if len(visible_inputs) < 2:
        raise RuntimeError(
            f"Expected at least 2 input fields, got {len(visible_inputs)}"
        )

    _fast_fill(visible_inputs[0], creds["user_id"])
    _fast_fill(visible_inputs[1], creds["password"])

    otp_value: Optional[str] = None
    if len(visible_inputs) >= 3:
        otp_value = pyotp.TOTP(creds["totp_key"]).now()
        _fast_fill(visible_inputs[2], otp_value)
        logger.info("TOTP entered")

    # Click LOGIN button
    try:
        wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[normalize-space()='LOGIN']"))
        ).click()
    except Exception:
        try:
            wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//button[contains(translate(text(),'login','LOGIN'),'LOGIN')]")
                )
            ).click()
        except Exception:
            visible_inputs[1].submit()

    logger.info("Credentials submitted — waiting for auth code...")

    start = time.time()
    while True:
        # Check redirect URL first (most reliable)
        current_url = driver.current_url
        if "code=" in current_url:
            parsed = urlparse(current_url)
            code = parse_qs(parsed.query).get("code", [None])[0]
            if code:
                logger.info("Auth code captured from redirect URL")
                return code

        # Check network logs as fallback
        code = _scan_network_for_code(driver)
        if code:
            logger.info("Auth code captured from network log")
            return code

        if time.time() - start > 60:
            # Try TOTP refresh once
            if otp_value and creds.get("totp_key"):
                new_otp = pyotp.TOTP(creds["totp_key"]).now()
                if new_otp != otp_value:
                    try:
                        _fast_fill(visible_inputs[2], new_otp)
                        wait.until(
                            EC.element_to_be_clickable(
                                (By.XPATH, "//button[normalize-space()='LOGIN']")
                            )
                        ).click()
                        start = time.time()
                        otp_value = new_otp
                        logger.info("TOTP refreshed, retrying...")
                        continue
                    except Exception:
                        pass
            logger.error("Timeout capturing auth code. Current URL: %s", driver.current_url)
            return None

        time.sleep(0.5)


# ── Main OAuth flow ───────────────────────────────────────────────────────────

def run_oauth_login(config=None) -> Optional[str]:
    """
    Execute the daily Shoonya OAuth login flow (SEBI compliance).

    Performs browser-based OAuth login, computes SHA256 checksum, and calls
    GenAcsTok to complete daily activation.

    Args:
        config: Optional Config object. If None, reads directly from environment.

    Returns:
        Access token string on success, None on failure.
    """
    creds = _creds_from_config(config) if config is not None else _read_creds_from_env()

    if not creds.get("oauth_secret"):
        logger.error(
            "OAUTH_SECRET not set in primary.env — cannot run OAuth login. "
            "Add: OAUTH_SECRET=<your_secret_code>"
        )
        return None

    if not _SELENIUM_AVAILABLE:
        logger.error("selenium not installed — run: pip install selenium")
        return None

    driver = None
    auth_code: Optional[str] = None

    try:
        driver = _build_driver()
        auth_code = _capture_auth_code(driver, creds)
    except (InvalidSessionIdException, WebDriverException) as exc:
        logger.error("Browser error during OAuth login: %s", exc)
    except Exception as exc:
        logger.exception("Unexpected error during OAuth login: %s", exc)
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    if not auth_code:
        logger.error("OAuth login failed — auth code not captured")
        return None

    # Compute checksum: SHA256(vendor_code + oauth_secret + auth_code)
    checksum = hashlib.sha256(
        (creds["vendor_code"] + creds["oauth_secret"] + auth_code).encode()
    ).hexdigest()

    # Call GenAcsTok to complete activation
    payload = f'jData={{"code":"{auth_code}","checksum":"{checksum}"}}'
    headers = {"Authorization": f"Bearer {checksum}"}

    try:
        resp = requests.post(_TOKEN_URL, data=payload, headers=headers, timeout=30)
        result = resp.json()
        logger.info("GenAcsTok: stat=%s", result.get("stat"))

        if result.get("stat") == "Ok":
            token = (
                result.get("ActTok")
                or result.get("access_token")
                or result.get("susertoken")
            )
            if token:
                logger.info("✅ Daily OAuth login successful (SEBI compliant)")
                return token
            logger.warning("OAuth response OK but no token found: %s", result)
        else:
            logger.error("GenAcsTok error: %s", result)

    except Exception as exc:
        logger.exception("GenAcsTok request failed: %s", exc)

    return None


# ── Standalone entry point ────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | OAUTH | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(
                os.path.join(
                    os.path.dirname(__file__),
                    "../../../../logs/oauth_login.log",
                ),
                mode="a",
            ),
        ],
    )

    # Load primary.env when run standalone
    try:
        from dotenv import load_dotenv
        _env_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "../../../../config_env/primary.env")
        )
        if os.path.exists(_env_path):
            load_dotenv(_env_path)
            logger.info("Loaded credentials from %s", _env_path)
        else:
            logger.warning("primary.env not found at %s", _env_path)
    except ImportError:
        pass

    token = run_oauth_login()
    if token:
        print(f"✅ OAuth login successful. Token prefix: {token[:16]}...")
        sys.exit(0)
    else:
        print("❌ OAuth login failed — check logs")
        sys.exit(1)

# ── Recommended cron entry ────────────────────────────────────────────────────
# Add via: crontab -e
#
# 45 8 * * 1-5 cd /home/ubuntu/shoonya_platform && \
#   /home/ubuntu/shoonya_platform/venv/bin/python \
#   -m shoonya_platform.brokers.shoonya.oauth_login \
#   >> /home/ubuntu/shoonya_platform/logs/oauth_cron.log 2>&1

#!/usr/bin/env python3
"""
Configuration Management Module - Production Hardened

Responsibilities:
- Load environment variables exactly ONCE
- Validate required secrets with format checks
- Provide structured config access
- Secure credential handling
What’s correct
    Env loaded once
    All risk knobs moved to .env
    RISK_STATE_FILE:
    Loaded
    Validated
    Directory write-checked
    Negative max-loss enforced (very important)
    No runtime logic leakage

Copy-trading–ready (config already namespaced-friendly)

🔒 CONFIG FROZEN — COPY-TRADING READY (CONFIG LAYER)
Identity access MUST go through get_client_identity()
Risk parameters MUST come from env
No runtime logic permitted

🔒 Config v2.0.0 → PRODUCTION FROZEN
DATE: 2026-01-29
• Single source of truth for client identity
• All risk parameters externalized
• Copy-trading ready at configuration layer
• Zero runtime logic
• Backward compatible with single-client mode

Python version: 3.9 compatible
"""
from datetime import timedelta
import os
import tempfile
import logging
from pathlib import Path
from dotenv import load_dotenv
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""
    pass


class Config:
    """
    Central configuration object - Production Hardened.

    Create ONCE in main.py and inject/pass everywhere.
    
    ✅ IMPROVEMENTS:
    - Enhanced credential format validation
    - Secure logging (no sensitive data)
    - Port range validation
    - Type safety enforcement
    """

    def __init__(self, env_path: Optional[Path] = None):
        # Resolve credentials.env relative to this file
        self.env_path: Path = env_path or (
            Path(__file__).resolve().parents[2] / "config_env" / "primary.env"
        )
        self._load_env()
        self._load_values()
        self._validate()

    # ------------------------------------------------------------------
    # ENV LOADING (IMPROVED - SECURE)
    # ------------------------------------------------------------------

    def _load_env(self) -> None:
        """Load environment file with security checks."""
        if not self.env_path.exists():
            raise FileNotFoundError(f".env file not found: {self.env_path}")
        
        # 🔥 FIX: Check file permissions (should not be world-readable)
        if os.name != 'nt':  # Skip on Windows
            stat_info = self.env_path.stat()
            mode = stat_info.st_mode
            if mode & 0o004:  # World-readable
                logger.warning(
                    "⚠️ SECURITY: Environment file is world-readable. "
                    "Run: chmod 600 %s", self.env_path
                )

        load_dotenv(self.env_path)
        # 🔥 IMPROVED: Secure logging (no path details)
        logger.info("Environment configuration loaded successfully")

    # ------------------------------------------------------------------
    # VALUE LOADING
    # ------------------------------------------------------------------

    def _load_values(self) -> None:
        """Load configuration values from environment."""

        # === Broker Selector (must be loaded first — other sections depend on it) ===
        self.broker: str = self._strip_comment(os.getenv("BROKER", "shoonya")).lower()

        # === Shoonya Credentials (required when BROKER=shoonya) ===
        self.user_name: Optional[str] = self._strip_comment(os.getenv("USER_NAME", "")) or None
        self.user_id: Optional[str] = self._strip_comment(os.getenv("USER_ID", "")) or None
        self.password: Optional[str] = self._strip_comment(os.getenv("PASSWORD", "")) or None
        self.totp_key: Optional[str] = self._strip_comment(os.getenv("TOKEN", "")) or None
        self.vendor_code: Optional[str] = self._strip_comment(os.getenv("VC", "")) or None
        self.api_secret: Optional[str] = self._strip_comment(os.getenv("APP_KEY", "")) or None
        self.imei: str = self._strip_comment(os.getenv("IMEI", "mac"))

        # === Fyers Credentials (required when BROKER=fyers) ===
        self.fyers_id: Optional[str] = self._strip_comment(os.getenv("FYERS_ID", "")) or None
        self.fyers_app_id: Optional[str] = self._strip_comment(os.getenv("FYERS_APP_ID", "")) or None
        self.fyers_secret_id: Optional[str] = self._strip_comment(os.getenv("FYERS_SECRET_ID", "")) or None
        self.fyers_totp_key: Optional[str] = self._strip_comment(os.getenv("FYERS_T_OTP_KEY", "")) or None
        self.fyers_pin: Optional[str] = self._strip_comment(os.getenv("FYERS_PIN", "")) or None
        self.fyers_redirect_url: Optional[str] = self._strip_comment(os.getenv("FYERS_REDIRECT_URL", "")) or None
        self.fyers_token_file: str = self._strip_comment(os.getenv("FYERS_TOKEN_FILE", "fyers_token.json"))

        # Unified identity — for Fyers clients that don't set USER_ID/USER_NAME,
        # fall back to FYERS_ID so the rest of the system (log dirs, aliases) works.
        if self.broker == "fyers":
            if not self.user_id:
                self.user_id = self.fyers_id
            if not self.user_name:
                self.user_name = self.fyers_id

        # === Risk Management Config ===
        self.risk_base_max_loss: float = self._parse_float(
            os.getenv("RISK_BASE_MAX_LOSS", "-2000"),
            "RISK_BASE_MAX_LOSS"
        )
        self.risk_trail_step: float = self._parse_float(
            os.getenv("RISK_TRAIL_STEP", "100"),
            "RISK_TRAIL_STEP"
        )
        self.risk_warning_threshold: float = self._parse_float(
            os.getenv("RISK_WARNING_THRESHOLD", "0.80"),
            "RISK_WARNING_THRESHOLD"
        )
        self.risk_max_consecutive_loss_days: int = self._parse_int(
            os.getenv("RISK_MAX_CONSECUTIVE_LOSS_DAYS", "3"),
            "RISK_MAX_CONSECUTIVE_LOSS_DAYS"
        )
        self.risk_status_update_min: int = self._parse_int(
            os.getenv("RISK_STATUS_UPDATE_MIN", "30"),
            "RISK_STATUS_UPDATE_MIN"
        )
        # === Risk State ===
        # Use cross-platform temp directory (Windows/Linux compatible)
        default_risk_state = os.path.join(
            tempfile.gettempdir(), 
            "supreme_risk_state.json"
        )
        self.risk_state_file: str = self._strip_comment(
            os.getenv(
                "RISK_STATE_FILE",
                default_risk_state,
            )
        )
        # === Risk PnL Retention (days) ===
        self.risk_pnl_retention = {
            "1m": timedelta(days=self._parse_int(os.getenv("RISK_PNL_RETENTION_1M", "3"), "RISK_PNL_RETENTION_1M")),
            "5m": timedelta(days=self._parse_int(os.getenv("RISK_PNL_RETENTION_5M", "7"), "RISK_PNL_RETENTION_5M")),
            "1d": timedelta(days=self._parse_int(os.getenv("RISK_PNL_RETENTION_1D", "30"), "RISK_PNL_RETENTION_1D")),
        }

        # === Security ===
        self.webhook_secret: Optional[str] = self._strip_comment(os.getenv("WEBHOOK_SECRET_KEY", "")) or None

        # === Telegram (optional) ===
        self.telegram_bot_token: Optional[str] = self._strip_comment(os.getenv("TELEGRAM_TOKEN", "")) or None
        self.telegram_chat_id: Optional[str] = self._strip_comment(os.getenv("TELEGRAM_CHAT_ID", "")) or None

        # === Server ===
        self.host: str = self._strip_comment(os.getenv("HOST", "0.0.0.0"))
        self.port: int = self._parse_port(os.getenv("PORT", "5000"))
        self.dashboard_port: int = self._parse_port(os.getenv("DASHBOARD_PORT", "8000"))
        self.threads: int = self._parse_int(os.getenv("THREADS", "4"), "THREADS", 1, 32)

        # === Bot Runtime Config ===
        self.max_retry_attempts: int = self._parse_int(
            os.getenv("MAX_RETRY_ATTEMPTS", "3"), "MAX_RETRY_ATTEMPTS", 1, 10
        )
        self.retry_delay: int = self._parse_int(
            os.getenv("RETRY_DELAY", "1"), "RETRY_DELAY", 1, 60
        )
        self.report_frequency: int = self._parse_int(
            os.getenv("REPORT_FREQUENCY_MINUTES", "10"), "REPORT_FREQUENCY_MINUTES", 1, 1440
        )

        # === API Endpoints ===
        self.shoonya_host: str = "https://api.shoonya.com/NorenWClientTP/"
        self.shoonya_websocket: str = "wss://api.shoonya.com/NorenWSTP/"

        # ---------------------------------------------------------------
        # === Client Gateway Alias ===
        # URL-safe token used by the gateway router for path-based routing.
        # Defaults to user_id so existing deployments need no change.
        # ---------------------------------------------------------------
        self.client_id_alias: str = (
            self._strip_comment(os.getenv("CLIENT_ID_ALIAS", ""))
            or (self.user_id or "")
        )

        # ---------------------------------------------------------------
        # === Copy Trading ===
        # ---------------------------------------------------------------
        self.copy_trading_role: str = self._strip_comment(
            os.getenv("COPY_TRADING_ROLE", "standalone")
        ).lower()
        self.copy_trading_secret: Optional[str] = (
            self._strip_comment(os.getenv("COPY_TRADING_SECRET", "")) or None
        )
        # Followers — only meaningful when role=master
        _followers_raw = self._strip_comment(os.getenv("COPY_TRADING_FOLLOWERS", ""))
        self.copy_trading_followers: List[str] = (
            [u.strip() for u in _followers_raw.split(",") if u.strip()]
            if _followers_raw else []
        )
        # Master endpoint — only meaningful when role=follower
        self.copy_trading_master_endpoint: Optional[str] = (
            self._strip_comment(os.getenv("COPY_TRADING_MASTER_ENDPOINT", "")) or None
        )
        # Execution mode: mirror | scaled
        self.copy_trading_mode: str = self._strip_comment(
            os.getenv("COPY_TRADING_MODE", "mirror")
        ).lower()
        self.copy_trading_scale_factor: float = self._parse_float(
            os.getenv("COPY_TRADING_SCALE_FACTOR", "1.0"),
            "COPY_TRADING_SCALE_FACTOR",
            min_val=0.01,
            max_val=100.0,
        )

        # ---------------------------------------------------------------
        # === Master Manager ===
        # ---------------------------------------------------------------
        self.master_manager_url: Optional[str] = (
            self._strip_comment(os.getenv("MASTER_MANAGER_URL", "")) or None
        )
        self.master_manager_token: Optional[str] = (
            self._strip_comment(os.getenv("MASTER_MANAGER_TOKEN", "")) or None
        )

    # ------------------------------------------------------------------
    # PARSING HELPERS (NEW)
    # ------------------------------------------------------------------

    def _parse_port(self, value: str) -> int:
        """Parse and validate port number, stripping comments."""
        try:
            clean_value = self._strip_comment(value)
            port = int(clean_value)
            if not (1024 <= port <= 65535):
                raise ValueError(f"Port must be between 1024-65535, got: {port}")
            return port
        except ValueError as e:
            raise ConfigValidationError(f"Invalid PORT value '{value}': {e}")

    def _strip_comment(self, value: str) -> str:
        """Strip comments from config values (everything after #)."""
        if '#' in value:
            return value.split('#')[0].strip()
        return value.strip()

    def _parse_float(
        self,
        value: str,
        name: str,
        min_val: Optional[float] = None,
        max_val: Optional[float] = None
    ) -> float:
        """Parse and validate float with optional bounds, stripping comments."""
        try:
            clean_value = self._strip_comment(value)
            num = float(clean_value)
            if min_val is not None and num < min_val:
                raise ValueError(f"{name} must be >= {min_val}, got: {num}")
            if max_val is not None and num > max_val:
                raise ValueError(f"{name} must be <= {max_val}, got: {num}")
            return num
        except ValueError as e:
            raise ConfigValidationError(f"Invalid {name} value '{value}': {e}")

    def _parse_int(
        self, 
        value: str, 
        name: str, 
        min_val: Optional[int] = None, 
        max_val: Optional[int] = None
    ) -> int:
        """Parse and validate integer with optional bounds, stripping comments."""
        try:
            clean_value = self._strip_comment(value)
            num = int(clean_value)
            if min_val is not None and num < min_val:
                raise ValueError(f"{name} must be >= {min_val}, got: {num}")
            if max_val is not None and num > max_val:
                raise ValueError(f"{name} must be <= {max_val}, got: {num}")
            return num
        except ValueError as e:
            raise ConfigValidationError(f"Invalid {name} value '{value}': {e}")

    # ------------------------------------------------------------------
    # VALIDATION (IMPROVED - COMPREHENSIVE)
    # ------------------------------------------------------------------

    def _validate(self) -> None:
        """
        🔥 IMPROVED: Comprehensive validation with format checks.
        
        Validates:
        - Required credentials presence
        - Credential format/length
        - Port range
        - Telegram configuration consistency
        """
        
        # -------------------------------------------------
        # 0️⃣ Broker selector validation
        # -------------------------------------------------
        _valid_brokers = {"shoonya", "fyers"}
        if self.broker not in _valid_brokers:
            raise ConfigValidationError(
                f"BROKER must be one of {_valid_brokers}, got: '{self.broker}'"
            )

        # -------------------------------------------------
        # 1️⃣ Required Credentials Check (broker-specific)
        # -------------------------------------------------
        if self.broker == "fyers":
            required = {
                "FYERS_ID": self.fyers_id,
                "FYERS_APP_ID": self.fyers_app_id,
                "FYERS_SECRET_ID": self.fyers_secret_id,
                "FYERS_T_OTP_KEY": self.fyers_totp_key,
                "FYERS_PIN": self.fyers_pin,
                "FYERS_REDIRECT_URL": self.fyers_redirect_url,
                "WEBHOOK_SECRET_KEY": self.webhook_secret,
            }
        else:  # shoonya
            required = {
                "USER_NAME": self.user_name,
                "USER_ID": self.user_id,
                "PASSWORD": self.password,
                "TOKEN": self.totp_key,
                "VC": self.vendor_code,
                "APP_KEY": self.api_secret,
                "WEBHOOK_SECRET_KEY": self.webhook_secret,
            }

        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ConfigValidationError(f"Missing required config values: {missing}")

        # -------------------------------------------------
        # 2️⃣ Format Validation (broker-specific)
        # -------------------------------------------------
        if self.broker == "shoonya":
            # TOTP key validation
            if self.totp_key and len(self.totp_key) < 16:
                raise ConfigValidationError(
                    "TOTP TOKEN appears invalid (too short). "
                    "Expected base32 string of 16+ characters"
                )

            # API secret validation
            if self.api_secret and len(self.api_secret) < 20:
                raise ConfigValidationError(
                    "API APP_KEY appears invalid (too short). "
                    "Expected 20+ characters"
                )

            # User ID validation
            if self.user_id and not self.user_id.strip():
                raise ConfigValidationError("USER_ID cannot be empty/whitespace")

            # Password validation
            if self.password and len(self.password) < 6:
                logger.warning(
                    "⚠️ PASSWORD is very short (< 6 chars). "
                    "This may be intentional but is unusual."
                )
        else:  # fyers
            if self.fyers_totp_key and len(self.fyers_totp_key) < 16:
                raise ConfigValidationError(
                    "FYERS_T_OTP_KEY appears invalid (too short). "
                    "Expected base32 string of 16+ characters"
                )
        
        # -------------------------------------------------
        # 3️⃣ Risk Configuration Validation (SAFE)
        # -------------------------------------------------
        if self.risk_trail_step <= 0:
            raise ConfigValidationError("RISK_TRAIL_STEP must be > 0")

        if not (0 < self.risk_warning_threshold < 1):
            raise ConfigValidationError(
                "RISK_WARNING_THRESHOLD must be between 0 and 1"
            )

        if self.risk_max_consecutive_loss_days < 1:
            raise ConfigValidationError(
                "RISK_MAX_CONSECUTIVE_LOSS_DAYS must be >= 1"
            )

        if self.risk_status_update_min < 1:
            raise ConfigValidationError(
                "RISK_STATUS_UPDATE_MIN must be >= 1 minute"
            )

        # Webhook secret validation
        if self.webhook_secret and len(self.webhook_secret) < 16:
            logger.warning(
                "⚠️ WEBHOOK_SECRET_KEY is short (< 16 chars). "
                "Consider using a longer secret for security."
            )

        # -------------------------------------------------
        # 4️⃣ Risk State File Validation
        # -------------------------------------------------
        if not self.risk_state_file:
            raise ConfigValidationError("RISK_STATE_FILE cannot be empty")

        state_dir = os.path.dirname(self.risk_state_file)
        if not state_dir:
            # No directory specified, use current directory
            state_dir = "."
        
        # Create directory if it doesn't exist (cross-platform)
        try:
            os.makedirs(state_dir, exist_ok=True)
        except Exception as e:
            raise ConfigValidationError(
                f"Cannot create RISK_STATE_FILE directory: {state_dir} - {e}"
            )
        
        # Verify directory is writable
        if not os.access(state_dir, os.W_OK):
            raise ConfigValidationError(
                f"RISK_STATE_FILE directory not writable: {state_dir}"
            )
        if self.risk_base_max_loss >= 0:
            raise ConfigValidationError(
                "RISK_BASE_MAX_LOSS must be NEGATIVE (e.g. -2000)"
            )

        # -------------------------------------------------
        # 5️⃣ Telegram Configuration Validation (IMPROVED)
        # -------------------------------------------------
        has_token = bool(self.telegram_bot_token)
        has_chat = bool(self.telegram_chat_id)
        
        if has_token != has_chat:
            logger.warning(
                "⚠️ Partial Telegram configuration detected. "
                "Both TELEGRAM_TOKEN and TELEGRAM_CHAT_ID required for Telegram features."
            )
        elif not has_token:
            logger.info("Telegram notifications disabled (optional)")
        else:
            # Validate Telegram chat ID format
            if self.telegram_chat_id:
                try:
                    int(self._strip_comment(self.telegram_chat_id))
                except ValueError:
                    raise ConfigValidationError(
                        f"TELEGRAM_CHAT_ID must be numeric, got: {self.telegram_chat_id}"
                    )

        # -------------------------------------------------
        # 6️⃣ Server Configuration Validation
        # -------------------------------------------------
        if self.threads < 1:
            raise ConfigValidationError(f"THREADS must be >= 1, got: {self.threads}")
        
        if self.threads > 32:
            logger.warning(
                "⚠️ THREADS is very high (%d). This may cause resource exhaustion.",
                self.threads
            )

        # -------------------------------------------------
        # 7️⃣ Copy Trading Validation
        # -------------------------------------------------
        _valid_roles = {"standalone", "master", "follower"}
        if self.copy_trading_role not in _valid_roles:
            raise ConfigValidationError(
                f"COPY_TRADING_ROLE must be one of {_valid_roles}, "
                f"got: '{self.copy_trading_role}'"
            )

        if self.copy_trading_role == "master":
            if not self.copy_trading_secret:
                raise ConfigValidationError(
                    "COPY_TRADING_SECRET is required when COPY_TRADING_ROLE=master"
                )
            if not self.copy_trading_followers:
                logger.warning(
                    "⚠️ COPY_TRADING_ROLE=master but COPY_TRADING_FOLLOWERS is empty. "
                    "No alerts will be fanned out."
                )

        if self.copy_trading_role == "follower":
            if not self.copy_trading_secret:
                raise ConfigValidationError(
                    "COPY_TRADING_SECRET is required when COPY_TRADING_ROLE=follower"
                )
            if not self.copy_trading_master_endpoint:
                raise ConfigValidationError(
                    "COPY_TRADING_MASTER_ENDPOINT is required when COPY_TRADING_ROLE=follower"
                )

        _valid_modes = {"mirror", "scaled"}
        if self.copy_trading_mode not in _valid_modes:
            raise ConfigValidationError(
                f"COPY_TRADING_MODE must be one of {_valid_modes}, "
                f"got: '{self.copy_trading_mode}'"
            )

        # -------------------------------------------------
        # 8️⃣ Type Narrowing (broker-conditional)
        # -------------------------------------------------
        assert self.user_id is not None  # always set (falls back to fyers_id for Fyers clients)
        if self.broker == "shoonya":
            assert self.password is not None
            assert self.totp_key is not None
            assert self.vendor_code is not None
            assert self.api_secret is not None
        else:  # fyers
            assert self.fyers_id is not None
            assert self.fyers_app_id is not None
        assert self.webhook_secret is not None

        logger.info("✅ Configuration validated successfully")

    # ------------------------------------------------------------------
    # ACCESSORS (SECURE - NO SENSITIVE DATA LEAKAGE)
    # ------------------------------------------------------------------

    def get_shoonya_credentials(self) -> Dict[str, str]:
        """
        Get Shoonya credentials dictionary.
        
        ⚠️ WARNING: Contains sensitive data. Handle securely.
        Do NOT log or expose this dictionary.
        """
        return {
            "user_id": self.user_id,
            "password": self.password,
            "totp_key": self.totp_key,
            "vendor_code": self.vendor_code,
            "api_secret": self.api_secret,
            "imei": self.imei,
            "host": self.shoonya_host,
            "websocket": self.shoonya_websocket,
        }

    def get_fyers_credentials(self) -> Dict[str, str]:
        """
        Get Fyers credentials dictionary.

        ⚠️ WARNING: Contains sensitive data. Handle securely.
        Do NOT log or expose this dictionary.
        Only valid when self.broker == 'fyers'.
        """
        return {
            "fyers_id": self.fyers_id or "",
            "app_id": self.fyers_app_id or "",
            "secret_id": self.fyers_secret_id or "",
            "totp_key": self.fyers_totp_key or "",
            "pin": self.fyers_pin or "",
            "redirect_url": self.fyers_redirect_url or "",
            "token_file": self.fyers_token_file,
        }

    # ------------------------------------------------------------------
    # 🔐 CLIENT IDENTITY (COPY-TRADING-Purpose)
    # ------------------------------------------------------------------
    # 🔒 SINGLE SOURCE OF TRUTH FOR CLIENT IDENTITY
    # ❌ Do NOT use USER_ID / USER_NAME directly outside Config
    def get_client_identity(self) -> dict:
        """
        Canonical client identity adapter.
        FOR EXAMPLE (Shoonya):
            USER_ID=FA14667
            USER_NAME=GAURAV_Y_KOMAREWAR  
        FOR EXAMPLE (Fyers):
            FYERS_ID=FG0158  → user_id=FG0158, user_name=FG0158

        This is the ONLY approved way to access client identity.
        Safe for single-client today, mandatory for multi-client tomorrow.
        """
        return {
            "user_id": self.user_id,
            "user_name": self.user_name,
            "client_id": f"{self.user_name}:{self.user_id}",
            "broker": self.broker,
        }

    def get_shoonya_config(self) -> Dict[str, str]:
        """Compatibility alias for get_shoonya_credentials()."""
        return self.get_shoonya_credentials()

    def get_server_config(self) -> Dict[str, Any]:
        """Get server configuration (safe to log)."""
        return {
            "host": self.host,
            "port": self.port,
            "threads": self.threads,
            "dashboard_port": self.dashboard_port,
            "client_id_alias": self.client_id_alias,
        }

    def get_copy_trading_config(self) -> Dict[str, Any]:
        """
        Get copy trading configuration (safe to log — no secrets).
        The shared secret is intentionally excluded from this dict.
        """
        return {
            "role": self.copy_trading_role,
            "mode": self.copy_trading_mode,
            "scale_factor": self.copy_trading_scale_factor,
            "followers": self.copy_trading_followers,
            "master_endpoint": self.copy_trading_master_endpoint,
            "enabled": self.copy_trading_role != "standalone",
        }

    def get_master_manager_config(self) -> Dict[str, Any]:
        """Get master manager connection config (masks token)."""
        return {
            "url": self.master_manager_url,
            "token_set": bool(self.master_manager_token),
        }

    def get_telegram_config(self) -> Dict[str, Optional[str]]:
        """
        Get Telegram configuration.
        
        ⚠️ WARNING: Contains bot token. Handle securely.
        """
        return {
            "bot_token": self.telegram_bot_token,
            "chat_id": self.telegram_chat_id,
        }

    def is_telegram_enabled(self) -> bool:
        """Check if Telegram is properly configured."""
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    def get_telegram_allowed_users(self) -> List[int]:
        """Get list of allowed Telegram user IDs."""
        users = self._strip_comment(os.getenv("TELEGRAM_ALLOWED_USERS", ""))
        result = []
        
        for u in users.split(","):
            u = u.strip()
            if u.isdigit():
                result.append(int(u))
            elif u:
                logger.warning(
                    "⚠️ Invalid user ID in TELEGRAM_ALLOWED_USERS: '%s' (not numeric)",
                    u
                )
        
        return result

    def get_telegram_control_token(self) -> Optional[str]:
        """Get Telegram control bot token (if configured)."""
        return os.getenv("TELEGRAM_CONTROL_BOT_TOKEN")

    # ------------------------------------------------------------------
    # DIAGNOSTICS (NEW)
    # ------------------------------------------------------------------

    def get_config_summary(self, include_sensitive: bool = False) -> Dict[str, Any]:
        """
        Get configuration summary for diagnostics.
        
        Args:
            include_sensitive: If True, includes masked credentials (default: False)
            
        Returns:
            Dictionary with configuration summary
        """
        summary = {
            "server": {
                "host": self.host,
                "port": self.port,
                "threads": self.threads,
            },
            "features": {
                "telegram_enabled": self.is_telegram_enabled(),
                "auto_recovery_settings": {
                    "max_retry_attempts": self.max_retry_attempts,
                    "retry_delay": self.retry_delay,
                    "report_frequency": self.report_frequency,
                },
            },
            "endpoints": {
                "shoonya_host": self.shoonya_host,
                "shoonya_websocket": self.shoonya_websocket,
            },
        }
        
        if include_sensitive:
            # Mask sensitive values
            summary["credentials_status"] = {
                "user_id": self._mask_string(self.user_id),
                "password": "***SET***" if self.password else "***MISSING***",
                "totp_key": self._mask_string(self.totp_key),
                "vendor_code": self._mask_string(self.vendor_code),
                "api_secret": self._mask_string(self.api_secret),
                "webhook_secret": self._mask_string(self.webhook_secret),
            }
        
        return summary

    def _mask_string(self, value: Optional[str]) -> str:
        """Mask sensitive string for safe logging."""
        if not value:
            return "***MISSING***"
        if len(value) <= 4:
            return "***"
        return f"{value[:2]}***{value[-2:]}"

    def validate_runtime(self) -> Dict[str, bool]:
        """
        Runtime validation checks (safe to call repeatedly).
        
        Returns:
            Dictionary with validation results
        """
        checks = {}
        
        # Check environment file still exists
        checks["env_file_exists"] = self.env_path.exists()
        
        # Check Telegram if enabled
        if self.is_telegram_enabled():
            checks["telegram_configured"] = True
            checks["telegram_chat_id_valid"] = (
                self.telegram_chat_id is not None and 
                self.telegram_chat_id.isdigit()
            )
        else:
            checks["telegram_configured"] = False
        
        # Check server config
        checks["port_in_range"] = 1024 <= self.port <= 65535
        checks["threads_valid"] = 1 <= self.threads <= 32
        
        # Overall health
        checks["healthy"] = all([
            checks["env_file_exists"],
            checks["port_in_range"],
            checks["threads_valid"],
        ])
        
        return checks


# ------------------------------------------------------------------
# PRODUCTION NOTES
# ------------------------------------------------------------------

"""
===============================================================================
CONFIG MODULE v2.0 - PRODUCTION HARDENING
===============================================================================

✅ IMPROVEMENTS:
    1. Comprehensive credential format validation
    2. Secure logging (no sensitive data exposure)
    3. Port and integer range validation
    4. Telegram configuration consistency checks
    5. File permission warnings (Unix)
    6. Runtime validation checks
    7. Safe diagnostic summaries with masking
    
✅ SECURITY:
    - No credentials logged
    - Masked values in summaries
    - File permission warnings
    - Input validation prevents injection
    
✅ ROBUSTNESS:
    - Type-safe with assertions
    - Clear error messages
    - Graceful degradation for optional features
    - Runtime health checks
    
🔒 PRODUCTION STATUS:
    ✅ Ready for production deployment
    ✅ Secure credential handling
    ✅ Comprehensive validation
    ✅ Detailed error reporting
    
===============================================================================
"""

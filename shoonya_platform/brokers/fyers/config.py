"""
FyersConfig — loads Fyers credentials from environment / .env file.

Supports two sources (checked in order):
  1. A dedicated env file path (passed explicitly or via FYERS_ENV_FILE env var).
  2. Standard environment variables (already set in the process).

Environment variables expected:
    FYERS_ID         — Fyers user ID (e.g. FG0158)
    FYERS_APP_ID     — API app ID including type suffix (e.g. IQOURN2NSJ-100)
    FYERS_SECRET_ID  — API secret key
    FYERS_T_OTP_KEY  — Base32 TOTP key for 2FA
    FYERS_PIN        — 4-digit login PIN
    FYERS_REDIRECT_URL — OAuth redirect URL
    FYERS_TOKEN_FILE — (optional) path to cached token JSON (default: fyers_token.json)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


class FyersConfig:
    """Immutable Fyers credential bag."""

    def __init__(
        self,
        fyers_id: str,
        app_id: str,
        secret_id: str,
        totp_key: str,
        pin: str,
        redirect_url: str,
        token_file: str = "fyers_token.json",
    ) -> None:
        if not all([fyers_id, app_id, secret_id, totp_key, pin, redirect_url]):
            raise ValueError("All Fyers credential fields are required.")
        self.fyers_id = fyers_id
        self.app_id = app_id
        self.secret_id = secret_id
        self.totp_key = totp_key
        self.pin = pin
        self.redirect_url = redirect_url
        self.token_file = token_file

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls, env_file: Optional[str] = None) -> "FyersConfig":
        """
        Build from environment variables, optionally loading a .env file first.

        Args:
            env_file: Path to a .env file (defaults to FYERS_ENV_FILE env var,
                      falling back to the fyers project credentials.env if found).
        """
        _load_dotenv(env_file)

        # Support both prefixed (FYERS_XXX) and legacy (XXX) keys so the
        # existing option_trading_system_fyers/config/credentials.env works
        # without modification.
        def _get(prefixed: str, legacy: str) -> str:
            return os.getenv(prefixed) or os.getenv(legacy, "")

        return cls(
            fyers_id=_get("FYERS_ID", "FYERS_ID"),
            app_id=_get("FYERS_APP_ID", "APP_ID"),
            secret_id=_get("FYERS_SECRET_ID", "SECRETE_ID"),
            totp_key=_get("FYERS_T_OTP_KEY", "T_OTP_KEY"),
            pin=_get("FYERS_PIN", "PIN"),
            redirect_url=_get("FYERS_REDIRECT_URL", "REDIRECT_URL"),
            token_file=os.getenv("FYERS_TOKEN_FILE", "fyers_token.json"),
        )

    @classmethod
    def from_dict(cls, d: dict) -> "FyersConfig":
        """Build from a plain dict (useful for loading from trading_config.json)."""
        return cls(
            fyers_id=d["fyers_id"],
            app_id=d["app_id"],
            secret_id=d["secret_id"],
            totp_key=d["totp_key"],
            pin=d["pin"],
            redirect_url=d["redirect_url"],
            token_file=d.get("token_file", "fyers_token.json"),
        )

    @classmethod
    def from_config(cls, config) -> "FyersConfig":
        """
        Build from a platform Config instance.

        This is the preferred factory when running inside the shoonya_platform
        process — the Config object has already loaded and validated all Fyers
        credential env vars from the client's own .env file.

        Args:
            config: shoonya_platform.core.config.Config instance with
                    broker == 'fyers' and fyers_* fields populated.
        """
        return cls(
            fyers_id=config.fyers_id or "",
            app_id=config.fyers_app_id or "",
            secret_id=config.fyers_secret_id or "",
            totp_key=config.fyers_totp_key or "",
            pin=config.fyers_pin or "",
            redirect_url=config.fyers_redirect_url or "",
            token_file=getattr(config, "fyers_token_file", "fyers_token.json"),
        )


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _load_dotenv(env_file: Optional[str]) -> None:
    """Try to load a .env file; silently skip if python-dotenv is unavailable."""
    try:
        from dotenv import load_dotenv  # type: ignore
    except ImportError:
        return

    # Explicit path takes priority
    if env_file:
        load_dotenv(dotenv_path=env_file, override=False)
        return

    # Check env var
    env_via_var = os.getenv("FYERS_ENV_FILE")
    if env_via_var and Path(env_via_var).exists():
        load_dotenv(dotenv_path=env_via_var, override=False)
        return

    # Fallback: look for the fyers project credentials.env relative to the
    # shoonya_platform root (two levels up from this file).
    project_root = Path(__file__).resolve().parents[4]  # shoonya_platform/
    candidates = [
        project_root.parent / "option_trading_system_fyers" / "config" / "credentials.env",
        project_root / "config_env" / "fyers.env",
    ]
    for candidate in candidates:
        if candidate.exists():
            load_dotenv(dotenv_path=candidate, override=False)
            return

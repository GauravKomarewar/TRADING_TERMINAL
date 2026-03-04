# ======================================================================
# ROUTES: Telegram Notification Preferences
# Controls which categories of telegram messages are enabled/disabled.
# ======================================================================
from fastapi import APIRouter, Depends, Body
import logging
import json
import threading
from pathlib import Path

from shoonya_platform.api.dashboard.deps import require_dashboard_auth
from shoonya_platform.api.dashboard.api._shared import _PROJECT_ROOT

sub_router = APIRouter()
logger = logging.getLogger("DASHBOARD.TELEGRAM")

# ── Preference file location ──
_PREFS_DIR = _PROJECT_ROOT / "logs"
_PREFS_DIR.mkdir(parents=True, exist_ok=True)
_prefs_lock = threading.Lock()


def _prefs_file(client_id: str) -> Path:
    """Per-client telegram preference file."""
    safe_id = "".join(c for c in str(client_id) if c.isalnum() or c in ("_", "-", ":"))
    return _PREFS_DIR / f"telegram_prefs_{safe_id}.json"


def _load_prefs(client_id: str) -> dict:
    """Load preferences from disk. Defaults: all enabled."""
    defaults = {"all": True, "system": True, "strategy": True, "reports": True}
    path = _prefs_file(client_id)
    if not path.exists():
        return defaults
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Ensure all keys exist
        for k in defaults:
            if k not in data:
                data[k] = defaults[k]
        return data
    except Exception as e:
        logger.warning("Failed to load telegram prefs for %s: %s", client_id, e)
        return defaults


def _save_prefs(client_id: str, prefs: dict) -> None:
    """Persist preferences to disk."""
    path = _prefs_file(client_id)
    with _prefs_lock:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(prefs, f, indent=2)


def _apply_prefs_to_bot(bot, prefs: dict) -> None:
    """Apply telegram preferences to the live bot instance.
    
    NOTE: We intentionally do NOT set bot.telegram_enabled = False.
    The telegram_enabled flag must stay True so that the outer guards
    (if self.telegram_enabled and self.telegram:) still pass and messages
    are logged to the JSONL file for dashboard display.
    The _should_send() check inside TelegramNotifier controls whether
    the actual HTTP send to Telegram happens.
    """
    # Store granular prefs on bot
    bot._telegram_prefs = {
        "all": prefs.get("all", True),
        "system": prefs.get("system", True),
        "strategy": prefs.get("strategy", True),
        "reports": prefs.get("reports", True),
    }

    # Push prefs into the TelegramNotifier so _should_send() is aware
    if bot.telegram is not None:
        bot.telegram.set_preferences(bot._telegram_prefs)


# ==================================================
# GET PREFERENCES
# ==================================================
@sub_router.get("/telegram/preferences")
def get_telegram_preferences(ctx=Depends(require_dashboard_auth)):
    """Get current telegram notification preferences."""
    client_id = ctx.get("client_id", "default")
    prefs = _load_prefs(client_id)

    # Also read live state from bot
    bot = ctx.get("bot")
    if bot:
        live_prefs = getattr(bot, "_telegram_prefs", None)
        if live_prefs:
            prefs = {**prefs, **live_prefs}

    return {
        "preferences": prefs,
        "telegram_configured": bot.telegram is not None if bot else False,
        "telegram_enabled": bot.telegram_enabled if bot else False,
    }


# ==================================================
# SET PREFERENCES
# ==================================================
@sub_router.post("/telegram/preferences")
def set_telegram_preferences(
    payload: dict = Body(...),
    ctx=Depends(require_dashboard_auth),
):
    """Update telegram notification preferences."""
    client_id = ctx.get("client_id", "default")

    # Sanitize input
    prefs = {
        "all": bool(payload.get("all", True)),
        "system": bool(payload.get("system", True)),
        "strategy": bool(payload.get("strategy", True)),
        "reports": bool(payload.get("reports", True)),
    }

    # Save to disk
    _save_prefs(client_id, prefs)

    # Apply to live bot
    bot = ctx.get("bot")
    if bot:
        _apply_prefs_to_bot(bot, prefs)

    logger.info(
        "Telegram preferences updated | client=%s | all=%s system=%s strategy=%s reports=%s",
        client_id,
        prefs["all"],
        prefs["system"],
        prefs["strategy"],
        prefs["reports"],
    )

    return {
        "accepted": True,
        "preferences": prefs,
        "telegram_enabled": bot.telegram_enabled if bot else False,
    }

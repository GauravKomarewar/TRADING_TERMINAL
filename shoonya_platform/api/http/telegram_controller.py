"""Telegram Controller - Read-only monitoring"""

import logging
from typing import Optional, Set

logger = logging.getLogger(__name__)


class TelegramController:
    """Handles Telegram webhook messages for bot monitoring"""

    def __init__(self, bot=None, allowed_users: Optional[Set[int]] = None, **kwargs):
        """
        Compatibility-friendly constructor.

        Supports:
        - TelegramController(bot, allowed_users)
        - TelegramController(service=bot, allowed_users=...)
        """

        # Backward compatibility: service=bot
        if bot is None and "service" in kwargs:
            bot = kwargs["service"]

        if allowed_users is None:
            allowed_users = set()

        self.bot = bot
        self.allowed_users = allowed_users
        self.commands = {
            "status": self._cmd_status,
            "risk": self._cmd_risk,
            "positions": self._cmd_positions,
            "pnl": self._cmd_pnl,
        }


    def handle_message(self, payload: dict) -> Optional[str]:
        """Main webhook handler"""
        try:
            message = payload.get("message", {})
            user_id = message.get("from", {}).get("id")
            text = (message.get("text") or "").strip()

            # 🔧 FIX 1: Check user_id exists before anything else
            if not user_id:
                return None

            # Security check
            if user_id not in self.allowed_users:
                logger.warning(f"Unauthorized user: {user_id}")
                return None

            # Parse command
            if not text.startswith("/trade"):
                return None

            tokens = text.lower().split()
            if len(tokens) < 2:
                return self._help()

            cmd = tokens[1]
            handler = self.commands.get(cmd)

            return handler() if handler else self._help()

        except Exception:
            logger.exception("TelegramController error")
            return "❌ Error processing command"

    # -------------------------
    # COMMANDS
    # -------------------------
    def _cmd_status(self) -> str:
        session = self.bot.get_session_info()
        risk = self.bot.risk_manager.get_status()
        # 🔧 FIX 2: Safe dict access to prevent KeyError
        stats = session.get("trade_stats", {})

        api = '✅' if session.get('api_session') else '❌'
        tg = '✅' if session.get('telegram_enabled') else '❌'
        loss = '⚠️ HIT' if risk['daily_loss_hit'] else '✅ OK'
        cooldown = '⏳ Active' if risk.get('cooldown_until') else 'None'

        return (
            f"📊 <b>BOT STATUS</b>\n"
            f"────────────\n"
            f"API: {api} | Telegram: {tg}\n\n"
            f"Trades Today: {stats.get('today_trades', 0)} | "
            f"Total: {stats.get('total_trades', 0)}\n"
            f"Last Active: {stats.get('last_activity') or 'N/A'}\n\n"
            f"Daily PnL: ₹{risk['daily_pnl']:.2f}\n"
            f"Loss Limit: {loss} | Cooldown: {cooldown}"
        )

    def _cmd_risk(self) -> str:
        r = self.bot.risk_manager.get_status()
        return (
            "🛡 <b>RISK STATUS</b>\n"
            "────────────\n"
            f"Daily PnL: ₹{r['daily_pnl']:.2f}\n"
            f"Loss Limit: {'⚠️ HIT' if r['daily_loss_hit'] else '✅ OK'}\n"
            f"Cooldown: {'⏳ Active' if r.get('cooldown_until') else 'None'}"
        )

    def _cmd_positions(self) -> str:
        account = self.bot.get_account_info()
        if not account:
            return "⚠️ Unable to fetch positions"

        positions = [
            p for p in getattr(account, 'positions', [])
            if isinstance(p, dict) and p.get("netqty", "0") != "0"
        ]

        if not positions:
            return "📍 <b>POSITIONS</b>\n────────────\nNo open positions"

        # Include urmtom for broker-accurate MTM
        total_pnl = sum(
            float(p.get("rpnl", 0)) + float(p.get("urmtom", 0))
            for p in positions
        )
        lines = ["📍 <b>POSITIONS</b>", "────────────"]

        for p in positions:
            pnl = float(p.get("rpnl", 0)) + float(p.get("urmtom", 0))
            lines.append(f"{p.get('tsym')}: {p.get('netqty')} qty | ₹{pnl:.2f}")

        lines.append(f"\n<b>Total MTM: ₹{total_pnl:.2f}</b>")
        return "\n".join(lines)

    def _cmd_pnl(self) -> str:
        risk = self.bot.risk_manager.get_status()
        trades = self.bot.get_trade_history(date_filter="today")
        wins = sum(1 for t in trades if t.get("status") == "Ok")

        return (
            "💰 <b>PNL SUMMARY</b>\n"
            "────────────\n"
            f"Today MTM: ₹{risk['daily_pnl']:.2f}\n"
            f"Trades: {len(trades)} ({wins}W / {len(trades) - wins}L)"
        )

    def _help(self) -> str:
        cmds = "\n".join(f"/trade {cmd}" for cmd in self.commands.keys())
        return f"<b>Available Commands:</b>\n{cmds}"
#!/usr/bin/env python3
"""
EXECUTION GATEWAY HTTP SERVICE (PRODUCTION — FROZEN)
===================================================

Responsibilities:
- TradingView webhook ingestion
- Telegram webhook ingestion
- Health & diagnostics APIs

STRICT RULES:
- NO HTML rendering
- NO templates
- NO dashboard
- NO manual trading controls
- NO state mutation outside ShoonyaBot

This service is part of the EXECUTION PLANE.
"""

import logging
from datetime import datetime
from flask import Flask, request, jsonify

from shoonya_platform.utils.utils import (
    parse_json_safely,
    create_response_dict,
    log_exception,
)
from shoonya_platform.api.http.telegram_controller import TelegramController

logger = logging.getLogger(__name__)

class ExecutionApp:
    """
    Execution-only Flask application.
    """

    def __init__(self, trading_bot):
        self.bot = trading_bot
        self.app = Flask(__name__)

        # Telegram controller (engine input)
        allowed_users = set(trading_bot.config.get_telegram_allowed_users())
        self.telegram_controller = TelegramController(
            bot=trading_bot,
            allowed_users=allowed_users,
        )

        self._register_routes()

    # ------------------------------------------------------------------
    # ROUTES
    # ------------------------------------------------------------------

    def _register_routes(self):

        # -------------------------------
        # TradingView Webhook
        # -------------------------------
        @self.app.route("/webhook", methods=["POST"])
        def webhook():
            try:
                payload = request.get_data(as_text=True)
                signature = request.headers.get("X-Signature", "")

                if not self.bot.validate_webhook_signature(payload, signature):
                    return jsonify({"error": "Invalid signature"}), 401

                alert_data, parse_error = parse_json_safely(payload)
                if parse_error:
                    return jsonify({"error": parse_error}), 400

                result = self.bot.process_alert(alert_data)
                status = 200 if result["status"] != "error" else 500
                return jsonify(result), status

            except Exception as e:
                log_exception("execution_webhook", e)
                return jsonify(
                    create_response_dict(
                        status="error",
                        message="Internal execution error",
                    )
                ), 500

        # -------------------------------
        # Broker Positions Endpoint
        # -------------------------------
        @self.app.route("/positions", methods=["GET"])
        def positions():
            try:
                # Returns the broker's current open positions (truth)
                positions = self.bot.get_positions()
                return jsonify({"positions": positions, "status": "ok"}), 200
            except Exception as e:
                log_exception("positions", e)
                return jsonify({"status": "error", "message": str(e)}), 500

        # -------------------------------
        # Telegram Webhook
        # -------------------------------
        @self.app.route("/telegram/webhook", methods=["POST"])
        def telegram_webhook():
            try:
                payload = request.get_json(force=True, silent=True)
                if not payload:
                    return jsonify({"ok": True})

                response = self.telegram_controller.handle_message(payload)
                if response:
                    self.bot.telegram.send_message(response)

                return jsonify({"ok": True})

            except Exception:
                logger.exception("telegram_webhook_error")
                return jsonify({"ok": True})

        # -------------------------------
        # Health Check
        # -------------------------------
        @self.app.route("/health", methods=["GET"])
        def health():
            try:
                logged_in = self.bot.api.logged_in or self.bot.login()
                stats = self.bot.get_bot_stats()

                return jsonify(
                    {
                        "status": "healthy" if logged_in else "unhealthy",
                        "logged_in": logged_in,
                        "total_trades": stats.total_trades,
                        "today_trades": stats.today_trades,
                        "last_activity": stats.last_activity,
                        "timestamp": datetime.now().isoformat(),
                    }
                ), 200 if logged_in else 503

            except Exception as e:
                log_exception("health", e)
                return jsonify(
                    create_response_dict(
                        status="unhealthy",
                        message=str(e),
                    )
                ), 500

        # -------------------------------
        # Status Snapshot
        # -------------------------------
        @self.app.route("/status", methods=["GET"])
        def status():
            try:
                if not self.bot.api.logged_in:
                    self.bot.login()

                stats = self.bot.get_bot_stats()
                account = self.bot.get_account_info()

                return jsonify(
                    {
                        "engine": "active",
                        "account_connected": account is not None,
                        "total_trades": stats.total_trades,
                        "today_trades": stats.today_trades,
                        "last_activity": stats.last_activity,
                        "timestamp": datetime.now().isoformat(),
                    }
                ), 200

            except Exception as e:
                log_exception("status", e)
                return jsonify(
                    create_response_dict(
                        status="error",
                        message=str(e),
                    )
                ), 500

    def get_app(self):
        return self.app

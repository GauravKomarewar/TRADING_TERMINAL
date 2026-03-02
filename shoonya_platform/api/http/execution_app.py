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
import os
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

                # ---- COPY TRADING FAN-OUT (MASTER ONLY) ----
                # Fan out to followers only when execution succeeded and this
                # client is configured as master. Fanout is fire-and-forget
                # (does not affect HTTP response to TradingView).
                copy_svc = getattr(self.bot, "copy_trading_service", None)
                if (
                    copy_svc is not None
                    and copy_svc.is_master
                    and result.get("status") not in ("error", "blocked", "FAILED")
                ):
                    try:
                        fanout_results = copy_svc.fan_out_alert(alert_data, result)
                        result["copy_trading"] = {
                            "fanned_out": True,
                            "followers_attempted": len(fanout_results),
                            "followers_delivered": sum(
                                1 for r in fanout_results if r.get("status") == "delivered"
                            ),
                        }
                    except Exception as _ct_err:
                        logger.warning("CopyTrading fan-out error (non-fatal): %s", _ct_err)

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
                self.bot._ensure_login()
                positions = self.bot.broker_view.get_positions(force_refresh=True)
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
                logged_in = self.bot.api.logged_in  # Read-only check; never trigger login()
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
                # Read-only: report current state without triggering login()
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

        # -------------------------------
        # Copy-Alert Endpoint (FOLLOWER / RELAY)
        # Receives fan-out alerts from a master client.
        #
        # INDEPENDENT TRADING NOTE:
        # Every client — regardless of copy_trading_role — ALWAYS
        # receives its own TradingView webhooks on /webhook and trades
        # independently.  Copy trading is purely additive:
        #   • standalone:  only /webhook   (no copy involvement)
        #   • master:      /webhook → process → fan-out to followers
        #   • follower:    /webhook (own alerts) + /copy-alert (master's alerts)
        #   • relay:       follower who is also a master for sub-followers;
        #                  copy-alert is processed AND re-fanned-out
        # -------------------------------
        @self.app.route("/copy-alert", methods=["POST"])
        def copy_alert():
            try:
                copy_svc = getattr(self.bot, "copy_trading_service", None)

                # Silently accept (200) if copy trading not configured on this client,
                # so the master doesn't get spurious errors.
                if copy_svc is None or not copy_svc.is_follower:
                    return jsonify({"status": "not_a_follower"}), 200

                payload_bytes = request.get_data()
                signature = request.headers.get("X-Copy-Signature", "")

                if not copy_svc.validate_copy_signature(payload_bytes, signature):
                    return jsonify({"error": "Invalid copy signature"}), 401

                raw_payload = parse_json_safely(payload_bytes.decode("utf-8", errors="replace"))
                copy_payload, parse_error = raw_payload
                if parse_error:
                    return jsonify({"error": parse_error}), 400

                alert_data, metadata = copy_svc.extract_alert_from_copy_payload(copy_payload)

                logger.info(
                    "COPY_ALERT_RECEIVED | master=%s | strategy=%s | mode=%s",
                    metadata.get("master_client_id", "unknown"),
                    alert_data.get("strategy_name", "unknown"),
                    metadata.get("copy_mode", "mirror"),
                )

                result = self.bot.process_alert(alert_data)

                # ---- RELAY FAN-OUT (this client is also a master for sub-followers) ----
                # If this follower is ALSO a master for other followers, re-fan the
                # alert so chains like A-master → B-relay → C-follower work correctly.
                if (
                    copy_svc.is_master
                    and result.get("status") not in ("error", "blocked", "FAILED")
                ):
                    try:
                        fanout_results = copy_svc.fan_out_alert(alert_data, result)
                        result["relay_copy_trading"] = {
                            "relayed": True,
                            "followers_attempted": len(fanout_results),
                            "followers_delivered": sum(
                                1 for r in fanout_results if r.get("status") == "delivered"
                            ),
                        }
                    except Exception as _relay_err:
                        logger.warning("Relay fan-out error (non-fatal): %s", _relay_err)

                status_code = 200 if result.get("status") != "error" else 500
                return jsonify({**result, "copy_meta": metadata}), status_code

            except Exception as e:
                log_exception("copy_alert_endpoint", e)
                return jsonify(
                    create_response_dict(status="error", message="Copy alert processing failed")
                ), 500

        # -------------------------------
        # Master Manager Status Endpoint
        # Called by the master manager health poller.
        # Returns structured client status without auth
        # (internal loopback only — don't expose publicly).
        # -------------------------------
        @self.app.route("/master-status", methods=["GET"])
        def master_status():
            # --- Loopback guard: only allow requests from 127.0.0.1 / ::1 ---
            # Additionally accept an optional X-Internal-Token header for
            # non-loopback internal networks (configure via INTERNAL_TOKEN env var).
            allowed_addrs = {"127.0.0.1", "::1", "localhost"}
            internal_token = os.environ.get("INTERNAL_TOKEN")
            remote = request.remote_addr or ""
            token_header = request.headers.get("X-Internal-Token", "")
            if remote not in allowed_addrs:
                if not (internal_token and token_header == internal_token):
                    return jsonify({"error": "Forbidden"}), 403
            try:
                cfg = self.bot.config
                ct_cfg = cfg.get_copy_trading_config()
                identity = cfg.get_client_identity()
                stats = self.bot.get_bot_stats()
                return jsonify({
                    "client_id": identity.get("client_id"),
                    "client_alias": getattr(cfg, "client_id_alias", identity.get("user_id")),
                    "display_name": identity.get("client_id"),
                    "service": "execution",
                    "logged_in": bool(self.bot.api.logged_in),
                    "copy_trading_role": ct_cfg.get("role"),
                    "copy_trading_enabled": ct_cfg.get("enabled"),
                    "total_trades": stats.total_trades,
                    "today_trades": stats.today_trades,
                    "timestamp": datetime.now().isoformat(),
                }), 200
            except Exception as e:
                log_exception("master_status", e)
                return jsonify({"status": "error", "message": "Internal server error"}), 500

    def get_app(self):
        return self.app

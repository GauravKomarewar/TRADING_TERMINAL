import logging

logger = logging.getLogger("REPORTER")


def _fmt(val, precision=3):
    """Safe numeric formatter"""
    if val is None:
        return "—"
    try:
        return f"{val:.{precision}f}"
    except Exception:
        return "—"


def _money(val):
    try:
        return f"₹{val:.2f}"
    except Exception:
        return "₹—"


def build_strategy_report(strategy, market):
    """
    Build a clean, Telegram-ready live status report.

    COMPATIBLE WITH:
    - DeltaNeutralShortStrangleStrategy v1.0.2 (PRODUCTION FROZEN)

    RULES:
    - No greeks assumed beyond delta
    - Uses only strategy-owned state
    - Silent when strategy inactive
    """

    state = strategy.state

    # 🔕 Do not spam when inactive
    if not state.active:
        return None

    ce = state.ce_leg
    pe = state.pe_leg

    snap = market.snapshot() or {}
    spot = snap.get("spot", "—")

    unrealized = state.total_unrealized_pnl()
    realized = state.realized_pnl or 0.0
    net_delta = state.total_delta()

    lines = []

    # =========================
    # HEADER
    # =========================
    lines.append("📊 *DELTA NEUTRAL – LIVE STATUS*")
    lines.append(f"📈 Spot: `{spot}`")
    lines.append("")

    # =========================
    # LEGS
    # =========================
    if ce:
        lines.append(
            "🟥 *CALL LEG (CE)*\n"
            f"• Symbol: `{ce.symbol}`\n"
            f"• Delta: `{_fmt(ce.delta)}`\n"
            f"• Entry: `{_money(ce.entry_price)}`\n"
            f"• LTP: `{_money(ce.current_price)}`\n"
            f"• PnL: `{_money(ce.unrealized_pnl())}`"
        )
    else:
        lines.append("🟥 *CALL LEG (CE)*\n• Status: `—`")

    lines.append("")

    if pe:
        lines.append(
            "🟩 *PUT LEG (PE)*\n"
            f"• Symbol: `{pe.symbol}`\n"
            f"• Delta: `{_fmt(pe.delta)}`\n"
            f"• Entry: `{_money(pe.entry_price)}`\n"
            f"• LTP: `{_money(pe.current_price)}`\n"
            f"• PnL: `{_money(pe.unrealized_pnl())}`"
        )
    else:
        lines.append("🟩 *PUT LEG (PE)*\n• Status: `—`")

    # =========================
    # SUMMARY
    # =========================
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append(f"📐 *Net Delta*: `{_fmt(net_delta)}`")
    lines.append(f"💰 *Unrealized*: `{_money(unrealized)}`")
    lines.append(f"💵 *Realized*: `{_money(realized)}`")

    # =========================
    # ADJUSTMENT INFO
    # =========================
    if state.adjustment_phase:
        lines.append("")
        lines.append(
            f"🔄 *Adjustment In Progress*\n"
            f"• Phase: `{state.adjustment_phase}`\n"
            f"• Leg: `{state.adjustment_leg_type}`\n"
            f"• Target Δ: `{_fmt(state.adjustment_target_delta)}`"
        )
    else:
        lines.append("")
        lines.append(
            "🎯 *Adjustment Rules*\n"
            f"• Next Profit Target: `{_money(state.next_profit_target)}`\n"
            f"• Cooldown: `{strategy.config.cooldown_seconds}s`"
        )

    return "\n".join(lines)

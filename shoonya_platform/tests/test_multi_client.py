def test_client_a_loss_does_not_affect_b(bot_a, bot_b):
    bot_a.risk_manager.daily_pnl = -3000
    bot_a.risk_manager._handle_daily_loss_breach()

    assert bot_a.risk_manager.daily_loss_hit is True
    assert bot_b.risk_manager.daily_loss_hit is False

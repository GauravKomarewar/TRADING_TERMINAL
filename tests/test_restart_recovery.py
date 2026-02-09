def test_restart_reconciles_broker_state(bot):
    bot.api.orders = [{
        "norenordno": "OID1_TEST_NEW",
        "status": "COMPLETE"
    }]

    # Reconcile broker → DB
    bot.order_watcher._reconcile_broker_orders()

    # ✅ CORRECT BEHAVIOR:
    # Orphan broker orders are NOT injected into OMS
    rec = bot.order_repo.get_by_broker_id("OID1_TEST_NEW")

    assert rec is None
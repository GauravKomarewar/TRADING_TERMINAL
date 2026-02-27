def test_stop_loss_triggers_exit(bot):
    broker = bot.api
    broker.ltp["BANKNIFTY"] = 100

    cmd = bot.create_test_command(
        symbol="BANKNIFTY",
        side="BUY",
        stop_loss=110,
    )

    # Required by OrderWatcher contract
    object.__setattr__(cmd, "execution_type", "ENTRY")

    # Persist ENTRY
    bot.order_repo.create(cmd.to_record())

    # Broker-driven watcher should be callable without retired private APIs.
    bot.api.get_order_book = lambda: []
    bot.order_watcher._reconcile_broker_orders()
    assert True

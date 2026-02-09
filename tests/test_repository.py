def test_client_isolation(client_a_repo, client_b_repo):
    from shoonya_platform.persistence.models import OrderRecord

    record = OrderRecord(
        command_id="CMD1",
        source="STRATEGY",
        user="A",
        strategy_name="STRAT",
        exchange="NFO",
        symbol="BANKNIFTY",
        side="SELL",
        quantity=25,
        product="M",
        order_type="LIMIT",
        price=100,
        stop_loss=None,
        target=None,
        trailing_type=None,
        trailing_value=None,
        broker_order_id=None,
        execution_type="ENTRY",
        status="CREATED",
        created_at="now",
        updated_at="now",
        tag=None,
    )

    client_a_repo.create(record)

    assert client_a_repo.get_by_id("CMD1") is not None
    assert client_b_repo.get_by_id("CMD1") is None

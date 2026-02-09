import pytest
from shoonya_platform.execution.intent import UniversalOrderCommand

def test_exit_submission_blocked(bot):
    cmd = UniversalOrderCommand(
        intent="EXIT",
        symbol="BANKNIFTY",
        exchange="NFO",
        side="BUY",
        quantity=25,
        product="M"
    )

    with pytest.raises(RuntimeError):
        bot.command_service.submit(cmd, execution_type="EXIT")

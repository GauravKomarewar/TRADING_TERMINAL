import pytest
import os
import tempfile
from unittest.mock import MagicMock

from shoonya_platform.execution.order_watcher import OrderWatcherEngine
from shoonya_platform.risk.supreme_risk import SupremeRiskManager
from shoonya_platform.execution.intent import UniversalOrderCommand
from shoonya_platform.persistence.repository import OrderRepository
from shoonya_platform.execution.command_service import CommandService

from .fake_broker import FakeBroker

# Global temp directory for test state files
_TEST_TEMP_DIR = tempfile.mkdtemp(prefix="shoonya_test_")


class FakeBot:
    def __init__(self, client_id, broker):
        self.client_id = client_id
        self.api = broker

        # Minimal config required by SupremeRiskManager
        from types import SimpleNamespace
        # Use temp dir for state files so they don't persist across test runs
        state_file = os.path.join(_TEST_TEMP_DIR, f"risk_state_{client_id}.json")
        self.config = SimpleNamespace(
            risk_state_file=state_file,
            risk_base_max_loss=-1000,  # Smaller limit for tests
            risk_trail_step=100,
            risk_warning_threshold=0.5,
            risk_max_consecutive_loss_days=3,
            risk_status_update_min=1,
            risk_pnl_retention=30,
            report_frequency=60,
        )

        self.order_repo = OrderRepository(client_id)
        
        # ExecutionGuard (must be before CommandService)
        self.execution_guard = MagicMock()
        
        # OrderWatcher (must be before CommandService)
        # ❌ DO NOT start background thread in tests
        self.order_watcher = OrderWatcherEngine(self, poll_interval=9999)
        
        # CommandService (depends on order_watcher, execution_guard, order_repo)
        self.command_service = CommandService(self)

        # RMS
        self.risk_manager = SupremeRiskManager(self)

        self.telegram_enabled = False

    def _ensure_login(self):
        return True

    def execute_command(self, command, trailing_engine=None):
        return {"status": "SUBMITTED"}

    def mark_command_executed(self, command_id):
        pass

    def mark_command_executed_by_broker_id(self, broker_id):
        pass

    def get_open_commands(self):
        return getattr(self, "pending_commands", [])

    # -------------------------------
    # Test helper
    # -------------------------------
    def create_test_command(
        self,
        symbol,
        side,
        stop_loss=None,
        execution_type="ENTRY",
    ):
        order_params = {
            "exchange": "NFO",
            "tradingsymbol": symbol,
            "quantity": 25,
            "direction": side,
            "product": "M",
            "order_type": "MARKET",
            "price": None,
        }
        if stop_loss is not None:
            order_params["stop_loss"] = stop_loss
        
        return UniversalOrderCommand.from_order_params(
            order_params=order_params,
            source="STRATEGY",
            user=self.client_id,
        )


@pytest.fixture
def fake_broker():
    return FakeBroker()


@pytest.fixture
def bot(fake_broker):
    return FakeBot("TEST_CLIENT", fake_broker)


@pytest.fixture
def bot_a():
    return FakeBot("A", FakeBroker())


@pytest.fixture
def bot_b():
    return FakeBot("B", FakeBroker())


@pytest.fixture
def client_a_repo():
    return OrderRepository("A")


@pytest.fixture
def client_b_repo():
    return OrderRepository("B")

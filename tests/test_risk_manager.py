import pytest
import numpy as np
from decimal import Decimal
from datetime import datetime, timezone
from typing import Dict, Any

from risk_management.risk_manager import RiskManager, Position
from data_ingestion.memory_store import MemoryStore, OrderBook

@pytest.fixture
def risk_manager():
    return RiskManager(
        max_position_size=Decimal("1.0"),
        max_leverage=Decimal("3.0"),
        max_drawdown=Decimal("0.1"),
        stop_loss_threshold=Decimal("0.05"),
        position_timeout=3600,  # 1 hour
        volatility_threshold=Decimal("0.02")
    )

@pytest.fixture
def memory_store():
    return MemoryStore()

def test_position_size_limit(risk_manager):
    """Test position size limits."""
    # Test within limits
    assert risk_manager.check_position_size(Decimal("0.5")) is True
    
    # Test at limit
    assert risk_manager.check_position_size(Decimal("1.0")) is True
    
    # Test exceeding limit
    assert risk_manager.check_position_size(Decimal("1.5")) is False

def test_leverage_limit(risk_manager):
    """Test leverage limits."""
    # Setup test position
    position = Position(
        symbol="BTC/USD",
        size=Decimal("1.0"),
        entry_price=Decimal("50000"),
        current_price=Decimal("51000"),
        unrealized_pnl=Decimal("1000"),
        realized_pnl=Decimal("0"),
        status="OPEN",
        opened_at=datetime.now(timezone.utc)
    )
    
    # Test within limits
    assert risk_manager.check_leverage(position, Decimal("100000")) is True
    
    # Test at limit
    assert risk_manager.check_leverage(position, Decimal("150000")) is True
    
    # Test exceeding limit
    assert risk_manager.check_leverage(position, Decimal("200000")) is False

def test_drawdown_monitoring(risk_manager):
    """Test drawdown monitoring."""
    initial_equity = Decimal("100000")
    
    # Test within limits
    current_equity = Decimal("95000")  # 5% drawdown
    assert risk_manager.check_drawdown(initial_equity, current_equity) is True
    
    # Test at limit
    current_equity = Decimal("90000")  # 10% drawdown
    assert risk_manager.check_drawdown(initial_equity, current_equity) is True
    
    # Test exceeding limit
    current_equity = Decimal("85000")  # 15% drawdown
    assert risk_manager.check_drawdown(initial_equity, current_equity) is False

def test_stop_loss_trigger(risk_manager):
    """Test stop loss triggering."""
    position = Position(
        symbol="BTC/USD",
        size=Decimal("1.0"),
        entry_price=Decimal("50000"),
        current_price=Decimal("47500"),  # 5% loss
        unrealized_pnl=Decimal("-2500"),
        realized_pnl=Decimal("0"),
        status="OPEN",
        opened_at=datetime.now(timezone.utc)
    )
    
    # Test stop loss trigger
    assert risk_manager.check_stop_loss(position) is False

def test_position_timeout(risk_manager):
    """Test position timeout."""
    # Create position with old timestamp
    from datetime import timedelta
    
    old_time = datetime.now(timezone.utc) - timedelta(hours=2)
    position = Position(
        symbol="BTC/USD",
        size=Decimal("1.0"),
        entry_price=Decimal("50000"),
        current_price=Decimal("51000"),
        unrealized_pnl=Decimal("1000"),
        realized_pnl=Decimal("0"),
        status="OPEN",
        opened_at=old_time
    )
    
    # Test timeout
    assert risk_manager.check_position_timeout(position) is False

def test_volatility_check(risk_manager, memory_store):
    """Test volatility monitoring."""
    # Create price history
    prices = []
    base_price = 50000
    for i in range(100):
        # Create synthetic volatility
        price = base_price * (1 + 0.01 * np.sin(i / 10))
        ob = OrderBook(
            timestamp=datetime.now(timezone.utc),
            symbol="BTC/USD",
            bids=[{"price": Decimal(str(price)), "quantity": Decimal("1.0")}],
            asks=[{"price": Decimal(str(price * 1.001)), "quantity": Decimal("1.0")}]
        )
        memory_store.update_orderbook("BTC/USD", ob)
        prices.append(price)
    
    # Test normal volatility
    assert risk_manager.check_volatility("BTC/USD", memory_store) is True
    
    # Test high volatility
    prices = []
    for i in range(100):
        # Create high volatility
        price = base_price * (1 + 0.05 * np.sin(i / 10))
        ob = OrderBook(
            timestamp=datetime.now(timezone.utc),
            symbol="BTC/USD",
            bids=[{"price": Decimal(str(price)), "quantity": Decimal("1.0")}],
            asks=[{"price": Decimal(str(price * 1.001)), "quantity": Decimal("1.0")}]
        )
        memory_store.update_orderbook("BTC/USD", ob)
        prices.append(price)
    
    assert risk_manager.check_volatility("BTC/USD", memory_store) is False

def test_risk_metrics(risk_manager):
    """Test risk metrics calculation."""
    # Create test positions and trades
    positions = [
        Position(
            symbol="BTC/USD",
            size=Decimal("1.0"),
            entry_price=Decimal("50000"),
            current_price=Decimal("51000"),
            unrealized_pnl=Decimal("1000"),
            realized_pnl=Decimal("500"),
            status="OPEN",
            opened_at=datetime.now(timezone.utc)
        )
    ]
    
    metrics = risk_manager.calculate_risk_metrics(positions)
    
    assert "total_exposure" in metrics
    assert "unrealized_pnl" in metrics
    assert "realized_pnl" in metrics
    assert metrics["total_exposure"] == Decimal("51000")
    assert metrics["unrealized_pnl"] == Decimal("1000")
    assert metrics["realized_pnl"] == Decimal("500")

def test_risk_alerts(risk_manager):
    """Test risk alert generation."""
    # Create high-risk scenario
    position = Position(
        symbol="BTC/USD",
        size=Decimal("0.9"),  # Near position limit
        entry_price=Decimal("50000"),
        current_price=Decimal("47500"),  # Near stop loss
        unrealized_pnl=Decimal("-2500"),
        realized_pnl=Decimal("0"),
        status="OPEN",
        opened_at=datetime.now(timezone.utc)
    )
    
    alerts = risk_manager.check_risk_alerts([position])
    
    assert len(alerts) > 0
    assert any(alert["level"] == "WARNING" for alert in alerts)
    assert any("position size" in alert["message"].lower() for alert in alerts)
    assert any("stop loss" in alert["message"].lower() for alert in alerts)

def test_concurrent_risk_checks(risk_manager):
    """Test concurrent risk checking."""
    import threading
    import queue
    
    # Create a queue for results
    results = queue.Queue()
    
    def check_risks():
        try:
            position = Position(
                symbol="BTC/USD",
                size=Decimal("1.0"),
                entry_price=Decimal("50000"),
                current_price=Decimal("51000"),
                unrealized_pnl=Decimal("1000"),
                realized_pnl=Decimal("0"),
                status="OPEN",
                opened_at=datetime.now(timezone.utc)
            )
            
            # Run multiple risk checks
            risk_manager.check_position_size(position.size)
            risk_manager.check_leverage(position, Decimal("100000"))
            risk_manager.check_stop_loss(position)
            risk_manager.check_position_timeout(position)
            
            results.put(True)
        except Exception as e:
            results.put(e)
    
    # Start multiple threads
    threads = []
    for _ in range(10):
        t = threading.Thread(target=check_risks)
        t.start()
        threads.append(t)
    
    # Wait for all threads to complete
    for t in threads:
        t.join()
    
    # Check results
    errors = []
    while not results.empty():
        result = results.get()
        if isinstance(result, Exception):
            errors.append(result)
    
    assert len(errors) == 0

if __name__ == '__main__':
    pytest.main([__file__]) 
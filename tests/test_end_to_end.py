import pytest
from src.risk_management import RiskManager, RiskLimits

alerts = []


def _capture(msg: str) -> None:
    alerts.append(msg)


@pytest.fixture
def risk_manager():
    limits = RiskLimits(
        max_drawdown=0.10,
        circuit_breaker_pct=0.07,
        correlation_threshold=0.8,
        position_limit=10_000,
        multi_level_drawdown={"L1": 0.02, "L2": 0.05, "L3": 0.10},
    )
    return RiskManager(limits, alert_sink=_capture)


def test_drawdown_breach(risk_manager):
    # establish high water-mark then trigger 20 % drawdown
    risk_manager.update_pnl(100_000)
    risk_manager.update_pnl(80_000)

    assert any("Max drawdown limit breached" in a for a in alerts)


def test_circuit_breaker(risk_manager):
    risk_manager.update_positions({"AAPL": 100}, {"AAPL": 100.0})
    # 8 % price move triggers breaker
    risk_manager.check_market_moves({"AAPL": 108.0})

    assert any("Circuit-breaker triggered" in a for a in alerts)
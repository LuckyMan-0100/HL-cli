class RiskManager:
    """
    Enforces simple notional caps and trade fee accounting.
    """

    def __init__(self, max_notional: float = 100_000.0, fee_rate: float = 0.0004) -> None:
        self.max_notional = max_notional
        self.fee_rate = fee_rate

    # ------------------------------------------------------------------ #
    # Public helpers
    # ------------------------------------------------------------------ #
    def allow_trade(self, notional: float) -> bool:
        """
        Return *True* if the notional is within limits.
        """
        return abs(notional) <= self.max_notional

    def apply_fees(self, pnl: float) -> float:
        """
        Deduct proportional fees from a raw PnL figure.
        """
        return pnl - abs(pnl) * self.fee_rate
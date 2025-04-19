from dataclasses import dataclass
import time

@dataclass
class RiskState:
    equity: float = 100.0
    max_dd_pct: float = 0.2
    notional_target: float = 1_000_000
    notional_done: float = 0.0
    consecutive_loss: int = 0
    is_killed: bool = False

    def update_fill(self, notional: float, pnl: float) -> None:
        self.notional_done += notional
        if pnl < 0:
            self.consecutive_loss += 1
        else:
            self.consecutive_loss = 0
        self.equity += pnl
        if self.equity <= (1 - self.max_dd_pct) * 100:
            self.is_killed = True
        if self.notional_done >= self.notional_target:
            self.is_killed = True
        if self.consecutive_loss >= 3:
            self.is_killed = True
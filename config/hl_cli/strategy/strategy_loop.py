from __future__ import annotations

import numpy as np

from rl.environment import MarketEnv
from rl.agent import QLearningAgent
from risk_management import RiskManager
from strategy.execution_interface import ExecutionInterface, LiveExecution


class StrategyRunner:
    """
    High‑level event loop that:

    1. Gets an observation from ``MarketEnv``.
    2. Chooses an action via ``QLearningAgent``.
    3. Checks the ``RiskManager`` and sends it through an ``ExecutionInterface``.
    4. Feeds the transition back to the agent for learning.
    """

    def __init__(
        self,
        env: MarketEnv | None = None,
        agent: QLearningAgent | None = None,
        executor: ExecutionInterface | None = None,
        risk: RiskManager | None = None,
        qty: float = 1.0,
    ) -> None:
        self.env = env or MarketEnv()
        self.agent = agent or QLearningAgent()
        self.exec = executor or LiveExecution()
        self.risk = risk or RiskManager()
        self.qty = qty

    # ------------------------------------------------------------------ #
    # Main loop
    # ------------------------------------------------------------------ #
    def run_episode(self) -> float:
        obs = self.env.reset()
        done = False
        total_reward = 0.0

        while not done:
            action = self.agent.act(obs)
            if action in (1, 2):  # trade requested
                notional = self.qty * float(self.env.price)
                if self.risk.allow_trade(notional):
                    side = "BUY" if action == 1 else "SELL"
                    self.exec.place_order(
                        side=side,
                        qty=self.qty,
                        price=float(self.env.price),
                        symbol=self.env.symbol
                    )

            step_out = self.env.step(action)
            self.agent.learn(obs, action, step_out.reward, step_out.obs, step_out.done)

            obs = step_out.obs
            done = step_out.done
            total_reward += step_out.reward

        # Apply fees only once per episode for simplicity
        return self.risk.apply_fees(total_reward)
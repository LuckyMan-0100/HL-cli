import random
from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np


@dataclass
class StepOutput:
    """Typed bundle returned by ``MarketEnv.step``."""
    obs: np.ndarray
    reward: float
    done: bool
    info: Dict


class MarketEnv:
    """
    Extremely simplified price‑walk environment.

    * **Observation** – 7‑dim float vector (mirrors `feature_engineering.features`).
    * **Actions** – 0: HOLD, 1: BUY (go long +1), 2: SELL (flat/short –1).
    * **Reward** – Mark‑to‑market PnL delta after the price update.
    """

    ACTIONS = ("HOLD", "BUY", "SELL")

    def __init__(self, max_steps: int = 200, seed: int | None = None) -> None:
        self.max_steps = max_steps
        self.rng = random.Random(seed)
        self.reset()

    # ------------------------------------------------------------------ #
    # Gym‑like API
    # ------------------------------------------------------------------ #
    def reset(self) -> np.ndarray:
        self.step_idx = 0
        self.price = 100.0
        self.prev_price = self.price
        self.position = 0  # +1 long, ‑1 short, 0 flat
        return self._obs()

    def step(self, action: int) -> StepOutput:
        assert 0 <= action < 3, "Action must be 0,1,2"
        self.step_idx += 1

        # ---------- Execute action ----------
        if action == 1:    # BUY   → long
            self.position = 1
        elif action == 2:  # SELL  → flat/short
            self.position = -1 if self.position == 0 else 0

        # ---------- Environment dynamics ----------
        self.prev_price = self.price
        self.price *= 1 + (self.rng.random() - 0.5) * 0.01  # ±0.5 %

        # ---------- Reward ----------
        reward = (self.price - self.prev_price) * self.position

        obs = self._obs()
        done = self.step_idx >= self.max_steps
        info: Dict = {"price": self.price}
        return StepOutput(obs, reward, done, info)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _obs(self) -> np.ndarray:
        """
        Build a 7‑dim observation vector similar to the prod feature pipeline.
        Here we just emit simple, deterministic stand‑ins.
        """
        spread = self.price * 0.0002
        bid = self.price - spread / 2
        ask = self.price + spread / 2
        imbalance = self.position  # simplistic stand‑in

        obs = np.array(
            [
                self.price % 100,            # fake RSI
                (self.price % 50) - 25,      # fake MACD
                ((self.price % 20) - 10) / 2,  # fake BB position
                imbalance,
                bid,
                ask,
                self.price,
            ],
            dtype=np.float32,
        )
        return obs
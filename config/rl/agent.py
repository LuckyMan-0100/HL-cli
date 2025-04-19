from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Hashable, Tuple

import numpy as np


Observation = Tuple[int, ...]  # discretised feature tuple


def _discretise(obs: np.ndarray, bins: int = 20) -> Observation:
    """
    Very rough state hash by bucketing each feature into ``bins`` segments.
    """
    return tuple(int(math.floor(v * bins)) for v in obs)


class QLearningAgent:
    """
    Table‑based ε‑greedy Q‑learning agent for the 3‑action `MarketEnv`.
    """

    def __init__(
        self,
        lr: float = 0.1,
        gamma: float = 0.99,
        epsilon: float = 0.1,
        seed: int | None = None,
    ) -> None:
        self.lr = lr
        self.gamma = gamma
        self.epsilon = epsilon
        self.rng = random.Random(seed)
        self.q: defaultdict[Observation, np.ndarray] = defaultdict(
            lambda: np.zeros(3, dtype=np.float32)  # 3 actions
        )

    # ------------------------------------------------------------------ #
    # Policy
    # ------------------------------------------------------------------ #
    def act(self, obs: np.ndarray) -> int:
        state = _discretise(obs)
        if self.rng.random() < self.epsilon:
            return self.rng.randrange(3)
        return int(np.argmax(self.q[state]))

    # ------------------------------------------------------------------ #
    # Learning
    # ------------------------------------------------------------------ #
    def learn(
        self,
        obs: np.ndarray,
        action: int,
        reward: float,
        next_obs: np.ndarray,
        done: bool,
    ) -> None:
        s, ns = _discretise(obs), _discretise(next_obs)
        best_next = 0.0 if done else float(np.max(self.q[ns]))
        td_target = reward + self.gamma * best_next
        td_error = td_target - self.q[s][action]
        self.q[s][action] += self.lr * td_error


# --------------------------------------------------------------------- #
# A trivial baseline agent
# --------------------------------------------------------------------- #
class RandomAgent:
    def __init__(self, seed: int | None = None) -> None:
        self.rng = random.Random(seed)

    def act(self, obs: np.ndarray) -> int:  # noqa: ARG002 – obs unused
        return self.rng.randrange(3)

    def learn(self, *_, **__) -> None:  # type: ignore[no-self-use]
        """Random agent does not learn."""
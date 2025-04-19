import numpy as np
from rl.environment import MarketEnv


def test_market_env_basic():
    env = MarketEnv(max_steps=5, seed=42)
    obs = env.reset()
    assert isinstance(obs, np.ndarray) and obs.shape == (7,)

    done = False
    steps = 0
    while not done:
        step_out = env.step(0)  # HOLD
        assert step_out.obs.shape == (7,)
        done = step_out.done
        steps += 1
    assert steps == 5
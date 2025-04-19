"""
Entry‑point triggered by Airflow or manual runs.

Current flow:
1. Generate a tiny synthetic dataset with `feature_engineering.label_good_entry`.
2. Train the gradient‑boosting model and persist it.
3. Run a short RL episode to refresh the agent tables.

Extend this script as needed for production workloads.
"""
from datetime import datetime
import numpy as np
import pandas as pd

from feature_engineering.features import label_good_entry
from ml.model import train
from rl.environment import MarketEnv
from rl.agent import QLearningAgent
from strategy.strategy_loop import StrategyRunner


def _generate_synthetic_dataset(rows: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(seed=123)
    prices = np.cumprod(1 + rng.normal(0, 0.002, size=rows)) * 100
    df = pd.DataFrame({"close": prices})
    df["future"] = df["close"].pct_change(periods=5).shift(-5).fillna(0)
    df["label"] = df["future"].rolling(5).apply(lambda x: label_good_entry(pd.Series(x)), raw=False)
    df["features"] = df["close"].rolling(10).apply(lambda x: rng.normal(size=7).tolist()).shift(1)
    df = df.dropna()
    return df[["features", "label"]]


def main():
    print(f"[{datetime.utcnow().isoformat()}] starting synthetic training run")
    data = _generate_synthetic_dataset()
    train(data)  # saves model to artifacts/

    # Run one RL episode for freshness statistics
    runner = StrategyRunner(env=MarketEnv(max_steps=50), agent=QLearningAgent())
    reward = runner.run_episode()
    print(f"Finished RL simulation – episode reward {reward:.2f}")


if __name__ == "__main__":
    main()
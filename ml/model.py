from pathlib import Path
import joblib, numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

MODEL_PATH = Path("artifacts/model.pkl")

def train(df: pd.DataFrame) -> None:
    X = np.vstack(df["features"].to_list())
    y = df["label"].values
    model = HistGradientBoostingClassifier(max_depth=4, learning_rate=0.07)
    model.fit(X, y)
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    print("Saved model to", MODEL_PATH)

def load():
    return joblib.load(MODEL_PATH)

def predict_proba(model, feats: np.ndarray) -> float:
    return float(model.predict_proba(feats.reshape(1, -1))[0, 1])
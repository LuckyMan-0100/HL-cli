"""
ml/train_boosting.py
--------------------
Train a gradient‑boosting (XGBoost) model on the labelled dataset and save it
to `models/gbm_entry.pkl`.
"""

import pathlib
import joblib

import pandas as pd
from xgboost import XGBClassifier
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split


FEATURE_COLS = [
    c
    for c in [
        "RSI_14",
        "MACD_12_26_9",
        "MACDs_12_26_9",
        "MACDh_12_26_9",
        "BBL_20_2.0",
        "BBM_20_2.0",
        "BBU_20_2.0",
        "ATRr_14",
    ]
    if c  # keep as‑is
]


def main() -> None:
    data_path = pathlib.Path("data/dataset.parquet")
    if not data_path.exists():
        raise FileNotFoundError(
            "data/dataset.parquet not found. Run feature_engineering.labeller first."
        )

    df = pd.read_parquet(data_path)
    X = df[FEATURE_COLS]
    y = df["label"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, shuffle=True, stratify=y, random_state=42
    )

    model = XGBClassifier(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.9,
        colsample_bytree=0.8,
        eval_metric="logloss",
        n_jobs=-1,
    )
    model.fit(X_train, y_train)

    print(classification_report(y_test, model.predict(X_test)))

    pathlib.Path("models").mkdir(exist_ok=True)
    out_file = pathlib.Path("models/gbm_entry.pkl")
    joblib.dump(model, out_file)
    print(f"Saved model ➜ {out_file}")


if __name__ == "__main__":
    main() 
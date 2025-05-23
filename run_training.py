#!/usr/bin/env python3
"""Training pipeline orchestrator."""

import logging
import os
from datetime import datetime, timedelta
import pandas as pd
from pathlib import Path

from feature_engineering.l2_only_trainer import main as train_l2
from ml.train_model import ModelTrainer
from orderflow.tail_reader import DepthTailReader
from data.kline_reader import KlineReader
from settings import settings  # Import settings directly

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Ensure required directories exist
Path("ml/models").mkdir(parents=True, exist_ok=True)
Path("/tmp").mkdir(parents=True, exist_ok=True)

def main() -> None:
    try:
        # ------------------------------------------------------------------------------------------------------------------
        # Time window configuration
        # ------------------------------------------------------------------------------------------------------------------
        end_time = datetime.now()
        start_time = end_time - timedelta(days=7)  # Last 7 days to match l2_only_trainer

        logger.info(f"Training window: {start_time} to {end_time}")

        # ------------------------------------------------------------------------------------------------------------------
        # Step 1: Train L2-only model and generate features
        # ------------------------------------------------------------------------------------------------------------------
        logger.info("Step 1: Training L2-only model and generating features")
        train_l2()  # This will save features to /tmp/features.parquet
        
        if not Path("/tmp/features.parquet").exists():
            logger.error("Feature generation failed - features.parquet not found")
            return

        # ------------------------------------------------------------------------------------------------------------------
        # Step 2: Initialize data readers
        # ------------------------------------------------------------------------------------------------------------------
        logger.info("Step 2: Initializing data readers")
        
        # Use database configuration from settings
        l2_reader = DepthTailReader(
            dsn=settings.database.dsn,
            table="orderbook_snapshots",  # Use the correct table name
            batch_size=100_000
        )
        
        kline_reader = KlineReader(db_url=settings.database.dsn)

        # ------------------------------------------------------------------------------------------------------------------
        # Step 3: Train combined model
        # ------------------------------------------------------------------------------------------------------------------
        logger.info("Step 3: Training combined L2 + Kline model")
        
        trainer = ModelTrainer(
            model_dir="ml/models",
            purge_window=pd.Timedelta(minutes=10),
            embargo_pct=0.01,
        )

        # Prepare dataset with both L2-depth and kline features
        features, y, edge, fill_prob = trainer.prepare_dataset(
            l2_reader=l2_reader,
            kline_reader=kline_reader,
            start=start_time,
            end=end_time,
            horizon=10,  # minutes
        )

        if len(features) == 0:
            logger.error("Dataset preparation failed - no features generated")
            return

        # Train models
        dir_model, edge_model, metadata = trainer.train_model(
            features, y, edge, fill_prob, n_splits=5
        )

        if dir_model is None or edge_model is None:
            logger.error("Model training failed")
            return

        # Save models and metadata
        trainer.save_models(dir_model, edge_model, metadata)

        logger.info(
            "Training complete. Models saved with scores:\n"
            f"• Direction AUC: {metadata['best_dir_score']:.4f}\n"
            f"• Edge RMSE:    {metadata['best_edge_score']:.4f}"
        )

    except Exception as e:
        logger.error(f"Training pipeline failed: {e}")
        raise

if __name__ == "__main__":
    main() 
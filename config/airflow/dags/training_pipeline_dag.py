from datetime import datetime, timedelta
from pathlib import Path
import subprocess

from airflow import DAG
from airflow.operators.python import PythonOperator


PROJECT_ROOT = Path(__file__).resolve().parents[3]  # HL‑cli repo root


def run_training():
    """CLI task that triggers the Python training pipeline."""
    script = PROJECT_ROOT / "config" / "scripts" / "run_training.py"
    subprocess.run(["python", str(script)], check=True)


with DAG(
    dag_id="hl_model_training",
    description="Retrain HL‑cli model & RL agent daily",
    start_date=datetime(2025, 1, 1),
    schedule_interval="@daily",
    catchup=False,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=5)},
    tags=["hl-cli", "training"],
) as dag:
    train_task = PythonOperator(task_id="train_model", python_callable=run_training)
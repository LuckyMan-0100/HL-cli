from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta

with DAG(
    "volume_churn_retrain",
    description="Nightly retrain & deploy of volume-churn strategy",
    start_date=datetime(2025, 4, 1),
    schedule_interval="0 3 * * *",
    catchup=False,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=5)},
) as dag:
    collect = BashOperator(
        task_id="collect_data",
        bash_command="python -m scripts.collect_to_parquet",
    )
    retrain = BashOperator(
        task_id="retrain_model",
        bash_command="python -m scripts.retrain_model",
    )
    build = BashOperator(
        task_id="build_image",
        bash_command="docker build -t hl_cli:latest .",
    )
    restart = BashOperator(
        task_id="restart_container",
        bash_command="docker stop hl_cli || true && docker run -d --rm --env-file .env --name hl_cli hl_cli:latest",
    )
    collect >> retrain >> build >> restart
# High-Leverage Trading System

This project implements a high-frequency trading strategy targeting high notional turnover with tight risk controls, based on machine learning predictions and reinforcement learning fine-tuning.

## Architecture Overview

- **Data Ingestion**: Connects to Backpack Exchange WebSocket API for real-time order book and trade data, storing it in PostgreSQL and an in-memory cache.
- **Feature Engineering**: Computes various technical indicators (RSI, MACD, BB%, ATR) and order book features (imbalance, depth ratio, micro-price).
- **ML Model**: Uses a Gradient Boosting Classifier (sklearn/XGBoost/LightGBM) trained on historical data to predict profitable entry points.
- **RL Fine-tuning**: Employs Proximal Policy Optimization (PPO) via Stable-Baselines3 to optimize trading actions (flat, long, short) based on a custom reward function aiming to maximize volume while penalizing losses.
- **Execution**: Leverages the `backpack-cpp-sdk` via a C++ wrapper (bound to Python using pybind11) for low-latency (<20ms) market order execution.
- **Strategy Loop**: Runs periodically (e.g., every 3 minutes), fetches data, generates predictions, calculates position size based on model confidence (up to 100x leverage), executes trades, and places bracket (TP/SL) orders.
- **Risk Management**: Implements kill-switches (consecutive losses, drawdown) and a cumulative notional trading limit.
- **Orchestration**: Uses Airflow DAGs for nightly model retraining, weekly RL fine-tuning, and automated container deployment.

## Project Structure

```
hl_trading_system/
├── airflow/              # Airflow DAGs for orchestration
├── cpp_exec/             # C++ execution wrapper and Python bindings
├── data_ingestion/       # WebSocket client, DB writer, memory store
├── feature_engineering/  # Feature calculation and labelling
├── ml/                   # ML model training and prediction
├── rl/                   # RL environment and agent training
├── risk_management/      # Kill switch, notional limits, fee handling
├── strategy/             # Core strategy logic, order book, execution interface
├── config/               # Configuration management (API keys, params)
├── tests/                # Unit/integration tests (Placeholder)
├── scripts/              # Utility scripts (Placeholder)
├── .env.example          # Example environment variables
├── .gitignore
├── CMakeLists.txt        # Root CMake for C++ build (optional)
├── Dockerfile
├── README.md
└── requirements.txt
```

## Setup

1.  **Prerequisites**:
    *   Python 3.9+
    *   C++ Compiler (supporting C++17)
    *   CMake (3.15+)
    *   PostgreSQL Server
    *   `ta-lib` C library (`brew install ta-lib` or equivalent)
    *   Backpack Exchange API Key (ED25519 keypair)

2.  **Clone the repository**:
    ```bash
    git clone <repository-url>
    cd hl_trading_system
    ```

3.  **Set up C++ SDK**: Place or submodule the `backpack-cpp-sdk` into `cpp_exec/vendor/`.

4.  **Configure Environment**: Copy `.env.example` to `.env` and fill in your API keys, database credentials, etc.
    ```bash
    cp .env.example .env
    # Edit .env with your details
    ```

5.  **Install Python Dependencies**:
    ```bash
    python -m venv venv
    source venv/bin/activate # Or .env\Scripts\activate on Windows
    pip install -r requirements.txt
    ```

6.  **Build C++ Extension**:
    ```bash
    cd cpp_exec
    mkdir build
    cd build
    cmake .. -DCMAKE_BUILD_TYPE=Release # Add other necessary CMake flags
    make
    # Copy the built shared library (e.g., _cpp_exec*.so) to the project root or strategy/ directory
    # Adjust based on CMake output location
    cp src/_cpp_exec*.so ../../strategy/
    cd ../..
    ```

7.  **Database Setup**: Ensure PostgreSQL is running and create the necessary database and tables (schema definitions needed).

## Running

- **Data Ingestion**: Run the WebSocket client script.
  ```bash
  # (Assuming a runnable script exists)
  python -m data_ingestion.main_ws 
  ```
- **Strategy**: Run the main strategy loop.
  ```bash
  python -m strategy.main_loop
  ```
- **Training**: Run the training scripts manually or via Airflow.
  ```bash
  python -m ml.train_boosting
  python -m rl.train_ppo
  ```
- **Airflow**: Set up Airflow and add the DAGs from the `airflow/dags` directory.

## Disclaimer

Trading involves significant risk. The high leverage enabled by this system can lead to substantial losses, potentially exceeding your initial capital. Use extreme caution. This code is provided for educational purposes and demonstration of the architectural plan; it is **not production-ready** without extensive testing, validation, robust error handling, and adaptation to specific exchange rules and market dynamics. Ensure you fully understand the risks before deploying any trading system. 
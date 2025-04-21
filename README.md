# PPO Trading Agent Training

This repository contains a training script for a PPO (Proximal Policy Optimization) agent designed for trading in financial markets, along with components for data ingestion and order execution.

## Project Structure (Overview)

```
.
├── cpp_exec/                 # C++ Order Execution Bridge (L1 Consumer)
│   ├── exec_bridge.cpp
│   ├── exec_bridge.hpp
│   ├── redis_subscriber.cpp
│   ├── redis_subscriber.hpp
│   ├── tests/                  # C++ Unit/Integration Tests
│   │   └── exec_bridge_latency_test.cpp
│   └── CMakeLists.txt          # Build file for exec_bridge
├── data_ingestion/           # Data Collection & Processing
│   ├── backpack_data_service.cpp # Collects L1/L2 from Backpack WS
│   ├── pg_tail.py              # Tails Postgres for L2 data
│   └── tests/                  # Python Unit/Integration Tests
│       └── pg_tail_integration_test.py
├── feature_engineering/      # Feature Calculation (L2 Consumer)
│   └── calculator.py         # Reads L2 from pg_tail, calculates features
├── ml/                       # Machine Learning Models
├── rl/                       # Reinforcement Learning Components (Existing)
│   ├── train.py
│   ├── env.py
│   ├── agent.py
│   ├── memory.py
│   └── risk.py
├── config/                   # Configuration files
├── models/                   # Saved ML/RL models
├── logs/                     # Logs
├── .env.example              # Environment variable template
├── requirements.txt          # Python dependencies
└── README.md                 # This file
```

## System Dependencies

Ensure the following system libraries are installed before building C++ components:

*   **Core:** `cmake`, `gcc` (supporting C++20) or `clang`
*   **Networking & Crypto:** `openssl` (dev headers), `libcurl` (dev headers)
*   **Boost:** Libraries (`system`, `thread`) and headers (>= 1.71.0)
*   **PostgreSQL Client:** `libpq` (dev headers), `libpqxx` (dev headers)
*   **Redis Client:** `hiredis`, `hiredis-plus-plus` (from source or package manager)
*   **JSON:** `nlohmann-json` (header-only, often included via package manager)
*   **Testing (Optional):** `googletest` (dev headers/library)

**Example (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install build-essential cmake pkg-config libssl-dev libcurl4-openssl-dev \
                 libboost-system-dev libboost-thread-dev libpq-dev libpqxx-dev \
                 libhiredis-dev nlohmann-json3-dev libgoogle-test-dev
# Install hiredis-plus-plus (check their repo for latest instructions)
# Example: git clone https://github.com/sewenew/redis-plus-plus.git && cd redis-plus-plus && mkdir build && cd build && cmake .. && make && sudo make install
```

**Example (macOS with Homebrew):**
```bash
brew update
brew install cmake openssl curl boost libpq libpqxx hiredis nlohmann-json googletest redis-plus-plus
# Ensure CMake can find brewed packages (might need to set CMAKE_PREFIX_PATH)
export CMAKE_PREFIX_PATH="$(brew --prefix openssl);$(brew --prefix curl);$(brew --prefix boost);$(brew --prefix libpq);$(brew --prefix hiredis);$(brew --prefix nlohmann-json);$(brew --prefix redis-plus-plus)"
```

## Python Dependencies

Install Python requirements:
```bash
pip install -r requirements.txt
# Core requirements include:
# - pandas, numpy, psycopg2-binary, pyarrow, python-dotenv, pytest
# - cryptography (for ED25519 signing)
# - websockets (for WebSocket connections)
# - talib-binary (if used)
```

## Configuration

1.  Copy the environment variable template:
    ```bash
    cp .env.example .env
    ```
2.  Edit `.env` and fill in your credentials and settings:
    *   `REDIS_HOST`, `REDIS_PORT`
    *   `PG_HOST`, `PG_PORT`, `PG_DBNAME`, `PG_USER`, `PG_PASSWORD`
    *   `BACKPACK_API_KEY`, `BACKPACK_API_SECRET` (Base64-encoded ED25519 private key)
    *   `TRADING_SYMBOL` (e.g., `SOL_USDC_PERP`)

### WebSocket Authentication

The WebSocket client uses ED25519 signatures for authentication with Backpack Exchange:

1. The API secret should be a Base64-encoded ED25519 private key
2. Authentication flow:
   - Generate timestamp (milliseconds) and window (5000ms)
   - Create message string: `timestamp + window`
   - Sign message using ED25519 private key
   - Base64 encode the signature
   - Send authentication payload with API key, timestamp, window, and signature

Example authentication payload:
```json
{
    "op": "auth",
    "key": "your-api-key",
    "timestamp": 1698898000000,
    "window": 5000,
    "signature": "base64-encoded-ed25519-signature"
}
```

## Building C++ Components

1.  **Execution Bridge (`exec_bridge`):**
    ```bash
    cd cpp_exec
    mkdir -p build
    cd build
    cmake ..
    make -j$(nproc) # Adjust -j based on your CPU cores
    cd ../.. 
    # Executable will be at cpp_exec/build/exec_bridge
    ```
    *Note: If CMake fails to find dependencies (Boost, Redis++, etc.), you may need to provide hints via `CMAKE_PREFIX_PATH` or install them to standard locations.*

2.  **Data Service (`backpack_data_service`):**
    *This service is currently built using a direct g++ command (see comment in the source file).* 
    ```bash
    cd data_ingestion
    # Ensure dependencies listed in the source file comment are installed
    # Example build command (adjust paths/flags as needed for your system):
    g++ -std=c++20 -O2 backpack_data_service.cpp -o backpack_data_service \
           -lswresample -lavformat -lavcodec -lavutil -lcurl -lssl -lcrypto -lpqxx -lpq \
           -lboost_system -lpthread -lhiredis++ -lhiredis \
           -I/usr/local/include -I/opt/homebrew/include `# Add include paths` \
           -L/usr/local/lib -L/opt/homebrew/lib `# Add library paths`
    cd ..
    # Executable will be at data_ingestion/backpack_data_service
    ```

## Running the System

Ensure Redis and PostgreSQL are running and accessible with the credentials in `.env`.

1.  **Start Data Ingestion (L1 to Redis, L2 to Postgres):**
    ```bash
    # Terminal 1: Start the data service
    ./data_ingestion/backpack_data_service
    ```

2.  **Start Execution Bridge (Consumes L1 from Redis):**
    ```bash
    # Terminal 2: Start the execution bridge
    ./cpp_exec/build/exec_bridge 
    ```

3.  **Start Feature Engineering (Consumes L2 from Postgres):**
    ```bash
    # Terminal 3: Start the feature calculator
    python feature_engineering/calculator.py
    # Features will be appended to /tmp/features.parquet
    ```

## Running Tests

1.  **C++ Tests (exec_bridge latency):**
    *Requires `googletest`.*
    ```bash
    # Assuming you built in cpp_exec/build
    cd cpp_exec/build 
    # You might need to add the test target to CMakeLists.txt if not already done
    # Example CMake addition:
    # enable_testing()
    # find_package(GTest REQUIRED)
    # add_executable(exec_bridge_test tests/exec_bridge_latency_test.cpp)
    # target_link_libraries(exec_bridge_test PRIVATE GTest::gtest GTest::gtest_main exec_bridge)
    # add_test(NAME ExecBridgeLatencyTest COMMAND exec_bridge_test)
    
    # After adding test target and rebuilding:
    ctest --verbose
    # Or run directly:
    # ./exec_bridge_test 
    cd ../..
    ```

2.  **Python Tests (pg_tail integration):**
    *Requires `pytest` and a running/configured PostgreSQL.*
    ```bash
    # Ensure .env is configured for the test database
    pytest data_ingestion/tests/pg_tail_integration_test.py -v -s
    ```

## Existing RL Training

The training script (`rl/train.py`) provides a comprehensive implementation for training a PPO agent. Key features include:

- Generalized Advantage Estimation (GAE)
- Rollout buffer for trajectory storage
- Periodic evaluation and model checkpointing
- Training metrics logging

### Example Usage

```python
from rl.train import train
from rl.env import TradingEnvironment
from rl.agent import PPOAgent
from rl.memory import MemoryStore
from rl.risk import RiskManager

# Initialize components
memory_store = MemoryStore()
risk_manager = RiskManager()
env = TradingEnvironment(memory_store, risk_manager)
agent = PPOAgent(env)

# Start training
train(
    env=env,
    agent=agent,
    total_timesteps=1_000_000,
    n_steps=2048,
    eval_freq=10000,
    n_eval_episodes=5,
    save_freq=10000,
    save_path="models",
    log_path="logs"
)
```

### Training Parameters

- `total_timesteps`: Total number of environment steps for training
- `n_steps`: Number of steps to run for each environment per update
- `eval_freq`: Frequency of evaluation during training
- `n_eval_episodes`: Number of episodes to run during evaluation
- `save_freq`: Frequency of model checkpointing
- `save_path`: Directory to save model checkpoints
- `log_path`: Directory to save training logs

## Monitoring Training

Training progress can be monitored through the logs directory, which contains:
- Training metrics (rewards, losses)
- Evaluation results
- Model checkpoints

## Contributing

Feel free to submit issues and enhancement requests! 
# High-Frequency ML Trading System

A low-latency machine learning system for cryptocurrency trading, optimized for high-frequency market making and statistical arbitrage.

## Features



### ML Model
- LightGBM-based triclass classifier (long/short/neutral)
- Feature set:
  - Time-of-day seasonality (strongest signal)
  - Volatility metrics (ATR, Bollinger Bands)
  - Price momentum (MACD variants)
  - Order book microstructure
- Performance:
  - ~56% validation accuracy
  - Expected PnL: 17.83bps per long trade, 5.54bps per short trade
  - Sub-millisecond inference time

### Risk Management
- Dynamic position sizing based on volatility
- Automated stop-loss and take-profit
- Maximum drawdown controls
- Fee-aware trade filtering

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/HL-cli.git
cd HL-cli
```

2. Create and activate a virtual environment:
```bash

source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up TimescaleDB:
```bash
# Setup DB
brew serve postgres14


psql -d trading_data -
```

5. Configure environment variables:
```bash
cp .env.example .env
# Edit .env with your Backpack API keys and database settings
```

## Usage

### Data Collection
```bash
# Start market data collection
python data_ingestion/collector.py

# Verify data ingestion
psql -d trading_data -c "SELECT COUNT(*) FROM orderbook_snapshots;"
```

### Model Training
```bash
# Train the model
python ml/train_boosting.py

Key parameters:
Training window: 30 days
Sampling interval: 1 minute
Prediction horizon: 5-20 bars
Min return threshold: 5-20bps
```

### Live Trading
```bash
# Start the trading system
python trading/main.py

# Monitor performance
python monitoring/dashboard.py
```

## Project Structure

```

```

## Performance Metrics

### Model Performance
- Feature importance ranking
- Walk-forward validation results
- PnL attribution by signal type

### System Performance
- Average round-trip latency: <5ms
- Order book update rate: >100/sec
- Model inference time: <1ms

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- LightGBM team for the efficient gradient boosting implementation
- TimescaleDB for high-performance time-series storage
- Backpack Exchange for the trading API

# Paper Trading Test Runner

A robust paper trading system with comprehensive monitoring and risk management capabilities.

## Features

- Real-time paper trading simulation
- Prometheus metrics monitoring (port 8000)
- Comprehensive risk management controls
- Feature drift monitoring
- Performance tracking and reporting
- Graceful shutdown handling

## Prerequisites

- Python 3.8+
- Required packages (install via pip):
  ```bash
  pip install -r requirements.txt
  ```

## Usage

### Basic Run
```bash
./scripts/run_paper_trading.py
```
This will run the paper trading test for the default duration of 7 days.

### Custom Duration
```bash
./scripts/run_paper_trading.py --days 14
```
Specify custom duration in days.

## Risk Management Parameters

The system enforces the following risk limits:
- Max Position Notional: $1,000
- Max Daily Loss: $10
- Max Drawdown: 2%
- Max Leverage: 3x

## Output and Monitoring

### Logs
- Real-time logs are written to `paper_trading.log`
- Structured logging with timestamp, component, and level information

### Results Directory
The system creates a `paper_trading_results` directory containing:
- Performance metrics (JSON format)
- Feature drift reports
- Timestamped files for each run

### Metrics
- Prometheus metrics available on port 8000
- Real-time monitoring of:
  - Trading performance
  - Risk metrics
  - System health

## Shutdown

The system handles graceful shutdown on:
- SIGINT (Ctrl+C)
- SIGTERM

During shutdown:
- Final metrics are saved
- Results are exported
- Resources are properly cleaned up

## Development

### Code Style
- Black formatting
- Flake8 linting
- MyPy type checking
- Isort import sorting

### Testing
```bash
pytest tests/
```

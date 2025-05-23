import pandas as pd
import numpy as np
from typing import Dict, Any

def calculate_technical_indicators(df):
    """
    Calculate technical indicators and features
    """
    # Ensure numeric columns
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    df[numeric_cols] = df[numeric_cols].fillna(method='ffill')
    
    # Momentum Indicators
    df['rsi'] = calculate_rsi(df['close'])
    df['macd'], df['macd_signal'] = calculate_macd(df['close'])
    
    # Volume-based features
    eps = 1e-10  # Small constant to prevent division by zero
    df['volume_price_ratio'] = np.where(
        df['close'] > eps,
        df['volume'] / (df['close'] + eps),
        0
    )
    
    # Volatility indicators
    df['atr'] = calculate_atr(df)
    df['bollinger_upper'], df['bollinger_lower'] = calculate_bollinger_bands(df['close'])
    
    # Price-based features
    df['price_momentum'] = df['close'].pct_change(periods=5).fillna(0)
    df['high_low_ratio'] = np.where(
        df['low'] > eps,
        df['high'] / (df['low'] + eps),
        1
    )
    
    # Clean up any remaining NaN values
    df = df.fillna(method='ffill').fillna(0)
    
    return df

def calculate_rsi(prices, periods=14):
    """
    Calculate Relative Strength Index
    """
    deltas = np.diff(prices)
    deltas = np.append(deltas[0], deltas)  # Add first value to match length
    
    # Separate gains and losses
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    # Calculate average gains and losses
    avg_gains = pd.Series(gains).ewm(alpha=1/periods).mean()
    avg_losses = pd.Series(losses).ewm(alpha=1/periods).mean()
    
    # Calculate RS and RSI
    eps = 1e-10  # Small constant to prevent division by zero
    rs = np.where(
        avg_losses > eps,
        avg_gains / (avg_losses + eps),
        100
    )
    rsi = 100 - (100 / (1 + rs))
    
    return pd.Series(rsi).fillna(50)  # Fill NaN with neutral value

def calculate_macd(prices, fast=12, slow=26, signal=9):
    """
    Calculate MACD and Signal line
    """
    exp1 = prices.ewm(span=fast, adjust=False).mean()
    exp2 = prices.ewm(span=slow, adjust=False).mean()
    macd = exp1 - exp2
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    
    return macd.fillna(0), signal_line.fillna(0)

def calculate_atr(df, period=14):
    """
    Calculate Average True Range
    """
    high = df['high']
    low = df['low']
    close = df['close']
    
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    
    tr = pd.DataFrame([tr1, tr2, tr3]).max()
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    
    return atr.fillna(0)

def calculate_bollinger_bands(prices, period=20, std_dev=2):
    """
    Calculate Bollinger Bands
    """
    sma = prices.rolling(window=period).mean()
    std = prices.rolling(window=period).std()
    
    upper_band = sma + (std * std_dev)
    lower_band = sma - (std * std_dev)
    
    return upper_band.fillna(method='ffill'), lower_band.fillna(method='ffill') 
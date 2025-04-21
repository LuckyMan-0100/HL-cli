#pragma once

#include <deque>
#include <vector>
#include <cmath>
#include <numeric>
#include <algorithm>
#include <mutex>
#include <map>
#include <unordered_map>

namespace bp {

// OHLCV bar for 1-second data
struct OHLCVBar {
    double open;
    double high;
    double low;
    double close;
    double volume;
    int64_t timestamp;
    bool is_complete;  // true if this is an exchange-provided kline

    // Constructor for trade-based bars
    OHLCVBar(double price, double vol, int64_t ts)
        : open(price), high(price), low(price), close(price), 
          volume(vol), timestamp(ts), is_complete(false) {}

    // Constructor for exchange-provided klines
    OHLCVBar(double o, double h, double l, double c, double v, int64_t ts)
        : open(o), high(h), low(l), close(c), 
          volume(v), timestamp(ts), is_complete(true) {}

    void update_from_trade(double price, double vol) {
        if (is_complete) return;  // Don't update exchange-provided bars
        if (open == 0) open = price;  // Set open price if this is first trade
        high = std::max(high, price);
        low = std::min(low, price);
        close = price;
        volume += vol;
    }
};

// Thread-safe OHLCV buffer supporting multiple timeframes
class OHLCVBuffer {
public:
    struct Candle {
        double open;
        double high;
        double low;
        double close;
        double volume;
        int64_t timestamp;
    };

    void update_from_trade(const std::string& symbol, double price, double quantity, int64_t timestamp_ms);
    void update_from_kline(const std::string& symbol, const std::string& interval,
                          double open, double high, double low, double close,
                          double volume, int64_t timestamp_ms);
    std::vector<double> get_close_prices(const std::string& symbol, const std::string& interval) const;

private:
    std::unordered_map<std::string, std::map<std::string, std::deque<Candle>>> data_; // symbol -> interval -> candles
    static constexpr size_t MAX_CANDLES = 1000;
};

// EMA implementation (must be defined before MACD)
class EMA {
public:
    explicit EMA(size_t period) : period_(period) {}
    
    double calculate(const std::vector<double>& prices) const {
        if (prices.empty()) return std::numeric_limits<double>::quiet_NaN();
        if (prices.size() < period_) return prices.back();
        
        double multiplier = 2.0 / (period_ + 1);
        double ema = prices[0];
        
        for (size_t i = 1; i < prices.size(); ++i) {
            ema = (prices[i] - ema) * multiplier + ema;
        }
        
        return ema;
    }

private:
    size_t period_;
};

class RSI {
public:
    explicit RSI(size_t period = 14) : period_(period) {}
    
    double calculate(const std::vector<double>& prices) const {
        if (prices.size() < period_ + 1) return std::numeric_limits<double>::quiet_NaN();
        
        double avg_gain = 0;
        double avg_loss = 0;
        
        // First RSI calculation
        for (size_t i = 1; i <= period_; ++i) {
            double change = prices[i] - prices[i-1];
            if (change > 0) avg_gain += change;
            else avg_loss -= change;
        }
        
        avg_gain /= period_;
        avg_loss /= period_;
        
        // Subsequent calculations
        for (size_t i = period_ + 1; i < prices.size(); ++i) {
            double change = prices[i] - prices[i-1];
            if (change > 0) {
                avg_gain = (avg_gain * (period_ - 1) + change) / period_;
                avg_loss = (avg_loss * (period_ - 1)) / period_;
            } else {
                avg_gain = (avg_gain * (period_ - 1)) / period_;
                avg_loss = (avg_loss * (period_ - 1) - change) / period_;
            }
        }
        
        if (avg_loss == 0) return 100;
        double rs = avg_gain / avg_loss;
        return 100 - (100 / (1 + rs));
    }

private:
    size_t period_;
};

class MACD {
public:
    MACD(size_t fast_period = 12, size_t slow_period = 26, size_t signal_period = 9)
        : fast_period_(fast_period), slow_period_(slow_period) {}
    
    double calculate(const std::vector<double>& prices) const {
        if (prices.size() < slow_period_) return std::numeric_limits<double>::quiet_NaN();
        
        EMA fast_ema(fast_period_);
        EMA slow_ema(slow_period_);
        
        double fast_line = fast_ema.calculate(prices);
        double slow_line = slow_ema.calculate(prices);
        
        return fast_line - slow_line;
    }

private:
    size_t fast_period_;
    size_t slow_period_;
};

} // namespace bp 
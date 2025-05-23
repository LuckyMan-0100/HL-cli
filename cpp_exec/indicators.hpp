#pragma once

#include <deque>
#include <vector>
#include <cmath>
#include <numeric>
#include <algorithm>
#include <mutex>
#include <map>
#include <unordered_map>
#include <string>

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
    struct OHLCV {
        double open;
        double high;
        double low;
        double close;
        double volume;
        uint64_t timestamp;
    };

    void update_from_trade(const std::string& symbol, double price, double quantity, uint64_t timestamp) {
        auto& candle = get_or_create_candle(symbol, timestamp);
        
        if (candle.open == 0.0) candle.open = price;
        candle.high = std::max(candle.high, price);
        candle.low = candle.low == 0.0 ? price : std::min(candle.low, price);
        candle.close = price;
        candle.volume += quantity;
    }
    
    void update_from_kline(const std::string& symbol, const std::string& interval,
                          double open, double high, double low, double close,
                          double volume, uint64_t timestamp) {
        auto key = make_key(symbol, interval);
        auto& buffer = buffers_[key];
        
        OHLCV candle{open, high, low, close, volume, timestamp};
        
        if (buffer.empty() || buffer.back().timestamp < timestamp) {
            buffer.push_back(candle);
            if (buffer.size() > max_buffer_size_) {
                buffer.pop_front();
            }
        }
    }
    
    std::vector<double> get_close_prices(const std::string& symbol, const std::string& interval) const {
        auto key = make_key(symbol, interval);
        auto it = buffers_.find(key);
        if (it == buffers_.end()) return std::vector<double>();
        
        std::vector<double> prices;
        prices.reserve(it->second.size());
        for (const auto& candle : it->second) {
            prices.push_back(candle.close);
        }
        return prices;
    }
    
private:
    static std::string make_key(const std::string& symbol, const std::string& interval) {
        return symbol + "_" + interval;
    }
    
    OHLCV& get_or_create_candle(const std::string& symbol, uint64_t timestamp) {
        auto key = make_key(symbol, "1m");
        auto& buffer = buffers_[key];
        
        if (buffer.empty() || buffer.back().timestamp < timestamp) {
            if (buffer.size() >= max_buffer_size_) {
                buffer.pop_front();
            }
            buffer.push_back(OHLCV{});
            buffer.back().timestamp = timestamp;
        }
        
        return buffer.back();
    }
    
    std::map<std::string, std::deque<OHLCV>> buffers_;
    static constexpr size_t max_buffer_size_ = 1000;
};

// EMA implementation (must be defined before MACD)
class EMA {
public:
    explicit EMA(size_t period = 200) : period_(period) {}
    
    double calculate(const std::vector<double>& prices) const {
        if (prices.size() < period_) return std::nan("");
        
        double multiplier = 2.0 / (period_ + 1.0);
        double ema = std::accumulate(prices.begin(), prices.begin() + period_, 0.0) / period_;
        
        for (size_t i = period_; i < prices.size(); ++i) {
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
        if (prices.size() < period_ + 1) return std::nan("");
        
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
        
        // Calculate subsequent values
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
        
        if (avg_loss == 0.0) return 100.0;
        double rs = avg_gain / avg_loss;
        return 100.0 - (100.0 / (1.0 + rs));
    }

private:
    size_t period_;
};

class MACD {
public:
    MACD(size_t fast_period = 12, size_t slow_period = 26, size_t signal_period = 9)
        : fast_period_(fast_period)
        , slow_period_(slow_period)
        , signal_period_(signal_period) {}
    
    double calculate(const std::vector<double>& prices) const {
        if (prices.size() < slow_period_) return std::nan("");
        
        std::vector<double> fast_ema = calculateEMA(prices, fast_period_);
        std::vector<double> slow_ema = calculateEMA(prices, slow_period_);
        
        // Calculate MACD line
        std::vector<double> macd_line;
        for (size_t i = 0; i < fast_ema.size(); ++i) {
            macd_line.push_back(fast_ema[i] - slow_ema[i]);
        }
        
        // Calculate signal line
        std::vector<double> signal_line = calculateEMA(macd_line, signal_period_);
        
        // Return latest MACD histogram value
        if (signal_line.empty()) return std::nan("");
        return macd_line.back() - signal_line.back();
    }
    
private:
    std::vector<double> calculateEMA(const std::vector<double>& prices, size_t period) const {
        if (prices.size() < period) return std::vector<double>();
        
        std::vector<double> ema(prices.size());
        double multiplier = 2.0 / (period + 1.0);
        
        // Initialize EMA with SMA
        double sum = 0;
        for (size_t i = 0; i < period; ++i) {
            sum += prices[i];
        }
        ema[period-1] = sum / period;
        
        // Calculate EMA
        for (size_t i = period; i < prices.size(); ++i) {
            ema[i] = (prices[i] - ema[i-1]) * multiplier + ema[i-1];
        }
        
        return ema;
    }
    
    size_t fast_period_;
    size_t slow_period_;
    size_t signal_period_;
};

} // namespace bp 
#include "indicators.hpp"
#include <algorithm>

namespace bp {

void OHLCVBuffer::update_from_trade(const std::string& symbol, double price, double quantity, int64_t timestamp_ms) {
    auto& candles = data_[symbol]["1m"]; // Use 1-minute candles for trades
    int64_t candle_ts = (timestamp_ms / 60000) * 60000; // Round to minute

    if (candles.empty() || candles.back().timestamp < candle_ts) {
        // Create new candle
        if (candles.size() >= MAX_CANDLES) {
            candles.pop_front();
        }
        candles.push_back({price, price, price, price, quantity, candle_ts});
    } else {
        // Update existing candle
        auto& candle = candles.back();
        candle.high = std::max(candle.high, price);
        candle.low = std::min(candle.low, price);
        candle.close = price;
        candle.volume += quantity;
    }
}

void OHLCVBuffer::update_from_kline(const std::string& symbol, const std::string& interval,
                                  double open, double high, double low, double close,
                                  double volume, int64_t timestamp_ms) {
    auto& candles = data_[symbol][interval];
    
    // Find or create candle
    auto it = std::find_if(candles.begin(), candles.end(),
                          [timestamp_ms](const Candle& c) { return c.timestamp == timestamp_ms; });
    
    if (it != candles.end()) {
        // Update existing candle
        *it = {open, high, low, close, volume, timestamp_ms};
    } else {
        // Add new candle
        if (candles.size() >= MAX_CANDLES) {
            candles.pop_front();
        }
        candles.push_back({open, high, low, close, volume, timestamp_ms});
    }
}

std::vector<double> OHLCVBuffer::get_close_prices(const std::string& symbol, const std::string& interval) const {
    std::vector<double> prices;
    
    auto symbol_it = data_.find(symbol);
    if (symbol_it == data_.end()) return prices;
    
    auto interval_it = symbol_it->second.find(interval);
    if (interval_it == symbol_it->second.end()) return prices;
    
    const auto& candles = interval_it->second;
    prices.reserve(candles.size());
    
    for (const auto& candle : candles) {
        prices.push_back(candle.close);
    }
    
    return prices;
}

} // namespace bp 
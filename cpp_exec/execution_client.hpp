#pragma once

#include <string>
#include <cstdint>

namespace bp {

class ExecutionClient {
public:
    virtual ~ExecutionClient() = default;

    // Book ticker updates
    virtual void onTick(const std::string& symbol, double bid_price, double ask_price, 
                       double bid_qty, double ask_qty, uint64_t timestamp) = 0;

    // Trade updates
    virtual void onTrade(const std::string& symbol, double price, double quantity, 
                        uint64_t timestamp) = 0;

    // Kline/candlestick updates
    virtual void onKline(const std::string& symbol, const std::string& interval,
                        double open, double high, double low, double close,
                        double volume, uint64_t timestamp) = 0;
};

} // namespace bp 
#include "execution_client.hpp"
#include <spdlog/spdlog.h>

namespace bp {

class DefaultExecutionClient : public ExecutionClient {
public:
    void onTick(const std::string& symbol, double bid_price, double ask_price, 
                double bid_qty, double ask_qty, uint64_t timestamp) override {
        spdlog::info("Book Ticker - Symbol: {}, Bid: {} ({}), Ask: {} ({}), Timestamp: {}", 
                     symbol, bid_price, bid_qty, ask_price, ask_qty, timestamp);
    }

    void onTrade(const std::string& symbol, double price, double quantity, 
                 uint64_t timestamp) override {
        spdlog::info("Trade - Symbol: {}, Price: {}, Quantity: {}, Timestamp: {}", 
                     symbol, price, quantity, timestamp);
    }

    void onKline(const std::string& symbol, const std::string& interval,
                 double open, double high, double low, double close,
                 double volume, uint64_t timestamp) override {
        spdlog::info("Kline - Symbol: {}, Interval: {}, OHLC: [{}, {}, {}, {}], Volume: {}, Timestamp: {}", 
                     symbol, interval, open, high, low, close, volume, timestamp);
    }
};

} // namespace bp 
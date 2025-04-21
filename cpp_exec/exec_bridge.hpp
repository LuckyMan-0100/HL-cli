#pragma once

#include <string>
#include <memory>
#include <atomic>
#include <mutex>
#include <limits>
#include <nlohmann/json.hpp>
#include <sw/redis++/redis++.h>
#include <boost/asio.hpp>
#include <boost/beast.hpp>
#include <boost/beast/websocket.hpp>
#include <spdlog/spdlog.h>
#include <backpack/backpack_client.hpp>
#include "indicators.hpp"
#include "risk_manager.hpp"
#include "execution_client.hpp"

namespace bp {

using backpack::OrderRequest;
using backpack::OrderSide;
using backpack::OrderType;
using backpack::TimeInForce;
using backpack::BackpackClient;

// Forward declarations
class RiskManager;

// Self-trade prevention strategies
enum class SelfTradePrevention {
    NONE,
    REJECT_TAKER,
    REJECT_MAKER,
    REJECT_BOTH
};

// Extended order request with strategy flags
struct OrderFlags {
    bool post_only = false;      // Maker-only, reject if would cross book
    bool reduce_only = false;    // Only shrink existing position (futures only)
    bool auto_borrow = false;    // Auto-borrow if insufficient balance (spot only)
    SelfTradePrevention self_trade_prevention = SelfTradePrevention::NONE;
};

// Ensure NO definition of ExecutionClient exists here.
// The definition should only be in execution_client.hpp

class DefaultExecutionClient : public ExecutionClient { // Inherit from base class
public:
    DefaultExecutionClient(const std::string& api_key, 
                         const std::string& base64_private_key,
                         const std::string& symbol,
                         double max_daily_drawdown_pct = 0.02);
    
    ~DefaultExecutionClient() override;

    // Market data accessors implementation (NOT overriding base class)
    double bestBid() const;
    double bestAsk() const;
    double mid() const;

    // Market data handlers implementation (These DO override base class)
    void onTick(const std::string& symbol, double bid, double ask, double bid_qty, double ask_qty, uint64_t timestamp) override;
    void onTrade(const std::string& symbol, double price, double quantity, uint64_t timestamp) override;
    void onKline(const std::string& symbol, const std::string& interval,
                 double open, double high, double low, double close,
                 double volume, uint64_t timestamp) override;

    // Order execution methods
    void send_market(const std::string& symbol, double quantity, bool is_buy, 
                    const OrderFlags& flags = OrderFlags());
    void send_limit(const std::string& symbol, double quantity, double price, bool is_buy, 
                   TimeInForce tif = TimeInForce::GTC, const OrderFlags& flags = OrderFlags());
    void send_order(const OrderRequest& order, const OrderFlags& flags = OrderFlags());
    bool cancel_order(const std::string& symbol, const std::string& order_id);
    int cancel_all_orders(const std::string& symbol = "");

    // Technical indicators
    double getRSI(const std::string& interval = "1m") const;
    double getMACD(const std::string& interval = "1m") const;
    double getEMA200(const std::string& interval = "1m") const;
    bool checkTechnicalFilters(bool is_buy, const std::string& interval = "1m") const;

    // Position sizing
    double getConfidenceWeightedSize(double base_size, double confidence) const;
    double sigmoid(double x) const;

    // Risk management
    bool checkRiskLimits() const;
    void sleepOnDrawdown(std::chrono::seconds duration);
    double getDailyPnL() const;
    double getCurrentDrawdown() const;

private:
    // Utility methods
    static std::string order_side_to_string(OrderSide side);
    static std::string order_type_to_string(OrderType type);
    static std::string self_trade_prevention_to_string(SelfTradePrevention stp);
    void add_strategy_flags(nlohmann::json& params, const OrderFlags& flags) const;
    std::string build_signing_string(const std::string& instruction, const nlohmann::json& params) const;
    std::string sign_request(const std::string& signing_string) const;
    nlohmann::json execute_signed_request(const std::string& endpoint,
                                        const std::string& instruction,
                                        const nlohmann::json& params) const;

    // Member variables
    std::string trading_symbol_;
    std::string api_key_;
    std::string base64_private_key_;
    std::string api_secret_;
    
    std::unique_ptr<BackpackClient> client_;
    std::unique_ptr<sw::redis::Redis> redis_client_;
    std::unique_ptr<RiskManager> risk_manager_;
    
    std::atomic<double> best_bid_{0.0};
    std::atomic<double> best_ask_{0.0};
    
    boost::asio::io_context ioc_;
    std::unique_ptr<boost::beast::websocket::stream<boost::beast::tcp_stream>> ws_;
    std::thread io_thread_;
    std::atomic<bool> running_{false};

    // Technical indicators
    OHLCVBuffer ohlcv_buffer_;
    RSI rsi_{14};
    MACD macd_{12, 26, 9};
    EMA ema200_{200};

    // Constants
    static constexpr int64_t DEFAULT_WINDOW = 5000;
    static constexpr const char* BASE_URL = "https://api.backpack.exchange";
    static constexpr double CONFIDENCE_SCALE = 5.0;
};

} // namespace bp 
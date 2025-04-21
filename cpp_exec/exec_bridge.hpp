#ifndef CPP_EXEC_EXEC_BRIDGE_HPP
#define CPP_EXEC_EXEC_BRIDGE_HPP

#include <string>
#include <memory>
#include <atomic>
#include <mutex>
#include <limits>

#include <backpack/backpack_client.hpp> // Include necessary SDK headers

namespace bp {

    // Forward declare if needed, or include necessary types
    using backpack::OrderRequest;

    using backpack::OrderSide;
    using backpack::OrderType;
    using backpack::TimeInForce;
    using backpack::BackpackClient;

    class ExecutionClient {
    public:
        ExecutionClient();
        ~ExecutionClient() = default;

        // Disable copy/move semantics for simplicity with unique_ptr and atomics
        ExecutionClient(const ExecutionClient&) = delete;
        ExecutionClient& operator=(const ExecutionClient&) = delete;
        ExecutionClient(ExecutionClient&&) = delete;
        ExecutionClient& operator=(ExecutionClient&&) = delete;

        double bestBid() const;
        double bestAsk() const;
        double mid() const;
        void onTick(double received_bid, double received_ask, int64_t timestamp_ms);

        void send_market(const std::string& symbol, double quantity, bool is_buy);
        void send_limit(const std::string& symbol, double quantity, double price, bool is_buy, TimeInForce tif = TimeInForce::GTC);
...
    void send_order(const OrderRequest& order);
    private:
    OrderResponse send_order(const OrderRequest& order);

    // ──────────────── indicator helpers ────────────────
    void update_indicators(double price);
    bool long_signal()  const;
    bool short_signal() const;

        std::unique_ptr<BackpackClient> client_;
        std::string trading_symbol_;
    
        // user‑configurable sizing
        double leverage_{1.0};          // e.g. 50 = 50 ×
        double base_order_qty_{0.1};    // contract / coin units before leverage
    
    // L1 Cache
    std::atomic<double> best_bid_;
    std::atomic<double> best_ask_;

    // ──────────────── indicator state ────────────────
    std::deque<double> prices_;
    double ema12_{std::numeric_limits<double>::quiet_NaN()};
    double ema26_{std::numeric_limits<double>::quiet_NaN()};
    double ema200_{std::numeric_limits<double>::quiet_NaN()};
    double macd_line_{std::numeric_limits<double>::quiet_NaN()};
    double signal_{std::numeric_limits<double>::quiet_NaN()};
    double avg_gain_{std::numeric_limits<double>::quiet_NaN()};
    double avg_loss_{std::numeric_limits<double>::quiet_NaN()};
    double rsi_{std::numeric_limits<double>::quiet_NaN()};
    };

} // namespace bp

#endif // CPP_EXEC_EXEC_BRIDGE_HPP 
#pragma once

#include <string>
#include <memory>
#include <atomic>
#include <mutex>
#include <limits>
#include <nlohmann/json.hpp>
#include <sw/redis++/redis++.h>
#include <spdlog/spdlog.h>
#include <backpack/backpack_client.hpp>
#include "indicators.hpp"
#include <functional>
#include <optional>
#include <vector>
#include <thread>
#include <map>
#include <cstdint>  // For RestClass underlying type
#include <unordered_map>
#include <unordered_set>
#include <chrono>
#include <csignal>
#include <iostream>
#include <fstream>
#include <sstream>
#include <iomanip>
#include <algorithm> // For std::remove_if
#include "risk_manager.hpp"

namespace bp {

using backpack::OrderRequest;
using backpack::OrderSide;
using backpack::OrderType;
using backpack::TimeInForce;
using backpack::BackpackClient;
using backpack::Order;
using json = nlohmann::json;

// Rate-limit class categories
enum class RestClass : uint8_t { TRADE, ORDER_QUERY, META };

// Forward declarations
class RiskManager;
struct BBO;

// L1 data structure for book tickers
struct BookTicker {
    std::string symbol;
    double bid_price;
    double ask_price;
    double bid_qty;
    double ask_qty;
    uint64_t timestamp;
    uint64_t update_id;

    BookTicker() : bid_price(0), ask_price(0), bid_qty(0), ask_qty(0), timestamp(0), update_id(0) {}
    
    BookTicker(const std::string& s, double bp, double ap, double bq, double aq, uint64_t ts, uint64_t uid = 0)
        : symbol(s), bid_price(bp), ask_price(ap), bid_qty(bq), ask_qty(aq), timestamp(ts), update_id(uid) {}
};

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

// L1 data callback type
using L1Callback = std::function<void(const BookTicker&)>;

// Structure for ML signal payload from file
struct MlSignalPayload {
    long long timestamp_ms = 0;
    int signal_action = 0; // -1 (short), 0 (flat), 1 (long)
    std::string model_id;
    int max_hold_bars_config = 0;
    double stop_loss_pct_config = 0.0; // e.g., 0.3 for 0.3%
    double order_quantity_config = 0.0;
    // Optional: Add other fields from JSON if needed, e.g., target_prediction_value

    // Basic validation
    bool isValid() const {
        return timestamp_ms > 0 && 
               (signal_action >= -1 && signal_action <= 1) &&
               !model_id.empty() &&
               max_hold_bars_config >= 0 && // 0 might mean no time stop if desired
               stop_loss_pct_config > 0.0 && // SL must be positive
               order_quantity_config > 0.0; // Quantity must be positive
    }
};

// Structure for conditional order parameters
struct ConditionalOrderParams {
    std::optional<double> stop_loss_trigger_price;
    std::optional<double> stop_loss_limit_price;
    std::optional<double> take_profit_trigger_price; // For future use
    std::optional<double> take_profit_limit_price; // For future use
    // Add other conditional fields like stopLossLimitPrice, takeProfitLimitPrice if needed
};

// Ladder level definition for entry orders
struct LadderLevel {
    double trigger_price; // Price at which to trigger this level
    double size;          // Quantity for this level
    bool reduce_only = false; // If true, this order will be reduce-only after fill
};

class ExecutionClient {
public:
    virtual ~ExecutionClient() = default;
    virtual double bestBid() const = 0;
    virtual double bestAsk() const = 0;
    virtual double mid() const = 0;
    virtual void onTick(const std::string& symbol, double bid, double ask, 
                       double bidQty, double askQty, uint64_t timestamp) = 0;
    virtual void onTrade(const std::string& symbol, double price, double quantity, uint64_t timestamp) = 0;
    virtual void onKline(const std::string& symbol, const std::string& interval,
                        double open, double high, double low, double close,
                        double volume, uint64_t timestamp) = 0;
    virtual void registerL1Callback(L1Callback callback) = 0;
};

enum class SignalDirection {
    NEUTRAL,
    LONG,
    SHORT
};

// Added Side enum for RestingOrder
enum class RestingOrderSide {
    BID,
    ASK
};

// Added RestingOrder struct
struct RestingOrder {
    std::string  orderId;
    std::string  symbol;
    RestingOrderSide side;
    double       price;
    double       qty; // Represents current open quantity
    std::chrono::steady_clock::time_point placedAt;
    std::string  clientId; // model_id, if available/needed
};

// Structured trade event types for ML logging
enum class TradeEventType {
    SIGNAL_RECEIVED,
    ENTRY_ORDER_SENT,
    ORDER_NEW,                      // Added to log new orders
    ENTRY_ORDER_FILLED,
    ENTRY_ORDER_PARTIALLY_FILLED,
    STOP_ORDER_SENT,
    POSITION_CLOSED_STOP_LOSS,
    POSITION_CLOSED_TAKE_PROFIT,
    POSITION_CLOSED_MAX_HOLD,
    POSITION_CLOSED_MANUAL,
    ORDER_CANCELLED,
    ORDER_REJECTED,                 // Added to log rejected orders
    OTHER
};

inline std::string trade_event_type_to_string(TradeEventType type) {
    switch (type) {
        case TradeEventType::SIGNAL_RECEIVED: return "SIGNAL_RECEIVED";
        case TradeEventType::ENTRY_ORDER_SENT: return "ENTRY_ORDER_SENT";
        case TradeEventType::ORDER_NEW: return "ORDER_NEW";             // Added mapping
        case TradeEventType::ENTRY_ORDER_FILLED: return "ENTRY_ORDER_FILLED";
        case TradeEventType::ENTRY_ORDER_PARTIALLY_FILLED: return "ENTRY_ORDER_PARTIALLY_FILLED";
        case TradeEventType::STOP_ORDER_SENT: return "STOP_ORDER_SENT";
        case TradeEventType::POSITION_CLOSED_STOP_LOSS: return "POSITION_CLOSED_STOP_LOSS";
        case TradeEventType::POSITION_CLOSED_TAKE_PROFIT: return "POSITION_CLOSED_TAKE_PROFIT";
        case TradeEventType::POSITION_CLOSED_MAX_HOLD: return "POSITION_CLOSED_MAX_HOLD";
        case TradeEventType::POSITION_CLOSED_MANUAL: return "POSITION_CLOSED_MANUAL";
        case TradeEventType::ORDER_CANCELLED: return "ORDER_CANCELLED";
        case TradeEventType::ORDER_REJECTED: return "ORDER_REJECTED";   // Added mapping
        default: return "OTHER";
    }
}

struct TradeEventData {
    std::string trade_id;
    std::string event_id;
    uint64_t event_timestamp;
    TradeEventType event_type;

    std::string model_id;
    std::string trading_symbol;
    std::optional<std::string> order_id;
    std::optional<std::string> client_order_id;

    std::optional<double> price;
    std::optional<double> quantity;
    std::optional<double> filled_quantity;
    std::optional<std::string> side;

    std::optional<double> market_bid_at_event;
    std::optional<double> market_ask_at_event;

    std::optional<std::string> reason;
    std::optional<double> pnl;

    json additional_data;

    TradeEventData() : event_timestamp(0), event_type(TradeEventType::OTHER) {}
};

class DefaultExecutionClient : public ExecutionClient {
public:
    // Singleton instance getter
    static DefaultExecutionClient& getInstance() {
        static DefaultExecutionClient instance("", "", "", 0.02); // Default values
        return instance;
    }

    DefaultExecutionClient(const std::string& api_key, 
                         const std::string& base64_private_key,
                         const std::string& symbol,
                         double max_daily_drawdown_pct = 0.02,
                         const std::string& signal_file = "signal.json");
    
    ~DefaultExecutionClient() override;

    // Signal handler setup
    void setupSignalHandler();
    void stop();

    // L1 data access (lock-free, atomic)
    double bestBid() const override { return best_bid_.load(std::memory_order_relaxed); }
    double bestAsk() const override { return best_ask_.load(std::memory_order_relaxed); }
    double mid() const override { 
        double bid = bestBid();
        double ask = bestAsk();
        return (bid + ask) * 0.5;
    }

    // Register callback for L1 updates
    void registerL1Callback(L1Callback callback) override {
        l1_callback_ = std::move(callback);
    }

    // Callback for L1 updates
    void onTick(const std::string& symbol, double bid, double ask,
                double bidQty, double askQty, uint64_t timestamp) override;

    // Market data handlers
    void onTrade(const std::string& symbol, double price, double quantity, uint64_t timestamp) override;
    void onKline(const std::string& symbol, const std::string& interval,
                 double open, double high, double low, double close,
                 double volume, uint64_t timestamp) override;

    // Order execution methods
    std::string send_market(
        const std::string& symbol,
        double quantity,
        bool is_buy,
        const OrderFlags& flags = OrderFlags(),
        const ConditionalOrderParams& cond_params = {},
        const std::string& model_id = "",
        std::optional<double> associated_entry_price = std::nullopt);
    std::string send_limit(
        const std::string& symbol,
        double quantity,
        double price,
        bool is_buy,
        TimeInForce tif = TimeInForce::GTC,
        const OrderFlags& flags = OrderFlags(),
        const ConditionalOrderParams& cond_params = {},
        const std::string& model_id = "",
        std::optional<double> associated_entry_price = std::nullopt);
    std::string send_order(
        const OrderRequest& order,
        const OrderFlags& flags = OrderFlags(), 
        const ConditionalOrderParams& cond_params = {},
        const std::string& model_id = "",
        std::optional<double> associated_entry_price = std::nullopt);
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

    // Post-only maker order example
    std::string postOnlyMaker(bool is_buy, double size, double limit_price);

    // Method to be called periodically to check for new signals
    void check_for_new_signal();

    // Added for balance query
    nlohmann::json query_balances();

    void handle_l1_update(const std::string& message);

    // Place a sequence of maker orders at specified ladder levels
    void send_entry_ladder(const std::string& symbol, bool is_buy, const std::vector<LadderLevel>& levels);

    // Ladder and stop-loss fallback logic (v3 implementations)
    void attempt_ladder_entry_order_with_fallback(const MlSignalPayload& pos_candidate,
                                                 const BBO& current_bbo);
    void attempt_stop_loss_order_with_fallback(const MlSignalPayload& pos_candidate,
                                                 const BBO& current_bbo);

    // Websocket order tracking
    void setupOrderWebSocket();
    void onOrderUpdate(const nlohmann::json& j);
    std::unordered_map<std::string, backpack::Order> order_cache_;
    std::mutex order_cache_mutex_;
    // Open order safety-valves: count-based circuit-breaker and age-based sweeper
    std::unordered_map<std::string, RestingOrder> openOrders_;
    std::mutex openOrdersMutex_;
    static constexpr std::size_t MAX_OPEN_ORDERS = 150;
    static constexpr std::chrono::seconds MAX_ORDER_AGE = std::chrono::seconds(30);
    static constexpr std::chrono::seconds SWEEP_INTERVAL = std::chrono::seconds(15);
    std::thread orderSweeperThread_;
    // Safety mechanism methods
    void enforceOpenOrderLimit(const std::string& symbol_to_check_and_cancel, std::unique_lock<std::mutex>& open_orders_lock);
    void sweeperThreadLogic();
    bool cancelAllOrdersForSymbol(const std::string& symbol);
    bool cancelSingleOrder(const std::string& order_id, const std::string& symbol);
    void sweeperThread();
    std::atomic<bool> ws_orders_initialized_{false};
    std::atomic<bool> ws_connected_{false};
    std::atomic<bool> ws_orders_subscribed_{false};
    std::atomic<bool> ws_connection_healthy_{false};
    std::atomic<bool> bootstrap_in_progress_{false};
    std::chrono::steady_clock::time_point ws_last_connection_attempt_;
    std::mutex ws_mutex_; // Ensure ws_mutex_ is also declared

    // Method to cancel orders by model_id (clientId)
    int cancel_orders_by_model_id(const std::string& symbol, const std::string& model_id_to_cancel);

    // WebSocket methods
    void bootstrapOrderCache();
    void processSdkOrderUpdate(const backpack::Order& sdk_order);
    void onUserFill(const backpack::Trade& sdk_trade);

    void initialize_order_ws();
    void stop_order_ws();

    // TEST METHOD - Public wrapper for testing execute_signed_request
    nlohmann::json test_execute_signed_request(RestClass rest_class,
                                              const std::string& method,
                                              const std::string& endpoint,
                                              const std::string& instruction,
                                              const nlohmann::json& params) {
        return execute_signed_request(rest_class, method, endpoint, instruction, params);
    }

private:
    // Redis pub/sub handling
    void setupRedisSubscriber();
    void handleL1Update(const std::string& message);
    void publishL1Update(const BookTicker& ticker);

    // ML Signal processing and trade management
    MlSignalPayload read_signal_file();
    void process_new_ml_signal(const MlSignalPayload& new_payload);
    void place_entry_order_with_stop(const MlSignalPayload& payload);
    void close_current_position(double exit_price, const std::string& reason);
    std::string format_price(double price); // Helper for formatting price to string

    // Post-order processing and polling
    void process_fill_response(const json& fill_response,
                               const OrderRequest& original_order,
                               const std::string& model_id,
                               std::optional<double> associated_entry_price);
    void poll_order_status(std::string symbol,
                           std::string order_id,
                           OrderRequest original_order,
                           std::string model_id,
                           std::optional<double> associated_entry_price);

    // Utility methods
    static std::string order_side_to_string(OrderSide side);
    static std::string order_type_to_string(OrderType type);
    static std::string self_trade_prevention_to_string(SelfTradePrevention stp);
    void add_strategy_flags(json& params, const OrderFlags& flags) const;
    std::string build_signing_string(const std::string& instruction, const json& params) const;
    std::string sign_request(const std::string& signing_string) const;
    json execute_signed_request(RestClass rest_class,
                              const std::string& http_method,
                              const std::string& endpoint,
                              const std::string& instruction,
                              const json& params) const;
    // Helper for formatting quantity to minimum step size
    double format_quantity(double qty) const;

    // WebSocket error handler
    void order_ws_error_handler_(const std::string& error_code);

    // Member variables
    std::string trading_symbol_;
    std::string api_key_;
    std::string base64_private_key_;
    std::string api_secret_;
    
    std::unique_ptr<BackpackClient> client_;
    std::unique_ptr<sw::redis::Redis> redis_client_;
    std::unique_ptr<RiskManager> risk_manager_;
    
    double tick_size_;
    double min_qty_;
    
    std::atomic<double> best_bid_{0.0};
    std::atomic<double> best_ask_{0.0};
    std::atomic<double> bid_qty_{0.0};
    std::atomic<double> ask_qty_{0.0};
    std::atomic<uint64_t> last_update_{0};
    std::atomic<bool> running_{true};
    std::thread redis_subscriber_thread_;  // Thread for Redis subscription
    
    L1Callback l1_callback_;
    
    std::mutex trade_state_mutex_; // Mutex for protecting trade state variables
    std::unordered_map<std::string, std::string> trade_id_map_; // Map model_id to trade_id for event logging
    std::mutex missing_order_ids_mutex_; // Mutex for recently_missing_order_ids_
    std::unordered_set<std::string> recently_missing_order_ids_; // Cache for order IDs that returned 404

    // Redis connection details
    static constexpr const char* REDIS_HOST = "localhost";
    static constexpr int REDIS_PORT = 6379;
    static constexpr int REDIS_OUTPUT_PORT = 6380;
    
    // Technical indicators
    OHLCVBuffer ohlcv_buffer_;
    RSI rsi_{14};
    MACD macd_{12, 26, 9};
    EMA ema200_{200};
    
    // Constants
    static constexpr int64_t DEFAULT_WINDOW = 5000;
    static constexpr double CONFIDENCE_SCALE = 5.0;

    // Support multiple concurrent trades
    struct Position {
        std::string model_id;
        double entry_price;
        double stop_loss;
        double size;
        int max_hold_bars;
        int bars_held;
        int side; // +1 for long, -1 for short
        std::string trade_id; // Unique ID for the ML model instance/trade lifecycle
    };
    std::vector<Position> open_positions_;

    // Active position tracking with stop orders
    struct ActivePosition {
        std::string model_id;
        std::string trading_symbol;
        OrderSide side;
        double entry_price;
        std::optional<double> stop_loss_price;
        double quantity;                     // Current quantity of the position
        double quantity_filled_so_far;       // Total quantity filled so far for this position (cumulative)
        uint64_t entry_timestamp;
        std::vector<std::string> order_ids;
        std::vector<std::string> stop_order_ids;
        std::optional<std::string> closing_order_id; // ID of the pending closure order
        TradeEventType closure_type = TradeEventType::OTHER; // Type of closure event
        bool pending_closure = false; // Indicates we're awaiting closure fills
        // Default constructor to initialize numeric fields
        ActivePosition() : entry_price(0.0), quantity(0.0), quantity_filled_so_far(0.0), entry_timestamp(0) {}
    };
    std::map<std::string, ActivePosition> active_positions_;
    void positions_to_json();
    void load_positions_from_json();

    // Signal file handling
    std::string signal_file_path_;
    long long last_signal_file_timestamp_processed_{0};
    std::chrono::steady_clock::time_point last_signal_check_time_;

    // New constants for order placement logic
    static constexpr int INITIAL_SAFETY_TICKS = 2;
    static constexpr int FALLBACK_SAFETY_TICK_INCREMENT = 2;
    static constexpr int MAX_FALLBACK_ATTEMPTS = 3;

    // Structured logging members
    void log_trade_event(const TradeEventData& event_data);
    std::ofstream trade_event_log_file_;

    void log_stop_order_sent(const std::string& model_id,
                              double price,
                              double quantity,
                              OrderSide side,
                              const std::string& trading_symbol);
};

// Simple BBO structure
struct BBO {
    double bid;
    double ask;
    BBO(double b, double a) : bid(b), ask(a) {}
};

} // namespace bp 
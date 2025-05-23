#include <fstream> // For std::ofstream
#include <string>
#include <vector>
#include <optional>
// Assuming nlohmann/json.hpp is available and included, e.g. #include <nlohmann/json.hpp>
// For now, we'll use forward declaration trick if full include isn't already there,
// or rely on it being included elsewhere. For the TradeEventData struct, we need its definition.
// If not already present, ensure <nlohmann/json.hpp> is included.
// For the purpose of this edit, assuming json is a known type.
// If nlohmann::json is not found, a full include would be #include "nlohmann/json.hpp" or similar. 

// Forward declarations
class RiskManager;

// L1 data structure for book tickers
struct BookTicker { // ... existing code ... };

// Simple BBO structure
struct BBO {
    double bid;
    double ask;
    BBO(double b, double a) : bid(b), ask(a) {}
};

enum class TradeEventType {
    SIGNAL_RECEIVED,
    ENTRY_ORDER_SENT,
    ENTRY_ORDER_FILLED,
    ENTRY_ORDER_PARTIALLY_FILLED,
    STOP_ORDER_SENT,
    POSITION_CLOSED_STOP_LOSS,
    POSITION_CLOSED_TAKE_PROFIT,
    POSITION_CLOSED_MAX_HOLD,
    POSITION_CLOSED_MANUAL,
    ORDER_CANCELLED,
    OTHER
};

inline std::string trade_event_type_to_string(TradeEventType type) {
    switch (type) {
        case TradeEventType::SIGNAL_RECEIVED: return "SIGNAL_RECEIVED";
        case TradeEventType::ENTRY_ORDER_SENT: return "ENTRY_ORDER_SENT";
        case TradeEventType::ENTRY_ORDER_FILLED: return "ENTRY_ORDER_FILLED";
        case TradeEventType::ENTRY_ORDER_PARTIALLY_FILLED: return "ENTRY_ORDER_PARTIALLY_FILLED";
        case TradeEventType::STOP_ORDER_SENT: return "STOP_ORDER_SENT";
        case TradeEventType::POSITION_CLOSED_STOP_LOSS: return "POSITION_CLOSED_STOP_LOSS";
        case TradeEventType::POSITION_CLOSED_TAKE_PROFIT: return "POSITION_CLOSED_TAKE_PROFIT";
        case TradeEventType::POSITION_CLOSED_MAX_HOLD: return "POSITION_CLOSED_MAX_HOLD";
        case TradeEventType::POSITION_CLOSED_MANUAL: return "POSITION_CLOSED_MANUAL";
        case TradeEventType::ORDER_CANCELLED: return "ORDER_CANCELLED";
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

    nlohmann::json additional_data; 

    TradeEventData() : event_timestamp(0), event_type(TradeEventType::OTHER) {} 
};

// Self-trade prevention strategies
// ... existing code ...
    void registerL1Callback(L1Callback callback) override;
};

class DefaultExecutionClient : public ExecutionClient {
public:
    // ... existing code ...
    // Method to be called periodically to check for new signals
    void check_for_new_signal();

    // Added for balance query
    nlohmann::json query_balances();

    void handle_l1_update(const std::string& message);

    // Place a sequence of maker orders at specified ladder levels
    void send_entry_ladder(const std::string& symbol, bool is_buy, const std::vector<LadderLevel>& levels);

private:
    // ... existing code ...
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
    
    // New/modified function declarations
    void attempt_ladder_entry_order_with_fallback(const MlSignalPayload& pos_candidate, const BBO& current_bbo);
    double determine_entry_price_with_safety(const BBO& bbo, backpack::OrderSide side, int safety_ticks, bool post_only);
    void attempt_stop_loss_order_with_fallback(const ConditionalOrderParams& stop_params, const std::string& model_id, const BBO& current_bbo);

    // Utility methods
// ... existing code ... 
    // For structured trade event logging
    void log_trade_event(const TradeEventData& event_data);
    std::ofstream trade_event_log_file_;

    // New constants for order placement logic
// ... existing code ...

    // Helper to log STOP_ORDER_SENT events
    void log_stop_order_sent(const std::string& model_id, double price, double quantity, OrderSide side, const std::string& trading_symbol);
};

// Simple BBO structure
// ... existing code ...

// ... existing code ... 

struct ActivePosition {
    std::string model_id;                // Unique ID for the ML model instance/trade lifecycle
    std::string trading_symbol;          // Symbol for the position
    OrderSide side;                      // BUY or SELL
    double entry_price;                  // Average entry price of the position
    double quantity;                     // Current quantity of the position
    double quantity_filled_so_far;       // Total quantity filled so far for this position (cumulative)
    std::optional<double> stop_loss_price; // Optional stop-loss price
    uint64_t entry_timestamp;            // Timestamp of first entry related event (e.g. signal or order)
    std::vector<std::string> order_ids;  // Associated exchange order IDs
    // Add other relevant state as needed

    ActivePosition() : entry_price(0.0), quantity(0.0), quantity_filled_so_far(0.0), entry_timestamp(0) {}
};

// Maps model_id to its current active position details
// ... existing code ...

// ... existing code ... 

// Configuration for ML signals processed by the system
// ... existing code ... 

// This should be the Position struct definition around line 386
struct Position {
    std::string model_id;
    double entry_price;
    double stop_loss;
    double size;
    int max_hold_bars;
    int bars_held;
    int side; // 1 for long, -1 for short
    std::string trade_id; // Added to link to the overall trade lifecycle
};

// ... existing code ... 
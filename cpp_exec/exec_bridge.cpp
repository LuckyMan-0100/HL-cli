#define SPDLOG_ACTIVE_LEVEL SPDLOG_LEVEL_TRACE // Force active log level

#include <string>
#include <chrono>
#include <iostream>
#include <memory>
#include <atomic>
#include <mutex>
#include <thread>
#include <stdexcept>
#include <cstdlib> // For std::getenv
#include <limits> // For std::numeric_limits
#include <future> // For std::async
#include <csignal> // For signal handling
#include <cmath>
#include <sys/resource.h>  // For getrusage

#include <boost/asio.hpp>
#include <boost/asio/steady_timer.hpp>
#include <boost/asio/ip/tcp.hpp>
#include <boost/asio/post.hpp>
#include <boost/asio/executor_work_guard.hpp>
// Inject compatibility aliases for WebSocket++ (map io_service→io_context, strand_ptr → shared_ptr<strand>)
namespace websocketpp {
namespace lib {
namespace asio {
    using io_service = boost::asio::io_context;
    using io_service_ptr = std::shared_ptr<io_service>;
    using strand = boost::asio::strand<boost::asio::io_context::executor_type>;
    using strand_ptr = std::shared_ptr<strand>;
} } }

#include <backpack/backpack_client.hpp> // Assuming this exists and has necessary types
#include <nlohmann/json.hpp>
#include "../redis-plus-plus/src/sw/redis++/redis++.h"
#include <spdlog/spdlog.h>
#include <spdlog/fmt/ostr.h> // For logging custom types if needed
#include <spdlog/fmt/chrono.h> // For logging std::chrono types
#include <fstream> // For std::ifstream
#include <sstream> // For std::ostringstream, std::fixed
#include <iomanip> // For std::setprecision
#include <optional> // For std::optional
#include <random>   // For UUID generation
#include <sstream>  // For UUID generation
#include <iomanip>  // For UUID generation, std::hex

#include "exec_bridge.hpp"
#include "risk_manager.hpp" // Include the header file
#include "risk_manager.hpp"
#include "indicators.hpp"

#include <openssl/evp.h>
#include <openssl/bio.h>
#include <openssl/buffer.h>
#include <curl/curl.h>

namespace bp {

using json = nlohmann::json;

// Helper struct for ScopedUnlock
struct ScopedUnlock {
    std::unique_lock<std::mutex>& lock_;
    bool initially_owned_;

    ScopedUnlock(std::unique_lock<std::mutex>& lock) : lock_(lock), initially_owned_(lock_.owns_lock()) {
        if (initially_owned_) {
            lock_.unlock();
        }
    }

    ~ScopedUnlock() {
        if (initially_owned_ && !lock_.owns_lock()) { // Re-lock only if it was owned and is not currently locked by us
            lock_.lock();
        }
    }
    // Delete copy and move constructors/assignment operators
    ScopedUnlock(const ScopedUnlock&) = delete;
    ScopedUnlock& operator=(const ScopedUnlock&) = delete;
    ScopedUnlock(ScopedUnlock&&) = delete;
    ScopedUnlock& operator=(ScopedUnlock&&) = delete;
};

// Helper function to format a double to a string with specified precision
std::string format_double_to_string(double val, int precision) {
    std::ostringstream oss;
    oss << std::fixed << std::setprecision(precision) << val;
    return oss.str();
}

// Helper to get environment variable or default
inline std::string getenv_or(const char* key, const std::string& def = "") {
    const char* val = std::getenv(key);
    return val ? std::string(val) : def;
}

// Helper function to safely get double from string or number
inline double json_get_double(const nlohmann::json& j, const char* key, double default_val = 0.0) {
    if (j.contains(key)) {
        if (j[key].is_string()) {
            try { return std::stod(j[key].get<std::string>()); } catch(...) {}
        } else if (j[key].is_number()) {
            return j[key].get<double>();
        }
    }
    return default_val;
}
// Helper function to safely get int64 from string or number
inline int64_t json_get_int64(const nlohmann::json& j, const char* key, int64_t default_val = 0) {
    if (j.contains(key)) {
        if (j[key].is_string()) {
            try { return std::stoll(j[key].get<std::string>()); } catch(...) {}
        } else if (j[key].is_number_integer()) {
            return j[key].get<int64_t>();
        }
    }
    return default_val;
}

// Convert microseconds or seconds to milliseconds
inline int64_t to_ms(int64_t ts) {
    if (ts > 1'000'000'000'000LL) return ts / 1'000;   // µs
    if (ts < 1'000'000'000LL)      return ts * 1'000;   //  s
    return ts; // already ms
}

// Helper function for CURL response handling
size_t WriteCallback(void* contents, size_t size, size_t nmemb, std::string* userp) {
    userp->append((char*)contents, size * nmemb);
    return size * nmemb;
}

// Helper function for CURL header handling
static size_t HeaderCallback(char* buffer, size_t size, size_t nitems, void* userdata) {
    std::string* headers = static_cast<std::string*>(userdata);
    headers->append(buffer, size * nitems);
    return size * nitems;
}

// Helper function to URL encode a string
std::string url_encode(const std::string& value) {
    std::ostringstream escaped;
    escaped.fill('0');
    escaped << std::hex;

    for (char c : value) {
        if (std::isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~') {
            escaped << c;
        } else {
            escaped << std::uppercase;
            escaped << '%' << std::setw(2) << int((unsigned char)c);
            escaped << std::nouppercase;
        }
    }
    return escaped.str();
}

// Helper function to convert JSON object to an alphabetically sorted query string
// Values are NOT URL-encoded for the signing string, as per API clarification.
std::string json_to_sorted_query_string(const nlohmann::json& j) {
    if (!j.is_object()) {
        return "";
    }

    std::map<std::string, std::string> sorted_params; // Use std::map to sort keys alphabetically
    for (auto& el : j.items()) {
        std::string value_str;
        if (el.value().is_string()) {
            value_str = el.value().get<std::string>();
        } else if (el.value().is_number()) {
            value_str = el.value().dump(); // dump numbers as strings, e.g. 1.0 -> "1.0"
        } else if (el.value().is_boolean()) {
            value_str = el.value().get<bool>() ? "true" : "false";
        } else {
            spdlog::warn("Unsupported JSON value type in json_to_sorted_query_string for key: {}. Skipping.", el.key());
            continue;
        }
        sorted_params[el.key()] = value_str; // Store plain string values
    }

    std::string query_string;
    for (auto const& [key, val] : sorted_params) {
        if (!query_string.empty()) {
            query_string += "&";
        }
        query_string += key + "=" + val; 
    }
    return query_string;
}

// Base64 encoding helper
std::string base64_encode(const unsigned char* input, int length) {
    BIO* bio, *b64;
    BUF_MEM* bufferPtr;

    b64 = BIO_new(BIO_f_base64());
    bio = BIO_new(BIO_s_mem());
    bio = BIO_push(b64, bio);

    BIO_set_flags(b64, BIO_FLAGS_BASE64_NO_NL);
    BIO_write(bio, input, length);
    (void)BIO_flush(bio); // Cast to void to silence unused result warning
    BIO_get_mem_ptr(bio, &bufferPtr);

    std::string result(bufferPtr->data, bufferPtr->length);

    BIO_free_all(bio);
    return result;
}

// Define defaults for ML signals
static constexpr int DEFAULT_MAX_HOLD_BARS = 0; // Disabled time_stop by default
static constexpr double DEFAULT_STOP_LOSS_PCT = 0.5; // 0.5%

// inside namespace bp, add UUID generator before constructor

// Helper function to generate a simple UUID (version 4 like)
// This is a basic implementation. For production, a robust UUID library might be better.
std::string generate_uuid_v4() {
    static std::random_device rd;
    static std::mt19937 gen(rd());
    static std::uniform_int_distribution<> dis(0, 15);
    static std::uniform_int_distribution<> dis2(8, 11);

    std::stringstream ss;
    ss << std::hex;
    for (int i = 0; i < 8; i++) ss << dis(gen);
    ss << '-';
    for (int i = 0; i < 4; i++) ss << dis(gen);
    ss << "-4"; // Version 4
    for (int i = 0; i < 3; i++) ss << dis(gen);
    ss << '-';
    ss << dis2(gen);
    for (int i = 0; i < 3; i++) ss << dis(gen);
    ss << '-';
    for (int i = 0; i < 12; i++) ss << dis(gen);
    return ss.str();
}

DefaultExecutionClient::DefaultExecutionClient(
    const std::string& api_key,
    const std::string& base64_private_key,
    const std::string& symbol,
    double max_daily_drawdown_pct,
    const std::string& signal_file)
    : trading_symbol_(symbol),
      api_key_(api_key),
      base64_private_key_(base64_private_key),
      // Corrected initialization order: signal_file_path_ moved after tick_size_ and min_qty_
      tick_size_(0.01),       // Initialize tick_size_
      min_qty_(0.00001),      // Initialize min_qty_
      signal_file_path_(signal_file),
      last_signal_check_time_(std::chrono::steady_clock::now()) {
    
    spdlog::info("DefaultExecutionClient constructor: Called for symbol '{}'", symbol);
    try {
        running_ = true; // Initialize running_ flag
        spdlog::info("DefaultExecutionClient constructor: running_ flag set to true.");

        // Initialize Redis client
        spdlog::info("DefaultExecutionClient constructor: Initializing Redis client...");
        sw::redis::ConnectionOptions connection_options;
        connection_options.host = "localhost"; // Consider making these configurable
        connection_options.port = REDIS_PORT;  // Use the constant from header
        connection_options.keep_alive = true; // Explicitly set to true
        connection_options.connect_timeout = std::chrono::milliseconds(500); // Explicitly set
        connection_options.socket_timeout = std::chrono::milliseconds(0);  // Explicitly set to 0 (was 500)
        spdlog::info("DefaultExecutionClient constructor: Redis connection options set (Host: {}, Port: {}, KeepAlive: {}, ConnectTimeout: 500ms, SocketTimeout: 0ms).",
                     connection_options.host, connection_options.port, connection_options.keep_alive);
        redis_client_ = std::make_unique<sw::redis::Redis>(connection_options);
        spdlog::info("DefaultExecutionClient constructor: Redis client created. Pinging Redis...");
        std::string ping_reply = redis_client_->ping();
        spdlog::info("DefaultExecutionClient constructor: Redis ping reply: '{}'", ping_reply);
        
        // Initialize Backpack client
        spdlog::info("DefaultExecutionClient constructor: Initializing Backpack client...");
        client_ = std::make_unique<backpack::BackpackClient>(); // Uses default URLs
        spdlog::info("DefaultExecutionClient constructor: Backpack client created.");
        spdlog::info("DefaultExecutionClient constructor: Setting Backpack credentials...");
        client_->set_credentials(api_key, base64_private_key_); // Ensure these are valid
        spdlog::info("DefaultExecutionClient constructor: Backpack credentials set.");
        
        // Set up WebSocket order tracking
        setupOrderWebSocket();
        
        // Initialize risk manager
        spdlog::info("DefaultExecutionClient constructor: Initializing RiskManager...");
        risk_manager_ = std::make_unique<RiskManager>(max_daily_drawdown_pct);
        spdlog::info("DefaultExecutionClient constructor: RiskManager initialized.");
        
        // Setup Redis subscriber for L1 data
        spdlog::info("DefaultExecutionClient constructor: Setting up Redis subscriber...");
        setupRedisSubscriber();
        spdlog::info("DefaultExecutionClient constructor: Redis subscriber setup complete.");
        
        // Start a detached thread to log memory usage periodically
        spdlog::info("DefaultExecutionClient constructor: Starting memory logger thread...");
        std::thread([this]{\
            while (running_) {
                struct rusage usage;
                if (getrusage(RUSAGE_SELF, &usage) == 0) {
                    double mem_mb = static_cast<double>(usage.ru_maxrss) / (1024.0 * 1024.0); // ru_maxrss is in bytes on macOS
                    spdlog::info("[Memory] RSS: {:.2f} MB", mem_mb);
                }
                std::this_thread::sleep_for(std::chrono::seconds(15));
            }
        }).detach();
        spdlog::info("DefaultExecutionClient constructor: Memory logger thread started.");
        
        // Initialize trade event log file
        trade_event_log_file_.open("tradelog.jsonl", std::ios::out | std::ios::app);
        if (!trade_event_log_file_.is_open()) {
            spdlog::error("Failed to open tradelog.jsonl for writing.");
        } else {
            spdlog::info("Trade event log (tradelog.jsonl) opened successfully.");
        }
        
        // Start order sweeper thread for open order safety  
        // Stagger the startup to avoid coinciding with other 30-second timers
        orderSweeperThread_ = std::thread([this] { 
            spdlog::info("Order sweeper thread started for symbol: {}. Waiting 45 seconds before starting sweeper logic (staggered timing)...", trading_symbol_);
            std::this_thread::sleep_for(std::chrono::seconds(45));  // Changed from 30 to 45 seconds
            if (running_) {  // Check if still running before starting logic
                this->sweeperThreadLogic(); 
            } else {
                spdlog::info("Order sweeper thread for symbol {} exiting early as running_ is false", trading_symbol_);
            }
        }); 
        orderSweeperThread_.detach();
        spdlog::info("DefaultExecutionClient constructor: Order sweeper thread started with 45-second staggered delay.");
        
        spdlog::info("DefaultExecutionClient initialized successfully");
    } catch (const sw::redis::IoError& e) {
        spdlog::error("DefaultExecutionClient constructor: Redis I/O Error: {}. Check if Redis server is running and accessible on {}:{}.", e.what(), "localhost", REDIS_PORT);
        throw; // Re-throw to ensure the application knows initialization failed
    } catch (const sw::redis::Error& e) {
        spdlog::error("DefaultExecutionClient constructor: Redis++ Error: {}", e.what());
        throw;
    } catch (const std::exception& e) {
        spdlog::error("DefaultExecutionClient constructor: Generic C++ Error: {}", e.what());
        throw;
    } catch (...) {
        spdlog::error("DefaultExecutionClient constructor: Unknown error during initialization.");
        throw;
    }
}

DefaultExecutionClient::~DefaultExecutionClient() {
    stop(); // Call stop to ensure threads are joined

    if (trade_event_log_file_.is_open()) {
        trade_event_log_file_.close();
        spdlog::info("Trade event log (tradelog.jsonl) closed.");
    }
    // ... any other cleanup ...
}

void DefaultExecutionClient::stop() {
    running_ = false;
    if (redis_subscriber_thread_.joinable()) {
        redis_subscriber_thread_.join();
    }
    // Disconnect WebSocket if client_ and its ws_disconnect_orders method exist
    if (client_ && client_->is_connected()) { // Use SDK's is_connected()
        spdlog::info("Stopping DefaultExecutionClient: attempting to disconnect order WebSocket.");
        try {
            client_->disconnect(); // Use SDK's disconnect()
        } catch (const std::exception& e) {
            spdlog::error("Exception during WebSocket disconnect on stop: {}", e.what());
        }
    }
    ws_connected_.store(false, std::memory_order_relaxed); // Ensure flags are reset
    ws_orders_initialized_.store(false, std::memory_order_relaxed);

    // Add join for memory logger thread if it's made joinable
}

void DefaultExecutionClient::setupRedisSubscriber() {
    spdlog::info("setupRedisSubscriber: Called.");
    try {
        auto subscriber = redis_client_->subscriber();
        spdlog::info("setupRedisSubscriber: Subscriber object created.");
        
        // Subscribe to L1 data channel
        // std::string l1_channel = "l1:" + trading_symbol_; // Use the dynamic trading_symbol
        std::string actual_subscribe_channel = "l1:quotes"; // Changed to actual channel from L1 feeder
        spdlog::info("setupRedisSubscriber: Subscribing to L1 channel: '{}' (was originally configured for l1:{})", actual_subscribe_channel, trading_symbol_);
        subscriber.subscribe(actual_subscribe_channel);
        spdlog::info("setupRedisSubscriber: subscribe() call completed for channel '{}'.", actual_subscribe_channel);
        
        // Set callback once before starting the consume loop
        spdlog::info("setupRedisSubscriber: Setting on_message callback...");
        subscriber.on_message([this, actual_subscribe_channel](std::string channel, std::string msg) { // Capture actual_subscribe_channel
            spdlog::debug("Redis on_message: Received message on channel '{}' (expecting '{}')", channel, actual_subscribe_channel);
            if (channel == actual_subscribe_channel) { // Compare with the actual subscribed channel
                this->handleL1Update(msg); // handleL1Update will filter by trading_symbol_ internally
            } else {
                spdlog::warn("Redis on_message: Received message on unexpected channel '{}', subscribed to '{}'", channel, actual_subscribe_channel);
            }
        });
        spdlog::info("setupRedisSubscriber: on_message callback set.");
        
        // Log successful subscription once
        spdlog::info("Subscribed to L1 quotes channel '{}' - listening for real-time market data", actual_subscribe_channel);
        
        // Start subscription in a separate thread
        spdlog::info("setupRedisSubscriber: Starting Redis subscriber thread...");
        redis_subscriber_thread_ = std::thread([this, subscriber = std::move(subscriber)]() mutable { // Store thread
            spdlog::info("Redis subscriber thread starting...");
            uint64_t consume_call_count = 0;
            while (running_) {
                try {
                    consume_call_count++;
                    spdlog::debug("[ConsumeAttempt:{}] Attempting to consume Redis messages...", consume_call_count);
                    subscriber.consume(); // Blocking call
                    if (!running_) {
                        spdlog::info("[ConsumeAttempt:{}] running_ is false after consume() returned, exiting loop.", consume_call_count);
                        break;
                    }
                } catch (const sw::redis::Error& e) { // Catch specific redis-plus-plus errors
                    spdlog::error("[ConsumeAttempt:{}] Redis++ error in subscription: {}. Sleeping 5s.", consume_call_count, e.what());
                    if (!running_) break;
                    std::this_thread::sleep_for(std::chrono::seconds(5)); // Wait before retrying consume
                } catch (const std::exception& e) {
                    spdlog::error("[ConsumeAttempt:{}] Generic C++ exception in subscription: {}. Sleeping 1s.", consume_call_count, e.what());
                    if (!running_) break;
                    std::this_thread::sleep_for(std::chrono::seconds(1));
                } catch (...) {
                    spdlog::error("[ConsumeAttempt:{}] Unknown exception in subscription. Sleeping 1s.", consume_call_count);
                    if (!running_) break;
                    std::this_thread::sleep_for(std::chrono::seconds(1));
                }
            }
            spdlog::info("Redis subscriber thread finished. Total consume calls: {}", consume_call_count);
        }); //.detach(); // Now joinable
        
    } catch (const std::exception& e) {
        spdlog::error("Failed to setup Redis subscriber: {}", e.what());
        throw;
    }
}

void DefaultExecutionClient::handleL1Update(const std::string& message) {
    spdlog::info("handleL1Update: Received L1 message for processing.");
    // [Initial signal processing moved below after market data update]

    try {
        auto j = json::parse(message);
        
        BookTicker ticker{
            j["symbol"].get<std::string>(),
            json_get_double(j, "bidPrice"),
            json_get_double(j, "askPrice"),
            json_get_double(j, "bidQty"),
            json_get_double(j, "askQty"),
            static_cast<uint64_t>(json_get_int64(j, "timestamp")),
            static_cast<uint64_t>(json_get_int64(j, "updateId"))
        };
        
        spdlog::info("handleL1Update: Successfully processed L1 for symbol {}, Bid: {}, Ask: {}", ticker.symbol, ticker.bid_price, ticker.ask_price);
        
        // Update atomic values - low latency (<80 µs) best bid/best ask cache
        best_bid_.store(ticker.bid_price, std::memory_order_relaxed);
        best_ask_.store(ticker.ask_price, std::memory_order_relaxed);
        bid_qty_.store(ticker.bid_qty, std::memory_order_relaxed);
        ask_qty_.store(ticker.ask_qty, std::memory_order_relaxed);
        last_update_.store(ticker.timestamp, std::memory_order_relaxed);
        
        // Execute onTick to run strategy logic (now primarily SL check)
        if (ticker.symbol == trading_symbol_) {
            onTick(ticker.symbol, ticker.bid_price, ticker.ask_price, 
                   ticker.bid_qty, ticker.ask_qty, ticker.timestamp);
        }
        
        // Call registered callback if any
        if (l1_callback_) {
            l1_callback_(ticker);
        }
        
    } catch (const std::exception& e) {
        spdlog::error("Error processing L1 update: {}", e.what());
    }
    // Process new signals after updating bestBid and bestAsk
    check_for_new_signal();
}

void DefaultExecutionClient::publishL1Update(const BookTicker& ticker) {
    try {
        json j = {
            {"symbol", ticker.symbol},
            {"bidPrice", ticker.bid_price},
            {"askPrice", ticker.ask_price},
            {"bidQty", ticker.bid_qty},
            {"askQty", ticker.ask_qty},
            {"timestamp", ticker.timestamp},
            {"updateId", std::to_string(ticker.update_id)}
        };
        
        // Use the output port (6380) via stunnel for publishing processed data
        sw::redis::ConnectionOptions output_options;
        output_options.host = REDIS_HOST;
        output_options.port = REDIS_OUTPUT_PORT; // Use the stunnel port
        
        static sw::redis::Redis output_redis(output_options);
        output_redis.publish("l1:processed", j.dump());
    } catch (const std::exception& e) {
        spdlog::error("Error publishing L1 update: {}", e.what());
    }
}

void DefaultExecutionClient::onTick(const std::string& symbol,
                                   double bid [[maybe_unused]], double ask [[maybe_unused]],
                                   double bidQty [[maybe_unused]], double askQty [[maybe_unused]],
                                   uint64_t timestamp [[maybe_unused]]) {
    if (symbol != trading_symbol_) return;
    std::lock_guard<std::mutex> lock(trade_state_mutex_);

    // Log current size of open_positions_ periodically or if large
    static std::chrono::steady_clock::time_point last_pos_log_time = std::chrono::steady_clock::now();
    auto now = std::chrono::steady_clock::now();
    if (open_positions_.size() > 50 || 
        std::chrono::duration_cast<std::chrono::seconds>(now - last_pos_log_time).count() >= 60) {
        spdlog::info("[onTick] Open positions count: {}", open_positions_.size());
        last_pos_log_time = now;
    }

    for (int i = open_positions_.size() - 1; i >= 0; --i) {
        auto &pos = open_positions_[i];
        pos.bars_held++;
        double price = (pos.side == 1) ? bestBid() : bestAsk();
        bool should_close = false;
        std::string reason;
        if (pos.max_hold_bars > 0 && pos.bars_held >= pos.max_hold_bars) {
            reason = "time_stop"; should_close = true;
        } else if (pos.side == 1 && price > 0 && price <= pos.stop_loss) {
            reason = "stop_loss_hit"; should_close = true;
        } else if (pos.side == -1 && price > 0 && price >= pos.stop_loss) {
            reason = "stop_loss_hit"; should_close = true;
        }
        if (should_close) {
            bool was_buy = (pos.side == 1);
            // Send market order to close position and get order ID
            std::string closing_order_id = send_market(trading_symbol_, pos.size, !was_buy,
                                                      OrderFlags{true}, ConditionalOrderParams{},
                                                      pos.model_id, pos.entry_price);
            // Record pending closure for later fill handling
            {
                std::lock_guard<std::mutex> lock(trade_state_mutex_);
                auto &ap = active_positions_[pos.model_id];
                ap.closing_order_id = closing_order_id;
                ap.closure_type = (reason == "time_stop")
                                   ? TradeEventType::POSITION_CLOSED_MAX_HOLD
                                   : TradeEventType::POSITION_CLOSED_STOP_LOSS;
                ap.pending_closure = true;
            }
            spdlog::info("Sent closing market order {} for model {} reason {}", closing_order_id, pos.model_id, reason);
            // Fallback for closures: poll REST endpoint to capture fills if WebSocket fails
            {
                // Build a market order request for polling
                backpack::OrderRequest close_order_req;
                close_order_req.symbol = trading_symbol_;
                close_order_req.side = was_buy ? backpack::OrderSide::SELL : backpack::OrderSide::BUY;
                close_order_req.type = backpack::OrderType::MARKET;
                close_order_req.quantity = pos.size;
                close_order_req.price = price;
                close_order_req.time_in_force = backpack::TimeInForce::GTC;
                std::string model_id = pos.model_id;
                double associated_entry_price = pos.entry_price;
                std::thread([this, closing_order_id, close_order_req, model_id, associated_entry_price](){
                    this->poll_order_status(this->trading_symbol_, closing_order_id, close_order_req, model_id, associated_entry_price);
                }).detach();
            }
            // Skip removal here; position will be removed upon closure fill in WebSocket handler
            continue;
        }
    }
}

std::string DefaultExecutionClient::postOnlyMaker(bool is_buy, double size, double limit_price) {
    try {
        // Validate price against current market
        double current_bid = bestBid();
        double current_ask = bestAsk();

        // For post-only orders, ensure we're not crossing the spread
        if (is_buy && limit_price >= current_ask) {
            spdlog::warn("Post-only buy rejected: limit {} would cross ask {}", limit_price, current_ask);
            return "";
        }
        if (!is_buy && limit_price <= current_bid) {
            spdlog::warn("Post-only sell rejected: limit {} would cross bid {}", limit_price, current_bid);
            return "";
        }

        // Check risk limits
        if (!risk_manager_->checkRiskLimits(is_buy, size, limit_price)) {
            spdlog::warn("Order rejected by risk manager");
            return "";
        }

        // Create order request
        backpack::OrderRequest order;
        order.symbol = trading_symbol_;
        order.side = is_buy ? backpack::OrderSide::BUY : backpack::OrderSide::SELL;
        order.type = backpack::OrderType::LIMIT;
        order.quantity = size;
        order.price = limit_price;
        order.time_in_force = backpack::TimeInForce::GTC;

        // Place the order via Backpack SDK
        auto result = client_->create_order(order);
        
        if (!result.id.empty()) {
            spdlog::info("Post-only {} order placed: {} @ {}, order_id: {}", 
                is_buy ? "buy" : "sell", size, limit_price, result.id);
            return result.id;
        } else {
            spdlog::error("Order placement failed");
            return "";
        }
    } catch (const std::exception& e) {
        spdlog::error("Error in postOnlyMaker: {}", e.what());
        return "";
    }
}

void DefaultExecutionClient::setupSignalHandler() {
    std::signal(SIGINT, [](int) {
        spdlog::info("Received SIGINT, shutting down...");
        DefaultExecutionClient::getInstance().stop();
    });
}

void DefaultExecutionClient::onTrade(
    const std::string& symbol,
    double price,
    double quantity,
    uint64_t timestamp) {
    
    if (symbol != trading_symbol_) return;
    
    spdlog::debug("Trade: {} {} @ {} [{}]", 
        symbol, quantity, price, timestamp);
}

void DefaultExecutionClient::onKline(
    const std::string& symbol,
    const std::string& interval,
    double open,
    double high,
    double low,
    double close,
    double volume,
    uint64_t timestamp) {
    
    if (symbol != trading_symbol_) return;
    
    spdlog::debug("Kline: {} {} O:{} H:{} L:{} C:{} V:{} [{}]",
        symbol, interval, open, high, low, close, volume, timestamp);
}

std::string DefaultExecutionClient::send_market(
    const std::string& symbol,
    double quantity,
    bool is_buy,
    const OrderFlags& flags,
    const ConditionalOrderParams& cond_params,
    const std::string& model_id,
    std::optional<double> associated_entry_price) {
    double price = is_buy ? bestBid() : bestAsk();
    return send_limit(symbol, quantity, price, is_buy, TimeInForce::GTC, flags, cond_params, model_id, associated_entry_price);
}

std::string DefaultExecutionClient::send_limit(
    const std::string& symbol,
    double quantity,
    double price,
    bool is_buy,
    TimeInForce time_in_force,
    const OrderFlags& flags,
    const ConditionalOrderParams& cond_params,
    const std::string& model_id,
    std::optional<double> associated_entry_price) {
    OrderRequest order;
    order.symbol = symbol;
    order.side = is_buy ? OrderSide::BUY : OrderSide::SELL;
    order.type = OrderType::LIMIT;
    order.quantity = quantity;
    order.price = price;
    order.time_in_force = time_in_force;
    return send_order(order, flags, cond_params, model_id, associated_entry_price);
}

std::string DefaultExecutionClient::send_order(
    const OrderRequest& order_request,
    const OrderFlags& flags,
    const ConditionalOrderParams& cond_params,
    const std::string& model_id,
    std::optional<double> associated_entry_price) {
    
    if (!client_) {
        spdlog::error("BackpackClient not initialized in send_order.");
        return std::string();
    }

    try {
        // Start with the JSON from the basic OrderRequest (SDK's types.hpp)
        json j_params = order_request.to_json(); 
        // Remove clientOrderId to match server expectations (omit unknown keys)
        j_params.erase("clientOrderId");

        // Add strategy flags (postOnly, etc.)
        add_strategy_flags(j_params, flags); // This function already exists

        bool price_field_managed_by_post_only = false; // Flag to track if price was adjusted

        // For post-only orders, let's double-check that we're not trying to cross the spread
        // bool is_post_only = flags.post_only; // Already available via flags.post_only
        if (flags.post_only && order_request.type == OrderType::LIMIT && order_request.price > 0) {
            double current_bid = bestBid();
            double current_ask = bestAsk();
            
            bool would_cross = false;
            if (order_request.side == OrderSide::BUY && order_request.price >= current_ask && current_ask > 0) { // Added current_ask > 0 guard
                would_cross = true;
                spdlog::warn("Post-only buy order would cross the spread: price={}, current_ask={}", 
                             order_request.price, current_ask);
            } else if (order_request.side == OrderSide::SELL && order_request.price <= current_bid && current_bid > 0) { // Added current_bid > 0 guard
                would_cross = true;
                spdlog::warn("Post-only sell order would cross the spread: price={}, current_bid={}", 
                             order_request.price, current_bid);
            }
            
            if (would_cross) {
                // Adjust the price to be valid for post-only
                double adjusted_price;
                if (order_request.side == OrderSide::BUY) {
                    adjusted_price = current_ask - tick_size_; // Use class member tick_size_
                } else {
                    adjusted_price = current_bid + tick_size_; // Use class member tick_size_
                }
                adjusted_price = std::round(adjusted_price / tick_size_) * tick_size_; // Ensure it's on a tick boundary
                
                // Final safety check for adjusted price
                if ((order_request.side == OrderSide::BUY && adjusted_price >= current_ask && current_ask > 0) || 
                    (order_request.side == OrderSide::SELL && adjusted_price <= current_bid && current_bid > 0)) {
                    spdlog::error("Post-only price adjustment failed to place price passively. Original: {}, Adjusted: {}, Bid: {}, Ask: {}. Order will likely fail.", 
                                  order_request.price, adjusted_price, current_bid, current_ask);
                    // Potentially throw an error or return early to prevent sending a bad order
                } else {
                    spdlog::info("Adjusting post-only order price from {} to {} to avoid crossing the spread",
                                 order_request.price, adjusted_price);
                                 
                    // Update the price in the JSON params
                    j_params["price"] = format_double_to_string(adjusted_price, 2); // Using 2 decimal places as per prior logs, adjust if tick_size implies more
                    price_field_managed_by_post_only = true; // Mark that price was handled here
                }
            }
        }
        
        // Add conditional parameters from cond_params
        if (cond_params.stop_loss_trigger_price.has_value()) {
            j_params["stopLossTriggerPrice"] = format_double_to_string(cond_params.stop_loss_trigger_price.value(), 2);
            // As per API: if stopLossTriggerPrice is set, it's a market stop.
            // If stopLossLimitPrice were also set, it'd be a limit stop.
            // For now, only supporting stopLossTriggerPrice for market stop.
        }
        if (cond_params.take_profit_trigger_price.has_value()) {
            j_params["takeProfitTriggerPrice"] = format_double_to_string(cond_params.take_profit_trigger_price.value(), 2);
            // Similarly, this would make it a market take profit order.
        }
        if (cond_params.stop_loss_limit_price.has_value()) {
            j_params["stopLossLimitPrice"] = format_double_to_string(cond_params.stop_loss_limit_price.value(), 2);
        }
        if (cond_params.take_profit_limit_price.has_value()) {
            j_params["takeProfitLimitPrice"] = format_double_to_string(cond_params.take_profit_limit_price.value(), 2);
        }

        // Add this logic:
        if (cond_params.stop_loss_trigger_price.has_value() || cond_params.take_profit_trigger_price.has_value()) {
            // Conditional orders (stops/take profits) should generally be GTC.
            // If the original TIF was IOC for a market entry that now has a stop, change it to GTC.
            bool tif_overridden = false;
            if (j_params.contains("timeInForce")) {
                if (order_request.type == OrderType::MARKET && j_params["timeInForce"] == "IOC") {
                    j_params["timeInForce"] = "GTC"; // Good Till Cancelled
                    tif_overridden = true;
                }
            } else {
                // If no TIF was set explicitly in the order_request for a conditional order, default to GTC
                j_params["timeInForce"] = "GTC";
                tif_overridden = true;
            }
            if (tif_overridden) {
                spdlog::debug("Adjusted TimeInForce to GTC for conditional order.");
            }
        }

        // The user's API doc shows side as "Bid" or "Ask", orderType as "Market" or "Limit"
        // The SDK's order_request.to_json() uses order_side_to_string and order_type_to_string.
        // We need to ensure these map correctly or override them if necessary.
        // bp::order_side_to_string converts OrderSide::BUY to "buy", OrderSide::SELL to "sell".
        // The API expects "Bid" for buy, "Ask" for sell. This needs alignment.
        if (j_params.contains("side")) {
            if (order_request.side == OrderSide::BUY) j_params["side"] = "Bid";
            else if (order_request.side == OrderSide::SELL) j_params["side"] = "Ask";
        }
        // bp::order_type_to_string converts OrderType::MARKET to "market", OrderType::LIMIT to "limit"
        // The API expects "Market" or "Limit" (capitalized).
        if (j_params.contains("type")) {
            if (order_request.type == OrderType::MARKET) j_params["type"] = "Market";
            else if (order_request.type == OrderType::LIMIT) j_params["type"] = "Limit";
        }
        
        // Quantity and Price should be strings per API doc. to_json() from SDK already does this.
        // j_params["quantity"] = format_price(order_request.quantity); // Ensure correct formatting if SDK's to_string isn't sufficient
        // if (order_request.price > 0) j_params["price"] = format_price(order_request.price);
        // The SDK's OrderRequest::to_json uses std::to_string which might not have enough precision.
        // Overriding them here using format_double_to_string for consistency and control, if they exist.
        if (j_params.contains("quantity")) {
             j_params["quantity"] = format_double_to_string(order_request.quantity, 2); // Assuming 2 decimal for quantity based on logs, adjust as needed
        }
        if (!price_field_managed_by_post_only && j_params.contains("price") && order_request.price > 0.0) { // Only format price if it was set AND NOT already managed
             j_params["price"] = format_double_to_string(order_request.price, 2); // Using 2 decimal places, adjust if tick_size implies more
        }

        // Correctly set orderType field name and value
        // The Backpack API expects "orderType" not "type"
        if (j_params.contains("type")) { 
            // Assuming order_request.type is the definitive source from our internal enum
            j_params.erase("type"); // Remove the old "type" field generated by OrderRequest::to_json()
        }
        // Always set orderType based on our internal enum, ensuring correct capitalization
        if (order_request.type == OrderType::MARKET) {
            j_params["orderType"] = "Market";
        } else if (order_request.type == OrderType::LIMIT) {
            j_params["orderType"] = "Limit";
        } else {
            spdlog::error("Unhandled bp::OrderType in send_order. Cannot set orderType for JSON payload.");
            // Potentially throw or return error as this is a critical missing field for the API
        }

        spdlog::debug("Sending order JSON: {}", j_params.dump(4));

        // client_->create_order expects backpack::OrderRequest, which we've used to create j_params.
        // However, the actual sending mechanism seems to be execute_signed_request in this class.
        json response_json = execute_signed_request(RestClass::TRADE, "POST", "/api/v1/order", "orderExecute", j_params);
        
        spdlog::info("Order execution response: {}", response_json.dump(4));
        
        std::string order_id = response_json.value("orderId", "");
        if (order_id.empty() && response_json.contains("id")) {
            order_id = response_json.value("id", "");
        }

        if (!order_id.empty()) {
            // Log order sent event for ML reward system
            {
                std::string trade_id;
                {
                    std::lock_guard<std::mutex> lock(trade_state_mutex_);
                    auto it = trade_id_map_.find(model_id);
                    trade_id = (it != trade_id_map_.end() ? it->second : generate_uuid_v4());
                }
                TradeEventData order_event;
                order_event.trade_id = trade_id;
                order_event.event_id = generate_uuid_v4();
                order_event.event_timestamp = std::chrono::duration_cast<std::chrono::milliseconds>(
                                            std::chrono::system_clock::now().time_since_epoch()).count();
                order_event.event_type = TradeEventType::ENTRY_ORDER_SENT;
                order_event.model_id = model_id;
                order_event.trading_symbol = order_request.symbol;
                order_event.order_id = order_id;
                order_event.client_order_id = model_id;
                order_event.price = order_request.price;
                order_event.quantity = order_request.quantity;
                order_event.side = order_side_to_string(order_request.side);
                order_event.market_bid_at_event = bestBid();
                order_event.market_ask_at_event = bestAsk();
                log_trade_event(order_event);
            }
            // Predicted circuit breaker: count current open orders + new one
            {
                std::size_t count = 0;
                {
                    std::lock_guard<std::mutex> lock(openOrdersMutex_);
                    for (auto &p : openOrders_) {
                        if (p.second.symbol == order_request.symbol) {
                            count++;
                        }
                    }
                }
                if (count + 1 >= MAX_OPEN_ORDERS) {
                    spdlog::warn("Predicted circuit breaker triggered: open orders {} + new >= {}. Cancelling all for symbol {}", 
                                 count, MAX_OPEN_ORDERS, order_request.symbol);
                    cancelAllOrdersForSymbol(order_request.symbol);
                }
            }

            // Existing WebSocket vs polling logic follows
            if (ws_connected_.load(std::memory_order_relaxed) && ws_orders_initialized_) {
                spdlog::info("WebSocket is active. Order {} for symbol {} will be tracked via WebSocket stream.", order_id, order_request.symbol);
            } else {
                // fallback polling...
            }
        } else {
            spdlog::error("Order ID not found in response for instruction orderExecute. Cannot monitor order status.");
        }

        return order_id;

    } catch (const std::exception& e) {
        spdlog::error("Error sending order: {}", e.what());
        // TODO: Handle order sending failure (e.g., retry or report)
        throw; // Re-throw the caught exception
    }
}

void DefaultExecutionClient::add_strategy_flags(json& params, const OrderFlags& flags) const {
    if (flags.post_only) {
        params["postOnly"] = true;
    }
    if (flags.reduce_only) {
        // This flag is specific to futures on some exchanges, ensure it's applicable
        params["reduceOnly"] = true; 
    }
    // Add other flags like autoBorrow, selfTradePrevention as needed, mapping to correct API fields
    // Example for selfTradePrevention (ensure enum matches API string values)
    // if (flags.self_trade_prevention != SelfTradePrevention::NONE) {
    //     params["selfTradePrevention"] = self_trade_prevention_to_string(flags.self_trade_prevention);
    // }
}

std::string DefaultExecutionClient::sign_request(const std::string& signing_string) const {
    if (base64_private_key_.empty()) {
        spdlog::error("API secret (base64 private key) not set for signing.");
        return "";
    }

    // Delegate to the SDK's utility function
    // This function is declared in <backpack/utils.hpp> and defined in the SDK's utils.cpp
    // It should already be available as exec_bridge.cpp includes <backpack/backpack_client.hpp>
    // which in turn should include <backpack/utils.hpp>.
    return backpack::generate_ed25519_signature(base64_private_key_, signing_string);
}

// FIRST_EDIT: add rate-limiter, backoff and instrumentation utilities
#include <atomic>
#include <random>
#include <algorithm>
#include <chrono>
#include <time.h>
#include <errno.h> // For strerror with clock_nanosleep

#if 0 // prevent duplicate definition; already in header exec_bridge.hpp
// Define RestClass and TokenBucket
enum class RestClass : uint8_t {
    TRADE,          // Order placement, cancellation
    ORDER_QUERY,    // Order status polling
    META            // Balance checks, other non-critical info
};
#endif

// Forward declaration for now_mono_us and precise_sleep_us if they are defined later
// but they are inline and defined before the buckets, so it should be fine.
inline uint64_t now_mono_us();
void precise_sleep_us(uint64_t us);


struct TokenBucket {
    std::atomic<uint64_t> next_slot_us;
    uint32_t              rate_rps; // Not atomic, initialized once
};

// Removed old global rate limiter atomics:
// static std::atomic<uint64_t> global_next_slot_us{...};
// static std::atomic<uint32_t> throttle_rate_rps{25};
// static std::atomic<uint64_t> total_requests{0}; // Will be replaced by sum of bucket counts or new global logic if needed
// static std::atomic<uint64_t> throttled_requests{0}; // Same as above

// Existing global metrics for RETRY LOGIC (429 handling) remain:
static std::atomic<uint64_t> backoff_events{0};
// ... (other retry-related atomics: retry_elapsed_ms_sum, max_retries_config, base_backoff_ms_config, jitter_frac_config, max_backoff_ms_config)

static std::atomic<uint64_t> retry_elapsed_ms_sum{0};
static std::atomic<uint32_t> max_retries_config{3};
static std::atomic<double> base_backoff_ms_config{100.0};
static std::atomic<double> jitter_frac_config{0.2};
static std::atomic<double> max_backoff_ms_config{1000.0};

static TokenBucket buckets[] = {
    {0, 12}, // TRADE (next_slot_us initially 0, rate_rps) - Reduced from 25
    {0, 3},  // ORDER_QUERY - Further reduced from 7 (was 15)
    {0, 5}   // META
};

// New rate_limit function taking RestClass
inline void rate_limit(RestClass cls) {
    auto &bucket = buckets[static_cast<uint8_t>(cls)];
    uint64_t time_to_wait_us;

    uint64_t current_time_snapshot = now_mono_us(); // Take a snapshot of current time for this operation

    // Atomically reserve the next slot
    uint64_t reserved_slot_start_time; // This will be the time our request is scheduled to run

    uint64_t previous_next_slot_val = bucket.next_slot_us.load(std::memory_order_acquire);
    while (true) {
        // Determine when this request *should* run:
        // If previous_next_slot_val is in the past, our request can run 'now' (current_time_snapshot).
        // If previous_next_slot_val is in the future, our request must wait until that time.
        uint64_t candidate_slot_start_time = std::max(current_time_snapshot, previous_next_slot_val);
        
        // Calculate what the next_slot_us should be if we successfully claim candidate_slot_start_time
        uint64_t next_slot_if_cas_succeeds = candidate_slot_start_time + (1'000'000 / bucket.rate_rps);

        // Attempt to atomically update next_slot_us from its previous value to our new calculated value.
        // If previous_next_slot_val has changed since we loaded it (i.e., another thread updated it),
        // CAS will fail, previous_next_slot_val will be updated with the *new* current value from the atomic,
        // and we'll loop to recalculate.
        if (bucket.next_slot_us.compare_exchange_weak(previous_next_slot_val, // Expected current value
                                                      next_slot_if_cas_succeeds,   // Value to set if expected matches
                                                      std::memory_order_release,
                                                      std::memory_order_relaxed)) {
            // CAS succeeded: we've "reserved" candidate_slot_start_time
            reserved_slot_start_time = candidate_slot_start_time;
            break; 
        }
        // CAS failed: previous_next_slot_val is now updated with the current value in bucket.next_slot_us.
        // Loop again to contend for the new slot.
    }

    // Calculate how long to sleep, if at all
    if (reserved_slot_start_time > current_time_snapshot) {
        time_to_wait_us = reserved_slot_start_time - current_time_snapshot;
        precise_sleep_us(time_to_wait_us);
    }
    // No sleep needed if reserved_slot_start_time was current_time_snapshot
}


// ... existing code ...
// static std::atomic<double> max_backoff_ms_config{1000.0}; // This line is part of retry logic, ensure it's not removed if it was after old rate_limit atomics

inline uint64_t now_mono_us() { // Ensure this is defined before TokenBucket usage if not already
    return std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

void precise_sleep_us(uint64_t us) {
    if (us == 0) return; // No need to sleep for 0 microseconds
    spdlog::debug("precise_sleep_us: called for {} µs", us); // Added detailed log for sleep call itself
    const uint64_t spin_threshold = 20; // microseconds
    uint64_t start = now_mono_us();
    if (us <= spin_threshold) {
        while (now_mono_us() - start < us);
    } else {
        while (now_mono_us() - start < spin_threshold);
        uint64_t sleep_us = us - spin_threshold;
#if defined(__APPLE__)
        std::this_thread::sleep_for(std::chrono::microseconds(sleep_us));
#else
        struct timespec req{};
        req.tv_sec = sleep_us / 1000000;
        req.tv_nsec = (sleep_us % 1000000) * 1000;
        // For relative sleep, flags should be 0. TIMER_ABSTIME is for absolute time.
        if (clock_nanosleep(CLOCK_MONOTONIC, 0, &req, nullptr) != 0) {
            spdlog::error("clock_nanosleep failed for {} us: {}", sleep_us, strerror(errno));
        }
#endif
    }
}

// REMOVE old inline void rate_limit() { ... } function entirely.
// The apply model should be smart enough to remove the old rate_limit() function
// that takes no arguments, as it's replaced by rate_limit(RestClass cls).

// SECOND_EDIT should now be:
// Modify execute_signed_request to use new rate_limit(RestClass)
json DefaultExecutionClient::execute_signed_request(
    RestClass rest_class, 
    const std::string& http_method,
    const std::string& endpoint,
    const std::string& instruction, 
    const json& params
) const {
    rate_limit(rest_class); 
    uint32_t max_retries = max_retries_config.load(std::memory_order_relaxed);
    double base_backoff_ms = base_backoff_ms_config.load(std::memory_order_relaxed);
    double jitter_frac = jitter_frac_config.load(std::memory_order_relaxed);
    double max_backoff_ms = max_backoff_ms_config.load(std::memory_order_relaxed);

    for (uint32_t attempt = 0; ; ++attempt) {
        auto now = std::chrono::system_clock::now();
        long long timestamp_ms = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count();
        std::string timestamp_str = std::to_string(timestamp_ms);
        std::string window_str = "5000"; 

        std::string params_component_for_sig; // Will hold "key1=value1&key2=value2..."
        std::string string_to_sign;
        std::string actual_http_request_body; // For POST/PUT, this will be the JSON string

        // Check if this is a DELETE request to /api/v1/order, which needs special body handling for params
        bool is_delete_single_order = (http_method == "DELETE" && endpoint == "/api/v1/order");

        // 1. Construct params_component_for_sig (flattened, sorted key-value string)
        //    This component is the same whether params come from a GET query or a POST/PUT/DELETE-with-body body.
        if (!params.is_null() && params.is_object() && !params.empty()) {
            params_component_for_sig = json_to_sorted_query_string(params);
        }

        // 2. Construct string_to_sign: instruction first, then params, then timestamp & window
        string_to_sign = "instruction=" + instruction;
        if (!params_component_for_sig.empty()) {
            string_to_sign += "&" + params_component_for_sig;
        }
        string_to_sign += "&timestamp=" + timestamp_str;
        string_to_sign += "&window=" + window_str;

        // 3. Determine actual_http_request_body
        // Body is for POST, PUT, and DELETE requests (Backpack API expects JSON payload for DELETE).
        // GET requests MUST have an empty body.
        if (http_method == "POST" || http_method == "PUT" || http_method == "DELETE") {
            if (!params.is_null() && params.is_object()) {
                actual_http_request_body = params.dump(-1, ' ', false, nlohmann::json::error_handler_t::strict);
            } else {
                actual_http_request_body = "{}"; // Default empty JSON object for body
                spdlog::warn("[exec_bridge] Params for {} to {} instruction '{}' was null/non-object. Sending '{{}}' as body.", http_method, endpoint, instruction);
            }
        }
        // For GET, actual_http_request_body remains empty by default.
        
        spdlog::debug("[exec_bridge] String to sign for instruction '{}': {}", instruction, string_to_sign);
        std::string signature = sign_request(string_to_sign); 

        if (signature.empty()) {
            spdlog::error("Failed to sign request for instruction: {}", instruction);
            throw std::runtime_error("Failed to sign request.");
        }

        CURL* curl = curl_easy_init();
        std::string read_buffer;
        std::string header_buffer; // To store response headers
        long http_response_code = 0;
        const std::string base_url = "https://api.backpack.exchange";

        std::string query_params_for_get_delete_url_str; // Only for GET URL

        // Determine request body and if Content-Type is needed
        // std::string request_body_payload_str; // Replaced by actual_http_request_body
        bool should_send_content_type = false;

        if (http_method == "GET") {
            // For GET requests, params (if any) go into the query string.
            query_params_for_get_delete_url_str = params_component_for_sig; 
        }
        // For POST/PUT/DELETE, query_params_for_get_delete_url_str remains empty; params are in the body.

        if (curl) {
            std::string full_url = base_url + endpoint;
            if (!query_params_for_get_delete_url_str.empty()) { // This condition ensures only relevant GET/DELETEs append query string
                full_url += "?" + query_params_for_get_delete_url_str;
            }
            
            spdlog::debug("Request URL: {}", full_url);
            curl_easy_setopt(curl, CURLOPT_URL, full_url.c_str());
            curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, WriteCallback);
            curl_easy_setopt(curl, CURLOPT_WRITEDATA, &read_buffer);
            curl_easy_setopt(curl, CURLOPT_HEADERFUNCTION, HeaderCallback);
            curl_easy_setopt(curl, CURLOPT_HEADERDATA, &header_buffer);
            curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, 10000L); 

            struct curl_slist* headers = NULL;
            headers = curl_slist_append(headers, ("X-API-Key: " + api_key_).c_str());
            headers = curl_slist_append(headers, ("X-Timestamp: " + timestamp_str).c_str());
            headers = curl_slist_append(headers, ("X-Window: " + window_str).c_str());
            headers = curl_slist_append(headers, ("X-Signature: " + signature).c_str());
            headers = curl_slist_append(headers, ("X-BP-Instruction: " + instruction).c_str());
            
            // Configure method, body, and Content-Type
            if (http_method == "POST" || http_method == "PUT") {
                should_send_content_type = true; // POST/PUT get Content-Type: application/json
                
                if (http_method == "POST") {
                    curl_easy_setopt(curl, CURLOPT_POST, 1L);
                } else { // PUT
                    curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, "PUT");
                }
                curl_easy_setopt(curl, CURLOPT_POSTFIELDS, actual_http_request_body.c_str());
                spdlog::debug("{} body: {}", http_method, actual_http_request_body);

            } else if (http_method == "DELETE") {
                should_send_content_type = true; // Backpack API requires Content-Type even for DELETE
                curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, "DELETE");
                // Backpack API expects JSON payload in the body for DELETE requests
                curl_easy_setopt(curl, CURLOPT_POSTFIELDS, actual_http_request_body.c_str());
                spdlog::debug("DELETE request for {}. Body: {}", endpoint, actual_http_request_body);
            }
            // For GET, no special body/method options needed beyond URL.

            if (should_send_content_type) {
                headers = curl_slist_append(headers, "Content-Type: application/json");
            } else {
                // Ensure Content-Type is NOT sent for GET requests only
            }

            curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);

            CURLcode res = curl_easy_perform(curl);
            if (res != CURLE_OK) {
                spdlog::error("curl_easy_perform() failed: {}", curl_easy_strerror(res));
                curl_slist_free_all(headers);
                curl_easy_cleanup(curl);
                throw std::runtime_error(std::string("CURL request failed: ") + curl_easy_strerror(res));
            }

            curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http_response_code);
            spdlog::info("HTTP Response Code: {}", http_response_code);
            spdlog::debug("Response Headers:\n{}", header_buffer); // Log all headers in debug
            spdlog::info("Response Body: {}", read_buffer);

            curl_slist_free_all(headers);
            curl_easy_cleanup(curl);

            if (http_response_code >= 200 && http_response_code < 300) {
                if (read_buffer.empty() && http_response_code != 204) { 
                     spdlog::warn("Successful HTTP response {} but empty body.", http_response_code);
                     return nlohmann::json::object(); 
                }
                try {
                     if (read_buffer.empty() && http_response_code == 204) { 
                        return nlohmann::json::object(); 
                     }
                    return nlohmann::json::parse(read_buffer);
                } catch (const nlohmann::json::parse_error& e) {
                    spdlog::error("JSON parse error: {}. Response: {}", e.what(), read_buffer);
                    throw; 
                }
            } else if (http_response_code == 429) {
                spdlog::warn("Rate limit hit (429). Response Headers:\n{}", header_buffer); // Log headers on 429
                backoff_events.fetch_add(1, std::memory_order_relaxed);
                long ra = 0;
                try {
                    auto ej = json::parse(read_buffer);
                    if (ej.contains("retry_after")) ra = ej["retry_after"].get<long>();
                } catch(...) {}
                if (ra > 0) {
                    precise_sleep_us(ra * 1000);
                    retry_elapsed_ms_sum.fetch_add(ra, std::memory_order_relaxed);
                } else {
                    thread_local static std::mt19937 rng{std::random_device{}()};
                    std::uniform_real_distribution<double> dist(-jitter_frac, jitter_frac);
                    double jitter = 1.0 + dist(rng);
                    double sleep_ms = std::clamp(base_backoff_ms * std::pow(2.0, attempt) * jitter,
                                                1.0, max_backoff_ms);
                    precise_sleep_us(static_cast<uint64_t>(sleep_ms * 1000));
                    retry_elapsed_ms_sum.fetch_add(static_cast<uint64_t>(sleep_ms), std::memory_order_relaxed);
                }
                if (attempt >= max_retries)
                    throw std::runtime_error("Max retries exceeded due to rate limiting");
                continue;
            } else {
                spdlog::error("HTTP Error {}: {}\nResponse Headers:\n{}", http_response_code, read_buffer, header_buffer);
                try {
                    nlohmann::json error_json = nlohmann::json::parse(read_buffer);
                    error_json["http_status_code"] = http_response_code; 
                    throw std::runtime_error("API Error: " + error_json.dump());
                } catch (const nlohmann::json::parse_error& ) {
                    throw std::runtime_error("API Error (non-JSON response): " + std::to_string(http_response_code) + " - " + read_buffer);
                }
            }
        } else {
            spdlog::error("Failed to initialize CURL");
            throw std::runtime_error("Failed to initialize CURL");
        }
    }
}

nlohmann::json DefaultExecutionClient::query_balances() {
    spdlog::info("Querying account balances...");
    return execute_signed_request(RestClass::META, "GET", "/api/v1/capital", "balanceQuery", json::object());
}

bool DefaultExecutionClient::cancel_order(const std::string& symbol, const std::string& order_id) {
    spdlog::info("Attempting to cancel order ID {} for symbol {}", order_id, symbol);
    json params{{"symbol", symbol},{"orderId", order_id}};
    try {
        execute_signed_request(RestClass::TRADE, "DELETE", "/api/v1/order", "orderCancel", params);
        return true;
    } catch (const std::exception& e) {
        spdlog::error("Failed to cancel order ID {}: {}", order_id, e.what());
        return false;
    }
}

// Correct implementation for cancel_all_orders
int DefaultExecutionClient::cancel_all_orders(const std::string& symbol) {
    spdlog::info("Attempting to cancel all orders for symbol: {}", symbol.empty() ? "all symbols" : symbol);
    json params;
    if (!symbol.empty()) params["symbol"] = symbol;
    try {
        json response = execute_signed_request(RestClass::TRADE, "DELETE", "/api/v1/orders", "orderCancelAll", params);
        spdlog::info("Cancel all orders response: {}", response.dump(4));
        return response.is_array() ? response.size() : response.value("count", 1);
    } catch (const std::exception& e) {
        spdlog::error("Failed to cancel all orders for symbol {}: {}", symbol, e.what());
        return 0;
    }
}

void DefaultExecutionClient::process_fill_response(
    const json& fill_response,
    const OrderRequest& original_order, // Removed [[maybe_unused]]
    const std::string& model_id,
    std::optional<double> associated_entry_price [[maybe_unused]]) { // Marked as maybe_unused

    std::string trade_id_for_logging;
    {
        std::lock_guard<std::mutex> lock(trade_state_mutex_);
        auto it = trade_id_map_.find(model_id);
        if (it != trade_id_map_.end()) {
            trade_id_for_logging = it->second;
        } else {
            spdlog::warn("[process_fill_response] model_id '{}' not found in trade_id_map_. Generating a new trade_id for this fill log.", model_id);
            trade_id_for_logging = generate_uuid_v4(); // Fallback, should ideally not happen if signal was logged
        }
    }

    // Calculate average fill price and total filled quantity from the response
    double total_filled_qty_from_response = 0.0;
    double weighted_price_sum = 0.0;
    std::string order_id_from_response = fill_response.value("orderId", "");
    if (order_id_from_response.empty()){
        order_id_from_response = fill_response.value("id", ""); // some exchanges use "id"
    }


    // Attempt to get current BBO
    std::optional<double> current_market_bid = std::nullopt;
    std::optional<double> current_market_ask = std::nullopt;
    try {
        BBO current_bbo{bestBid(), bestAsk()}; // Assuming this function exists
        current_market_bid = current_bbo.bid;
        current_market_ask = current_bbo.ask;
    } catch (const std::exception& e) {
        spdlog::warn("Could not fetch BBO for {} in process_fill_response: {}", original_order.symbol, e.what());
    }


    if (fill_response.contains("fills") && fill_response["fills"].is_array()) {
        for (const auto& fill : fill_response["fills"]) {
            double qty = json_get_double(fill, "qty", 0.0);
            double price = json_get_double(fill, "price", 0.0);
            if (qty > 0.0) {
                total_filled_qty_from_response += qty;
            weighted_price_sum += price * qty;

                TradeEventData fill_event;
                fill_event.trade_id = trade_id_for_logging;
                fill_event.event_id = generate_uuid_v4();
                fill_event.event_timestamp = json_get_int64(fill, "timestamp", // Use fill specific timestamp if available
                                    std::chrono::duration_cast<std::chrono::milliseconds>(
                                        std::chrono::system_clock::now().time_since_epoch()
                                    ).count());
                fill_event.event_type = TradeEventType::ENTRY_ORDER_PARTIALLY_FILLED; // Log each as partial
                fill_event.model_id = model_id;
                fill_event.trading_symbol = original_order.symbol;
                fill_event.order_id = order_id_from_response; // Use orderId from overall response
                fill_event.client_order_id = model_id;
                fill_event.price = price;
                fill_event.filled_quantity = qty;
                fill_event.quantity = original_order.quantity; // Original order quantity
                fill_event.side = (original_order.side == backpack::OrderSide::BUY) ? "BUY" : "SELL";
                fill_event.market_bid_at_event = current_market_bid;
                fill_event.market_ask_at_event = current_market_ask;
                // additional_data could include fill["tradeId"] if available and distinct
                json additional_fill_data;
                if (fill.contains("tradeId")) additional_fill_data["exchange_fill_id"] = fill["tradeId"];
                if (fill.contains("commission")) additional_fill_data["commission"] = fill["commission"];
                if (fill.contains("commissionAsset")) additional_fill_data["commissionAsset"] = fill["commissionAsset"];
                fill_event.additional_data = additional_fill_data;

                log_trade_event(fill_event);
            }
        }
    }
    double avg_price = total_filled_qty_from_response > 0.0 ? weighted_price_sum / total_filled_qty_from_response : 0.0;
    spdlog::info("Model {} filled via REST poll: order_id='{}', avg_price={}, total_qty={}", model_id, order_id_from_response, avg_price, total_filled_qty_from_response);

    // Log a final ENTRY_ORDER_FILLED event if the order is fully filled based on response status or quantity
    // The `fill_response` itself should have a status.
    std::string overall_status = fill_response.value("status", "");
    bool is_fully_filled = (overall_status == "FILLED");
    // As a fallback, if status isn't "FILLED", but total_filled_qty_from_response >= original_order.quantity, consider it filled.
    // This needs care due to potential precision issues with doubles. Use a small epsilon.
    if (!is_fully_filled && total_filled_qty_from_response > 0 && 
        std::abs(total_filled_qty_from_response - original_order.quantity) < 1e-9) { // 1e-9 is a common epsilon for double comparison
        is_fully_filled = true; 
        spdlog::info("Order for model_id {} considered fully filled by quantity comparison ({} vs {})", model_id, total_filled_qty_from_response, original_order.quantity);
    }


    if (is_fully_filled && total_filled_qty_from_response > 0) { // Only log if there were actual fills
        TradeEventData final_fill_event;
        final_fill_event.trade_id = trade_id_for_logging;
        final_fill_event.event_id = generate_uuid_v4();
        final_fill_event.event_timestamp = std::chrono::duration_cast<std::chrono::milliseconds>(
                                        std::chrono::system_clock::now().time_since_epoch()
                                    ).count(); // Timestamp of this aggregation event
        final_fill_event.event_type = TradeEventType::ENTRY_ORDER_FILLED;
        final_fill_event.model_id = model_id;
        final_fill_event.trading_symbol = original_order.symbol;
        final_fill_event.order_id = order_id_from_response;
        final_fill_event.client_order_id = model_id;
        final_fill_event.price = avg_price; // Average price of all fills
        final_fill_event.filled_quantity = total_filled_qty_from_response; // Total filled quantity
        final_fill_event.quantity = original_order.quantity; // Original order quantity
        final_fill_event.side = (original_order.side == backpack::OrderSide::BUY) ? "BUY" : "SELL";
        final_fill_event.market_bid_at_event = current_market_bid; // BBO at the time of this aggregation
        final_fill_event.market_ask_at_event = current_market_ask;
        // Additional data could summarize number of partial fills, etc.
        json additional_summary_data;
        if (fill_response.contains("fills")) additional_summary_data["num_partial_fills"] = fill_response["fills"].size();
        final_fill_event.additional_data = additional_summary_data;
        log_trade_event(final_fill_event);
    }


    // Update active position with fill details (existing logic)
    if (avg_price > 0.0 && total_filled_qty_from_response > 0.0) { // Ensure meaningful values before updating
        std::lock_guard<std::mutex> lock(trade_state_mutex_);
        auto it = active_positions_.find(model_id);
        if (it != active_positions_.end()) {
            // If accumulating fills, update average price and total quantity carefully
            // For now, this assumes process_fill_response is for a terminal fill state or first major fill
            it->second.entry_price = avg_price;
            it->second.quantity = total_filled_qty_from_response; 
            spdlog::info("Active position for model_id {} updated: entry_price={}, quantity={}", model_id, avg_price, total_filled_qty_from_response);
        } else {
            // This case might happen if the order was placed but position wasn't created yet, or if this is an exit.
            // For entry fills, a position should ideally exist from process_new_ml_signal or send_order.
            // If it's an exit fill, new logic would be needed. For now, log a warning.
             spdlog::warn("[process_fill_response] Active position for model_id '{}' not found when trying to update fill details.", model_id);
        }
    }
}

void DefaultExecutionClient::poll_order_status(
    std::string symbol,
    std::string order_id,
    OrderRequest original_order,
    std::string model_id,
    std::optional<double> associated_entry_price) {
    
    // Check if this order_id is already known to be missing
    {
        std::lock_guard<std::mutex> lock(missing_order_ids_mutex_);
        if (recently_missing_order_ids_.count(order_id)) {
            spdlog::info("Order {} is known to be missing (previously 404'd), skipping polling.", order_id);
            return; // Avoid polling for an order known to be gone
        }
    }
    
    static constexpr int MAX_POLL_ATTEMPTS = 3; // Maximum number of polling attempts
    static constexpr int64_t MAX_ORDER_AGE_MS = 5 * 60 * 1000; // 5 minutes
    bool order_age_checked = false; // To ensure we only check age once after getting createdAt
    int poll_attempts = 0; // Poll attempt counter

    // Poll until status is Filled or Canceled
    json params;
    params["symbol"] = symbol;
    params["orderId"] = order_id;

    while (true) {
        // The rate_limit call within execute_signed_request will handle pacing for ORDER_QUERY.

        try {
            json response = execute_signed_request(RestClass::ORDER_QUERY, "GET", "/api/v1/order", "orderQuery", params);
            std::string status = response.value("status", "");

            // Check order age after first successful retrieval
            if (!order_age_checked && response.contains("createdAt")) {
                int64_t created_at_ts = json_get_int64(response, "createdAt", 0);
                if (created_at_ts > 0) {
                    int64_t current_system_time_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                                                        std::chrono::system_clock::now().time_since_epoch()
                                                     ).count();
                    if ((current_system_time_ms - created_at_ts) > MAX_ORDER_AGE_MS) {
                        spdlog::warn("Order {} (created at {} UTC ms) is older than max age ({} ms). Stopping polling.", 
                                     order_id, created_at_ts, MAX_ORDER_AGE_MS);
                        break; // Stop polling this very old order
                    }
                }
                order_age_checked = true; // Mark as checked, regardless of whether it was old enough to stop
            }

            if (status == "FILLED" || status == "CANCELED") {
                spdlog::info("Order {} status: {}", order_id, status);
                if (status == "FILLED") {
                    process_fill_response(response, original_order, model_id, associated_entry_price);
                }
                break; // Terminal state
            }
        } catch (const std::exception& e) {
            std::string error_what = e.what();
            // Replace old 404 handling block with robust conditions
            // Terminate polling on 404 or resource not found
            if (error_what.find("\"http_status_code\":404") != std::string::npos ||
                error_what.find("HTTP Error 404") != std::string::npos ||
                error_what.find("\"code\":\"RESOURCE_NOT_FOUND\"") != std::string::npos ||
                error_what.find("Order not found") != std::string::npos) {
                spdlog::info("Order {} not found or received 404, marking as terminal for polling.", order_id);
                // Add to cache of missing orders
                {
                    std::lock_guard<std::mutex> lock(missing_order_ids_mutex_);
                    recently_missing_order_ids_.insert(order_id);
                }
                break;
            }
            spdlog::error("Error polling order status for {}: {}", order_id, error_what);
        }
        
        poll_attempts++; // Increment poll counter
        if (poll_attempts >= MAX_POLL_ATTEMPTS) { // Check attempts after incrementing
            spdlog::warn("Reached maximum poll attempts ({}) for order {}, stopping polling", MAX_POLL_ATTEMPTS, order_id);
            break; // Exit loop if max attempts reached
        }
    }
}

// Helper for formatting quantity to minimum step size
double DefaultExecutionClient::format_quantity(double qty) const {
    // Truncate down to nearest min_qty_
    if (min_qty_ <= 0.0) return qty;
    double steps = std::floor(qty / min_qty_);
    return steps * min_qty_;
}

// Build ladder entry orders with fallback retries
void DefaultExecutionClient::attempt_ladder_entry_order_with_fallback(
    const MlSignalPayload& pos_candidate,
    const BBO& current_bbo) {
    int num_levels = 3;
    double total_qty = pos_candidate.order_quantity_config;
    double qty_per_level = total_qty / num_levels;
    qty_per_level = format_quantity(qty_per_level);
    if (qty_per_level <= 0.0) {
        spdlog::error("Calculated level quantity <= 0, cannot ladder: {} / {}", total_qty, num_levels);
        return;
    }
    std::vector<std::string> placed_ids;
    for (int attempt = 0; attempt < MAX_FALLBACK_ATTEMPTS; ++attempt) {
        bool any_success = false;
        double last_level_price = 0.0;
        int safety_buffer = attempt * FALLBACK_SAFETY_TICK_INCREMENT;
        for (int lvl = 1; lvl <= num_levels; ++lvl) {
            int ticks = lvl + safety_buffer;
            double raw_price = (pos_candidate.signal_action == 1)
                ? (current_bbo.bid - ticks * tick_size_)
                : (current_bbo.ask + ticks * tick_size_);
            double lvl_price = std::round(raw_price / tick_size_) * tick_size_;
            if (lvl_price <= 0.0) {
                spdlog::error("Level {} price <=0 after rounding: {}", lvl, lvl_price);
                continue;
            }
            last_level_price = lvl_price;
            // Build JSON params
            json j;
            j["symbol"] = trading_symbol_;
            j["side"] = (pos_candidate.signal_action == 1) ? "Bid" : "Ask";
            j["orderType"] = "Limit";
            j["quantity"] = format_double_to_string(qty_per_level, 8);
            j["price"] = format_double_to_string(lvl_price, 8);
            j["timeInForce"] = "GTC";
            spdlog::info("Ladder attempt {} level {}: qty {} price {}", attempt, lvl, qty_per_level, lvl_price);
            try {
                json resp = execute_signed_request(RestClass::TRADE, "POST", "/api/v1/order", "orderExecute", j);
                std::string oid = resp.value("orderId", resp.value("id", ""));
                if (!oid.empty()) {
                    placed_ids.push_back(oid);
                    any_success = true;
                } else {
                    spdlog::error("No orderId returned for ladder level {} on attempt {}", lvl, attempt);
                }
            } catch (const std::exception& e) {
                spdlog::error("Error sending ladder level {} on attempt {}: {}", lvl, attempt, e.what());
            }
        }
        if (any_success) {
            // persist active position
            ActivePosition ap;
            ap.model_id = pos_candidate.model_id;
            ap.trading_symbol = trading_symbol_;
            ap.side = (pos_candidate.signal_action == 1) ? OrderSide::BUY : OrderSide::SELL;
            ap.entry_price = last_level_price;
            ap.quantity = total_qty;
            ap.stop_loss_price = std::nullopt;
            ap.entry_timestamp = static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count());
            ap.order_ids = placed_ids;
            {
                std::lock_guard<std::mutex> lock(trade_state_mutex_);
                active_positions_[pos_candidate.model_id] = ap;
                positions_to_json();
            }
            // Spawn stop-loss
            attempt_stop_loss_order_with_fallback(pos_candidate, current_bbo);
            return;
        }
    }
    spdlog::error("All ladder fallback attempts failed for model {}", pos_candidate.model_id);
}

// Spawn stop-loss order after ladder entry
void DefaultExecutionClient::attempt_stop_loss_order_with_fallback(
    const MlSignalPayload& pos_candidate,
    const BBO& current_bbo) {
    // Compute stop-loss price based on last entry BBO reference
    double ref_price = (pos_candidate.signal_action == 1) ? current_bbo.bid : current_bbo.ask;
    double sl_pct = pos_candidate.stop_loss_pct_config / 100.0;
    double raw_sl = (pos_candidate.signal_action == 1)
        ? ref_price * (1.0 - sl_pct)
        : ref_price * (1.0 + sl_pct);
    double sl_price = std::round(raw_sl / tick_size_) * tick_size_;
    if (sl_price <= 0.0) {
        spdlog::error("Computed SL price <=0: {}", sl_price);
        return;
    }
    json j;
    j["symbol"] = trading_symbol_;
    j["side"] = (pos_candidate.signal_action == 1) ? "Ask" : "Bid";
    j["orderType"] = "Limit";
    j["quantity"] = format_double_to_string(pos_candidate.order_quantity_config, 8);
    j["price"] = format_double_to_string(sl_price, 8);
    j["timeInForce"] = "GTC";
    j["stopLossTriggerPrice"] = format_double_to_string(sl_price, 8);
    j["stopLossLimitPrice"] = format_double_to_string(sl_price, 8);
    try {
        json resp = execute_signed_request(RestClass::TRADE, "POST", "/api/v1/order", "orderExecute", j);
        std::string oid = resp.value("orderId", resp.value("id", ""));
        if (!oid.empty()) {
            std::lock_guard<std::mutex> lock(trade_state_mutex_);
            active_positions_[pos_candidate.model_id].stop_order_ids.push_back(oid);
            positions_to_json();
        } else {
            spdlog::error("No orderId returned for stop-loss of model {}", pos_candidate.model_id);
        }
    } catch (const std::exception& e) {
        spdlog::error("Error placing stop-loss for model {}: {}", pos_candidate.model_id, e.what());
    }
}

// Added: Serialize active_positions_ to JSON file
void DefaultExecutionClient::positions_to_json() {
    std::lock_guard<std::mutex> lock(trade_state_mutex_);
    json j = json::object();
    for (const auto& [id, ap] : active_positions_) {
        json pos_j;
        pos_j["model_id"] = ap.model_id;
        pos_j["trading_symbol"] = ap.trading_symbol;
        pos_j["side"] = order_side_to_string(ap.side);
        pos_j["entry_price"] = ap.entry_price;
        if (ap.stop_loss_price.has_value()) pos_j["stop_loss_price"] = ap.stop_loss_price.value();
        else pos_j["stop_loss_price"] = nullptr;
        pos_j["quantity"] = ap.quantity;
        pos_j["entry_timestamp"] = ap.entry_timestamp;
        pos_j["order_ids"] = ap.order_ids;
        pos_j["stop_order_ids"] = ap.stop_order_ids;
        j[id] = pos_j;
    }
    std::ofstream file("positions.json");
    if (file.is_open()) {
        file << j.dump(4);
    } else {
        spdlog::error("Unable to open positions.json for writing");
    }
}

// Added: Load active_positions_ from JSON file
void DefaultExecutionClient::load_positions_from_json() {
    std::ifstream file("positions.json");
    if (!file.is_open()) {
        spdlog::info("positions.json not found, skipping load");
        return;
    }
    json j;
    try {
        file >> j;
        std::lock_guard<std::mutex> lock(trade_state_mutex_);
        active_positions_.clear();
        for (auto& el : j.items()) {
            const std::string& id = el.key();
            const auto& pos_j = el.value();
            ActivePosition ap;
            ap.model_id = pos_j.value("model_id", std::string());
            ap.trading_symbol = pos_j.value("trading_symbol", std::string());
            std::string side_str = pos_j.value("side", std::string());
            ap.side = (side_str == order_side_to_string(OrderSide::BUY)) ? OrderSide::BUY : OrderSide::SELL;
            ap.entry_price = pos_j.value("entry_price", 0.0);
            if (pos_j.contains("stop_loss_price") && pos_j["stop_loss_price"].is_number())
                ap.stop_loss_price = pos_j.value("stop_loss_price", 0.0);
            else ap.stop_loss_price = std::nullopt;
            ap.quantity = pos_j.value("quantity", 0.0);
            ap.entry_timestamp = pos_j.value("entry_timestamp", 0ULL);
            ap.order_ids = pos_j.value("order_ids", std::vector<std::string>());
            ap.stop_order_ids = pos_j.value("stop_order_ids", std::vector<std::string>());
            active_positions_[id] = ap;
        }
    } catch (const std::exception& e) {
        spdlog::error("Error loading positions.json: {}", e.what());
    }
}

// ... rest of the code ...

void DefaultExecutionClient::order_ws_error_handler_(const std::string& error_code) {
    SPDLOG_ERROR("Order WebSocket Error ({}) for symbol {}: {}", error_code, trading_symbol_, error_code); // Log with symbol
    std::lock_guard<std::mutex> lock(ws_mutex_);
    ws_connected_ = false;
    ws_orders_subscribed_ = false;
    ws_connection_healthy_ = false;
    ws_orders_initialized_.store(false, std::memory_order_release); // Crucial: reset initialization state on error
    bootstrap_in_progress_.store(false, std::memory_order_release); // Reset bootstrap flag on error
    // Optionally, clear order cache if connection is deemed unrecoverable or state is uncertain
    // std::lock_guard<std::mutex> cache_lock(order_cache_mutex_);
    // order_cache_.clear();
    // SPDLOG_INFO("Order WebSocket: Order cache cleared due to error: {}", error_code);
    
    // Consider triggering a reconnect attempt, perhaps with a backoff strategy,
    // or signaling the main application logic to handle the error.
    // For now, just logging and setting flags.
}


void DefaultExecutionClient::bootstrapOrderCache() {
    spdlog::info("bootstrapOrderCache: Starting for symbol {}.", trading_symbol_);
    // Ensure bootstrap_in_progress_ is true when this function starts, and false when it exits (success or failure)
    // The caller of bootstrapOrderCache should manage setting bootstrap_in_progress_ true before calling,
    // and this function will set it false on exit. Or, the caller detaches and this func manages it.
    // Current setup: caller sets it true and detaches, this func sets it false on exit.

    // Add a check: if WebSocket is not even connected, abort bootstrap.
    if (!client_ || !client_->is_connected()) {
        SPDLOG_ERROR("bootstrapOrderCache: Aborting for symbol {}. WebSocket not connected or client is null.", trading_symbol_);
        ws_orders_initialized_.store(false, std::memory_order_release);
        // bootstrap_in_progress_ is reset by the calling thread context logic or at end of this function.
        return; // Early exit
    }

    try {
        json params_query;
        params_query["symbol"] = trading_symbol_;

        spdlog::info("bootstrapOrderCache: Fetching open orders via REST...");
        json open_orders_response = execute_signed_request(RestClass::ORDER_QUERY, "GET", "/api/v1/orders", "orderQueryAll", params_query);
        spdlog::info("bootstrapOrderCache: Received {} potential orders from REST API.", open_orders_response.is_array() ? open_orders_response.size() : 0);

        std::lock_guard<std::mutex> lock(order_cache_mutex_);
        order_cache_.clear(); // Clear previous cache contents

        if (open_orders_response.is_array()) {
            int added_to_cache_count = 0;
            for (const auto& order_json : open_orders_response) {
                std::string order_id = order_json.value("orderId", ""); // SDK's Order::from_json uses "orderId"
                 if (order_id.empty() && order_json.contains("id")) { // Fallback for "id"
                    order_id = order_json.value("id", "");
                }
                if (order_id.empty()) {
                    spdlog::warn("bootstrapOrderCache: Skipping order with no ID in JSON: {}", order_json.dump(2));
                    continue;
                }

                std::string status_str = order_json.value("status", "");
                std::optional<backpack::OrderStatus> status_opt = backpack::string_to_order_status(status_str);

                if (!status_opt) {
                    spdlog::warn("bootstrapOrderCache: Unknown order status string '{}' for order {}. Skipping.", status_str, order_id);
                    continue;
                }
                
                backpack::OrderStatus current_status = status_opt.value();

                // Cache only non-terminal orders
                if (current_status == backpack::OrderStatus::NEW || 
                    current_status == backpack::OrderStatus::PARTIALLY_FILLED) {
                    
                    // It's safer and more aligned with SDK to use Order::from_json if possible
                    // However, Order::from_json might throw if fields are missing, so manual population
                    // gives more control for logging/defaults if API response is sometimes sparse.
                    // Let's try manual first for robustness against partial API responses.

                    backpack::Order bp_order;
                    bp_order.id = order_id;
                    bp_order.symbol = order_json.value("symbol", trading_symbol_);
                    bp_order.status = current_status;
                    bp_order.client_order_id = order_json.value("clientOrderId", ""); // Corrected field name
                    
                    std::string side_str = order_json.value("side", "");
                    std::optional<backpack::OrderSide> side_opt = backpack::string_to_order_side(side_str);
                    if (side_opt) {
                        bp_order.side = side_opt.value();
                    } else {
                        spdlog::warn("bootstrapOrderCache: Unknown order side string '{}' for order {}. Defaulting to BUY.", side_str, order_id);
                        bp_order.side = backpack::OrderSide::BUY;
                    }

                    std::string type_str = order_json.value("type", ""); // SDK Order::from_json uses "type"
                    std::optional<backpack::OrderType> type_opt = backpack::string_to_order_type(type_str);
                     if (type_opt) {
                        bp_order.type = type_opt.value();
                    } else {
                        spdlog::warn("bootstrapOrderCache: Unknown order type string '{}' for order {}. Defaulting to LIMIT.", type_str, order_id);
                        bp_order.type = backpack::OrderType::LIMIT;
                    }
                    
                    bp_order.quantity = json_get_double(order_json, "quantity", 0.0);
                    bp_order.price = json_get_double(order_json, "price", 0.0); 
                    bp_order.executed_quantity = json_get_double(order_json, "executedQty", 0.0); // Corrected field name
                    
                    // timestamp field from SDK struct (maps to "timestamp" in JSON as per Order::from_json)
                    bp_order.timestamp = order_json.value("timestamp", ""); 


                    order_cache_[order_id] = bp_order;
                    added_to_cache_count++;
                    spdlog::debug("bootstrapOrderCache: Added order {} to cache. Status: {}", order_id, status_str);
                }
            }
            spdlog::info("bootstrapOrderCache: Added {} open orders to cache for symbol {}. Cache size: {}", added_to_cache_count, trading_symbol_, order_cache_.size());
        } else {
            spdlog::warn("bootstrapOrderCache: Received non-array response for open orders query: {}", open_orders_response.dump(2));
        }

        ws_orders_initialized_.store(true, std::memory_order_release);
        spdlog::info("bootstrapOrderCache: Successfully completed and order cache initialized for symbol {}. ws_orders_initialized_ is TRUE", trading_symbol_);

    } catch (const std::exception& e) {
        spdlog::error("bootstrapOrderCache: Exception for symbol {}: {}. Order cache may not be initialized.", trading_symbol_, e.what());
        ws_orders_initialized_.store(false, std::memory_order_release); // Ensure it's false on failure
        {
            std::lock_guard<std::mutex> lock(order_cache_mutex_);
            order_cache_.clear(); // Clear cache on bootstrap failure
        }
    }
    // Ensure bootstrap_in_progress_ is reset regardless of success or failure path IF this function is responsible
    // If caller detaches and this is the end of the detached thread's work:
    // bootstrap_in_progress_.store(false, std::memory_order_release); // This was moved to the calling lambda in setupOrderWebSocket
}

void DefaultExecutionClient::sweeperThreadLogic() {
    spdlog::info("Sweeper thread logic started for symbol: {} (improved logic - cancels ALL orders older than {} seconds)", trading_symbol_, MAX_ORDER_AGE.count());
    
    while (running_) {
        std::vector<RestingOrder> stale_orders;
        
        // Find all orders older than MAX_ORDER_AGE (not just exactly that age)
        {
            std::lock_guard<std::mutex> lk(openOrdersMutex_);
            auto now = std::chrono::steady_clock::now();
            
            for (const auto& kv : openOrders_) {
                const RestingOrder& order = kv.second;
                auto order_age = now - order.placedAt;
                
                // Cancel ALL orders older than MAX_ORDER_AGE, not just exactly MAX_ORDER_AGE
                if (order_age > MAX_ORDER_AGE && order.symbol == trading_symbol_) {
                    stale_orders.push_back(order);
                    spdlog::info("Found stale order: ID={}, Symbol={}, Age={}s (limit={}s)", 
                        order.orderId, 
                        order.symbol,
                        std::chrono::duration_cast<std::chrono::seconds>(order_age).count(),
                        MAX_ORDER_AGE.count()
                    );
                }
            }
        }
        
        // If we have many stale orders, use cancel-all instead of individual cancels
        if (stale_orders.size() >= 10) {
            spdlog::warn("Found {} stale orders for symbol {} - using cancel-all approach", stale_orders.size(), trading_symbol_);
            try {
                bool success = cancelAllOrdersForSymbol(trading_symbol_);
                if (success) {
                    spdlog::info("Successfully cancelled all orders for symbol {} (bulk approach)", trading_symbol_);
                } else {
                    spdlog::error("Failed to cancel all orders for symbol {} (bulk approach)", trading_symbol_);
                }
            } catch (const std::exception& ex) {
                spdlog::error("Exception during bulk cancel for symbol {}: {}", trading_symbol_, ex.what());
            }
        } else {
            // Cancel individual stale orders
            for (const auto& ord : stale_orders) {
                try {
                    spdlog::info("Cancelling stale order: ID={}, Symbol={}", ord.orderId, ord.symbol);
                    bool success = cancel_order(ord.symbol, ord.orderId);
                    if (success) {
                        // Remove from local openOrders_ map immediately
                        // The WebSocket should also update this, but this ensures consistency
                        std::lock_guard<std::mutex> lk(openOrdersMutex_);
                        openOrders_.erase(ord.orderId);
                        spdlog::info("Successfully cancelled and removed stale order: {}", ord.orderId);
                    } else {
                        spdlog::warn("Failed to cancel stale order: {}", ord.orderId);
                    }
                } catch (const std::exception& ex) {
                    spdlog::error("Exception cancelling stale order {}: {}", ord.orderId, ex.what());
                }
            }
        }
        
        // Log sweeper status periodically
        if (stale_orders.size() > 0) {
            std::lock_guard<std::mutex> lk(openOrdersMutex_);
            spdlog::info("Sweeper completed for symbol {}. Processed {} stale orders. Remaining open orders: {}", 
                trading_symbol_, stale_orders.size(), openOrders_.size());
        }
        
        // Sleep for SWEEP_INTERVAL before next sweep
        std::this_thread::sleep_for(SWEEP_INTERVAL);
    }
    
    spdlog::info("Sweeper thread logic stopped for symbol: {}", trading_symbol_);
}

// ... existing code ...

// Make sure this is after sweeperThreadLogic() and before other method implementations if any.
// Or place it in a logical section for WebSocket/Order update handlers.

// Implementation for cancelSingleOrder
bool DefaultExecutionClient::cancelSingleOrder(const std::string& order_id, const std::string& symbol) {
    if (order_id.empty() || symbol.empty()) {
        spdlog::error("cancelSingleOrder: order_id or symbol is empty. OrderID: '{}', Symbol: '{}'", order_id, symbol);
        return false;
    }
    // Ensure we only attempt to cancel for the symbol this instance is managing, 
    // or make symbol an explicit parameter if this function can be called for other symbols.
    if (symbol != trading_symbol_) {
        spdlog::error("cancelSingleOrder: Attempt to cancel order for symbol '{}' which is not the trading_symbol_ '{}' of this instance.", symbol, trading_symbol_);
        return false; // Or handle as per design if cross-symbol cancellation is intended & safe
    }

    spdlog::info("Attempting to cancel single order. ID: {}, Symbol: {}", order_id, symbol);
    
    json params;
    params["symbol"] = symbol;
    params["orderId"] = order_id;

    try {
        json response = execute_signed_request(RestClass::TRADE, "DELETE", "/api/v1/order", "orderCancel", params);
        spdlog::info("cancelSingleOrder REST response for order ID {}: {}", order_id, response.dump(2));
        
        // Check response for success. Often, a successful DELETE might return the object or a 200/204.
        // If execute_signed_request throws for non-2xx, we might not need explicit check here.
        // However, some APIs might return 200 OK with an error message in body.
        // For now, assume no throw means acknowledged. Actual removal from openOrders_ is via WebSocket.
        return true; 
    } catch (const std::exception& e) {
        spdlog::error("Exception in cancelSingleOrder for ID {}: {}. Symbol: {}", order_id, e.what(), symbol);
        // If cancellation failed, the order might still be in openOrders_. Sweeper might try again, or WS update might clarify.
        return false;
    }
}

// Implementation for cancelAllOrdersForSymbol
bool DefaultExecutionClient::cancelAllOrdersForSymbol(const std::string& symbol) {
    if (symbol.empty()) {
        spdlog::error("cancelAllOrdersForSymbol: symbol is empty.");
        return false;
    }
    if (symbol != trading_symbol_) {
        spdlog::error("cancelAllOrdersForSymbol: Attempt to cancel orders for symbol '{}' which is not the trading_symbol_ '{}' of this instance.", symbol, trading_symbol_);
        return false;
    }
    spdlog::info("Attempting to cancel ALL orders for symbol: {}", symbol);

    json params;
    params["symbol"] = symbol;

    try {
        json response = execute_signed_request(RestClass::TRADE, "DELETE", "/api/v1/orders", "orderCancelAll", params);
        spdlog::info("cancelAllOrdersForSymbol REST response for symbol {}: {}", symbol, response.dump(2));

        // After a successful bulk cancel, the openOrders_ map for this symbol should be cleared
        // to reflect the action immediately, as WebSocket updates might be delayed or individual.
        {
            std::lock_guard<std::mutex> lock(openOrdersMutex_);
            int orders_removed_count = 0;
            spdlog::info("Clearing openOrders_ for symbol {} after cancelAllOrdersForSymbol success. Orders before clear: {}", symbol, openOrders_.size());
            for (auto it = openOrders_.begin(); it != openOrders_.end(); ) {
                if (it->second.symbol == symbol) {
                    spdlog::debug("Locally removing order ID: {} (ClientID: {}) for symbol {} from openOrders_ due to cancelAll.", it->second.orderId, it->second.clientId, symbol);
                    it = openOrders_.erase(it); 
                    orders_removed_count++;
                } else {
                    ++it;
                }
            }
            spdlog::info("{} orders for symbol {} locally removed from openOrders_. Orders after clear: {}", orders_removed_count, symbol, openOrders_.size());
        }
        return true;
    } catch (const std::exception& e) {
        spdlog::error("Exception in cancelAllOrdersForSymbol for symbol {}: {}", symbol, e.what());
        return false;
    }
}

// Implementation for enforceOpenOrderLimit
void DefaultExecutionClient::enforceOpenOrderLimit(const std::string& symbol_to_check, std::unique_lock<std::mutex>& open_orders_lock) {
    if (symbol_to_check.empty() || symbol_to_check != trading_symbol_) {
        spdlog::warn("enforceOpenOrderLimit called for mismatching or empty symbol: '{}'. Instance handles: '{}'. Skipping.", symbol_to_check, trading_symbol_);
        return;
    }

    if (!open_orders_lock.owns_lock()) {
        spdlog::error("enforceOpenOrderLimit called without the lock being held. This is a programming error.");
        // Optionally, try to lock it here if that's a desired fallback, but indicates design issue.
        // For now, just return to prevent further issues.
        return;
    }

    std::size_t current_open_orders_for_symbol = 0;
    // openOrdersMutex_ is ALREADY HELD by the caller (processSdkOrderUpdate) via open_orders_lock.
    // Do not re-lock for counting.
    for (const auto& pair : openOrders_) {
        if (pair.second.symbol == symbol_to_check) {
            current_open_orders_for_symbol++;
        }
    }

    if (current_open_orders_for_symbol >= MAX_OPEN_ORDERS) {
        spdlog::warn("CIRCUIT BREAKER TRIPPED for symbol {}: Number of open orders ({}) >= MAX_OPEN_ORDERS ({}). Initiating cancel all orders for this symbol.",
                     symbol_to_check, current_open_orders_for_symbol, MAX_OPEN_ORDERS);
        
        bool cancel_all_success = false;
        {
            ScopedUnlock scoped_unlock(open_orders_lock); // Unlocks open_orders_lock here
            try {
                cancel_all_success = cancelAllOrdersForSymbol(symbol_to_check); // This will now acquire its own lock internally
            } catch (const std::exception& e) {
                // scoped_unlock will re-lock open_orders_lock in its destructor.
                spdlog::error("Exception during cancelAllOrdersForSymbol called from enforceOpenOrderLimit: {}", e.what());
                // Potentially rethrow or handle, but ensure lock is managed.
                // For now, just log. The lock will be re-acquired.
            }
        } // Relocks open_orders_lock when scoped_unlock goes out of scope

        if (cancel_all_success) {
            spdlog::info("Circuit breaker: Successfully initiated cancelAllOrdersForSymbol for symbol {}", symbol_to_check);
        } else {
            spdlog::error("Circuit breaker: Failed to initiate cancelAllOrdersForSymbol for symbol {}", symbol_to_check);
        }
    } else {
        // spdlog::debug("Open order count ({}) for symbol {} is within limit ({})",
        // current_open_orders_for_symbol, symbol_to_check, MAX_OPEN_ORDERS);
    }
}

// ... existing code ...
void DefaultExecutionClient::processSdkOrderUpdate(const backpack::Order& sdk_order) {
    spdlog::info("[ProcessSdkOrderUpdate] Received WS update for OrderID: {}, ClientID: {}, Symbol: {}, Status: {}, Price: {}, Qty: {}, ExecQty: {}",
                 sdk_order.id, sdk_order.client_order_id, sdk_order.symbol, backpack::order_status_to_string(sdk_order.status),
                 sdk_order.price, sdk_order.quantity, sdk_order.executed_quantity);

    if (sdk_order.id.empty()) {
        spdlog::warn("[ProcessSdkOrderUpdate] Ignored: Order update with empty OrderID. Symbol: {}, Status: {}",
                     sdk_order.symbol, backpack::order_status_to_string(sdk_order.status));
        return;
    }

    // Filter out updates for symbols not managed by this instance, unless circuit breaker needs to act on global state (which it currently does not based on symbol param)
    if (sdk_order.symbol != trading_symbol_) {
         spdlog::debug("[ProcessSdkOrderUpdate] Ignored: Order update for symbol {} which is not the trading_symbol {} of this instance.", sdk_order.symbol, trading_symbol_);
        return;
    }

    std::unique_lock<std::mutex> lock(openOrdersMutex_); // Use std::unique_lock

    const std::string& order_id = sdk_order.id;
    // Extract model_id from client_order_id for event logging
    std::string model_id = sdk_order.client_order_id;
    RestingOrderSide resting_side;
    if (sdk_order.side == backpack::OrderSide::BUY) {
        resting_side = RestingOrderSide::BID;
    } else if (sdk_order.side == backpack::OrderSide::SELL) {
        resting_side = RestingOrderSide::ASK;
    } else {
        spdlog::warn("[ProcessSdkOrderUpdate] Unknown order side for OrderID {}: {}. Defaulting to BID for safety, but this is an error.",
                     order_id, static_cast<int>(sdk_order.side));
        resting_side = RestingOrderSide::BID; // Or handle error more strictly
    }

    switch (sdk_order.status) {
        case backpack::OrderStatus::NEW: {
            // ... existing NEW handling ...
            enforceOpenOrderLimit(sdk_order.symbol, lock); // Pass the unique_lock
            // Added logging for new orders
            if (!model_id.empty()) {
                std::string trade_id_for_logging;
                {
                    std::lock_guard<std::mutex> trade_lock(trade_state_mutex_);
                    auto it2 = trade_id_map_.find(model_id);
                    if (it2 != trade_id_map_.end()) {
                        trade_id_for_logging = it2->second;
                    } else {
                        spdlog::warn("[ProcessSdkOrderUpdate] model_id '{}' not found in trade_id_map_ for new order. Generating trade_id.", model_id);
                        trade_id_for_logging = generate_uuid_v4();
                        trade_id_map_[model_id] = trade_id_for_logging;
                    }
                }
                TradeEventData new_event;
                new_event.trade_id = trade_id_for_logging;
                new_event.event_id = generate_uuid_v4();
                new_event.event_timestamp = std::chrono::duration_cast<std::chrono::milliseconds>(
                    std::chrono::system_clock::now().time_since_epoch()).count();
                new_event.event_type = TradeEventType::ORDER_NEW;
                new_event.model_id = model_id;
                new_event.trading_symbol = sdk_order.symbol;
                new_event.order_id = sdk_order.id;
                new_event.client_order_id = model_id;
                new_event.price = sdk_order.price;
                new_event.quantity = sdk_order.quantity;
                new_event.side = (sdk_order.side == backpack::OrderSide::BUY) ? "BUY" : "SELL";
                new_event.market_bid_at_event = bestBid();
                new_event.market_ask_at_event = bestAsk();
                log_trade_event(new_event);
            }
            break;
        }
        case backpack::OrderStatus::PARTIALLY_FILLED:
        case backpack::OrderStatus::FILLED: {
            // BEGIN MODIFICATION: Add trade event logging for fills
            if (!model_id.empty()) { // Only log if we have a model_id to associate
                std::string trade_id_for_logging;
                double previous_total_filled_quantity = 0.0;
                double original_order_quantity = sdk_order.quantity; // Default to SDK's order quantity

                {
                    std::lock_guard<std::mutex> trade_lock(trade_state_mutex_); 
                    auto trade_it = trade_id_map_.find(model_id);
                    if (trade_it != trade_id_map_.end()) {
                        trade_id_for_logging = trade_it->second;
                    } else {
                        spdlog::warn("[ProcessSdkOrderUpdate] model_id '{}' not found in trade_id_map_ for fill. Generating new trade_id.", model_id);
                        trade_id_for_logging = generate_uuid_v4();
                    }

                    auto pos_it = active_positions_.find(model_id);
                    if (pos_it != active_positions_.end()) {
                        // This line assumes ActivePosition has quantity_filled_so_far
                        previous_total_filled_quantity = pos_it->second.quantity_filled_so_far; 
                        original_order_quantity = pos_it->second.quantity; // Prefer position's original total quantity
                    } else {
                        spdlog::warn("[ProcessSdkOrderUpdate] ActivePosition not found for model_id '{}'. Using sdk_order.quantity as original.", model_id);
                    }
                }

                double filled_quantity_this_event = sdk_order.executed_quantity - previous_total_filled_quantity;

                // Use a small epsilon for comparing doubles to avoid issues with floating point arithmetic
                // Only log if a new quantity has actually been filled in this event
                if (filled_quantity_this_event > 1e-9) { 
                    TradeEventData fill_event;
                    fill_event.trade_id = trade_id_for_logging;
                    fill_event.event_id = generate_uuid_v4();
                    try {
                        fill_event.event_timestamp = std::stoull(sdk_order.timestamp);
                    } catch (const std::exception& e) {
                        spdlog::error("Error converting sdk_order.timestamp '{}' to uint64_t: {}. Using current time.", sdk_order.timestamp, e.what());
                        fill_event.event_timestamp = std::chrono::duration_cast<std::chrono::milliseconds>(
                                                    std::chrono::system_clock::now().time_since_epoch()).count();
                    }
                    fill_event.event_type = (sdk_order.status == backpack::OrderStatus::FILLED) ? 
                                            TradeEventType::ENTRY_ORDER_FILLED : 
                                            TradeEventType::ENTRY_ORDER_PARTIALLY_FILLED;
                    fill_event.model_id = model_id;
                    fill_event.trading_symbol = sdk_order.symbol;
                    fill_event.order_id = sdk_order.id;
                    fill_event.client_order_id = model_id;
                    // sdk_order.price is the order's limit price or current average filled price.
                    // For individual fill prices, a USER_TRADES stream would be needed.
                    fill_event.price = sdk_order.price; 
                    fill_event.filled_quantity = filled_quantity_this_event;
                    fill_event.quantity = original_order_quantity; // Original total order quantity from ActivePosition or sdk_order
                    fill_event.side = (sdk_order.side == backpack::OrderSide::BUY) ? "BUY" : "SELL";

                    std::optional<double> current_market_bid = std::nullopt;
                    std::optional<double> current_market_ask = std::nullopt;
                    try {
                        BBO current_bbo{bestBid(), bestAsk()}; // Assuming get_current_bbo() exists
                        current_market_bid = current_bbo.bid;
                        current_market_ask = current_bbo.ask;
                    } catch (const std::exception& e) {
                        spdlog::warn("Could not fetch BBO for {} in processSdkOrderUpdate: {}", sdk_order.symbol, e.what());
                    }
                    fill_event.market_bid_at_event = current_market_bid;
                    fill_event.market_ask_at_event = current_market_ask;

                    json additional_sdk_data;
                    additional_sdk_data["sdk_executed_quantity_total"] = sdk_order.executed_quantity;
                    additional_sdk_data["sdk_order_status"] = backpack::order_status_to_string(sdk_order.status);
                    fill_event.additional_data = additional_sdk_data;

                    log_trade_event(fill_event);
                }

                // Update ActivePosition state (average price and cumulative filled quantity)
                {
                    std::lock_guard<std::mutex> trade_lock(trade_state_mutex_);
                    auto pos_it = active_positions_.find(model_id);
                    if (pos_it != active_positions_.end()) {
                        // Update average entry price. sdk_order.price is the current average for all fills.
                        // This is only correct if sdk_order.price reflects the average filled price.
                        // If sdk_order.price is just the limit price, this logic is flawed for averaging.
                        // For now, let's assume sdk_order.price is the new average execution price.
                        if (sdk_order.executed_quantity > 1e-9) { // Avoid division by zero or near-zero
                             // A more robust weighted average: 
                             // (old_avg_price * old_filled_qty + new_fill_price * new_fill_qty) / (old_filled_qty + new_fill_qty)
                             // However, sdk_order.price is ALREADY the new average for sdk_order.executed_quantity if the exchange provides it.
                             // If sdk_order.price is merely the original limit price, we have an issue.
                             // For now, directly use sdk_order.price if it is positive.
                            if(sdk_order.price > 0) pos_it->second.entry_price = sdk_order.price; 
                        }
                        pos_it->second.quantity_filled_so_far = sdk_order.executed_quantity; // Update cumulative
                        
                        // If fully filled, ensure the main quantity field of ActivePosition also reflects the total filled amount.
                        if (sdk_order.status == backpack::OrderStatus::FILLED) {
                            pos_it->second.quantity = sdk_order.executed_quantity;
                        }
                        // Handle pending closure completion for WS-filled closing orders
                        if (pos_it->second.pending_closure && pos_it->second.closing_order_id.has_value()
                            && pos_it->second.closing_order_id.value() == sdk_order.id
                            && sdk_order.status == backpack::OrderStatus::FILLED) {
                            auto &ap = pos_it->second;
                            double exit_price = sdk_order.price;
                            double entry_price = ap.entry_price;
                            double qty = ap.quantity_filled_so_far;
                            double pnl = (ap.side == OrderSide::BUY)
                                         ? (exit_price - entry_price) * qty
                                         : (entry_price - exit_price) * qty;
                            std::string trade_id_for_logging = trade_id_map_.count(model_id)
                                                             ? trade_id_map_[model_id]
                                                             : generate_uuid_v4();
                            TradeEventData closure_event;
                            closure_event.trade_id = trade_id_for_logging;
                            closure_event.event_id = generate_uuid_v4();
                            closure_event.event_timestamp = std::chrono::duration_cast<std::chrono::milliseconds>(
                                std::chrono::system_clock::now().time_since_epoch()).count();
                            closure_event.event_type = ap.closure_type;
                            closure_event.model_id = model_id;
                            closure_event.trading_symbol = sdk_order.symbol;
                            closure_event.price = exit_price;
                            closure_event.quantity = qty;
                            closure_event.side = (ap.side == OrderSide::BUY) ? "BUY" : "SELL";
                            closure_event.pnl = pnl;
                            closure_event.market_bid_at_event = bestBid();
                            closure_event.market_ask_at_event = bestAsk();
                            log_trade_event(closure_event);
                            ap.pending_closure = false;
                        }
                        spdlog::info("[ProcessSdkOrderUpdate] ActivePosition for model_id '{}' updated: avg_price={}, filled_qty_so_far={}, total_sdk_exec_qty={}", 
                                     model_id, pos_it->second.entry_price, pos_it->second.quantity_filled_so_far, sdk_order.executed_quantity);
                    } else {
                        // This might occur if signal wasn't processed or position removed too early.
                        spdlog::warn("[ProcessSdkOrderUpdate] ActivePosition for model_id '{}' not found for updating fill state after logging.", model_id);
                    }
                }
            } else {
                 spdlog::warn("[ProcessSdkOrderUpdate] Ignored fill event for OrderID '{}' due to empty model_id (client_order_id).", sdk_order.id);
            }
            // END MODIFICATION

            // Original logic for updating openOrders_ map
            auto it = openOrders_.find(order_id);
            if (it == openOrders_.end()) {
                // New order
                openOrders_[order_id] = RestingOrder{
                    order_id,
                    sdk_order.symbol,
                    resting_side,
                    sdk_order.price,
                    sdk_order.quantity - sdk_order.executed_quantity, // Open quantity
                    std::chrono::steady_clock::now(),                 // PlacedAt - approximate with reception time
                    sdk_order.client_order_id
                };
                spdlog::info("[ProcessSdkOrderUpdate] Added NEW order to openOrders_. OrderID: {}, Symbol: {}. OpenOrders size: {}",
                             order_id, sdk_order.symbol, openOrders_.size());
            } else {
                // Update existing open order (e.g., partial fill update)
                it->second.qty = sdk_order.quantity - sdk_order.executed_quantity; // Update open quantity
                it->second.price = sdk_order.price; // Price might change for some updates, though usually not for resting limit orders
                it->second.side = resting_side; // Side should not change but update defensively
                it->second.clientId = sdk_order.client_order_id; // ClientID might be empty initially then updated
                spdlog::info("[ProcessSdkOrderUpdate] Updated PARTIALLY_FILLED order in openOrders_. OrderID: {}, Symbol: {}. Remaining Qty: {}. OpenOrders size: {}",
                             order_id, sdk_order.symbol, it->second.qty, openOrders_.size());
            }
            // Call circuit breaker logic AFTER updating the map and BEFORE releasing the lock
            // Use the symbol from the SDK order update, as enforceOpenOrderLimit expects it.
            enforceOpenOrderLimit(sdk_order.symbol, lock); // Pass the unique_lock
            break;
        }
        case backpack::OrderStatus::CANCELED:
        case backpack::OrderStatus::REJECTED: {
            if (openOrders_.erase(order_id) > 0) {
                spdlog::info("[ProcessSdkOrderUpdate] Removed TERMINAL order from openOrders_. OrderID: {}, Status: {}. OpenOrders size: {}",
                             order_id, backpack::order_status_to_string(sdk_order.status), openOrders_.size());
            } else {
                spdlog::info("[ProcessSdkOrderUpdate] Received TERMINAL update for OrderID {} (Status: {}), but it was not found in openOrders_. Potentially already removed or never added (e.g. if bootstrap missed it or it was quickly filled/cancelled). OpenOrders size: {}",
                             order_id, backpack::order_status_to_string(sdk_order.status), openOrders_.size());
            }
            // Added logging for canceled or rejected orders
            if (!model_id.empty()) {
                std::string trade_id_for_logging;
                {
                    std::lock_guard<std::mutex> trade_lock(trade_state_mutex_);
                    auto it2 = trade_id_map_.find(model_id);
                    if (it2 != trade_id_map_.end()) {
                        trade_id_for_logging = it2->second;
                    } else {
                        spdlog::warn("[ProcessSdkOrderUpdate] model_id '{}' not found in trade_id_map_ for cancel/reject. Generating trade_id.", model_id);
                        trade_id_for_logging = generate_uuid_v4();
                        trade_id_map_[model_id] = trade_id_for_logging;
                    }
                }
                TradeEventData cancel_event;
                cancel_event.trade_id = trade_id_for_logging;
                cancel_event.event_id = generate_uuid_v4();
                cancel_event.event_timestamp = std::chrono::duration_cast<std::chrono::milliseconds>(
                    std::chrono::system_clock::now().time_since_epoch()).count();
                cancel_event.event_type = (sdk_order.status == backpack::OrderStatus::CANCELED) ? 
                                         TradeEventType::ORDER_CANCELLED : TradeEventType::ORDER_REJECTED;
                cancel_event.model_id = model_id;
                cancel_event.trading_symbol = sdk_order.symbol;
                cancel_event.order_id = sdk_order.id;
                cancel_event.client_order_id = model_id;
                cancel_event.side = (sdk_order.side == backpack::OrderSide::BUY) ? "BUY" : "SELL";
                nlohmann::json ad;
                ad["order_status"] = backpack::order_status_to_string(sdk_order.status);
                cancel_event.additional_data = ad;
                log_trade_event(cancel_event);
            }
            break;
        }
        default:
            spdlog::warn("[ProcessSdkOrderUpdate] Received order update with unhandled status for OrderID {}: Status Enum Value {}",
                         order_id, static_cast<int>(sdk_order.status));
            break;
    }
}

void DefaultExecutionClient::log_trade_event(const TradeEventData& event_data) {
    if (!trade_event_log_file_.is_open()) {
        spdlog::warn("Trade event log file is not open. Cannot log event for trade_id: {}", event_data.trade_id);
        return;
    }

    nlohmann::json j_event;
    j_event["trade_id"] = event_data.trade_id;
    j_event["event_id"] = event_data.event_id;
    j_event["event_timestamp"] = event_data.event_timestamp;
    j_event["event_type"] = trade_event_type_to_string(event_data.event_type);
    j_event["model_id"] = event_data.model_id;
    j_event["trading_symbol"] = event_data.trading_symbol;

    if (event_data.order_id.has_value()) j_event["order_id"] = event_data.order_id.value();
    if (event_data.client_order_id.has_value()) j_event["client_order_id"] = event_data.client_order_id.value();
    if (event_data.price.has_value()) j_event["price"] = event_data.price.value();
    if (event_data.quantity.has_value()) j_event["quantity"] = event_data.quantity.value();
    if (event_data.filled_quantity.has_value()) j_event["filled_quantity"] = event_data.filled_quantity.value();
    if (event_data.side.has_value()) j_event["side"] = event_data.side.value();
    if (event_data.market_bid_at_event.has_value()) j_event["market_bid_at_event"] = event_data.market_bid_at_event.value();
    if (event_data.market_ask_at_event.has_value()) j_event["market_ask_at_event"] = event_data.market_ask_at_event.value();
    if (event_data.reason.has_value()) j_event["reason"] = event_data.reason.value();
    if (event_data.pnl.has_value()) j_event["pnl"] = event_data.pnl.value();
    
    if (!event_data.additional_data.is_null() && !event_data.additional_data.empty()) {
        j_event["additional_data"] = event_data.additional_data;
    }

    trade_event_log_file_ << j_event.dump() << std::endl;
    trade_event_log_file_.flush();
}

// ... existing code ...

void DefaultExecutionClient::log_stop_order_sent(
    const std::string& model_id,
    double price,
    double quantity,
    OrderSide side,
    const std::string& trading_symbol) {
    std::string trade_id;
    {
        std::lock_guard<std::mutex> lock(trade_state_mutex_);
        auto it = trade_id_map_.find(model_id);
        trade_id = (it != trade_id_map_.end()) ? it->second : generate_uuid_v4();
    }
    TradeEventData event;
    event.trade_id = trade_id;
    event.event_id = generate_uuid_v4();
    event.event_timestamp = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    event.event_type = TradeEventType::STOP_ORDER_SENT;
    event.model_id = model_id;
    event.trading_symbol = trading_symbol;
    event.price = price;
    event.quantity = quantity;
    event.side = (side == OrderSide::BUY) ? "BUY" : "SELL";
    event.market_bid_at_event = bestBid();
    event.market_ask_at_event = bestAsk();
    log_trade_event(event);
}

// Replace existing stub for setupOrderWebSocket
void DefaultExecutionClient::setupOrderWebSocket() {
    SPDLOG_CRITICAL("ENTERING setupOrderWebSocket IN EXEC_BRIDGE_CPP"); 
    spdlog::info("setupOrderWebSocket: Called for symbol {}", trading_symbol_);
    if (!client_) {
        spdlog::error("setupOrderWebSocket: BackpackClient (client_) is null. Cannot proceed.");
        return;
    }

    ws_last_connection_attempt_ = std::chrono::steady_clock::now();

    // Set up the callback for when the WebSocket client connects
    client_->get_ws_client()->set_open_handler([this]() {
        SPDLOG_CRITICAL("OPEN_HANDLER_CALLED in setupOrderWebSocket"); 
        spdlog::info("Order WebSocket: Connected for symbol {}. Attempting subscriptions...", trading_symbol_);
        ws_connected_.store(true, std::memory_order_release);
        ws_connection_healthy_.store(true, std::memory_order_release); // Assume healthy on connect

        SPDLOG_CRITICAL("=== WebSocket Open Handler Debug ===");
        SPDLOG_CRITICAL("Connected: {}", ws_connected_.load());
        SPDLOG_CRITICAL("Trading Symbol: {}", trading_symbol_);
        SPDLOG_CRITICAL("About to call subscribe_user_orders...");

        // Subscribe to user orders for the specific trading_symbol_
        SPDLOG_INFO("Order WebSocket: Attempting to subscribe to user orders for symbol {}", trading_symbol_);
        bool orders_subscribed = client_->subscribe_user_orders(trading_symbol_, 
            [this](const backpack::Order& sdk_order) {
                this->processSdkOrderUpdate(sdk_order);
            }
        );

        SPDLOG_CRITICAL("subscribe_user_orders returned: {}", orders_subscribed);

        if (orders_subscribed) {
            spdlog::info("Order WebSocket: Successfully sent subscription request for user orders on symbol {}", trading_symbol_);
            ws_orders_subscribed_.store(true, std::memory_order_release);
            
            if (!bootstrap_in_progress_.exchange(true, std::memory_order_acq_rel)) {
                std::thread([this](){\
                    bootstrapOrderCache(); \
                    bootstrap_in_progress_.store(false, std::memory_order_release);\
                }).detach();
            } else {
                spdlog::warn("Order WebSocket: Bootstrap already in progress for symbol {}. Skipping redundant call.", trading_symbol_);
            }
        } else {
            spdlog::error("Order WebSocket: Failed to send subscription request for user orders on symbol {}. Order tracking will be incomplete.", trading_symbol_);
            ws_orders_subscribed_.store(false, std::memory_order_release);
            ws_orders_initialized_.store(false, std::memory_order_release); // Mark as not initialized
            ws_connection_healthy_.store(false, std::memory_order_release);
        }

        // Subscribe to user trades (fills) - using symbol-less version for all account trades
        SPDLOG_INFO("Order WebSocket: Attempting to subscribe to user trades (fills) for the account");
        bool trades_subscribed = client_->subscribe_user_trades(
            [this](const backpack::Trade& sdk_trade) {
                this->onUserFill(sdk_trade);
            }
        );

        SPDLOG_CRITICAL("subscribe_user_trades returned: {}", trades_subscribed);

        if (trades_subscribed) {
            spdlog::info("Order WebSocket: Successfully sent subscription request for user trades (fills)");
        } else {
            spdlog::error("Order WebSocket: Failed to send subscription request for user trades (fills). Fill data will be missing.");
        }
        
        SPDLOG_CRITICAL("=== End WebSocket Open Handler ===");
    });

    client_->get_ws_client()->set_fail_handler([this](const std::string& reason) {
        spdlog::error("Order WebSocket: Connection failed or disconnected for symbol {}. Reason: {}", trading_symbol_, reason);
        order_ws_error_handler_("Connection_Fail_Or_Disconnect");
    });

    client_->get_ws_client()->set_close_handler([this]() { 
        spdlog::warn("Order WebSocket: Closed for symbol {}. (SDK close_handler does not provide specific status/reason to this lambda)", trading_symbol_);
        order_ws_error_handler_("Connection_Closed");
    });

    try {
        spdlog::info("Order WebSocket: Attempting to connect for symbol {}...", trading_symbol_);
        SPDLOG_CRITICAL("ATTEMPTING client_->connect() in setupOrderWebSocket");
        client_->connect(); 
    } catch (const std::exception& e) {
        spdlog::error("Order WebSocket: Exception during client_->connect() for symbol {}: {} ", trading_symbol_, e.what()); // Corrected string literal
        order_ws_error_handler_("Connect_Call_Exception");
    }
}

// Stub for cancel_orders_by_model_id (was declared in header)
int DefaultExecutionClient::cancel_orders_by_model_id(const std::string& symbol, const std::string& model_id_to_cancel) {
    spdlog::info("cancel_orders_by_model_id: Attempting to cancel orders for symbol {}, model_id (clientId) {}", symbol, model_id_to_cancel);
    std::vector<std::string> order_ids_to_cancel;
    {
        std::lock_guard<std::mutex> lock(openOrdersMutex_);
        for (const auto& pair : openOrders_) {
            if (pair.second.symbol == symbol && pair.second.clientId == model_id_to_cancel) {
                order_ids_to_cancel.push_back(pair.second.orderId);
            }
        }
    }

    if (order_ids_to_cancel.empty()) {
        spdlog::info("cancel_orders_by_model_id: No open orders found for symbol {} and clientId {}", symbol, model_id_to_cancel);
        return 0;
    }

    int successfully_cancelled_count = 0;
    for (const std::string& order_id : order_ids_to_cancel) {
        spdlog::debug("cancel_orders_by_model_id: Requesting cancellation for orderId: {}", order_id);
        if (cancelSingleOrder(order_id, symbol)) { // cancelSingleOrder sends the REST request
            successfully_cancelled_count++;
            // DO NOT remove from openOrders_ here. Let WebSocket updates handle that.
        } else {
            spdlog::warn("cancel_orders_by_model_id: Failed to send cancellation request for orderId: {}", order_id);
        }
    }
    spdlog::info("cancel_orders_by_model_id: Sent {} cancellation requests for symbol {} and clientId {}", successfully_cancelled_count, symbol, model_id_to_cancel);
    return successfully_cancelled_count; // Returns count of requests SENT, not confirmed cancellations.
}

// ... existing code ...

// Closing namespace
} // namespace bp

void bp::DefaultExecutionClient::onUserFill(const backpack::Trade& sdk_trade) { // ENSURE bp:: namespace qualifier IS PRESENT
    spdlog::info("[DefaultExecutionClient::onUserFill] Received user fill/trade for symbol {}: OrderID={}, TradeID={}, Side={}, Price={}, Quantity={}, Maker={}, Fee={} {}", 
                 sdk_trade.symbol, 
                 sdk_trade.orderId, 
                 sdk_trade.id, 
                 backpack::order_side_to_string(sdk_trade.side), 
                 sdk_trade.price, 
                 sdk_trade.quantity, 
                 sdk_trade.is_maker, 
                 sdk_trade.fee,      
                 sdk_trade.fee_symbol 
                 );
    // TODO: Implement logic to update position, P&L, etc., based on this fill.
}


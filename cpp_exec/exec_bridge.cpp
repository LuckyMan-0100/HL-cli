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

#include <backpack/backpack_client.hpp> // Assuming this exists and has necessary types
#include <nlohmann/json.hpp>
#include <sw/redis++/redis++.h>

#include "exec_bridge.hpp" // Include the header file
#include "redis_subscriber.hpp"
#include "indicators.hpp"

#include <sstream>
#include <iomanip>
#include <openssl/evp.h>
#include <openssl/bio.h>
#include <openssl/buffer.h>
#include <curl/curl.h>

#include <spdlog/spdlog.h>
#include <boost/asio.hpp>
#include <boost/beast.hpp>
#include <boost/beast/websocket.hpp>

#include "risk_manager.hpp"

namespace bp {

    // Using Backpack SDK types directly if available, otherwise define similar ones
    // Assuming backpack::OrderType, backpack::OrderSide, backpack::TimeInForce exist
    using backpack::OrderRequest;

    using backpack::OrderSide;
    using backpack::OrderType;
    using backpack::TimeInForce;

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
        if (ts > 1'000'000'000'000LL) return ts / 1'000;   // Âµs
        if (ts < 1'000'000'000LL)      return ts * 1'000;   //  s
        return ts; // already ms
    }

    using json = nlohmann::json;

    // Helper function for CURL response handling
    size_t WriteCallback(void* contents, size_t size, size_t nmemb, std::string* userp) {
        userp->append((char*)contents, size * nmemb);
        return size * nmemb;
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
        BIO_flush(bio);
        BIO_get_mem_ptr(bio, &bufferPtr);

        std::string result(bufferPtr->data, bufferPtr->length);

        BIO_free_all(bio);
        return result;
    }

    // Callback function for handling WebSocket trade updates
    void handle_trade_update(const backpack::Trade& trade) {
        try {
            json fill_status = {
                {"tradeId", trade.id},
                {"symbol", trade.symbol},
                {"price", trade.price},
                {"quantity", trade.quantity},
                {"isMaker", trade.is_buyer_maker}, // Note: Check if this aligns with your definition of maker
                {"status", "FILL"}, // Indicate it's a fill/partial fill
                {"timestamp", trade.timestamp}
            };
            
            // TODO: Need access to the Redis client or publish mechanism.
            // This static/global approach is problematic. 
            // Ideally, the callback should be a member function or lambda 
            // capturing the necessary context (like a Redis client instance).
            // For now, let's assume a global/static Redis instance for simplicity.
            static auto redis = sw::redis::Redis("tcp://127.0.0.1:6379"); 
            redis.publish("orders:fills", fill_status.dump());
            std::cout << "Published fill: " << fill_status.dump() << std::endl; // Logging

        } catch (const std::exception& e) {
            std::cerr << "Error processing trade update: " << e.what() << std::endl;
        }
         catch (...) {
             std::cerr << "Unknown error processing trade update." << std::endl;
         }
    }

    DefaultExecutionClient::DefaultExecutionClient(const std::string& api_key,
                                                 const std::string& base64_private_key,
                                                 const std::string& symbol,
                                                 double max_daily_drawdown_pct)
        : trading_symbol_(symbol)
        , api_key_(api_key)
        , base64_private_key_(base64_private_key)
        , client_(std::make_unique<backpack::BackpackClient>(api_key, base64_private_key))
        , redis_client_(std::make_unique<sw::redis::Redis>("tcp://127.0.0.1:6379"))
        , risk_manager_(std::make_unique<RiskManager>(max_daily_drawdown_pct))
        , best_bid_(0.0)
        , best_ask_(0.0)
        , running_(false) {
        
        // Start IO context in a separate thread
        io_thread_ = std::thread([this]() {
            running_ = true;
            while (running_) {
                try {
                    ioc_.run();
                } catch (const std::exception& e) {
                    spdlog::error("IO context error: {}", e.what());
                }
            }
        });
    }

    DefaultExecutionClient::~DefaultExecutionClient() {
        running_ = false;
        if (ws_) {
            boost::beast::error_code ec;
            ws_->close(boost::beast::websocket::close_code::normal, ec);
        }
        ioc_.stop();
        if (io_thread_.joinable()) {
            io_thread_.join();
        }
    }

    void DefaultExecutionClient::onTick(const std::string& symbol, double bid, double ask, 
                                      double bid_qty, double ask_qty, uint64_t timestamp) {
        if (symbol != trading_symbol_) return;
        
        best_bid_ = bid;
        best_ask_ = ask;
        
        // Log the tick data
        spdlog::debug("Tick: {} bid={} ask={} bidQty={} askQty={} ts={}", 
                      symbol, bid, ask, bid_qty, ask_qty, timestamp);
    }

    void DefaultExecutionClient::onTrade(const std::string& symbol, double price, double quantity, uint64_t timestamp) {
        if (symbol != trading_symbol_) return;
        
        // Update OHLCV buffer with trade data
        ohlcv_buffer_.update_from_trade(symbol, price, quantity, timestamp);
        
        // Log the trade
        spdlog::debug("Trade: {} price={} qty={} ts={}", 
                      symbol, price, quantity, timestamp);
    }

    void DefaultExecutionClient::onKline(const std::string& symbol, const std::string& interval,
                                       double open, double high, double low, double close,
                                       double volume, uint64_t timestamp) {
        if (symbol != trading_symbol_) return;
        
        // Update OHLCV buffer with exchange kline
        ohlcv_buffer_.update_from_kline(symbol, interval, open, high, low, close, 
                                       volume, timestamp);
        
        // Log the candlestick data
        spdlog::debug("Kline: {} interval={} open={} high={} low={} close={} volume={} ts={}", 
                      symbol, interval, open, high, low, close, volume, timestamp);
    }

    double DefaultExecutionClient::bestBid() const {
        return best_bid_;
    }

    double DefaultExecutionClient::bestAsk() const {
        return best_ask_;
    }

    double DefaultExecutionClient::mid() const {
        if (best_bid_ <= 0.0 || best_ask_ <= 0.0) {
            return 0.0;
        }
        return (best_bid_ + best_ask_) / 2.0;
    }

    // Technical indicators
    double DefaultExecutionClient::getRSI(const std::string& interval) const {
        auto prices = ohlcv_buffer_.get_close_prices(trading_symbol_, interval);
        return rsi_.calculate(prices);
    }

    double DefaultExecutionClient::getMACD(const std::string& interval) const {
        auto prices = ohlcv_buffer_.get_close_prices(trading_symbol_, interval);
        return macd_.calculate(prices);
    }

    double DefaultExecutionClient::getEMA200(const std::string& interval) const {
        auto prices = ohlcv_buffer_.get_close_prices(trading_symbol_, interval);
        return ema200_.calculate(prices);
    }

    bool DefaultExecutionClient::checkTechnicalFilters(bool is_buy, const std::string& interval) const {
        // Get current price and indicators
        double current_price = mid();
        double rsi_value = getRSI(interval);
        double macd_value = getMACD(interval);
        double ema200_value = getEMA200(interval);

        if (std::isnan(current_price) || std::isnan(rsi_value) || 
            std::isnan(macd_value) || std::isnan(ema200_value)) {
            return false; // Insufficient data
        }

        if (is_buy) {
            // Buy conditions:
            // 1. RSI < 30 (oversold)
            // 2. MACD > 0 (bullish momentum)
            // 3. Price above EMA200 (long-term uptrend)
            return rsi_value < 30 && macd_value > 0 && current_price > ema200_value;
        } else {
            // Sell conditions:
            // 1. RSI > 70 (overbought)
            // 2. MACD < 0 (bearish momentum)
            // 3. Price below EMA200 (long-term downtrend)
            return rsi_value > 70 && macd_value < 0 && current_price < ema200_value;
        }
    }

    // Position sizing
    double DefaultExecutionClient::sigmoid(double x) const {
        return 1.0 / (1.0 + std::exp(-x));
    }

    double DefaultExecutionClient::getConfidenceWeightedSize(double base_size, double confidence) const {
        // Scale confidence to be centered around 0.5
        double scaled_conf = CONFIDENCE_SCALE * (confidence - 0.5);
        // Apply sigmoid to get a multiplier between 0 and 1
        double multiplier = sigmoid(scaled_conf);
        return base_size * multiplier;
    }

    // Risk management
    bool DefaultExecutionClient::checkRiskLimits() const {
        return risk_manager_->checkRiskLimits();
    }

    void DefaultExecutionClient::sleepOnDrawdown(std::chrono::seconds duration) {
        // Cancel all orders first
        cancel_all_orders(trading_symbol_);
        
        // Sleep and reset risk metrics
        risk_manager_->sleepOnDrawdown(duration);
    }

    double DefaultExecutionClient::getDailyPnL() const {
        return risk_manager_->getDailyPnL();
    }

    double DefaultExecutionClient::getCurrentDrawdown() const {
        return risk_manager_->getCurrentDrawdown();
    }

    // Order execution methods
    void DefaultExecutionClient::send_market(const std::string& symbol, double quantity, bool is_buy, 
                                           const OrderFlags& flags) {
        OrderRequest order;
        order.symbol = symbol;
        order.side = is_buy ? OrderSide::BUY : OrderSide::SELL;
        order.type = OrderType::MARKET;
        order.quantity = quantity;
        send_order(order, flags);
    }

    void DefaultExecutionClient::send_limit(const std::string& symbol, double quantity, double price, bool is_buy, 
                                           TimeInForce tif, const OrderFlags& flags) {
        OrderRequest order;
        order.symbol = symbol;
        order.side = is_buy ? OrderSide::BUY : OrderSide::SELL;
        order.type = OrderType::LIMIT;
        order.quantity = quantity;
        order.price = price;
        order.time_in_force = tif;
        send_order(order, flags);
    }

    void DefaultExecutionClient::send_order(const OrderRequest& order, const OrderFlags& flags) {
        // Check risk limits before sending order
        if (!checkRiskLimits()) {
            spdlog::error("Order rejected: Risk limits exceeded");
            return;
        }

        try {
            json params = {
                {"symbol", order.symbol},
                {"side", order_side_to_string(order.side)},
                {"type", order_type_to_string(order.type)},
                {"quantity", order.quantity}
            };
            
            if (order.type == OrderType::LIMIT) {
                params["price"] = order.price;
                params["timeInForce"] = static_cast<int>(order.time_in_force);
            }
            
            // Add strategy flags
            add_strategy_flags(params, flags);
            
            auto response = execute_signed_request("/api/v1/order/execute", "orderExecute", params);
            
            // Prepare order status update
            json status = {
                {"orderId", response["orderId"]},
                {"symbol", order.symbol},
                {"side", order_side_to_string(order.side)},
                {"type", order_type_to_string(order.type)},
                {"price", order.price},
                {"quantity", order.quantity},
                {"status", "PLACED"},
                {"timestamp", std::chrono::system_clock::now().time_since_epoch().count()}
            };

            // Add flags to status update
            if (flags.post_only) status["postOnly"] = true;
            if (flags.reduce_only) status["reduceOnly"] = true;
            if (flags.auto_borrow) status["autoBorrow"] = true;
            if (flags.self_trade_prevention != SelfTradePrevention::NONE) {
                status["selfTradePrevention"] = self_trade_prevention_to_string(flags.self_trade_prevention);
            }

            // Publish order status to Redis
            redis_client_->publish("orders:status", status.dump());

        } catch (const std::exception& e) {
            spdlog::error("Error placing order: {}", e.what());
            
            // Publish error status
            json error_status = {
                {"symbol", order.symbol},
                {"side", order_side_to_string(order.side)},
                {"type", order_type_to_string(order.type)},
                {"price", order.price},
                {"quantity", order.quantity},
                {"status", "ERROR"},
                {"error", e.what()},
                {"timestamp", std::chrono::system_clock::now().time_since_epoch().count()}
            };

            // Add flags to error status
            if (flags.post_only) error_status["postOnly"] = true;
            if (flags.reduce_only) error_status["reduceOnly"] = true;
            if (flags.auto_borrow) error_status["autoBorrow"] = true;
            if (flags.self_trade_prevention != SelfTradePrevention::NONE) {
                error_status["selfTradePrevention"] = self_trade_prevention_to_string(flags.self_trade_prevention);
            }

            try {
                redis_client_->publish("orders:status", error_status.dump());
            } catch (const std::exception& redis_error) {
                spdlog::error("Error publishing to Redis: {}", redis_error.what());
            }
        }
    }

    // Add order cancellation with status updates
    bool DefaultExecutionClient::cancel_order(const std::string& symbol, const std::string& order_id) {
        try {
            json params = {
                {"symbol", symbol},
                {"orderId", order_id}
            };
            
            execute_signed_request("/api/v1/order/cancel", "orderCancel", params);
            
            // Publish cancellation status
            json status = {
                {"orderId", order_id},
                {"symbol", symbol},
                {"status", "CANCELLED"},
                {"timestamp", std::chrono::system_clock::now().time_since_epoch().count()}
            };

            auto redis = sw::redis::Redis("tcp://127.0.0.1:6379");
            redis.publish("orders:status", status.dump());
            return true;

        } catch (const std::exception& e) {
            std::cerr << "Error cancelling order: " << e.what() << std::endl;
            
            // Publish error status
            json error_status = {
                {"orderId", order_id},
                {"symbol", symbol},
                {"status", "CANCEL_ERROR"},
                {"error", e.what()},
                {"timestamp", std::chrono::system_clock::now().time_since_epoch().count()}
            };

            try {
                auto redis = sw::redis::Redis("tcp://127.0.0.1:6379");
                redis.publish("orders:status", error_status.dump());
            } catch (const std::exception& redis_error) {
                std::cerr << "Error publishing to Redis: " << redis_error.what() << std::endl;
            }
            return false;
        }
    }

    int DefaultExecutionClient::cancel_all_orders(const std::string& symbol) {
        // Implementation depends on the Backpack API/SDK
        // Assuming a method like client_->cancel_all_orders(symbol)
        spdlog::info("Cancelling all orders for symbol: {}", symbol.empty() ? "<all>" : symbol);
        try {
            // TODO: Replace with actual SDK call
            // int cancelled_count = client_->cancel_all(symbol);
            // Placeholder implementation
            json params = {};
            if (!symbol.empty()) {
                params["symbol"] = symbol;
            }
            auto response = execute_signed_request("/api/v1/order/cancel/all", "orderCancelAll", params);
            // Assuming response contains count or details
            spdlog::info("Cancel all response: {}", response.dump());
            // Parse response to get actual count if available
            return response.contains("count") ? response["count"].get<int>() : 0; 
        } catch (const std::exception& e) {
            spdlog::error("Error cancelling all orders: {}", e.what());
            return 0;
        }
    }

    std::string DefaultExecutionClient::order_side_to_string(OrderSide side) {
        switch (side) {
            case OrderSide::BUY: return "BUY";
            case OrderSide::SELL: return "SELL";
            default: return "UNKNOWN";
        }
    }

    std::string DefaultExecutionClient::order_type_to_string(OrderType type) {
        switch (type) {
            case OrderType::MARKET: return "MARKET";
            case OrderType::LIMIT: return "LIMIT";
            default: return "UNKNOWN";
        }
    }

    std::string DefaultExecutionClient::self_trade_prevention_to_string(SelfTradePrevention stp) {
        switch (stp) {
            case SelfTradePrevention::NONE: return "NONE";
            case SelfTradePrevention::REJECT_TAKER: return "REJECT_TAKER";
            case SelfTradePrevention::REJECT_MAKER: return "REJECT_MAKER";
            case SelfTradePrevention::REJECT_BOTH: return "REJECT_BOTH";
            default: return "UNKNOWN";
        }
    }

    void DefaultExecutionClient::add_strategy_flags(json& params, const OrderFlags& flags) const {
        if (flags.post_only) params["postOnly"] = true;
        if (flags.reduce_only) params["reduceOnly"] = true; // Check if supported by API
        if (flags.auto_borrow) params["trigger"] = true; // Check API docs for correct param name
        if (flags.self_trade_prevention != SelfTradePrevention::NONE) {
            params["selfTradePrevention"] = self_trade_prevention_to_string(flags.self_trade_prevention);
        }
    }

    std::string DefaultExecutionClient::build_signing_string(const std::string& instruction, const json& params) const {
        std::stringstream ss;
        int64_t timestamp = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();
        
        ss << "instruction=" << instruction;
        
        // Add parameters in alphabetical order
        for (auto it = params.begin(); it != params.end(); ++it) {
            ss << "&" << it.key() << "=" << it.value().dump();
        }
        
        ss << "&timestamp=" << timestamp;
        ss << "&window=" << DEFAULT_WINDOW;
        
        return ss.str();
    }

    std::string DefaultExecutionClient::sign_request(const std::string& signing_string) const {
        EVP_MD_CTX* ctx = EVP_MD_CTX_new();
        EVP_PKEY* key = nullptr;
        
        try {
            // Create key from API secret
            key = EVP_PKEY_new_raw_private_key(EVP_PKEY_ED25519, nullptr,
                reinterpret_cast<const unsigned char*>(api_secret_.c_str()),
                api_secret_.length());
            
            if (!key) {
                throw std::runtime_error("Failed to create private key");
            }
            
            // Initialize signing context
            if (EVP_DigestSignInit(ctx, nullptr, nullptr, nullptr, key) != 1) {
                throw std::runtime_error("Failed to initialize signing context");
            }
            
            // Sign the string
            size_t sig_len;
            if (EVP_DigestSign(ctx, nullptr, &sig_len,
                reinterpret_cast<const unsigned char*>(signing_string.c_str()),
                signing_string.length()) != 1) {
                throw std::runtime_error("Failed to determine signature length");
            }
            
            std::vector<unsigned char> sig(sig_len);
            if (EVP_DigestSign(ctx, sig.data(), &sig_len,
                reinterpret_cast<const unsigned char*>(signing_string.c_str()),
                signing_string.length()) != 1) {
                throw std::runtime_error("Failed to create signature");
            }
            
            // Base64 encode the signature
            std::string encoded_sig = base64_encode(sig.data(), sig_len);
            
            EVP_PKEY_free(key);
            EVP_MD_CTX_free(ctx);
            
            return encoded_sig;
            
        } catch (...) {
            if (key) EVP_PKEY_free(key);
            if (ctx) EVP_MD_CTX_free(ctx);
            throw;
        }
    }

    json DefaultExecutionClient::execute_signed_request(const std::string& endpoint,
                                                      const std::string& instruction,
                                                      const json& params) const {
        CURL* curl = curl_easy_init();
        if (!curl) {
            throw std::runtime_error("Failed to initialize CURL");
        }
        
        try {
            std::string url = std::string(BASE_URL) + endpoint;
            std::string signing_string = build_signing_string(instruction, params);
            std::string signature = sign_request(signing_string);
            int64_t timestamp = std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count();
            
            // Set up headers
            struct curl_slist* headers = nullptr;
            headers = curl_slist_append(headers, ("X-API-Key: " + api_key_).c_str());
            headers = curl_slist_append(headers, ("X-Timestamp: " + std::to_string(timestamp)).c_str());
            headers = curl_slist_append(headers, ("X-Window: " + std::to_string(DEFAULT_WINDOW)).c_str());
            headers = curl_slist_append(headers, ("X-Signature: " + signature).c_str());
            headers = curl_slist_append(headers, "Content-Type: application/json");
            
            std::string response_string;
            std::string request_body = params.dump();
            
            curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
            curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
            curl_easy_setopt(curl, CURLOPT_POSTFIELDS, request_body.c_str());
            curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, WriteCallback);
            curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response_string);
            
            CURLcode res = curl_easy_perform(curl);
            if (res != CURLE_OK) {
                throw std::runtime_error(std::string("CURL request failed: ") + curl_easy_strerror(res));
            }
            
            long response_code;
            curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &response_code);
            if (response_code != 200) {
                throw std::runtime_error("HTTP request failed with code " + std::to_string(response_code) +
                                       ": " + response_string);
            }
            
            curl_slist_free_all(headers);
            curl_easy_cleanup(curl);
            
            return json::parse(response_string);
            
        } catch (...) {
            curl_easy_cleanup(curl);
            throw;
        }
    }

} // namespace bp
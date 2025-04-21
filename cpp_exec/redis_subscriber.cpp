#include "redis_subscriber.hpp"
#include "execution_client.hpp"
#include <spdlog/spdlog.h>
#include <nlohmann/json.hpp>
#include <boost/asio.hpp>
#include <chrono>
#include <thread>

using json = nlohmann::json;

namespace bp {

// Helper to get environment variable or default (duplicate from exec_bridge, consider moving to common util header)
inline std::string getenv_or(const char* key, const std::string& def = "") {
    const char* val = std::getenv(key);
    return val ? std::string(val) : def;
}

// Helper function to safely get double from string or number (duplicate)
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

// Helper function to safely get int64 from string or number (duplicate)
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

// Convert microseconds or seconds to milliseconds (duplicate)
inline int64_t to_ms(int64_t ts) {
    if (ts > 1'000'000'000'000LL) return ts / 1'000;   // µs
    if (ts < 1'000'000'000LL)      return ts * 1'000;   //  s
    return ts; // already ms
}

RedisSubscriber::RedisSubscriber(ExecutionClient& exec_client)
    : exec_client_(exec_client) {
    try {
        auto redis = sw::redis::Redis("tcp://localhost:6379");
        subscriber_ = std::make_unique<sw::redis::Subscriber>(redis.subscriber());
    } catch (const sw::redis::Error& e) {
        spdlog::error("Failed to create Redis subscriber: {}", e.what());
        throw;
    }
}

RedisSubscriber::~RedisSubscriber() {
    stop();
}

void RedisSubscriber::start() {
    if (running_) return;
    running_ = true;

    // Set up message handlers
    auto handle_message = [this](std::string channel, std::string msg) {
        try {
            if (channel == "book_ticker") {
                handleBookTickerMessage(msg);
            } else if (channel == "trades") {
                handleTradeMessage(msg);
            } else if (channel == "klines") {
                handleKlineMessage(msg);
            }
        } catch (const std::exception& e) {
            spdlog::error("Error handling message on channel {}: {}", channel, e.what());
        }
    };

    // Subscribe to channels
    subscriber_->on_message(handle_message);
    subscriber_->subscribe("book_ticker");
    subscriber_->subscribe("trades");
    subscriber_->subscribe("klines");

    // Start consuming messages
    while (running_) {
        try {
            subscriber_->consume();
        } catch (const sw::redis::Error& e) {
            spdlog::error("Redis consume error: {}", e.what());
            std::this_thread::sleep_for(std::chrono::seconds(1));
        }
    }
}

void RedisSubscriber::stop() {
    running_ = false;
    if (subscriber_) {
        subscriber_->unsubscribe();
    }
}

void RedisSubscriber::handleBookTickerMessage(const std::string& msg) {
    auto j = json::parse(msg);
    std::string symbol = j["s"].get<std::string>();
    double bid_price = std::stod(j["b"].get<std::string>());
    double ask_price = std::stod(j["a"].get<std::string>());
    double bid_qty = std::stod(j["B"].get<std::string>());
    double ask_qty = std::stod(j["A"].get<std::string>());
    uint64_t timestamp = j["T"].get<uint64_t>();

    exec_client_.onTick(symbol, bid_price, ask_price, bid_qty, ask_qty, timestamp);
}

void RedisSubscriber::handleTradeMessage(const std::string& msg) {
    auto j = json::parse(msg);
    std::string symbol = j["s"].get<std::string>();
    double price = std::stod(j["p"].get<std::string>());
    double quantity = std::stod(j["q"].get<std::string>());
    int64_t timestamp = j["T"].get<int64_t>();

    exec_client_.onTrade(symbol, price, quantity, timestamp);
}

void RedisSubscriber::handleKlineMessage(const std::string& msg) {
    auto j = json::parse(msg);
    std::string symbol = j["s"].get<std::string>();
    std::string interval = j["i"].get<std::string>();
    double open = std::stod(j["o"].get<std::string>());
    double high = std::stod(j["h"].get<std::string>());
    double low = std::stod(j["l"].get<std::string>());
    double close = std::stod(j["c"].get<std::string>());
    double volume = std::stod(j["v"].get<std::string>());
    int64_t timestamp = j["T"].get<int64_t>();

    exec_client_.onKline(symbol, interval, open, high, low, close, volume, timestamp);
}

} // namespace bp 
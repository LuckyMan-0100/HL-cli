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

#include <backpack/backpack_client.hpp> // Assuming this exists and has necessary types
#include <nlohmann/json.hpp>
#include <sw/redis++/redis++.h>

#include "exec_bridge.hpp" // Include the header file
#include "redis_subscriber.hpp"

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


    ExecutionClient::ExecutionClient() 
        : client_(std::make_unique<backpack::BackpackClient>()),
          best_bid_(std::numeric_limits<double>::quiet_NaN()), 
          best_ask_(std::numeric_limits<double>::quiet_NaN()) 
    {
        // Load API Credentials from environment variables
        const std::string api_key = getenv_or("BACKPACK_API_KEY");
        const std::string api_secret = getenv_or("BACKPACK_API_SECRET");
        if (api_key.empty() || api_secret.empty()) {
            std::cerr << "Warning: BACKPACK_API_KEY or BACKPACK_API_SECRET not set." << std::endl;
            // Decide if this is a fatal error or if it can run without credentials (e.g., read-only)
            // For trading, it's likely fatal.
            throw std::runtime_error("API credentials not configured.");
        }
        client_->set_credentials(api_key, api_secret);
        trading_symbol_ = getenv_or("TRADING_SYMBOL", "SOL_USDC_PERP");
         std::cout << "ExecutionClient initialized for symbol: " << trading_symbol_ << std::endl;
    }

    // --- L1 Cache Accessors ---
    double ExecutionClient::bestBid() const {
        return best_bid_.load(std::memory_order_relaxed);
    }

    double ExecutionClient::bestAsk() const {
        return best_ask_.load(std::memory_order_relaxed);
    }

    double ExecutionClient::mid() const {
        double b = best_bid_.load(std::memory_order_relaxed);
        double a = best_ask_.load(std::memory_order_relaxed);
        if (std::isnan(b) || std::isnan(a) || b <= 0 || a <= 0) {
            return std::numeric_limits<double>::quiet_NaN();
        }
        return (b + a) / 2.0;
    }

    // --- Tick Handler --- 
    void ExecutionClient::onTick(double received_bid, double received_ask, int64_t timestamp_ms) {
        {
            best_bid_.store(received_bid, std::memory_order_relaxed);
            best_ask_.store(received_ask, std::memory_order_relaxed);
        } // Lock released

        // ---- Example Strategy: Post-Only Maker ----
        // If mid-price is valid, place a buy slightly below best bid 
        // and a sell slightly above best ask.
        // WARNING: Naive example. Needs cancellation logic, inventory management, risk checks etc.
        double current_mid = mid(); 
        if (!std::isnan(current_mid)) {
             // Configuration (consider moving to members or config file)
            const double tick_size = 0.0001; // Example tick size for SOL_USDC_PERP
            const double order_qty = 0.1; // Example order quantity
            const int spread_ticks = 5; // Place orders N ticks away from current BBO

            double post_buy_price = best_bid_.load(std::memory_order_relaxed) - spread_ticks * tick_size;
            double post_sell_price = best_ask_.load(std::memory_order_relaxed) + spread_ticks * tick_size;

            // TODO: Add cancellation logic for previous orders before placing new ones.
            // TODO: Add checks for sufficient balance.
            // TODO: Add inventory skew logic.
            // TODO: Add rate limiting / throttling.

            // Place Buy Order (Post-Only)
            try {
                 std::cout << "[Strategy] Attempting Post-Only Buy @ " << post_buy_price << std::endl;
                send_limit(trading_symbol_, order_qty, post_buy_price, true, TimeInForce::POST_ONLY); 
            } catch (const std::exception& e) {
                 std::cerr << "[Strategy] Failed Post-Only Buy: " << e.what() << std::endl;
            }

            // Place Sell Order (Post-Only)
             try {
                  std::cout << "[Strategy] Attempting Post-Only Sell @ " << post_sell_price << std::endl;
                 send_limit(trading_symbol_, order_qty, post_sell_price, false, TimeInForce::POST_ONLY);
             } catch (const std::exception& e) {
                 std::cerr << "[Strategy] Failed Post-Only Sell: " << e.what() << std::endl;
             }
        }
        // --------------------------------------------
    }

    // --- Order Execution Methods (using Backpack SDK) ---
    void ExecutionClient::send_order(const OrderRequest& order)
    {
        try {
            auto placed = client_->create_order(order);   // SDK call
            std::cout << "[Order] placed id=" << placed.id
                      << " px=" << placed.price
                      << " qty=" << placed.quantity << std::endl;
        }
        catch (const std::exception& e) {
            std::cerr << "[Order] failed: " << e.what() << std::endl;
        }
    }
        OrderRequest order;
        order.symbol = symbol;
        order.side = is_buy ? OrderSide::BUY : OrderSide::SELL;
        order.type = OrderType::MARKET;
        order.quantity = std::to_string(quantity); // SDK might expect string
        return send_order(order);
    }

    void ExecutionClient::send_order(const OrderRequest& order)
    {
        try {
            auto placed = client_->create_order(order);   // SDK call
            std::cout << "[Order] placed id=" << placed.id
                      << " px=" << placed.price
                      << " qty=" << placed.quantity << std::endl;
        }
        catch (const std::exception& e) {
            std::cerr << "[Order] failed: " << e.what() << std::endl;
        }
    }
        OrderRequest order;
        order.symbol = symbol;
        order.side = is_buy ? OrderSide::BUY : OrderSide::SELL;
        order.type = OrderType::LIMIT;
        order.quantity = std::to_string(quantity);
        order.price = std::to_string(price);
        order.time_in_force = tif; 
        return send_order(order);
    }
    
    // Add Cancel Order functionality if needed
    // bool ExecutionClient::cancel_order(const std::string& symbol, const std::string& order_id) {
    //     try {
    //          return client_->cancel_order(symbol, order_id);
    //      } catch (const std::exception& e) {
    //          std::cerr << "Failed to cancel order " << order_id << ": " << e.what() << std::endl;
    //          return false;
    //      }
    // }


private:
    OrderResponse ExecutionClient::send_order(const OrderRequest& order) {
        // Optional: Test order first (can add latency)
        // if (!client_->test_order(order)) {
        //     throw std::runtime_error("Order validation failed");
        // }
        try {
            auto placed_order = client_->create_order(order);
            std::cout << "Order placed: ID=" << placed_order.id 
                     << ", Symbol=" << placed_order.symbol
                     << ", Side=" << static_cast<int>(placed_order.side) // Assuming enum needs cast or stringify func
                     << ", Type=" << static_cast<int>(placed_order.type)
                     << ", Price=" << placed_order.price
                     << ", Qty=" << placed_order.quantity
                     << ", Status=" << backpack::order_status_to_string(placed_order.status) 
                     << std::endl;
             return placed_order;
        } catch (const std::exception& e) {
            // More specific error handling could be useful
             std::cerr << "Failed to send order: Type=" << static_cast<int>(order.type)
                      << ", Side=" << static_cast<int>(order.side)
                      << ", Price=" << order.price
                      << ", Qty=" << order.quantity
                      << ", Error: " << e.what() << std::endl;
            throw; // Re-throw after logging
        }
    }

    std::unique_ptr<backpack::BackpackClient> client_;
    std::string trading_symbol_;

    // L1 Cache
    std::atomic<double> best_bid_;
    std::atomic<double> best_ask_;
};

} // namespace bp

// --- Main Application Entry Point ---
int main() {
    std::cout << "Starting Execution Bridge..." << std::endl;

    try {
        bp::ExecutionClient exec_client; // Handles API creds
        bp::RedisSubscriber redis_subscriber(exec_client);

        redis_subscriber.start();

        // Keep main thread alive (e.g., wait for termination signal)
        // For simplicity, just sleep indefinitely. Proper signal handling is better.
        while (true) {
            std::this_thread::sleep_for(std::chrono::seconds(60));
            // Add health checks or other periodic tasks if needed
        }

        // Clean shutdown (won't be reached in this simple loop)
        // std::cout << "Shutting down..." << std::endl;
        // redis_subscriber.stop();

    } catch (const std::exception& e) {
        std::cerr << "Fatal Error: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}

/*
// --- Old Pybind11 Code (Removed) ---
PYBIND11_MODULE(exec_bridge, m) {
    py::class_<bp::ExecutionClient>(m, "ExecutionClient")
        .def(py::init<>())
        .def("set_credentials", &bp::ExecutionClient::set_credentials,
             py::arg("api_key"), py::arg("api_secret"))
        .def("send_market", &bp::ExecutionClient::send_market,
             py::arg("symbol"), py::arg("quantity"), py::arg("is_buy"))
        .def("send_limit", &bp::ExecutionClient::send_limit,
             py::arg("symbol"), py::arg("quantity"), py::arg("price"), py::arg("is_buy"))
        .def("send_stop_loss", &bp::ExecutionClient::send_stop_loss,
             py::arg("symbol"), py::arg("quantity"), py::arg("price"), py::arg("is_buy"))
        .def("send_take_profit", &bp::ExecutionClient::send_take_profit,
             py::arg("symbol"), py::arg("quantity"), py::arg("price"), py::arg("is_buy"));

    py::enum_<bp::Side>(m, "Side")
        .value("Buy", bp::Side::Buy)
        .value("Sell", bp::Side::Sell);

    py::enum_<bp::OrderType>(m, "OrderType")
        .value("Market", bp::OrderType::MARKET)
        .value("Limit", bp::OrderType::LIMIT)
        .value("StopLoss", bp::OrderType::STOP_LOSS)
        .value("TakeProfit", bp::OrderType::TAKE_PROFIT);
}
*/
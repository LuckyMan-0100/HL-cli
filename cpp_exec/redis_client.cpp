#include <iostream>
#include <string>
#include <unordered_map>
#include <vector>
#include <mutex>
#include <thread>
#include <chrono>

// Include compatibility aliases for WebSocket++
#include "websocketpp_compat.hpp"
#include <websocketpp/config/asio_client.hpp>
#include <websocketpp/client.hpp>

#include <boost/asio/ssl/context.hpp>
#include <boost/asio/ssl/stream.hpp>

#include <sw/redis++/redis++.h>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

namespace asio = boost::asio;

// Type aliases for WebSocket++
using ws_config = websocketpp::config::asio_tls_client;
using ws_client = websocketpp::client<ws_config>;
using message_ptr = ws_client::message_ptr;

// Redis connection ports
constexpr int REDIS_INPUT_PORT = 6379;  // WebSocket data comes in on this port
constexpr int REDIS_OUTPUT_PORT = 6380; // Data goes out through stunnel on this port

/****************************************************************************************
 * Simple in‑memory Level‑2 OrderBook representation for a single symbol.
 ****************************************************************************************/
struct OrderBook {
    using Price = double;
    using Qty   = double;
    std::unordered_map<Price, Qty> bids; // price → qty
    std::unordered_map<Price, Qty> asks; // price → qty
    std::mutex mtx;

    void apply_update(const json& msg) {
        std::lock_guard<std::mutex> lock(mtx);
        // Asks
        if (msg.contains("a")) {
            for (auto& lvl : msg["a"]) {
                Price p = std::stod(lvl[0].get<std::string>());
                Qty   q = std::stod(lvl[1].get<std::string>());
                if (q == 0) {
                    asks.erase(p);
                } else {
                    asks[p] = q;
                }
            }
        }
        // Bids
        if (msg.contains("b")) {
            for (auto& lvl : msg["b"]) {
                Price p = std::stod(lvl[0].get<std::string>());
                Qty   q = std::stod(lvl[1].get<std::string>());
                if (q == 0) {
                    bids.erase(p);
                } else {
                    bids[p] = q;
                }
            }
        }
        
        // After updating the orderbook, publish L1 data to Redis
        publish_l1_data();
    }

    void publish_l1_data() const {
        std::lock_guard<std::mutex> lock(mtx);
        if (bids.empty() || asks.empty()) return;
        
        // Find best bid and ask
        auto best_bid_it = std::max_element(bids.begin(), bids.end(), 
            [](const auto& a, const auto& b) { return a.first < b.first; });
        auto best_ask_it = std::min_element(asks.begin(), asks.end(), 
            [](const auto& a, const auto& b) { return a.first < b.first; });
        
        if (best_bid_it != bids.end() && best_ask_it != asks.end()) {
            double best_bid = best_bid_it->first;
            double best_ask = best_ask_it->first;
            double bid_qty = best_bid_it->second;
            double ask_qty = best_ask_it->second;
            
            // Get timestamp in microseconds
            auto now = std::chrono::system_clock::now();
            auto now_us = std::chrono::time_point_cast<std::chrono::microseconds>(now);
            uint64_t timestamp = now_us.time_since_epoch().count();
            
            // Create L1 data JSON
            json l1_data = {
                {"symbol", "SOL_USDC_PERP"}, // Could be made configurable
                {"bidPrice", best_bid},
                {"askPrice", best_ask},
                {"bidQty", bid_qty},
                {"askQty", ask_qty},
                {"timestamp", timestamp},
                {"updateId", timestamp} // Using timestamp as updateId for simplicity
            };
            
            // This needs to be called from a context with access to the Redis client
            if (ExecutionClient::redis_instance) {
                ExecutionClient::redis_instance->publish("l1:quotes", l1_data.dump());
            }
        }
    }

    json snapshot(int depth = 10) const {
        std::lock_guard<std::mutex> lock(mtx);
        json j;
        // Get top N levels (unsorted_map, so copy to vector & sort).
        std::vector<std::pair<Price, Qty>> bid_vec(bids.begin(), bids.end());
        std::vector<std::pair<Price, Qty>> ask_vec(asks.begin(), asks.end());
        std::sort(bid_vec.begin(), bid_vec.end(), [](auto& a, auto& b){ return a.first > b.first; });
        std::sort(ask_vec.begin(), ask_vec.end(), [](auto& a, auto& b){ return a.first < b.first; });

        for (int i = 0; i < depth && i < static_cast<int>(bid_vec.size()); ++i) {
            j["b"].push_back({ bid_vec[i].first, bid_vec[i].second });
        }
        for (int i = 0; i < depth && i < static_cast<int>(ask_vec.size()); ++i) {
            j["a"].push_back({ ask_vec[i].first, ask_vec[i].second });
        }
        return j;
    }
};

/****************************************************************************************
 * ExecutionClient: connects to WebSocket depth stream, updates OrderBook, and persists
 * snapshots to Redis. Replace stubbed place‑order logic with real exchange REST/WS calls.
 ****************************************************************************************/
class ExecutionClient {
public:
    // Static Redis client instance for L1 publishing
    static std::shared_ptr<sw::redis::Redis> redis_instance;
    static std::shared_ptr<sw::redis::Redis> redis_output_instance;
    
    ExecutionClient(const std::string& ws_uri,
                    const std::string& redis_uri,
                    const std::string& symbol,
                    int snapshot_ttl_ms = 1000)
      : _ws_uri(ws_uri), _symbol(symbol), _snapshot_ttl_ms(snapshot_ttl_ms)
    {
        // Create Redis client for primary data (port 6379)
        sw::redis::ConnectionOptions input_options;
        input_options.host = "localhost";
        input_options.port = REDIS_INPUT_PORT;
        _redis = std::make_unique<sw::redis::Redis>(input_options);
        redis_instance = _redis;
        
        // Create Redis client for output data (port 6380 - stunnel)
        sw::redis::ConnectionOptions output_options;
        output_options.host = "localhost";
        output_options.port = REDIS_OUTPUT_PORT;
        _redis_output = std::make_unique<sw::redis::Redis>(output_options);
        redis_output_instance = _redis_output;
        
        configure_websocket();
        
        std::cout << "[Redis] Connected to input port " << REDIS_INPUT_PORT 
                  << " and output port " << REDIS_OUTPUT_PORT << std::endl;
    }

    void run() {
        websocketpp::lib::error_code ec;
        auto con = _ws->get_connection(_ws_uri, ec);
        if (ec) {
            std::cerr << "[WS] Connect init error: " << ec.message() << std::endl;
            return;
        }
        _ws->connect(con);
        _ws_thread = std::thread([this]{ _ws->run(); });

        // Periodic snapshot writer
        std::thread snapshot_thread([this]{
            while (!_stop) {
                std::this_thread::sleep_for(std::chrono::milliseconds(_snapshot_ttl_ms));
                push_snapshot();
            }
        });

        // Wait until user terminates
        _ws_thread.join();
        snapshot_thread.join();
    }

    void stop() {
        _stop = true;
        _ws->stop();
    }

private:
    void configure_websocket() {
        _ws = std::make_unique<ws_client>();
        _ws->init_asio();

        _ws->set_tls_init_handler([this](const websocketpp::connection_hdl&) {
            auto ctx = std::make_shared<asio::ssl::context>(asio::ssl::context::tlsv12);
            ctx->set_options(asio::ssl::context::default_workarounds | asio::ssl::context::no_sslv2);
            return ctx;
        });

        _ws->set_message_handler([this](websocketpp::connection_hdl, message_ptr msg) {
            handle_message(msg->get_payload());
        });

        _ws->set_fail_handler([](websocketpp::connection_hdl){ std::cerr << "[WS] Connection failed" << std::endl; });
        _ws->set_close_handler([](websocketpp::connection_hdl){ std::cerr << "[WS] Connection closed" << std::endl; });
    }

    void handle_message(const std::string& payload) {
        try {
            auto j = json::parse(payload);
            if (j.contains("e") && j["e"] == "depth") {
                _ob.apply_update(j);
                
                // Extract and publish L1 data if it contains bookTicker information
                if (j.contains("b") && j.contains("a") && 
                    !j["b"].empty() && !j["a"].empty()) {
                    
                    json l1_data;
                    try {
                        // Get the best bid and ask
                        auto& bids = j["b"];
                        auto& asks = j["a"];
                        
                        // Check if we have valid bid/ask data
                        if (bids.size() > 0 && asks.size() > 0) {
                            // First entry is the best bid/ask
                            double best_bid = std::stod(bids[0][0].get<std::string>());
                            double best_ask = std::stod(asks[0][0].get<std::string>());
                            double bid_qty = std::stod(bids[0][1].get<std::string>());
                            double ask_qty = std::stod(asks[0][1].get<std::string>());
                            
                            // Get timestamp
                            auto now = std::chrono::system_clock::now();
                            auto now_us = std::chrono::time_point_cast<std::chrono::microseconds>(now);
                            uint64_t timestamp = now_us.time_since_epoch().count();
                            
                            l1_data = {
                                {"symbol", _symbol},
                                {"bidPrice", best_bid},
                                {"askPrice", best_ask},
                                {"bidQty", bid_qty},
                                {"askQty", ask_qty},
                                {"timestamp", timestamp},
                                {"updateId", j.contains("u") ? j["u"].get<uint64_t>() : timestamp}
                            };
                            
                            // Publish to L1 quotes channel for fast consumption (<80µs)
                            _redis->publish("l1:quotes", l1_data.dump());
                            
                            // Log low-latency data publication for debugging
                            std::cout << "[L1] Published quote: " << _symbol 
                                      << " bid=" << best_bid << " ask=" << best_ask << std::endl;
                        }
                    } catch (const std::exception& ex) {
                        std::cerr << "[Redis] Error publishing L1 data: " << ex.what() << std::endl;
                    }
                }
            }
        } catch (const std::exception& ex) {
            std::cerr << "[WS] JSON parse error: " << ex.what() << std::endl;
        }
    }

    void push_snapshot() {
        try {
            auto snap = _ob.snapshot();
            
            // Store L2 depth data via output Redis (stunnel)
            std::string key = "l2:depth:" + _symbol;
            _redis_output->set(key, snap.dump(), sw::redis::Expire(std::chrono::milliseconds(_snapshot_ttl_ms)));
        } catch (const std::exception& ex) {
            std::cerr << "[Redis] Error: " << ex.what() << std::endl;
        }
    }

private:
    std::unique_ptr<ws_client> _ws;
    std::unique_ptr<sw::redis::Redis> _redis;
    std::unique_ptr<sw::redis::Redis> _redis_output;
    OrderBook _ob;

    std::thread _ws_thread;
    std::atomic<bool> _stop{false};

    std::string _ws_uri;
    std::string _symbol;
    int _snapshot_ttl_ms;
};

// Initialize static Redis clients
std::shared_ptr<sw::redis::Redis> ExecutionClient::redis_instance;
std::shared_ptr<sw::redis::Redis> ExecutionClient::redis_output_instance;

/****************************************************************************************
 * Entry point – parse CLI args and launch the execution client.
 ****************************************************************************************/
int main(int argc, char* argv[]) {
    if (argc < 4) {
        std::cout << "Usage: " << argv[0] << " <wss_uri> <redis_uri> <symbol> [snapshot_ttl_ms]\n";
        std::cout << "localhost:6379 rediss://redis.com:443 SOL_USDC_PERP 10000\n";
        return 1;
    }

    std::string ws_uri   = argv[1];
    std::string redis_uri= argv[2];
    std::string symbol   = argv[3];
    int ttl              = (argc >= 5) ? std::stoi(argv[4]) : 1000;

    try {
        ExecutionClient client(ws_uri, redis_uri, symbol, ttl);
        client.run();
    } catch (const std::exception& ex) {
        std::cerr << "Fatal error: " << ex.what() << std::endl;
        return 1;
    }

    return 0;
}

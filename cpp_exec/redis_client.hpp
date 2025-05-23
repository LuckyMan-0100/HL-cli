#ifndef EXECUTION_CLIENT_HPP
#define EXECUTION_CLIENT_HPP

// Attempt to resolve Asio io_service/io_context issues with WebsocketPP
// by including the modern Boost.Asio context header first.
#include <boost/asio/io_context.hpp>
#include <boost/asio/strand.hpp> // Also include strand as it was mentioned in errors indirectly

#include <string>
#include <unordered_map>
#include <vector>
#include <mutex>
#include <atomic>
#include <memory>
#include <nlohmann/json.hpp>
#include <websocketpp/config/asio_client.hpp>
#include <websocketpp/client.hpp>
#include <sw/redis++/redis++.h>

// Redis connection ports
constexpr int REDIS_INPUT_PORT = 6379;  // WebSocket data comes in on this port
constexpr int REDIS_OUTPUT_PORT = 6380; // Data goes out through stunnel on this port

namespace client {

/**
 * Lightweight in‑memory Level‑1 order‑book for a single trading symbol.
 */
struct OrderBook {
    using Price = double;
    using Qty   = double;
    std::unordered_map<Price, Qty> bids; //!< price → qty
    std::unordered_map<Price, Qty> asks; //!< price → qty
    std::mutex mtx;

    /** Apply an incremental update coming from the depth WebSocket. */
    void apply_update(const nlohmann::json& msg);
    
    /** Publish L1 data to Redis for fast consumption by execution engine */
    void publish_l1_data() const;

    /** Return a depth snapshot (top *depth* levels) in JSON form. */
    nlohmann::json snapshot(int depth = 10) const;
};

/**
 * ExecutionClient
 *  ‑ Maintains a live order‑book from a depth WebSocket stream.
 *  ‑ Publishes L1 data via Redis pub-sub channel 'l1:quotes' in <80 µs
 *  ‑ Periodically publishes L2 snapshots to Redis with a configurable TTL.
 *  ‑ Provides hooks for real order‑execution logic (REST/WS) in the future.
 */
class ExecutionClient {
public:
    // Static Redis client instances for L1 publishing
    static std::shared_ptr<sw::redis::Redis> redis_instance;
    static std::shared_ptr<sw::redis::Redis> redis_output_instance;
    
    ExecutionClient(const std::string& ws_uri,
                    const std::string& redis_uri,
                    const std::string& symbol,
                    int snapshot_ttl_ms = 1000);

    /** Blocking run loop (returns when WebSocket exits or stop() called). */
    void run();

    /** Request a graceful shutdown. */
    void stop();

private:
    // Internal helpers
    void configure_websocket();
    void handle_message(const std::string& payload);
    void push_snapshot();

    // Aliases for WebSocket++
    using ws_config   = websocketpp::config::asio_tls_client;
    using ws_client   = websocketpp::client<ws_config>;
    using message_ptr = ws_client::message_ptr;

    // State
    std::unique_ptr<ws_client>       _ws;
    std::unique_ptr<sw::redis::Redis> _redis;
    std::unique_ptr<sw::redis::Redis> _redis_output;
    OrderBook                        _ob;

    std::thread _ws_thread;
    std::atomic<bool> _stop{false};

    std::string _ws_uri;
    std::string _symbol;
    int         _snapshot_ttl_ms;
};

} // namespace client

#endif // EXECUTION_CLIENT_HPP

#include "redis_subscriber.hpp"
#include "exec_bridge.hpp" // Assuming exec_bridge functionality is in a header now

#include <sw/redis++/redis++.h>
#include <nlohmann/json.hpp>
#include <iostream>
#include <string>
#include <chrono>
#include <stdexcept>
#include <cstdlib>

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
    if (ts > 1'000'000'000'000LL) return ts / 1'000;   // Âµs
    if (ts < 1'000'000'000LL)      return ts * 1'000;   //  s
    return ts; // already ms
}


RedisSubscriber::RedisSubscriber(ExecutionClient& exec_client)
    : exec_client_(exec_client), running_(false) {}

RedisSubscriber::~RedisSubscriber() {
    stop(); // Ensure thread is stopped and joined upon destruction
}

void RedisSubscriber::start() {
    if (running_.load()) return; // Already running
    running_.store(true);
    subscriber_thread_ = std::thread(&RedisSubscriber::run, this);
    std::cout << "RedisSubscriber thread started." << std::endl;
}

void RedisSubscriber::stop() {
    if (running_.exchange(false)) { 
        std::cout << "Stopping RedisSubscriber thread..." << std::endl;
        // Note: hiredis++ subscriber might block in consume(). 
        // A more robust stop might involve disconnecting the client 
        // or using a condition variable signal.
        if (subscriber_thread_.joinable()) {
            subscriber_thread_.join();
            std::cout << "RedisSubscriber thread stopped." << std::endl;
        } else {
             std::cout << "RedisSubscriber thread was not joinable." << std::endl;
        }
    } else {
         std::cout << "RedisSubscriber already stopped or not started." << std::endl;
    }
}

void RedisSubscriber::run() {
    try {
        sw::redis::ConnectionOptions connection_options;
        connection_options.host = getenv_or("REDIS_HOST", "127.0.0.1"); // Use 127.0.0.1 for clarity
        connection_options.port = std::stoi(getenv_or("REDIS_PORT", "6379"));
        connection_options.socket_timeout = std::chrono::milliseconds(0); // No timeout for subscribe

        // Add password if needed from env
        // std::string redis_password = getenv_or("REDIS_PASSWORD");
        // if (!redis_password.empty()) {
        //     connection_options.password = redis_password;
        // }

        sw::redis::Redis redis(connection_options);
        sw::redis::Subscriber sub = redis.subscriber();

        sub.on_message([this](std::string channel, std::string msg) {
            if (!running_.load()) return;
            try {
                // Lightweight check first
                if (msg.find("\"stream\":\"bookTicker.") == std::string::npos) {
                    //std::cout << "Ignoring non-bookTicker msg (quick check): " << msg.substr(0, 50) << "..." << std::endl;
                    return;
                }
                
                auto j = nlohmann::json::parse(msg);
                // More thorough check (redundant but safe)
                if (j.contains("stream") && j["stream"].is_string() && j["stream"].get<std::string>().find("bookTicker.") != std::string::npos && j.contains("data")) {
                    const auto& data = j["data"];
                    double bid = json_get_double(data, "b");
                    double ask = json_get_double(data, "a");
                    int64_t ts = to_ms(json_get_int64(data, "T"));

                    if (bid > 0 && ask > 0 && ts > 0) {
                        // Call the execution client's handler
                        exec_client_.onTick(bid, ask, ts);
                    } else {
                         std::cerr << "Invalid tick data fields: b=" << bid << ", a=" << ask << ", t=" << ts << " - Msg: " << msg << std::endl;
                    }
                } else {
                     //std::cout << "Ignoring non-bookTicker msg (detailed check)" << std::endl;
                }
            } catch (const nlohmann::json::parse_error& e) {
                std::cerr << "JSON parse error on Redis message: " << e.what() << " - Message: " << msg << std::endl;
            } catch (const std::exception& e) {
                std::cerr << "Error processing Redis message: " << e.what() << " - Message: " << msg << std::endl;
            }
        });

        sub.on_error([](const std::string &err) {
            std::cerr << "Redis Subscriber Error: " << err << std::endl;
            // TODO: Implement robust reconnection logic here
            // For now, it will likely exit the consume loop on persistent errors.
        });

        sub.subscribe("l1:quotes");
        std::cout << "Subscribed to Redis channel 'l1:quotes' on host " 
                  << connection_options.host << ":" << connection_options.port << std::endl;

        // Blocking consumption loop
        while (running_.load()) {
            try {
                sub.consume(); // Blocks until a message arrives or an error occurs
            } catch (const sw::redis::TimeoutError &e) {
                // Should not happen with socket_timeout = 0, but handle defensively
                continue;
            } catch (const sw::redis::Error &e) {
                std::cerr << "Redis consumption error: " << e.what() << std::endl;
                if (!running_.load()) break; // Check flag before sleeping
                
                // Basic retry logic: wait and try to resubscribe/reconnect
                 std::cerr << "Attempting Redis reconnect/resubscribe in 5s..." << std::endl;
                std::this_thread::sleep_for(std::chrono::seconds(5));
                
                if (!running_.load()) break; // Check flag again after sleep

                try {
                    // Ensure the subscriber object is still valid or recreate it
                     // For simplicity, we assume the `sub` object attempts reconnection internally 
                     // or throws an error that breaks the loop. A robust implementation might need
                     // to recreate the Redis and Subscriber objects here.
                     if (!redis.ping().empty()) { // Check connection
                         std::cout << "Re-checking subscription state..." << std::endl;
                         sub.unsubscribe(); // Clean previous state (if any)
                         sub.subscribe("l1:quotes");
                         std::cout << "Redis resubscription successful." << std::endl;
                     } else {
                         std::cerr << "Redis ping failed after error. Exiting subscriber loop." << std::endl;
                         break; // Exit loop if ping fails
                     }
                } catch (const sw::redis::Error &sub_err) {
                    std::cerr << "Redis reconnect/resubscribe failed: " << sub_err.what() << std::endl;
                    std::this_thread::sleep_for(std::chrono::seconds(10)); // Wait longer
                }
            }
        }

        std::cout << "Redis subscriber loop finished." << std::endl;
        try {
            sub.unsubscribe();
        } catch (const sw::redis::Error &e) {
             std::cerr << "Error during Redis unsubscribe: " << e.what() << std::endl;
        }

    } catch (const sw::redis::Error &e) {
        std::cerr << "Fatal Redis connection/subscription error: " << e.what() << std::endl;
        running_.store(false); // Signal that the thread failed
    } catch (const std::exception &e) {
        std::cerr << "Fatal error in Redis subscriber thread: " << e.what() << std::endl;
        running_.store(false); // Signal that the thread failed
    }
}

} // namespace bp 
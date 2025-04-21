#include <iostream>
#include "redis_subscriber.hpp"
#include "exec_bridge.hpp"
#include <spdlog/spdlog.h>
#include <thread>
#include <chrono>
#include <csignal>
#include <cstdlib> // For std::getenv

namespace {
    // Global flag to signal termination
    volatile std::sig_atomic_t g_signal_status;

    // Signal handler function
    void signal_handler(int signal) {
        g_signal_status = signal;
    }

    // Helper to get required environment variable
    std::string getenv_required(const char* key) {
        const char* val = std::getenv(key);
        if (!val) {
            throw std::runtime_error(std::string("Missing required environment variable: ") + key);
        }
        return std::string(val);
    }
}

int main(int argc, char *argv[]) {
    // Basic signal handling for clean shutdown
    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    // Set up logging
    spdlog::set_level(spdlog::level::debug); // Set default log level
    spdlog::info("Starting HL-cli...");

    try {
        // Get configuration from environment variables
        std::string api_key = getenv_required("BACKPACK_API_KEY");
        std::string api_secret_b64 = getenv_required("BACKPACK_API_SECRET_B64");
        std::string symbol = getenv_required("TRADING_SYMBOL"); // e.g., "SOL_USDC"
        // Optional: Get max drawdown from env, default to 2%
        double max_drawdown = 0.02;
        const char* drawdown_env = std::getenv("MAX_DAILY_DRAWDOWN_PCT");
        if (drawdown_env) {
            try {
                max_drawdown = std::stod(drawdown_env);
            } catch (const std::exception& e) {
                spdlog::warn("Invalid MAX_DAILY_DRAWDOWN_PCT value '{}', using default {}: {}", 
                             drawdown_env, max_drawdown, e.what());
            }
        }

        spdlog::info("Initializing Execution Client for symbol: {}", symbol);
        // Initialize ExecutionClient with credentials and symbol
        bp::DefaultExecutionClient exec_client(api_key, api_secret_b64, symbol, max_drawdown);
        
        spdlog::info("Initializing Redis Subscriber...");
        bp::RedisSubscriber redis_subscriber(exec_client);

        // Start Redis subscriber in a separate thread
        std::thread redis_thread([&redis_subscriber]() {
            try {
                redis_subscriber.start(); // This blocks until stopped
            } catch (const std::exception& e) {
                spdlog::critical("Redis subscriber thread failed: {}", e.what());
                g_signal_status = SIGTERM; // Signal main thread to exit
            }
        });

        spdlog::info("Application started. Waiting for termination signal (Ctrl+C)...");

        // Wait for termination signal
        while (g_signal_status == 0) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
            // Main thread can perform other tasks or just sleep
        }

        spdlog::info("Termination signal ({}) received. Shutting down...", g_signal_status);

        // Clean shutdown
        redis_subscriber.stop(); // Signal the subscriber to stop consuming
        if (redis_thread.joinable()) {
            redis_thread.join(); // Wait for the subscriber thread to finish
        }
        // DefaultExecutionClient destructor handles its cleanup (IO thread, etc.)

        spdlog::info("Shutdown complete.");

    } catch (const std::exception& e) {
        spdlog::critical("Fatal Error: {}", e.what());
        return 1;
    } catch (...) {
        spdlog::critical("Unknown Fatal Error.");
        return 1;
    }

    return 0;
} 
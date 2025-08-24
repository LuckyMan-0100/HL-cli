#include <iostream>
#include "exec_bridge.hpp"
#include <spdlog/spdlog.h>
#include <spdlog/sinks/stdout_color_sinks.h>
#include <thread>
#include <chrono>
#include <csignal>
#include <cstdlib> // For std::getenv
#include <algorithm>
#include <cctype>

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
    auto console_sink = std::make_shared<spdlog::sinks::stdout_color_sink_mt>();
    // Example: Set pattern if not already done, or keep existing pattern
    console_sink->set_pattern("[%Y-%m-%d %H:%M:%S.%e] [%^%l%$] [%s:%#] %v"); 
    auto logger = std::make_shared<spdlog::logger>("multi_sink", console_sink);
    spdlog::register_logger(logger);
    spdlog::set_default_logger(logger); // Ensure this is the default for all subsequent spdlog calls
    spdlog::set_level(spdlog::level::trace); // SET TO TRACE LEVEL
    spdlog::flush_on(spdlog::level::info); // Optional: flush on info or higher

    spdlog::info("Starting HL-cli...");

    try {
        // Get configuration from environment variables
        std::string api_key = getenv_required("BACKPACK_API_KEY");
        std::string api_secret_b64 = getenv_required("BACKPACK_API_SECRET_B64");
        std::string raw_symbol = getenv_required("TRADING_SYMBOL"); // e.g., "SOL_USDC_PERP"
        std::string symbol = raw_symbol;
        // Remove inline comments
        auto hash_pos = symbol.find('#');
        if (hash_pos != std::string::npos) symbol = symbol.substr(0, hash_pos);
        // Trim whitespace
        auto ltrim = [](std::string &s) {
            s.erase(s.begin(), std::find_if(s.begin(), s.end(), [](unsigned char ch) { return !std::isspace(ch); }));
        };
        auto rtrim = [](std::string &s) {
            s.erase(std::find_if(s.rbegin(), s.rend(), [](unsigned char ch) { return !std::isspace(ch); }).base(), s.end());
        };
        ltrim(symbol);
        rtrim(symbol);
        // Strip surrounding quotes
        if (symbol.size() >= 2 && ((symbol.front() == '"' && symbol.back() == '"') || (symbol.front() == '\'' && symbol.back() == '\''))) {
            symbol = symbol.substr(1, symbol.size() - 2);
        }

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

        // Redacted credential logging for verification
        auto redact = [](const std::string &s){
            if (s.size() <= 8) return std::string(s.size(), '*');
            return s.substr(0, 4) + std::string("…") + s.substr(s.size() - 4);
        };
        spdlog::debug("Using API key: {}", redact(api_key));
        spdlog::debug("Using API secret: {}", redact(api_secret_b64));

        spdlog::info("Initializing Execution Client for symbol: {}", symbol);
        // Explicitly pass the ML signal file path
        std::string signal_file = "/Users/penrose/HL-cli/signal.json";
        bp::DefaultExecutionClient exec_client(api_key, api_secret_b64, symbol, max_drawdown, signal_file);
        
        // Setup signal handler for graceful shutdown
        exec_client.setupSignalHandler();

        spdlog::info("Application started. Press Ctrl+C to exit...");

        // Main loop - wait for termination signal
        while (g_signal_status == 0) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
            // Main thread can perform other tasks or just sleep
        }

        spdlog::info("Termination signal ({}) received. Shutting down...", g_signal_status);

        // Clean shutdown 
        exec_client.stop(); // Signal the client to stop

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
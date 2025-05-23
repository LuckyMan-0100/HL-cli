#include <iostream>
#include <string>
#include <chrono>
#include <thread>
#include <cstdlib> // For std::getenv
#include <spdlog/spdlog.h>
#include <spdlog/sinks/stdout_color_sinks.h>
#include "backpack/backpack_client.hpp" // Changed to use BackpackClient
#include "backpack/types.hpp"         // Use types.hpp for Position and other types
#include <nlohmann/json.hpp>

// Raw message handler for BackpackClient's underlying WebSocket messages (if needed, or use specific data callbacks)
void on_sdk_raw_message(const std::string& message) {
    spdlog::info("SDK RAW WS MESSAGE RECEIVED: {}", message);
    // Further parsing can be added if direct inspection of raw messages through BackpackClient is desired
}

void on_user_order_update(const backpack::Order& order) {
    spdlog::info("=== USER ORDER UPDATE ===");
    spdlog::info("Order ID: {}", order.id);
    spdlog::info("Symbol: {}", order.symbol);
    spdlog::info("Side: {}", backpack::order_side_to_string(order.side));
    spdlog::info("Type: {}", backpack::order_type_to_string(order.type));
    spdlog::info("Status: {}", backpack::order_status_to_string(order.status));
    spdlog::info("Price: {}", order.price);
    spdlog::info("Quantity: {}", order.quantity);
    spdlog::info("Executed Quantity: {}", order.executed_quantity);
    spdlog::info("Timestamp: {}", order.timestamp);
    spdlog::info("=========================");
}

// Define callback for user position updates
void on_user_position_update(const backpack::Position& position) {
    spdlog::info("=== USER POSITION UPDATE ===");
    spdlog::info("Symbol: {}", position.symbol);
    spdlog::info("Size: {}", position.size);
    spdlog::info("Entry Price: {}", position.entry_price);
    spdlog::info("Mark Price: {}", position.mark_price);
    spdlog::info("Unrealized PnL: {}", position.unrealized_pnl);
    spdlog::info("=========================");
}

// Helper to get environment variable or default
inline std::string getenv_or(const char* key, const std::string& def = "") {
    const char* val = std::getenv(key);
    return val ? std::string(val) : def;
}

int main(int argc, char *argv[]) {
    // Initialize spdlog with a console logger
    auto console_sink = std::make_shared<spdlog::sinks::stdout_color_sink_mt>();
    auto logger = std::make_shared<spdlog::logger>("default", console_sink);
    // Set the logging level to trace to capture all details
    logger->set_level(spdlog::level::trace);
    // Flush on every log message above critical - useful for debugging
    logger->flush_on(spdlog::level::trace); 
    spdlog::set_default_logger(logger);

    SPDLOG_INFO("Spdlog initialized with trace level for default logger.");
    SPDLOG_INFO("Starting BackpackClient WebSocket connection test for private streams...");

    std::string api_key = getenv_or("BACKPACK_API_KEY");
    std::string api_secret_b64 = getenv_or("BACKPACK_API_SECRET_B64");
    std::string trading_symbol_spot = getenv_or("TRADING_SYMBOL", "SOL_USDC"); // Default if not set, e.g. SOL_USDC
    std::string trading_symbol_perp = trading_symbol_spot + "_PERP"; // e.g. SOL_USDC_PERP

    if (api_key.empty() || api_secret_b64.empty()) {
        spdlog::error("BACKPACK_API_KEY or BACKPACK_API_SECRET_B64 environment variables not set.");
        return 1;
    }
    spdlog::info("Using API Key: {}", api_key);
    // Do NOT log the secret, but let's log its properties for debugging this specific issue
    spdlog::debug("Raw BACKPACK_API_SECRET_B64 (length {}): '{}'", api_secret_b64.length(), api_secret_b64);

    // Trim whitespace (leading/trailing) from the secret
    std::string trimmed_api_secret_b64 = api_secret_b64;
    // Leading whitespace
    trimmed_api_secret_b64.erase(0, trimmed_api_secret_b64.find_first_not_of(" \t\n\r\f\v"));
    // Trailing whitespace
    trimmed_api_secret_b64.erase(trimmed_api_secret_b64.find_last_not_of(" \t\n\r\f\v") + 1);
    
    spdlog::debug("Trimmed BACKPACK_API_SECRET_B64 (length {}): '{}'", trimmed_api_secret_b64.length(), trimmed_api_secret_b64);

    backpack::BackpackClient client; // Uses default URLs

    // Optional: If you want to see raw messages from the underlying WebSocketClient used by BackpackClient
    client.get_ws_client()->set_message_handler(on_sdk_raw_message); // Requires a getter for ws_client_ in BackpackClient

    client.set_credentials(api_key, trimmed_api_secret_b64); // Use the trimmed secret
    spdlog::info("Credentials set.");

    spdlog::info("Attempting to connect BackpackClient...");
    if (client.connect()) {
        spdlog::info("BackpackClient connect() call succeeded. Waiting for connection to establish...");
        
        // Wait for the connection to be fully established
        // (BackpackClient::connect sets up handlers and calls ws_client_->connect, which is async)
        // A short pause, or better, a loop checking client.is_connected()
        int connect_attempts = 0;
        while(!client.is_connected() && connect_attempts < 100) { // Wait up to 10 seconds
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
            connect_attempts++;
        }

        if (!client.is_connected()) {
            spdlog::error("BackpackClient failed to establish connection after connect() call.");
            return 1;
        }
        spdlog::info("BackpackClient connection established (is_connected() is true).");

        // Send a ping first
        spdlog::info("Sending ping...");
        client.ping();
        // std::this_thread::sleep_for(std::chrono::seconds(2)); // Wait a bit for pong

        // Attempting to subscribe to user positions for the PERP symbol
        spdlog::info("Attempting to subscribe to user positions for WebSocket stream symbol: {}", trading_symbol_perp);

        bool sub_sent = client.subscribe_user_positions(trading_symbol_perp, on_user_position_update);
        if (sub_sent) {
            spdlog::info("subscribe_user_positions request sent successfully for symbol: {}.", trading_symbol_perp);
            spdlog::info("Listening for messages for 30 seconds...");
            // Check authentication status after a short delay
            std::this_thread::sleep_for(std::chrono::seconds(2));
            spdlog::info("Current authentication status (client.is_authenticated()): {}", client.is_authenticated());

            std::this_thread::sleep_for(std::chrono::seconds(28)); // Wait longer
            spdlog::info("Test period over. Final authentication status: {}", client.is_authenticated());
        } else {
            spdlog::error("subscribe_user_positions call returned false (failed to send) for symbol: {}.", trading_symbol_perp);
        }
        
        client.disconnect();
        spdlog::info("Client disconnected.");

    } else {
        spdlog::error("BackpackClient connect() call failed to initiate.");
        return 1;
    }

    spdlog::info("Test finished.");

    return 0;
} 
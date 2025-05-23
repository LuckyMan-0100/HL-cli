#include "backpack/position.hpp" // Required for Position type

void on_user_order_update(const backpack::Order& order) {
    SPDLOG_INFO("Received user order update: {}", order.to_json().dump());
    // Potentially update some state or trigger other actions
}

void on_user_position_update(const backpack::Position& position) {
    SPDLOG_INFO("Received user position update: {}", position.to_json().dump());
    // Potentially update some state or trigger other actions
}

int main(int argc, char *argv[]) {
    std::string trading_symbol_spot = backpack::utils::get_env_var("TRADING_SYMBOL"); // e.g., SOL_USDC
    std::string trading_symbol_perp = trading_symbol_spot + "_PERP"; // e.g., SOL_USDC_PERP

    backpack::BackpackClient client;
    client.set_credentials(api_key, api_secret_b64);

    client.on_connect([&]() {
        SPDLOG_INFO("Connected to BackpackClient WebSocket!");
        // Original test: Subscribe to user orders for the spot market symbol
        // if (client.subscribe_user_orders(trading_symbol_spot, on_user_order_update)) {
        //     SPDLOG_INFO("Attempting to subscribe to user orders for WebSocket stream symbol: {}", trading_symbol_spot);
        // } else {
        //     SPDLOG_ERROR("Failed to send user order subscription request for symbol: {}", trading_symbol_spot);
        // }

        // Test: Subscribe to user positions for the perp market symbol
        if (client.subscribe_user_positions(trading_symbol_perp, on_user_position_update)) {
            SPDLOG_INFO("Attempting to subscribe to user positions for WebSocket stream symbol: {}", trading_symbol_perp);
        } else {
            SPDLOG_ERROR("Failed to send user position subscription request for symbol: {}", trading_symbol_perp);
        }
    });
} 
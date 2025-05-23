#include "exec_bridge.hpp"
#include <spdlog/spdlog.h>
#include <filesystem>
#include <fstream>
#include <nlohmann/json.hpp>

namespace bp {

using json = nlohmann::json;

MlSignalPayload DefaultExecutionClient::read_signal_file() {
    spdlog::info("read_signal_file: ENTRY - attempting to read '{}'", signal_file_path_);
    std::ifstream file(signal_file_path_);
    if (!file.is_open()) {
        spdlog::warn("read_signal_file: unable to open '{}'", signal_file_path_);
        return MlSignalPayload{};
    }
    try {
        json j;
        file >> j;
        // Debug: log raw JSON
        spdlog::info("read_signal_file: raw JSON from '{}' -> {}", signal_file_path_, j.dump());
        // Extract raw values for debugging
        auto timestamp_raw = j.value("timestamp", 0LL);
        std::string type_raw = j.value("signal_type", "");
        std::string model_id_raw = j.value("signal_id", "");
        std::string qty_str_raw = j["order_quantity_config"].value("quantity", "0");
        double confidence_raw = j.value("confidence", 0.0);
        spdlog::info("read_signal_file: parsed fields -> timestamp={}, type={}, model_id={}, qty_str={}, confidence={}",
                     timestamp_raw, type_raw, model_id_raw, qty_str_raw, confidence_raw);
        MlSignalPayload p;
        p.timestamp_ms = timestamp_raw;
        std::string type = j.value("signal_type", "");
        if (type == "buy") p.signal_action = 1;
        else if (type == "sell") p.signal_action = -1;
        else p.signal_action = 0;
        p.model_id = model_id_raw;
        // Parse quantity
        std::string qty_str = qty_str_raw;
        p.order_quantity_config = std::stod(qty_str);
        // Use confidence as placeholder for stop-loss percentage
        p.stop_loss_pct_config = confidence_raw * 100.0;
        // Keep default max_hold_bars_config
        p.max_hold_bars_config = 60; // Set default value since signal file doesn't provide this
        
        // Debug log the final payload values and validity
        spdlog::info("read_signal_file: final payload -> timestamp_ms={}, signal_action={}, model_id={}, max_hold_bars_config={}, stop_loss_pct_config={}, order_quantity_config={}, isValid={}",
                     p.timestamp_ms, p.signal_action, p.model_id, p.max_hold_bars_config, p.stop_loss_pct_config, p.order_quantity_config, p.isValid());
        
        return p;
    } catch (const std::exception& e) {
        spdlog::error("read_signal_file: error parsing '{}': {}", signal_file_path_, e.what());
        return MlSignalPayload{};
    }
}

void DefaultExecutionClient::process_new_ml_signal(const MlSignalPayload& new_payload) {
    spdlog::info("process_new_ml_signal: action={}, qty={}, model_id={}",
                 new_payload.signal_action, new_payload.order_quantity_config, new_payload.model_id);
    // Only process non-neutral signals with positive quantity
    if (new_payload.signal_action == 0 || new_payload.order_quantity_config <= 0.0) {
        spdlog::warn("process_new_ml_signal: invalid payload, skipping");
        return;
    }
    // Send market order
    spdlog::info("process_new_ml_signal: placing market order...");
    std::string order_id = send_market(
        trading_symbol_,
        new_payload.order_quantity_config,
        new_payload.signal_action == 1,
        OrderFlags(),
        ConditionalOrderParams(),
        new_payload.model_id);
    if (!order_id.empty()) {
        spdlog::info("process_new_ml_signal: market order placed, id={}", order_id);
    } else {
        spdlog::error("process_new_ml_signal: market order failed");
    }
}

std::string DefaultExecutionClient::order_side_to_string(OrderSide side) {
    switch(side) {
        case OrderSide::BUY: return "buy";
        case OrderSide::SELL: return "sell";
        default: return "";
    }
}

std::string DefaultExecutionClient::order_type_to_string(OrderType type) {
    switch(type) {
        case OrderType::MARKET: return "market";
        case OrderType::LIMIT: return "limit";
        default: return "";
    }
}

std::string DefaultExecutionClient::self_trade_prevention_to_string(SelfTradePrevention stp) {
    switch(stp) {
        case SelfTradePrevention::NONE: return "NONE";
        case SelfTradePrevention::REJECT_TAKER: return "REJECT_TAKER";
        case SelfTradePrevention::REJECT_MAKER: return "REJECT_MAKER";
        case SelfTradePrevention::REJECT_BOTH: return "REJECT_BOTH";
        default: return "";
    }
}

void DefaultExecutionClient::check_for_new_signal() {
    // Log current working directory and signal file path for debugging
    auto cwd = std::filesystem::current_path().string();
    spdlog::info("check_for_new_signal: cwd='{}', checking file '{}'", cwd, signal_file_path_);
    
    // Check if file exists using ifstream
    std::ifstream test_file(signal_file_path_);
    bool file_exists = test_file.good();
    test_file.close();
    spdlog::info("check_for_new_signal: file exists = {}", file_exists);
    
    MlSignalPayload payload = read_signal_file();
    if (payload.isValid()) {
        spdlog::info("check_for_new_signal: valid payload => timestamp_ms={}, model_id={}, action={}",
                     payload.timestamp_ms, payload.model_id, payload.signal_action);
        process_new_ml_signal(payload);
    } else {
        spdlog::info("check_for_new_signal: no valid payload found");
    }
}

} // namespace bp 
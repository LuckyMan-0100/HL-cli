#include <iostream>
#include <fstream>
#include <filesystem>
#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

using json = nlohmann::json;

struct MlSignalPayload {
    long long timestamp_ms = 0;
    int signal_action = 0; // -1 (short), 0 (flat), 1 (long)
    std::string model_id;
    int max_hold_bars_config = 0;
    double stop_loss_pct_config = 0.0;
    double order_quantity_config = 0.0;

    bool isValid() const {
        return timestamp_ms > 0 && 
               (signal_action >= -1 && signal_action <= 1) &&
               !model_id.empty() &&
               max_hold_bars_config >= 0 &&
               stop_loss_pct_config > 0.0 &&
               order_quantity_config > 0.0;
    }
};

class TestClient {
public:
    std::string signal_file_path_ = "/Users/penrose/HL-cli/signal.json";
    
    MlSignalPayload read_signal_file() {
        spdlog::info("read_signal_file: ENTRY - attempting to read '{}'", signal_file_path_);
        std::ifstream file(signal_file_path_);
        if (!file.is_open()) {
            spdlog::warn("read_signal_file: unable to open '{}'", signal_file_path_);
            return MlSignalPayload{};
        }
        try {
            json j;
            file >> j;
            spdlog::info("read_signal_file: raw JSON from '{}' -> {}", signal_file_path_, j.dump());
            
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
            p.order_quantity_config = std::stod(qty_str_raw);
            p.stop_loss_pct_config = confidence_raw * 100.0;
            p.max_hold_bars_config = 60;
            
            spdlog::info("read_signal_file: final payload -> timestamp_ms={}, signal_action={}, model_id={}, max_hold_bars_config={}, stop_loss_pct_config={}, order_quantity_config={}, isValid={}",
                         p.timestamp_ms, p.signal_action, p.model_id, p.max_hold_bars_config, p.stop_loss_pct_config, p.order_quantity_config, p.isValid());
            
            return p;
        } catch (const std::exception& e) {
            spdlog::error("read_signal_file: error parsing '{}': {}", signal_file_path_, e.what());
            return MlSignalPayload{};
        }
    }
    
    void check_for_new_signal() {
        auto cwd = std::filesystem::current_path().string();
        spdlog::info("check_for_new_signal: cwd='{}', checking file '{}'", cwd, signal_file_path_);
        
        bool file_exists = std::filesystem::exists(signal_file_path_);
        spdlog::info("check_for_new_signal: file exists = {}", file_exists);
        
        MlSignalPayload payload = read_signal_file();
        if (payload.isValid()) {
            spdlog::info("check_for_new_signal: valid payload => timestamp_ms={}, model_id={}, action={}",
                         payload.timestamp_ms, payload.model_id, payload.signal_action);
        } else {
            spdlog::info("check_for_new_signal: no valid payload found");
        }
    }
};

int main() {
    spdlog::set_level(spdlog::level::info);
    std::cout << "Testing signal checking..." << std::endl;
    
    TestClient client;
    client.check_for_new_signal();
    
    return 0;
} 
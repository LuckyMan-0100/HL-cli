#include <iostream>
#include <fstream>
#include <nlohmann/json.hpp>

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

MlSignalPayload read_signal_file(const std::string& signal_file_path) {
    std::ifstream file(signal_file_path);
    if (!file.is_open()) {
        std::cout << "read_signal_file: unable to open '" << signal_file_path << "'" << std::endl;
        return MlSignalPayload{};
    }
    try {
        json j;
        file >> j;
        std::cout << "read_signal_file: raw JSON from '" << signal_file_path << "' -> " << j.dump() << std::endl;
        
        auto timestamp_raw = j.value("timestamp", 0LL);
        std::string type_raw = j.value("signal_type", "");
        std::string model_id_raw = j.value("signal_id", "");
        std::string qty_str_raw = j["order_quantity_config"].value("quantity", "0");
        double confidence_raw = j.value("confidence", 0.0);
        
        std::cout << "read_signal_file: parsed fields -> timestamp=" << timestamp_raw 
                  << ", type=" << type_raw << ", model_id=" << model_id_raw 
                  << ", qty_str=" << qty_str_raw << ", confidence=" << confidence_raw << std::endl;
        
        MlSignalPayload p;
        p.timestamp_ms = timestamp_raw;
        std::string type = j.value("signal_type", "");
        if (type == "buy") p.signal_action = 1;
        else if (type == "sell") p.signal_action = -1;
        else p.signal_action = 0;
        p.model_id = model_id_raw;
        p.order_quantity_config = std::stod(qty_str_raw);
        p.stop_loss_pct_config = confidence_raw * 100.0;
        p.max_hold_bars_config = 60; // Set default value since signal file doesn't provide this
        
        std::cout << "read_signal_file: final payload -> timestamp_ms=" << p.timestamp_ms 
                  << ", signal_action=" << p.signal_action << ", model_id=" << p.model_id 
                  << ", max_hold_bars_config=" << p.max_hold_bars_config 
                  << ", stop_loss_pct_config=" << p.stop_loss_pct_config 
                  << ", order_quantity_config=" << p.order_quantity_config 
                  << ", isValid=" << p.isValid() << std::endl;
        
        return p;
    } catch (const std::exception& e) {
        std::cout << "read_signal_file: error parsing '" << signal_file_path << "': " << e.what() << std::endl;
        return MlSignalPayload{};
    }
}

int main() {
    std::cout << "Testing signal reading..." << std::endl;
    auto payload = read_signal_file("signal.json");
    std::cout << "Result: isValid=" << payload.isValid() << std::endl;
    return 0;
} 
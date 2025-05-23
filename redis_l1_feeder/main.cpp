#include <iostream>
#include <string>
#include <chrono>
#include <thread>
#include <iomanip>    // For std::fixed, std::setprecision
#include <vector>     // For std::vector with curl buffer

#include <sw/redis++/redis++.h> // Assuming redis++ headers are accessible
#include <nlohmann/json.hpp>   // Assuming nlohmann/json headers are accessible
#include <curl/curl.h>         // For making HTTP requests

// Configuration
const std::string REDIS_HOST = "localhost";
const int REDIS_PORT = 6379;
const std::string L1_QUOTES_CHANNEL = "l1:quotes";
const std::string SYMBOL = "SOL_USDC_PERP"; // Make sure this matches exec_bridge if it uses a fixed symbol internally
const int FETCH_INTERVAL_MS = 1000; // Fetch new data every 1 second

// Helper function for CURL response handling
static size_t WriteCallback(void* contents, size_t size, size_t nmemb, void* userp) {
    ((std::string*)userp)->append((char*)contents, size * nmemb);
    return size * nmemb;
}

// Helper function to safely get double from string or number
// (Copied from exec_bridge.cpp for consistency, could be moved to a shared util header)
inline double json_get_double(const nlohmann::json& j, const std::string& key, double default_val = 0.0) {
    if (j.contains(key)) {
        if (j[key].is_string()) {
            try { return std::stod(j[key].get<std::string>()); } catch(...) {}
        } else if (j[key].is_number()) {
            return j[key].get<double>();
        }
    }
    return default_val;
}
inline uint64_t json_get_uint64(const nlohmann::json& j, const std::string& key, uint64_t default_val = 0) {
    if (j.contains(key)) {
        if (j[key].is_string()) {
            try { return std::stoull(j[key].get<std::string>()); } catch(...) {}
        } else if (j[key].is_number_unsigned() || j[key].is_number_integer()) { // Allow signed for flexibility if source is int
            return j[key].get<uint64_t>();
        }
    }
    return default_val;
}


int main() {
    // Initialize Redis client
    std::string redis_uri = "tcp://" + REDIS_HOST + ":" + std::to_string(REDIS_PORT);
    // sw::redis::ConnectionOptions conn_opts(redis_uri); // Problematic line removed
    // Optional: Set connection timeout (e.g., 500ms)
    // conn_opts.connect_timeout = std::chrono::milliseconds(500);
    // Optional: Set socket timeout (e.g., 500ms for send/receive)
    // conn_opts.socket_timeout = std::chrono::milliseconds(500);

    // sw::redis::Redis redis_client(conn_opts); // Old way
    sw::redis::Redis redis_client(redis_uri); // New way: Pass URI directly

    std::cout << "[" << std::time(nullptr) << "] L1 Feeder: Attempting to connect to Redis at " << redis_uri << std::endl;

    // Test connection early
    try {
        auto pong = redis_client.ping();
        std::cout << "[" << std::time(nullptr) << "] L1 Feeder: Connected to Redis. PING response: " << pong << std::endl;
    } catch (const sw::redis::Error &e) {
        std::cerr << "[" << std::time(nullptr) << "] L1 Feeder: Failed to connect to Redis or PING failed: " << e.what() << std::endl;
        return 1; // Exit if connection fails
    }

    // Initialize CURL (global setup)
    curl_global_init(CURL_GLOBAL_ALL);
    CURL* curl = curl_easy_init();
    if (!curl) {
        std::cerr << "L1 Feeder: Failed to initialize CURL" << std::endl;
        return 1;
    }

    std::string api_url = "https://api.backpack.exchange/api/v1/depth?symbol=" + SYMBOL;
    uint64_t update_id_counter = 0; // Use lastUpdateId from API if available, otherwise increment

    while (true) {
        std::string http_read_buffer;
        long http_response_code = 0;

        curl_easy_setopt(curl, CURLOPT_URL, api_url.c_str());
        curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, WriteCallback);
        curl_easy_setopt(curl, CURLOPT_WRITEDATA, &http_read_buffer);
        curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, FETCH_INTERVAL_MS - 100); // Timeout slightly less than interval

        CURLcode res = curl_easy_perform(curl);

        if (res == CURLE_OK) {
            curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http_response_code);
            if (http_response_code == 200) {
                try {
                    nlohmann::json depth_json = nlohmann::json::parse(http_read_buffer);

                    if (depth_json.contains("bids") && depth_json["bids"].is_array() && !depth_json["bids"].empty() &&
                        depth_json.contains("asks") && depth_json["asks"].is_array() && !depth_json["asks"].empty()) {

                        // Asks are ascending (lowest ask first), so index 0 is best ask.
                        auto& top_ask_arr = depth_json["asks"][0];
                        // Bids: Assuming API sends bids sorted ASCENDING by price, so highest bid is at the END.
                        auto& top_bid_arr = depth_json["bids"].back(); 

                        if (top_bid_arr.is_array() && top_bid_arr.size() >= 2 &&
                            top_ask_arr.is_array() && top_ask_arr.size() >= 2) {
                            
                            // Prices and quantities are strings in the API response
                            std::string best_bid_price_str = top_bid_arr[0].get<std::string>();
                            std::string best_bid_qty_str = top_bid_arr[1].get<std::string>();
                            std::string best_ask_price_str = top_ask_arr[0].get<std::string>();
                            std::string best_ask_qty_str = top_ask_arr[1].get<std::string>();
                            
                            uint64_t api_timestamp_us = json_get_uint64(depth_json, "timestamp", 0); // API gives µs
                            uint64_t api_update_id = json_get_uint64(depth_json, "lastUpdateId", update_id_counter++);


                            nlohmann::json l1_quote_payload;
                            l1_quote_payload["symbol"] = SYMBOL;
                            // exec_bridge expects numbers for prices/qtys based on its json_get_double
                            // but it can parse strings. Let's publish as strings like the example BookTicker stream format
                            // to be safe and explicit about source format.
                            // However, the target struct BookTicker in exec_bridge.hpp uses double.
                            // json_get_double in exec_bridge will handle string-to-double conversion.
                            // exec_bridge's handleL1Update expects timestamp to be ms.
                            // The API's "timestamp" field for /depth is in microseconds.
                            l1_quote_payload["bidPrice"] = best_bid_price_str;
                            l1_quote_payload["askPrice"] = best_ask_price_str;
                            l1_quote_payload["bidQty"] = best_bid_qty_str;
                            l1_quote_payload["askQty"] = best_ask_qty_str;
                            l1_quote_payload["timestamp"] = api_timestamp_us / 1000; // Convert µs to ms
                            l1_quote_payload["updateId"] = api_update_id;


                            std::string message_payload_str = l1_quote_payload.dump();
                            std::cerr << "DEBUG: Publishing to Redis: " << message_payload_str << std::endl;
                            redis_client.publish(L1_QUOTES_CHANNEL, message_payload_str);

                            char time_str[100];
                            std::time_t current_time_t = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
                            std::strftime(time_str, sizeof(time_str), "%Y-%m-%d %H:%M:%S", std::localtime(&current_time_t));
                            
                            std::cout << "[" << time_str << "] L1 Feeder: Published " << SYMBOL 
                                      << " B:" << best_bid_price_str << " A:" << best_ask_price_str
                                      << " T:" << (api_timestamp_us / 1000) << " U:" << api_update_id
                                      << std::endl;
                        } else {
                             std::cerr << "L1 Feeder: Top bid/ask array in API response is malformed." << std::endl;
                        }
                    } else {
                        std::cerr << "L1 Feeder: 'bids' or 'asks' array not found or empty in API response: " << http_read_buffer << std::endl;
                    }
                } catch (const nlohmann::json::parse_error& e) {
                    std::cerr << "L1 Feeder: JSON parse error: " << e.what() << ". Response: " << http_read_buffer << std::endl;
                } catch (const std::exception& e) {
                    std::cerr << "L1 Feeder: Exception processing API response: " << e.what() << std::endl;
                }
            } else {
                std::cerr << "L1 Feeder: HTTP error " << http_response_code << " from API: " << http_read_buffer << std::endl;
            }
        } else {
            std::cerr << "L1 Feeder: CURL request failed: " << curl_easy_strerror(res) << std::endl;
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(FETCH_INTERVAL_MS));
    }

    // Cleanup CURL
    curl_easy_cleanup(curl);
    curl_global_cleanup();

    return 0;
} 
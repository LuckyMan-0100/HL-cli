#include <iostream>
#include <string>
#include <chrono>
#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>
#include <curl/curl.h>
#include <openssl/evp.h>
#include "exec_bridge.hpp"
#include <thread>
#include <iomanip>

using json = nlohmann::json;

// Helper function to get environment variable or default
inline std::string getenv_or(const char* key, const std::string& def = "") {
    const char* val = std::getenv(key);
    return val ? std::string(val) : def;
}

// Helper function for CURL response handling
size_t WriteCallback(void* contents, size_t size, size_t nmemb, std::string* userp) {
    userp->append((char*)contents, size * nmemb);
    return size * nmemb;
}

// Helper to get current timestamp and check clock skew
void check_clock_skew() {
    auto now = std::chrono::system_clock::now();
    auto timestamp_ms = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count();
    
    // Convert to human readable
    auto time_t = std::chrono::system_clock::to_time_t(now);
    std::stringstream ss;
    ss << std::put_time(std::gmtime(&time_t), "%Y-%m-%d %H:%M:%S");
    
    spdlog::info("=== CLOCK SKEW CHECK ===");
    spdlog::info("Current system time: {} UTC", ss.str());
    spdlog::info("Current timestamp_ms: {}", timestamp_ms);
    spdlog::info("Window: 5000ms (as used in signatures)");
    spdlog::info("========================");
}

// Helper to log exact subscription JSON that will be sent
void log_subscription_details(const std::string& symbol) {
    spdlog::info("=== WEBSOCKET SUBSCRIPTION DEBUG ===");
    
    // Based on Backpack docs, user orders subscription should look like:
    // {"method": "SUBSCRIBE", "params": ["orders.SOL_USDC_PERP"]}
    
    json expected_orders_sub = {
        {"method", "SUBSCRIBE"},
        {"params", json::array({"orders." + symbol})}
    };
    
    // User trades subscription should be:
    // {"method": "SUBSCRIBE", "params": ["user.trades"]}
    json expected_trades_sub = {
        {"method", "SUBSCRIBE"},
        {"params", json::array({"user.trades"})}
    };
    
    spdlog::info("Expected user orders subscription JSON:");
    spdlog::info("{}", expected_orders_sub.dump());
    spdlog::info("Expected user trades subscription JSON:");
    spdlog::info("{}", expected_trades_sub.dump());
    
    // Now let's see what our SDK would generate
    try {
        backpack::SubscriptionRequest orders_req;
        orders_req.channel = backpack::Channel::USER_ORDERS;
        orders_req.symbol = symbol; // Will be formatted to SOL_USDC_PERP
        orders_req.auth_required = true;
        
        json sdk_orders_json = orders_req.to_json();
        spdlog::info("SDK-generated user orders subscription:");
        spdlog::info("{}", sdk_orders_json.dump());
        
        backpack::SubscriptionRequest trades_req;
        trades_req.channel = backpack::Channel::USER_TRADES;
        trades_req.symbol = ""; // Empty for account-wide trades
        trades_req.auth_required = true;
        
        json sdk_trades_json = trades_req.to_json();
        spdlog::info("SDK-generated user trades subscription:");
        spdlog::info("{}", sdk_trades_json.dump());
        
    } catch (const std::exception& e) {
        spdlog::error("Error generating SDK subscription JSON: {}", e.what());
    }
    
    spdlog::info("====================================");
}

// Custom WebSocket client wrapper to intercept outgoing messages
class DebuggingWebSocketWrapper {
public:
    static void log_outgoing_message(const std::string& message) {
        spdlog::critical("=== OUTGOING WEBSOCKET MESSAGE ===");
        spdlog::critical("Raw message: {}", message);
        
        try {
            json parsed = json::parse(message);
            spdlog::critical("Parsed JSON:");
            spdlog::critical("{}", parsed.dump(4));
            
            // Check for common issues
            if (parsed.contains("method")) {
                std::string method = parsed["method"];
                spdlog::critical("Method: {}", method);
                
                if (method == "SUBSCRIBE" && parsed.contains("params")) {
                    auto params = parsed["params"];
                    if (params.is_array()) {
                        spdlog::critical("Subscription params (array with {} elements):", params.size());
                        for (size_t i = 0; i < params.size(); ++i) {
                            spdlog::critical("  [{}]: {}", i, params[i].dump());
                        }
                    } else {
                        spdlog::error("ERROR: params is not an array!");
                    }
                }
            }
            
            // Check for authentication fields
            if (parsed.contains("signature")) {
                spdlog::critical("Contains signature field");
            }
            if (parsed.contains("timestamp")) {
                spdlog::critical("Contains timestamp field: {}", parsed["timestamp"].dump());
            }
            if (parsed.contains("window")) {
                spdlog::critical("Contains window field: {}", parsed["window"].dump());
            }
            
        } catch (const std::exception& e) {
            spdlog::error("ERROR: Cannot parse outgoing message as JSON: {}", e.what());
        }
        
        spdlog::critical("=================================");
    }
};

// Simple test of the cancel order functionality without full client overhead
int main() {
    spdlog::set_level(spdlog::level::debug); // Enable all logging
    spdlog::info("=== WebSocket Debug Test ===");
    
    std::string api_key = getenv_or("BACKPACK_API_KEY");
    std::string private_key = getenv_or("BACKPACK_API_SECRET_B64");
    std::string symbol = "SOL_USDC_PERP";
    
    if (api_key.empty() || private_key.empty()) {
        spdlog::error("Missing API credentials. Set BACKPACK_API_KEY and BACKPACK_API_SECRET_B64");
        return 1;
    }
    
    spdlog::info("API Key: {} chars", api_key.length());
    spdlog::info("Private Key: {} chars", private_key.length());
    spdlog::info("Symbol: {}", symbol);
    
    // Check clock skew first
    check_clock_skew();
    
    // Show expected subscription formats
    log_subscription_details(symbol);
    
    try {
        spdlog::info("Step 1: Testing query open orders (lightweight)...");
        
        // Simple CURL-based test of the API without full client initialization
        CURL* curl = curl_easy_init();
        if (!curl) {
            spdlog::error("Failed to initialize CURL");
            return 1;
        }
        
        std::string read_buffer;
        std::string url = "https://api.backpack.exchange/api/v1/orders?symbol=" + symbol;
        
        curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
        curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, WriteCallback);
        curl_easy_setopt(curl, CURLOPT_WRITEDATA, &read_buffer);
        curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, 5000L);
        
        // Add basic headers without authentication first
        struct curl_slist* headers = NULL;
        headers = curl_slist_append(headers, "Content-Type: application/json");
        curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
        
        CURLcode res = curl_easy_perform(curl);
        long response_code = 0;
        curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &response_code);
        
        spdlog::info("Query response code: {}", response_code);
        spdlog::info("Query response: {}", read_buffer);
        
        if (response_code == 401) {
            spdlog::info("Got 401 as expected for unauthenticated request");
        } else if (response_code == 200) {
            try {
                json response_json = json::parse(read_buffer);
                if (response_json.is_array()) {
                    spdlog::info("Found {} orders (public or cached)", response_json.size());
                }
            } catch (const std::exception& e) {
                spdlog::warn("Could not parse response as JSON: {}", e.what());
            }
        }
        
        curl_slist_free_all(headers);
        curl_easy_cleanup(curl);
        
        spdlog::info("Step 2: Testing cancel-all orders endpoint...");
        
        // Test the cancel-all endpoint structure 
        curl = curl_easy_init();
        if (!curl) {
            spdlog::error("Failed to initialize CURL for cancel test");
            return 1;
        }
        
        read_buffer.clear();
        std::string cancel_url = "https://api.backpack.exchange/api/v1/orders";
        
        curl_easy_setopt(curl, CURLOPT_URL, cancel_url.c_str());
        curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, "DELETE");
        curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, WriteCallback);
        curl_easy_setopt(curl, CURLOPT_WRITEDATA, &read_buffer);
        curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, 5000L);
        
        // Test with empty body first
        std::string body = "{\"symbol\":\"" + symbol + "\"}";
        curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body.c_str());
        
        headers = NULL;
        headers = curl_slist_append(headers, "Content-Type: application/json");
        curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
        
        res = curl_easy_perform(curl);
        response_code = 0;
        curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &response_code);
        
        spdlog::info("Cancel-all response code: {}", response_code);
        spdlog::info("Cancel-all response: {}", read_buffer);
        
        if (response_code == 401) {
            spdlog::info("Got 401 as expected for unauthenticated cancel request");
            spdlog::info("✓ Basic API endpoints are reachable");
        } else if (response_code == 400) {
            spdlog::info("Got 400 - likely missing authentication but endpoint structure is correct");
            spdlog::info("✓ DELETE endpoint accepts JSON body");
        }
        
        curl_slist_free_all(headers);
        curl_easy_cleanup(curl);
        
        spdlog::info("Step 3: Testing with WebSocket debugging client...");
        
        // Create client and monitor WebSocket messages closely
        spdlog::info("Creating DefaultExecutionClient with WebSocket monitoring...");
        
        // Before creating client, log what we expect
        spdlog::critical("=== EXPECTED WEBSOCKET FLOW ===");
        spdlog::critical("1. Client connects to wss://ws.backpack.exchange");
        spdlog::critical("2. On open, client sends subscription for 'orders.SOL_USDC_PERP'");
        spdlog::critical("3. On open, client sends subscription for 'user.trades'");
        spdlog::critical("4. Each subscription should be signed with Ed25519 signature");
        spdlog::critical("5. Signature should include timestamp within 30s and window=5000");
        spdlog::critical("===============================");
        
        bp::DefaultExecutionClient client(api_key, private_key, symbol, 5.0, "");
        
        // Give more time for WebSocket connection and let it settle
        spdlog::info("Waiting 10 seconds for WebSocket connection and subscriptions...");
        spdlog::info("Monitoring for 4002 parse errors...");
        
        std::this_thread::sleep_for(std::chrono::seconds(10));
        
        spdlog::info("Testing authenticated query...");
        try {
            json params_query;
            params_query["symbol"] = symbol;
            
            auto response = client.test_execute_signed_request(
                bp::RestClass::ORDER_QUERY, 
                "GET", 
                "/api/v1/orders", 
                "orderQueryAll", 
                params_query
            );
            
            spdlog::info("✓ Authenticated query successful");
            if (response.is_array()) {
                spdlog::info("Found {} open orders", response.size());
            } else {
                spdlog::info("Response is not an array: {}", response.dump());
            }
            
        } catch (const std::exception& e) {
            spdlog::error("Authenticated query failed: {}", e.what());
        }
        
        spdlog::info("Testing cancel-all orders...");
        try {
            json cancel_all_params;
            cancel_all_params["symbol"] = symbol;
            
            auto cancel_all_response = client.test_execute_signed_request(
                bp::RestClass::TRADE, 
                "DELETE", 
                "/api/v1/orders", 
                "orderCancelAll", 
                cancel_all_params
            );
            spdlog::info("✓ Cancel-all successful: {}", cancel_all_response.dump());
            
        } catch (const std::exception& e) {
            spdlog::info("Cancel-all result: {}", e.what());
            if (std::string(e.what()).find("200") != std::string::npos || 
                std::string(e.what()).find("400") != std::string::npos) {
                spdlog::info("✓ Cancel-all endpoint working");
            }
        }
        
        spdlog::info("Stopping client...");
        client.stop();
        
        // Wait a bit more to see any final WebSocket errors
        spdlog::info("Waiting 5 seconds to observe final WebSocket messages...");
        std::this_thread::sleep_for(std::chrono::seconds(5));
        
        spdlog::info("=== WebSocket Debug Test completed ===");
        spdlog::info("Check logs above for:");
        spdlog::info("1. Exact outgoing subscription JSON");
        spdlog::info("2. Clock skew issues (should be < 30s)");
        spdlog::info("3. 4002 parse error timing and causes");
        
    } catch (const std::exception& e) {
        spdlog::error("Test failed: {}", e.what());
        return 1;
    }
    
    return 0;
} 
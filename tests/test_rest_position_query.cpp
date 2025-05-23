#include <iostream>
#include <string>
#include <vector>
#include <chrono>
#include <cstdlib> // For std::getenv
#include <map>
#include <algorithm> // For std::remove_if
#include <iomanip> // For std::setprecision, std::fixed
#include <fstream> // For std::ifstream
#include <sstream> // For std::istringstream

#include <spdlog/spdlog.h>
#include <spdlog/sinks/stdout_color_sinks.h>
#include <nlohmann/json.hpp>
#include <curl/curl.h>

// SDK's signature generation function (declaration)
// This should be available if we link against the backpack_sdk library
namespace backpack {
    std::string generate_ed25519_signature(const std::string& private_key_base64, const std::string& message);
}

// Helper to get environment variable or default
inline std::string getenv_or(const char* key, const std::string& def = "") {
    const char* val = std::getenv(key);
    return val ? std::string(val) : def;
}

// Function to parse .env file and load variables
std::map<std::string, std::string> load_env_file(const std::string& path) {
    std::map<std::string, std::string> env_vars;
    std::ifstream file(path);
    std::string line;

    if (!file.is_open()) {
        SPDLOG_WARN("Could not open .env file at path: {}", path);
        return env_vars;
    }

    while (std::getline(file, line)) {
        // Remove comments and trim whitespace
        auto comment_pos = line.find('#');
        if (comment_pos != std::string::npos) {
            line = line.substr(0, comment_pos);
        }
        const std::string whitespace = " \t\n\r\f\v"; // Define all whitespace chars here
        line.erase(0, line.find_first_not_of(whitespace));
        line.erase(line.find_last_not_of(whitespace) + 1);

        if (line.empty()) {
            continue;
        }

        std::istringstream iss(line);
        std::string key, value;
        if (std::getline(iss, key, '=') && std::getline(iss, value)) {
            // Trim whitespace from key and value
            key.erase(0, key.find_first_not_of(whitespace));
            key.erase(key.find_last_not_of(whitespace) + 1);
            value.erase(0, value.find_first_not_of(whitespace));
            value.erase(value.find_last_not_of(whitespace) + 1);
            env_vars[key] = value;
        }
    }
    file.close();
    SPDLOG_INFO(".env file loaded successfully from path: {}", path);
    return env_vars;
}

// CURL write callback
size_t WriteCallback(void* contents, size_t size, size_t nmemb, std::string* userp) {
    userp->append((char*)contents, size * nmemb);
    return size * nmemb;
}

// CURL header callback
size_t HeaderCallback(char* buffer, size_t size, size_t nitems, void* userdata) {
    std::string* headers = static_cast<std::string*>(userdata);
    headers->append(buffer, size * nitems);
    return size * nitems;
}

// Function to trim leading/trailing whitespace
std::string trim_whitespace(const std::string& str) {
    const std::string whitespace = " \t\n\r\f\v";
    size_t start = str.find_first_not_of(whitespace);
    if (std::string::npos == start) {
        return ""; // Return empty string if only whitespace
    }
    size_t end = str.find_last_not_of(whitespace);
    return str.substr(start, end - start + 1);
}


int main() {
    auto console_sink = std::make_shared<spdlog::sinks::stdout_color_sink_mt>();
    auto logger = std::make_shared<spdlog::logger>("test_pos_query_logger", console_sink);
    logger->set_level(spdlog::level::debug);
    logger->flush_on(spdlog::level::debug);
    spdlog::set_default_logger(logger);

    // Assuming the executable is run from cpp_exec/build, .env is at ../../.env
    // Or if run from cpp_exec, it's ../.env
    // Let's try a common location first, assuming execution from cpp_exec/build
    std::string dot_env_path = "../../.env"; 
    std::map<std::string, std::string> env_values = load_env_file(dot_env_path);

    if (env_values.empty()) {
         // Fallback if not found, try relative to cpp_exec directory if executable is there
        dot_env_path = "../.env";
        SPDLOG_INFO("Trying fallback .env path: {}", dot_env_path);
        env_values = load_env_file(dot_env_path);
    }
    
    std::string api_key;
    std::string api_secret_b64_env;

    if (env_values.count("BACKPACK_API_KEY")) {
        api_key = env_values["BACKPACK_API_KEY"];
    } else {
        SPDLOG_WARN("BACKPACK_API_KEY not found in .env file. Trying environment variable.");
        api_key = getenv_or("BACKPACK_API_KEY");
    }

    if (env_values.count("BACKPACK_API_SECRET_B64")) {
        api_secret_b64_env = env_values["BACKPACK_API_SECRET_B64"];
    } else {
        SPDLOG_WARN("BACKPACK_API_SECRET_B64 not found in .env file. Trying environment variable.");
        api_secret_b64_env = getenv_or("BACKPACK_API_SECRET_B64");
    }


    if (api_key.empty() || api_secret_b64_env.empty()) {
        SPDLOG_ERROR("BACKPACK_API_KEY or BACKPACK_API_SECRET_B64 not found in .env file or environment variables.");
        return 1;
    }
    
    std::string api_secret_b64 = trim_whitespace(api_secret_b64_env);

    SPDLOG_INFO("Using API Key: {}", api_key);
    SPDLOG_DEBUG("Using API Secret (Base64, trimmed, length {}): '{}'", api_secret_b64.length(), api_secret_b64);


    const std::string instruction = "positionQuery";
    // Endpoint based on implementation-plan.mdc for "Get open positions".
    // The API doc for positionQuery did not specify an explicit path.
    const std::string endpoint = "/api/v1/position";
    const std::string http_method = "GET";

    auto now = std::chrono::system_clock::now();
    long long timestamp_ms = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count();
    std::string timestamp_str = std::to_string(timestamp_ms);
    std::string window_str = "5000"; // Default window

    std::string string_to_sign;

    // For GET request with NO parameters, as per documentation and successful WebSocket example:
    // instruction={{INSTRUCTION_VALUE}}&timestamp={{TIMESTAMP_VALUE}}&window={{WINDOW_VALUE}}
    string_to_sign = "instruction=" + instruction;
    string_to_sign += "&timestamp=" + timestamp_str;
    string_to_sign += "&window=" + window_str;

    SPDLOG_DEBUG("String to sign for instruction '{}': {}", instruction, string_to_sign);

    std::string signature;
    try {
        // This relies on the backpack_sdk providing this function and being linked.
        signature = backpack::generate_ed25519_signature(api_secret_b64, string_to_sign);
    } catch (const std::exception& e) {
        SPDLOG_ERROR("Error generating signature: {}", e.what());
        // This might happen if the SDK's generate_ed25519_signature is not found or throws.
        // Ensure the SDK is correctly built and linked, and that this function is accessible.
        return 1;
    }
    
    if (signature.empty()) {
        SPDLOG_ERROR("Failed to generate signature (empty string returned).");
        return 1;
    }
    SPDLOG_DEBUG("Generated Signature: {}", signature);

    CURL* curl = curl_easy_init();
    std::string read_buffer;
    std::string header_buffer;
    long http_response_code = 0;
    const std::string base_url = "https://api.backpack.exchange"; 

    if (curl) {
        std::string full_url = base_url + endpoint;
        
        SPDLOG_DEBUG("Request URL: {}", full_url);
        curl_easy_setopt(curl, CURLOPT_URL, full_url.c_str());
        curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, WriteCallback);
        curl_easy_setopt(curl, CURLOPT_WRITEDATA, &read_buffer);
        curl_easy_setopt(curl, CURLOPT_HEADERFUNCTION, HeaderCallback);
        curl_easy_setopt(curl, CURLOPT_HEADERDATA, &header_buffer);
        curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, 10000L); 

        struct curl_slist* headers = NULL;
        headers = curl_slist_append(headers, ("X-API-Key: " + api_key).c_str());
        headers = curl_slist_append(headers, ("X-Timestamp: " + timestamp_str).c_str());
        headers = curl_slist_append(headers, ("X-Window: " + window_str).c_str());
        headers = curl_slist_append(headers, ("X-Signature: " + signature).c_str());
        headers = curl_slist_append(headers, ("X-BP-Instruction: " + instruction).c_str());
        
        curl_easy_setopt(curl, CURLOPT_HTTPGET, 1L); // Explicitly set GET
        
        curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);

        CURLcode res = curl_easy_perform(curl);
        
        curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http_response_code);
        SPDLOG_INFO("HTTP Response Code: {}", http_response_code);
        SPDLOG_DEBUG("Response Headers:\n{}", header_buffer);
        SPDLOG_INFO("Response Body:\n{}", read_buffer);

        if (res != CURLE_OK) {
            SPDLOG_ERROR("curl_easy_perform() failed: {}", curl_easy_strerror(res));
        }

        curl_slist_free_all(headers);
        curl_easy_cleanup(curl);

        if (http_response_code >= 200 && http_response_code < 300) {
            SPDLOG_INFO("positionQuery successful!");
            try {
                if (!read_buffer.empty()) {
                    nlohmann::json response_json = nlohmann::json::parse(read_buffer);
                    SPDLOG_INFO("Parsed JSON response:\n{}", response_json.dump(4));
                } else if (http_response_code == 204) {
                     SPDLOG_INFO("Successful with 204 No Content.");
                } else {
                     SPDLOG_WARN("Successful HTTP response {} but empty body.", http_response_code);
                }
            } catch (const nlohmann::json::parse_error& e) {
                SPDLOG_ERROR("JSON parse error on successful response: {}. Body: {}", e.what(), read_buffer);
            }
        } else {
            SPDLOG_ERROR("positionQuery failed with HTTP status {}. Body: {}", http_response_code, read_buffer);
        }

    } else {
        SPDLOG_ERROR("Failed to initialize CURL");
        return 1;
    }

    return 0;
} 
// backpack_data_service.cpp
// Unified C++ service combining realâ€‘time and historical data collection for Backpack Exchange
// Inspired by backpack_websocket_service.py and data_collector.py provided by user.
// Build: g++ -std=c++20 -O2 backpack_data_service.cpp -o backpack_data_service \
//        -lswresample -lavformat -lavcodec -lavutil -lcurl -lssl -lcrypto -lpqxx -lpq \
//        -lboost_system -lpthread -lhiredis++ -lhiredis -I/usr/local/include -L/usr/local/lib
//        Note: Ensure Boost, OpenSSL, libcurl, libpqxx, hiredis-cpp, and nlohmann/json are installed.
//        Adjust include/library paths (-I / -L) if needed for your system.
// -----------------------------------------------------------------------------

#include <iostream>
#include <thread>
#include <mutex>
#include <shared_mutex>
#include <condition_variable>
#include <queue>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <string>
#include <chrono>
#include <atomic>
#include <optional>
#include <functional>
#include <csignal>
#include <cstdlib>
#include <memory>
#include <map>

// Third-party headers
#include <nlohmann/json.hpp>
#include <boost/asio.hpp>
#include <boost/beast.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/websocket.hpp>
#include <boost/beast/ssl.hpp>
#include <boost/property_tree/ptree.hpp>
#include <boost/property_tree/json_parser.hpp>
#include <pqxx/pqxx>
#include <curl/curl.h>
#include <openssl/ssl.h>
#include <openssl/err.h>
#include <sw/redis++/redis++.h>

namespace beast = boost::beast;
namespace http = beast::http;
namespace websocket = beast::websocket;
namespace net = boost::asio;
namespace ssl = boost::asio::ssl;
using tcp = boost::asio::ip::tcp;
using json = nlohmann::json;
using namespace std::chrono_literals;

// Global Redis Client (initialized in main)
static std::unique_ptr<sw::redis::Redis> g_redis_client;

// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// Utility helpers
// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
namespace util {
    inline std::string getenv_or(const char* key, const std::string& def="") {
        const char* val = std::getenv(key);
        return val ? std::string(val) : def;
    }

    inline int64_t now_ms() {
        return std::chrono::duration_cast<std::chrono::milliseconds>(
                   std::chrono::system_clock::now().time_since_epoch())
            .count();
    }

    inline int64_t to_ms(int64_t ts) {               // Î¼sâ†’ms or sâ†’ms
        if (ts > 1'000'000'000'000LL) return ts / 1'000;   // Âµs
        if (ts < 1'000'000'000LL)      return ts * 1'000;   //  s
        return ts;                                   // already ms
    }

    // Helper function to safely get string, avoiding exceptions on null/wrong type
    inline std::string json_get_string(const json& j, const char* key, const std::string& default_val = "") {
        if (j.contains(key) && j[key].is_string()) {
            return j[key].get<std::string>();
        }
        return default_val;
    }

    // Helper function to safely get double from string or number
    inline double json_get_double(const json& j, const char* key, double default_val = 0.0) {
        if (j.contains(key)) {
            if (j[key].is_string()) {
                try { return std::stod(j[key].get<std::string>()); } catch(...) {}
            } else if (j[key].is_number()) {
                return j[key].get<double>();
            }
        }
        return default_val;
    }

    // Helper function to safely get int64 from string or number
    inline int64_t json_get_int64(const json& j, const char* key, int64_t default_val = 0) {
        if (j.contains(key)) {
            if (j[key].is_string()) {
                try { return std::stoll(j[key].get<std::string>()); } catch(...) {}
            } else if (j[key].is_number_integer()) {
                return j[key].get<int64_t>();
            }
        }
        return default_val;
    }
}

// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// Database connection pool
// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class PgPool {
public:
    PgPool(const std::string& conninfo, std::size_t minconn = 2, std::size_t maxconn = 10)
        : conninfo_(conninfo), min_(minconn), max_(maxconn) {
        for (std::size_t i = 0; i < min_; ++i) pool_.push(std::make_unique<pqxx::connection>(conninfo_));
    }

    std::unique_ptr<pqxx::connection> acquire() {
        std::unique_lock lk(mtx_);
        if (pool_.empty() && used_ < max_) {
            return std::make_unique<pqxx::connection>(conninfo_);
        }
        cv_.wait(lk, [&]{ return !pool_.empty(); });
        auto conn = std::move(pool_.front());
        pool_.pop();
        ++used_;
        return conn;
    }

    void release(std::unique_ptr<pqxx::connection> conn) {
        std::lock_guard lk(mtx_);
        pool_.push(std::move(conn));
        --used_;
        cv_.notify_one();
    }

private:
    std::string conninfo_;
    std::size_t min_, max_;
    std::queue<std::unique_ptr<pqxx::connection>> pool_;
    std::mutex mtx_;
    std::condition_variable cv_;
    std::size_t used_{0};
};

// ----------------------------------------------------------------------------
// Async DB writer (single dedicated thread)
// ----------------------------------------------------------------------------
struct DBOperation {
    std::string query;
    std::vector<std::vector<std::string>> params;
};

class AsyncDBWriter {
public:
    AsyncDBWriter(std::shared_ptr<PgPool> pool)
        : pool_(pool) {
        running_.store(true);
        thr_ = std::thread(&AsyncDBWriter::worker, this);
    }

    ~AsyncDBWriter() { stop(); }

    void enqueue(const DBOperation& op) {
        {
            std::lock_guard lk(qmtx_);
            q_.push(op);
        }
        qcv_.notify_one();
    }

    void stop() {
        if (!running_.exchange(false)) return;
        qcv_.notify_all();
        if (thr_.joinable()) thr_.join();
    }

private:
    void worker() {
        while (running_) {
            std::unique_lock lk(qmtx_);
            qcv_.wait_for(lk, 500ms, [&]{ return !q_.empty() || !running_; });
            if (!running_ && q_.empty()) break;
            std::queue<DBOperation> local;
            std::swap(local, q_);
            lk.unlock();

            while (!local.empty()) {
                auto op = std::move(local.front());
                local.pop();
                try {
                    auto conn = pool_->acquire();
                    pqxx::work txn(*conn);
                    
                    // Build the parameterized query
                    std::string paramQuery = op.query;
                    paramQuery += " (";
                    size_t param_count = op.params.empty() ? 0 : op.params[0].size();
                    for (size_t i = 0; i < param_count; ++i) {
                        if (i > 0) paramQuery += ",";
                        paramQuery += "$" + std::to_string(i + 1);
                    }
                    paramQuery += ") ON CONFLICT DO NOTHING";
                    
                    // Execute each row of parameters
                    for (const auto& row : op.params) {
                        std::cout << "DB QUERY: " << paramQuery << std::endl;
                        std::cout << "DB PARAMS: ";
                        for (const auto& p : row) std::cout << p << ", ";
                        std::cout << std::endl;
                        
                        // Create params object and append each value
                        pqxx::params params;
                        for (const auto& value : row) {
                            params.append(value);
                        }
                        
                        // Execute parameterized query directly
                        txn.exec_params(paramQuery, params);
                    }
                    
                    // Commit all inserts in one transaction
                    txn.commit();
                    pool_->release(std::move(conn));
                } catch (const std::exception& ex) {
                    std::cerr << "DB write error: " << ex.what() << std::endl;
                }
            }
        }
    }

    std::shared_ptr<PgPool> pool_;
    std::atomic<bool> running_{false};
    std::thread thr_;
    std::queue<DBOperation> q_;
    std::mutex qmtx_;
    std::condition_variable qcv_;
};

// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// WebSocket client using Boost.Beast - DEPRECATED
// We now use SecureWebSocketClient below for TLS/WSS support
// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

////////////////////////////////////////////////////////////////////////////////
// SecureWebSocketClient â€“ TLS (wss://) client using Boost.Beast
////////////////////////////////////////////////////////////////////////////////
class SecureWebSocketClient {
public:
    using MessageHandler = std::function<void(const std::string&)>;

    SecureWebSocketClient(const std::string& host,
                         const std::string& port = "443",
                         const std::string& path = "/")
        : ioc_(),
          ctx_(ssl::context::tlsv12_client),
          resolver_(ioc_),
          ws_(std::make_unique<websocket::stream<ssl::stream<tcp::socket>>>(ioc_, ctx_)),
          host_(host),
          path_(path) {
        
        // Set SNI hostname and verify certificate
        if(!SSL_set_tlsext_host_name(ws_->next_layer().native_handle(), host_.c_str())) {
            throw boost::system::system_error(
                boost::system::error_code(
                    static_cast<int>(::ERR_get_error()),
                    net::error::get_ssl_category()
                )
            );
        }

        // DNS resolve & TCP connect
        auto const results = resolver_.resolve(host_, port);
        net::connect(ws_->next_layer().next_layer(), results);

        // SSL handshake
        ws_->next_layer().handshake(ssl::stream_base::client);

        // WebSocket handshake
        ws_->handshake(host_, path_);
    }

    void send(const std::string& text) {
        ws_->write(net::buffer(text));
    }

    void read(MessageHandler handler) {
        ws_->async_read(
            buffer_,
            [this, handler](beast::error_code ec, std::size_t) {
        if (ec) {
                    std::cerr << "WS read error: " << ec.message() << std::endl;
                    return;
                }
                std::string msg = beast::buffers_to_string(buffer_.data());
                buffer_.consume(buffer_.size());
                handler(msg);
                read(handler); // continue streaming
            });
    }

    void close() {
        beast::error_code ec;
        ws_->close(websocket::close_code::normal, ec);
        if(ec) {
            std::cerr << "Error closing WebSocket: " << ec.message() << std::endl;
        }
    }

    void run() {
        ioc_.run();
    }

private:
    net::io_context ioc_;
    ssl::context ctx_;
    tcp::resolver resolver_;
    std::unique_ptr<websocket::stream<ssl::stream<tcp::socket>>> ws_;
    beast::flat_buffer buffer_;
    std::string host_;
    std::string path_;
};

////////////////////////////////////////////////////////////////////////////////
// REST helper (minimal libcurl wrapper)

// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// REST helper (minimal libcurl wrapper)
// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class RestClient {
public:
    RestClient() { curl_global_init(CURL_GLOBAL_ALL); }
    ~RestClient() { curl_global_cleanup(); }

    std::optional<std::string> get(const std::string& url, const std::vector<std::string>& headers = {}) {
        CURL* curl = curl_easy_init();
        if (!curl) return std::nullopt;
        curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
        curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
        curl_easy_setopt(curl, CURLOPT_TIMEOUT, 30L);

        curl_slist* hdrs = nullptr;
        for (const auto& h : headers) hdrs = curl_slist_append(hdrs, h.c_str());
        curl_easy_setopt(curl, CURLOPT_HTTPHEADER, hdrs);

        std::string buf;
        curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, +[](char* ptr,size_t sz,size_t nm,void* userdata){
            auto* s = static_cast<std::string*>(userdata);
            s->append(ptr, sz*nm);
            return sz*nm;});
        curl_easy_setopt(curl, CURLOPT_WRITEDATA, &buf);

        CURLcode res = curl_easy_perform(curl);
        curl_slist_free_all(hdrs);
        curl_easy_cleanup(curl);
        if (res != CURLE_OK) return std::nullopt;
        return buf;
    }
};

////////////////////////////////////////////////////////////////////////////////
// OrderBook Cache
////////////////////////////////////////////////////////////////////////////////
struct OrderBookEntry {
    double price;
    double quantity;
    
    bool operator==(const OrderBookEntry& other) const {
        return std::abs(price - other.price) < 0.00001 && 
               std::abs(quantity - other.quantity) < 0.00001;
    }
};

struct OrderBookCache {
    int64_t last_update_id{0};
    int64_t last_write_time{0};
    std::map<double, double> bids;  // price -> quantity
    std::map<double, double> asks;  // price -> quantity
    
    static constexpr int64_t WRITE_INTERVAL_MS = 1000;  // Write every second
    static constexpr double MIN_QUANTITY_CHANGE = 0.001; // Min quantity change to consider significant
    
    bool shouldWrite(int64_t now_ms) const {
        return (now_ms - last_write_time) >= WRITE_INTERVAL_MS;
    }
    
    void update(const json& data) {
        // Update bids
        for (const auto& bid : data.value("b", json::array())) {
            if (bid.size() >= 2) {
                double price = std::stod(bid[0].get<std::string>());
                double qty = std::stod(bid[1].get<std::string>());
                if (qty <= 0.0) {
                    bids.erase(price);
                } else {
                    bids[price] = qty;
                }
            }
        }
        
        // Update asks
        for (const auto& ask : data.value("a", json::array())) {
            if (ask.size() >= 2) {
                double price = std::stod(ask[0].get<std::string>());
                double qty = std::stod(ask[1].get<std::string>());
                if (qty <= 0.0) {
                    asks.erase(price);
                } else {
                    asks[price] = qty;
                }
            }
        }
        
        last_update_id = data.value("u", last_update_id);
    }
    
    std::pair<json, json> getSnapshot() const {
        json bids_json = json::array();
        json asks_json = json::array();
        
        for (const auto& [price, qty] : bids) {
            if (qty > MIN_QUANTITY_CHANGE) {
                bids_json.push_back({{"price", price}, {"quantity", qty}});
            }
        }
        
        for (const auto& [price, qty] : asks) {
            if (qty > MIN_QUANTITY_CHANGE) {
                asks_json.push_back({{"price", price}, {"quantity", qty}});
            }
        }
        
        return {bids_json, asks_json};
    }
};

// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// Main service combining realâ€‘time + historical collection
// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class BackpackDataService {
public:
    BackpackDataService()
        : dbPool_(std::make_shared<PgPool>(buildConninfo())),
          dbWriter_(dbPool_),
          ws_("ws.backpack.exchange", "443") {
        running_.store(true);
        
        // Set up WebSocket message handler
        ws_.read([this](const std::string& payload) {
            onMessage(payload);
        });
    }

    void run() {
        try {
            // Subscribe to streams first
        subscribeStreams();

        // Historical fetch in separate thread
        histThread_ = std::thread([this]{ fetchHistorical(); });

            // Run the WebSocket client (blocking)
            ws_.run();
        } catch (const std::exception& e) {
            std::cerr << "Error in BackpackDataService::run: " << e.what() << std::endl;
            throw;
        }
    }

    void stop() {
        if (!running_.exchange(false)) return;
        ws_.close();
        dbWriter_.stop();
        if (histThread_.joinable()) histThread_.join();
    }

private:
    static std::string buildConninfo() {
        std::string s;
        s += "dbname=" + util::getenv_or("POSTGRES_DB", "trading_data");
        s += " user=" + util::getenv_or("POSTGRES_USER", "penrose");
        s += " password=" + util::getenv_or("POSTGRES_PASSWORD", "");
        s += " host=" + util::getenv_or("POSTGRES_HOST", "localhost");
        s += " port=" + util::getenv_or("POSTGRES_PORT", "5432");
        return s;
    }

    void subscribeStreams() {
        try {
            std::string trading_symbol = util::getenv_or("TRADING__SYMBOL", "SOL_USDC_PERP");
        json sub;
        sub["method"] = "SUBSCRIBE";
        sub["id"] = util::now_ms();
            sub["params"] = json::array();  // Initialize as array
            
            // Only subscribe to the configured symbol
            std::vector<std::string> streams = {
                "trade." + trading_symbol,
                "liquidation." + trading_symbol,
                "kline.1m." + trading_symbol,
                "depth." + trading_symbol,
                "bookTicker." + trading_symbol  // Add book ticker stream
            };
            
            for (const auto& stream : streams) {
                sub["params"].push_back(stream);
                std::cout << "Adding subscription to stream: " << stream << std::endl;
            }
            
            std::string msg = sub.dump();
            std::cout << "Sending subscription message: " << msg << std::endl;
            ws_.send(msg);
        } catch (const std::exception& e) {
            std::cerr << "Error in subscribeStreams: " << e.what() << std::endl;
            throw;
        }
    }

    void onMessage(const std::string& txt) {
        try {
            auto j = json::parse(txt);
            
            // Log subscription responses
            if (j.contains("result")) {
                std::cout << "Subscription response: " << txt << std::endl;
                return;
            }
            
            if (j.contains("error")) {
                std::cerr << "Server error: " << j.dump() << std::endl;
                return;
            }
            
            if (j.contains("stream") && j.contains("data")) {
                std::string stream = j["stream"].get<std::string>();
                std::cout << "Received message for stream: " << stream << std::endl;
                handleStream(stream, j["data"]);
            } else {
                std::cout << "Received non-stream message: " << txt << std::endl;
            }
        } catch (const std::exception& ex) {
            std::cerr << "JSON parse error: " << ex.what() << " for message: " << txt << std::endl;
        }
    }

    void handleStream(const std::string& stream, const json& data) {
        std::cout << "Processing stream: " << stream << " with data: " << data.dump() << std::endl;
        
        if (stream.rfind("trade.", 0) == 0) {
            std::cout << "Handling trade message" << std::endl;
            handleTrade(data);
        }
        else if (stream.rfind("liquidation.", 0) == 0) {
            std::cout << "Handling liquidation message" << std::endl;
            handleLiquidation(data);
        }
        else if (stream.rfind("kline.", 0) == 0) {
            std::cout << "Handling kline message" << std::endl;
            handleKline(stream, data);
        }
        else if (stream.rfind("depth.", 0) == 0) {
            std::cout << "Handling depth message" << std::endl;
            handleDepth(data);
        }
        else if (stream.rfind("bookTicker.", 0) == 0) {
            std::cout << "Handling book ticker message" << std::endl;
            handleBookTicker(data);
        }
    }

    void handleTrade(const json& d) {
        std::string symbol = d.value("s", "");
        if (symbol.empty() || symbol != util::getenv_or("TRADING__SYMBOL", "SOL_USDC_PERP")) {
            std::cout << "Skipping trade for non-matching symbol: " << symbol << std::endl;
            return;
        }
        
        std::string trade_id = std::to_string(d.value("t", 0));
        
        // Safe numeric conversions with error handling
        double price = 0.0, qty = 0.0;
        try {
            price = std::stod(d.value("p", "0"));
            qty = std::stod(d.value("q", "0"));
        } catch (const std::exception& e) {
            std::cerr << "Error converting price/quantity in trade: " << e.what() << std::endl;
            std::cerr << "Raw trade data: " << d.dump() << std::endl;
            return;
        }
        
        int64_t ts_ms = util::to_ms(d.value("T", 0LL));
        std::string side = d.value("m", false) ? "sell" : "buy";
        bool is_liquidation = d.value("l", false);
        
        std::cout << "TRADE: " << symbol << " | ID: " << trade_id 
                  << " | Price: " << price << " | Qty: " << qty 
                  << " | Side: " << side << " | Liquidation: " << is_liquidation 
                  << " | Time: " << ts_ms << std::endl;
        
        DBOperation op;
        op.query = "INSERT INTO trades (symbol, trade_id, side, price, quantity, timestamp, is_liquidation) VALUES";
        op.params.push_back({
            symbol,
            trade_id,
            side,
            str(price),
            str(qty),
            std::to_string(ts_ms),
            is_liquidation ? "true" : "false"
        });
        dbWriter_.enqueue(op);
    }

    void handleLiquidation(const json& d) {
        std::string symbol = d.value("symbol", "");
        if (symbol.empty()) return;
        std::string id = std::to_string(d.value("id", 0));
        double price  = d.value("price", 0.0);
        double qty    = d.value("quantity", 0.0);
        int64_t ts_ms = util::to_ms(d.value("timestamp", util::now_ms()));

        std::cout << "LIQUIDATION: " << symbol << " | ID: " << id 
                  << " | Price: " << price << " | Qty: " << qty 
                  << " | Time: " << ts_ms << std::endl;
        
        DBOperation op;
        op.query = "INSERT INTO liquidations (symbol, id, price, quantity, timestamp) VALUES";
        op.params.push_back({symbol, id, std::to_string(price), std::to_string(qty), std::to_string(ts_ms)});
        dbWriter_.enqueue(op);
    }

    void handleKline(const std::string& stream, const json& d) {
        auto parts = split(stream, '.');
        if (parts.size() != 3) {
            std::cout << "Invalid kline stream format: " << stream << std::endl;
            return;
        }
        
        std::string interval = parts[1];
        std::string symbol = parts[2];
        
        if (symbol != util::getenv_or("TRADING__SYMBOL", "SOL_USDC_PERP")) {
            std::cout << "Skipping kline for non-matching symbol: " << symbol << std::endl;
            return;
        }
        
        std::cout << "Processing kline data: " << d.dump() << std::endl;
        
        // Handle both string and numeric formats for timestamp
        int64_t ts_ms;
        try {
            if (d.contains("T") && d["T"].is_string()) {
                ts_ms = std::stoll(d["T"].get<std::string>());
            } else {
                ts_ms = util::to_ms(d.value("T", 0LL));
            }
        } catch (const std::exception& e) {
            std::cerr << "Error converting timestamp in kline: " << e.what() << std::endl;
            return;
        }
        
        // Safe numeric conversions with proper string handling
        double open = 0.0, high = 0.0, low = 0.0, close = 0.0, volume = 0.0;
        try {
            // Helper lambda for safe number conversion
            auto get_number = [](const json& j, const char* key) -> double {
                if (j.contains(key)) {
                    if (j[key].is_string()) {
                        return std::stod(j[key].get<std::string>());
                    } else if (j[key].is_number()) {
                        return j[key].get<double>();
                    }
                }
                return 0.0;
            };
            
            open = get_number(d, "o");
            high = get_number(d, "h");
            low = get_number(d, "l");
            close = get_number(d, "c");
            volume = get_number(d, "v");
        } catch (const std::exception& e) {
            std::cerr << "Error converting OHLCV values in kline: " << e.what() << std::endl;
            std::cerr << "Raw kline data: " << d.dump() << std::endl;
            return;
        }
        
        // Handle trade count as either string or number
        int trade_count = 0;
        try {
            if (d.contains("n")) {
                if (d["n"].is_string()) {
                    trade_count = std::stoi(d["n"].get<std::string>());
                } else {
                    trade_count = d["n"].get<int>();
                }
            }
        } catch (const std::exception& e) {
            std::cerr << "Error converting trade count in kline: " << e.what() << std::endl;
        }
        
        // Handle closed flag
        bool closed = false;
        try {
            if (d.contains("X")) {
                if (d["X"].is_string()) {
                    closed = (d["X"].get<std::string>() == "true");
                } else {
                    closed = d["X"].get<bool>();
                }
            }
        } catch (const std::exception& e) {
            std::cerr << "Error converting closed flag in kline: " << e.what() << std::endl;
        }
        
        std::cout << "KLINE: " << symbol << " | Interval: " << interval 
                  << " | Time: " << ts_ms << " | O: " << open 
                  << " | H: " << high << " | L: " << low 
                  << " | C: " << close << " | V: " << volume 
                  << " | Trades: " << trade_count 
                  << " | Closed: " << closed << std::endl;

        DBOperation op;
        op.query = "INSERT INTO klines (symbol, interval, timestamp, open, high, low, close, volume, trade_count, closed) VALUES";
        op.params.push_back({
            symbol,
            interval,
            std::to_string(ts_ms),
            str(open),
            str(high),
            str(low),
            str(close),
            str(volume),
            std::to_string(trade_count),
            closed ? "true" : "false"
        });
        dbWriter_.enqueue(op);
    }

    void handleDepth(const json& d) {
        std::string symbol = d.value("s", "");
        if (symbol.empty() || symbol != util::getenv_or("TRADING__SYMBOL", "SOL_USDC_PERP")) return;
        
        int64_t ts_ms = util::to_ms(d.value("T", 0LL));
        
        // Update cache
        auto& cache = orderbook_cache_[symbol];
        cache.update(d);
        
        std::cout << "ORDERBOOK: " << symbol << " | Time: " << ts_ms 
                  << " | Update ID: " << cache.last_update_id 
                  << " | Bids: " << cache.bids.size() 
                  << " | Asks: " << cache.asks.size() << std::endl;
        
        // Only write periodically
        if (cache.shouldWrite(ts_ms)) {
            auto [bids_json, asks_json] = cache.getSnapshot();
            
            DBOperation op;
            op.query = "INSERT INTO orderbook_snapshots (symbol, timestamp, last_update_id, bids, asks) VALUES";
            op.params.push_back({
                symbol,
                std::to_string(ts_ms),
                std::to_string(cache.last_update_id),
                bids_json.dump(),
                asks_json.dump()
            });
            dbWriter_.enqueue(op);
            
            cache.last_write_time = ts_ms;
        }
    }

    void handleBookTicker(const json& d) {
        std::string symbol = util::json_get_string(d, "s");
        if (symbol.empty() || symbol != util::getenv_or("TRADING_SYMBOL", "SOL_USDC_PERP")) {
            // std::cout << "Skipping book ticker for non-matching symbol: " << symbol << std::endl; // Optional: reduce log noise
            return;
        }

        int64_t ts_ms = util::to_ms(util::json_get_int64(d, "T", util::now_ms())); // Use now_ms() as fallback
        std::string update_id_str = util::json_get_string(d, "u");
        if (update_id_str.empty() && d.contains("u") && d["u"].is_number()) { // Handle numeric u
             update_id_str = std::to_string(d["u"].get<int64_t>());
        }

        double ask_price = util::json_get_double(d, "a");
        double ask_qty = util::json_get_double(d, "A");
        double bid_price = util::json_get_double(d, "b");
        double bid_qty = util::json_get_double(d, "B");


        // std::cout << "BOOK TICKER: " << symbol << " | Time: " << ts_ms
        //           << " | Ask: " << ask_price << "@" << ask_qty
        //           << " | Bid: " << bid_price << "@" << bid_qty
        //           << " | Update ID: " << update_id_str << std::endl; // Optional: reduce log noise

        // Publish to Redis
        if (g_redis_client) {
            try {
                std::string payload = d.dump(); // Use the original JSON data
                g_redis_client->publish("l1:quotes", payload);
                // std::cout << "Published to Redis l1:quotes: " << payload << std::endl; // Optional debug log
            } catch (const sw::redis::Error &e) {
                std::cerr << "Redis publish error: " << e.what() << std::endl;
                // Optional: attempt to reconnect or handle error
            }
        } else {
             std::cerr << "Redis client not initialized. Skipping publish." << std::endl;
        }

        // DBOperation op;                                               // <-- REMOVE DB WRITE
        // op.query = "INSERT INTO book_tickers (symbol, timestamp, update_id, ask_price, ask_quantity, bid_price, bid_quantity) VALUES"; // <-- REMOVE DB WRITE
        // op.params.push_back({                                         // <-- REMOVE DB WRITE
        //     symbol,                                                   // <-- REMOVE DB WRITE
        //     std::to_string(ts_ms),                                    // <-- REMOVE DB WRITE
        //     update_id_str,                                            // <-- REMOVE DB WRITE
        //     str(ask_price),                                           // <-- REMOVE DB WRITE
        //     str(ask_qty),                                             // <-- REMOVE DB WRITE
        //     str(bid_price),                                           // <-- REMOVE DB WRITE
        //     str(bid_qty)                                              // <-- REMOVE DB WRITE
        // });                                                           // <-- REMOVE DB WRITE
        // dbWriter_.enqueue(op);                                        // <-- REMOVE DB WRITE
    }

    // Simple split helper
    static std::vector<std::string> split(const std::string& s, char delim) {
        std::vector<std::string> out; size_t start = 0, pos;
        while ((pos = s.find(delim, start)) != std::string::npos) {
            out.push_back(s.substr(start, pos - start)); start = pos + 1;
        }
        out.push_back(s.substr(start)); return out;
    }

    static std::string str(double v) { char buf[64]; std::snprintf(buf, sizeof(buf), "%.8f", v); return buf; }

    // Historical fetch (only klines demo)
    void fetchHistorical() {
        RestClient rest;
        std::vector<std::string> pairs = {"BTC_USDC_PERP", "ETH_USDC_PERP"};
        for (const auto& sym : pairs) {
            std::string url = "https://api.backpack.exchange/api/v1/klines?symbol=" + sym + "&interval=1m&limit=1000";
            auto body = rest.get(url);
            if (!body) continue;
            try {
                auto arr = json::parse(*body);
                for (const auto& k : arr) {
                    int64_t open = k["start"].get<int64_t>() * 1000;
                    DBOperation op;
                    op.query = "INSERT INTO klines (symbol, interval, timestamp, open, high, low, close, volume, trade_count, closed) VALUES";
                    op.params.push_back({sym, "1m", std::to_string(open)}); // simplified
                    dbWriter_.enqueue(op);
                }
            } catch (...) {}
        }
    }

    // Members
    std::shared_ptr<PgPool> dbPool_;
    AsyncDBWriter dbWriter_;
    SecureWebSocketClient ws_;
    std::atomic<bool> running_{false};
    std::thread histThread_;
    std::unordered_map<std::string, OrderBookCache> orderbook_cache_;
};

// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// Signal handling & main
// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
static std::atomic<bool> gRun(true);

void signalHandler(int) {
    gRun.store(false);
}

int main() {
    std::signal(SIGINT, signalHandler);
    std::signal(SIGTERM, signalHandler);

    // --- Initialize Redis Connection ---
    try {
        sw::redis::ConnectionOptions connection_options;
        connection_options.host = util::getenv_or("REDIS_HOST", "localhost");
        connection_options.port = std::stoi(util::getenv_or("REDIS_PORT", "6379"));
        // Add password if needed: connection_options.password = util::getenv_or("REDIS_PASSWORD");
        // Add socket timeout if needed: connection_options.socket_timeout = std::chrono::milliseconds(500);

        g_redis_client = std::make_unique<sw::redis::Redis>(connection_options);
        std::cout << "Connected to Redis at " << connection_options.host << ":" << connection_options.port << std::endl;

    } catch (const std::exception& e) {
        std::cerr << "Failed to connect to Redis: " << e.what() << std::endl;
        // Depending on requirements, might exit or continue without Redis publishing
        // return 1; // Example: Exit if Redis connection is critical
    }
    // ---------------------------------

    BackpackDataService svc;
    std::thread svcThread([&]{ svc.run(); });

    while (gRun) std::this_thread::sleep_for(1s);

    svc.stop();
    svcThread.join();
    return 0;
}
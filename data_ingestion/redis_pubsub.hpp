#pragma once

#include <sw/redis++/redis++.h>
#include <chrono>
#include <thread>
#include <atomic>
#include <queue>
#include <mutex>
#include <condition_variable>
#include <string>
#include <vector>
#include <functional>

namespace hl {

// Channel priorities
enum class ChannelPriority {
    HIGH,   // Risk updates, critical alerts
    MEDIUM, // Order updates, trades
    LOW     // Telemetry, logs
};

struct Message {
    uint64_t seq_num;           // Sequence number for gap detection
    int64_t send_ts;           // Microsecond timestamp when sent
    std::string channel;       // Target channel
    std::string payload;       // Message content
    ChannelPriority priority;  // Message priority
    bool needs_compression;    // Whether to compress payload
};

class RedisPubSub {
public:
    RedisPubSub(const std::string& host, int port, 
                size_t batch_size = 50,
                std::chrono::milliseconds batch_interval = std::chrono::milliseconds(1))
        : batch_size_(batch_size)
        , batch_interval_(batch_interval)
        , next_seq_(0)
        , last_heartbeat_(0)
        , running_(false) {
        
        // Connect to Redis
        sw::redis::ConnectionOptions opts;
        opts.host = host;
        opts.port = port;
        
        // Enable AOF persistence
        sw::redis::ConnectionPoolOptions pool_opts;
        pool_opts.size = 3; // Separate pools for pub/sub/admin
        
        redis_ = std::make_unique<sw::redis::Redis>(opts, pool_opts);
        
        // Configure persistence
        redis_->command("CONFIG", "SET", "appendonly", "yes");
        redis_->command("CONFIG", "SET", "appendfsync", "everysec");
        
        // Initialize metrics
        metrics_ = std::make_unique<sw::redis::Redis>(opts);
    }
    
    ~RedisPubSub() {
        stop();
    }
    
    void start() {
        if (running_) return;
        running_ = true;
        
        // Start worker threads
        publisher_thread_ = std::thread(&RedisPubSub::publisher_loop, this);
        heartbeat_thread_ = std::thread(&RedisPubSub::heartbeat_loop, this);
        metrics_thread_ = std::thread(&RedisPubSub::metrics_loop, this);
        
        // Start priority-specific subscriber threads
        for (const auto& priority : {ChannelPriority::HIGH, 
                                   ChannelPriority::MEDIUM,
                                   ChannelPriority::LOW}) {
            subscriber_threads_.emplace_back(
                &RedisPubSub::subscriber_loop, this, priority);
        }
    }
    
    void stop() {
        if (!running_) return;
        running_ = false;
        
        // Stop all threads
        if (publisher_thread_.joinable()) publisher_thread_.join();
        if (heartbeat_thread_.joinable()) heartbeat_thread_.join();
        if (metrics_thread_.joinable()) metrics_thread_.join();
        
        for (auto& thread : subscriber_threads_) {
            if (thread.joinable()) thread.join();
        }
    }
    
    void publish(Message msg) {
        std::lock_guard<std::mutex> lock(queue_mutex_);
        msg.seq_num = next_seq_++;
        msg.send_ts = std::chrono::duration_cast<std::chrono::microseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();
        message_queue_.push(std::move(msg));
        queue_cv_.notify_one();
    }
    
    void subscribe(const std::string& channel, 
                  std::function<void(const Message&)> callback,
                  ChannelPriority priority = ChannelPriority::MEDIUM) {
        std::lock_guard<std::mutex> lock(callback_mutex_);
        callbacks_[priority][channel] = std::move(callback);
    }
    
    // Get current metrics
    std::unordered_map<std::string, double> get_metrics() const {
        std::lock_guard<std::mutex> lock(metrics_mutex_);
        return metrics_data_;
    }

private:
    void publisher_loop() {
        std::vector<Message> batch;
        batch.reserve(batch_size_);
        
        while (running_) {
            {
                std::unique_lock<std::mutex> lock(queue_mutex_);
                if (message_queue_.empty()) {
                    queue_cv_.wait_for(lock, batch_interval_);
                    continue;
                }
                
                // Collect batch
                while (batch.size() < batch_size_ && !message_queue_.empty()) {
                    batch.push_back(std::move(message_queue_.front()));
                    message_queue_.pop();
                }
            }
            
            if (!batch.empty()) {
                // Use pipelining for batch publish
                auto pipe = redis_->pipeline();
                
                for (const auto& msg : batch) {
                    std::string payload = serialize_message(msg);
                    if (msg.needs_compression) {
                        payload = compress(payload);
                    }
                    pipe.publish(msg.channel, payload);
                }
                
                pipe.exec();
                batch.clear();
            }
        }
    }
    
    void subscriber_loop(ChannelPriority priority) {
        auto sub = redis_->subscriber();
        
        // Subscribe to channels for this priority
        {
            std::lock_guard<std::mutex> lock(callback_mutex_);
            for (const auto& [channel, _] : callbacks_[priority]) {
                sub.subscribe(channel);
            }
        }
        
        while (running_) {
            try {
                sub.consume();
            } catch (const sw::redis::Error& e) {
                // Log error and retry
                std::cerr << "Redis subscriber error: " << e.what() << std::endl;
                std::this_thread::sleep_for(std::chrono::seconds(1));
            }
        }
    }
    
    void heartbeat_loop() {
        const auto heartbeat_interval = std::chrono::seconds(1);
        const auto max_missed = 3;
        
        while (running_) {
            auto now = std::chrono::system_clock::now();
            auto ts = std::chrono::duration_cast<std::chrono::microseconds>(
                now.time_since_epoch()).count();
                
            // Send heartbeat
            redis_->publish("heartbeat", "PING:" + std::to_string(ts));
            
            // Check for missed heartbeats
            {
                std::lock_guard<std::mutex> lock(heartbeat_mutex_);
                if (last_heartbeat_ > 0 && 
                    ts - last_heartbeat_ > heartbeat_interval.count() * max_missed) {
                    // Trigger reconnection/resync
                    handle_connection_loss();
                }
            }
            
            std::this_thread::sleep_for(heartbeat_interval);
        }
    }
    
    void metrics_loop() {
        while (running_) {
            try {
                // Get Redis stats
                auto info = redis_->command<std::string>("INFO", "stats");
                
                // Parse and update metrics
                update_metrics(info);
                
                std::this_thread::sleep_for(std::chrono::seconds(1));
            } catch (const std::exception& e) {
                std::cerr << "Metrics error: " << e.what() << std::endl;
            }
        }
    }
    
    void handle_connection_loss() {
        // Implement reconnection logic
        // Trigger WebSocket resync
        // Reset sequence numbers
    }
    
    void update_metrics(const std::string& info) {
        std::lock_guard<std::mutex> lock(metrics_mutex_);
        
        // Parse INFO output and update metrics_data_
        // Track: ops_per_sec, connected_clients, etc.
    }
    
    static std::string compress(const std::string& data) {
        // Implement Zstd compression
        return data; // Placeholder
    }
    
    static std::string serialize_message(const Message& msg) {
        // Implement message serialization
        return ""; // Placeholder
    }

private:
    std::unique_ptr<sw::redis::Redis> redis_;
    std::unique_ptr<sw::redis::Redis> metrics_;
    
    size_t batch_size_;
    std::chrono::milliseconds batch_interval_;
    
    std::atomic<uint64_t> next_seq_;
    std::atomic<int64_t> last_heartbeat_;
    std::atomic<bool> running_;
    
    std::queue<Message> message_queue_;
    std::mutex queue_mutex_;
    std::condition_variable queue_cv_;
    
    std::unordered_map<ChannelPriority, 
                      std::unordered_map<std::string, 
                      std::function<void(const Message&)>>> callbacks_;
    std::mutex callback_mutex_;
    
    std::thread publisher_thread_;
    std::thread heartbeat_thread_;
    std::thread metrics_thread_;
    std::vector<std::thread> subscriber_threads_;
    
    mutable std::mutex metrics_mutex_;
    std::unordered_map<std::string, double> metrics_data_;
    
    std::mutex heartbeat_mutex_;
};

} // namespace hl 
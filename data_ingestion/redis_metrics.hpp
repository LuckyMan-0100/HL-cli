#pragma once

#include <prometheus/counter.h>
#include <prometheus/gauge.h>
#include <prometheus/histogram.h>
#include <prometheus/registry.h>
#include <prometheus/exposer.h>

#include <string>
#include <memory>
#include <unordered_map>
#include <chrono>
#include <regex>

namespace hl {

class RedisMetrics {
public:
    RedisMetrics(const std::string& metrics_addr = "0.0.0.0:8080")
        : registry_(std::make_shared<prometheus::Registry>())
        , exposer_(metrics_addr) {
        
        // Register metrics endpoint
        exposer_.RegisterCollectable(registry_);
        
        // Initialize metrics
        auto& metrics = prometheus::BuildCounter()
            .Name("redis_messages_total")
            .Help("Total number of Redis messages processed")
            .Register(*registry_);
            
        message_counter_ = &metrics.Add({});
        
        auto& latency = prometheus::BuildHistogram()
            .Name("redis_message_latency_microseconds")
            .Help("Redis message latency in microseconds")
            .Buckets({100, 250, 500, 1000, 2500, 5000, 10000})
            .Register(*registry_);
            
        latency_histogram_ = &latency.Add({});
        
        auto& queue_depth = prometheus::BuildGauge()
            .Name("redis_queue_depth")
            .Help("Current Redis queue depth")
            .Register(*registry_);
            
        queue_depth_gauge_ = &queue_depth.Add({});
        
        auto& ops = prometheus::BuildGauge()
            .Name("redis_ops_per_sec")
            .Help("Redis operations per second")
            .Register(*registry_);
            
        ops_gauge_ = &ops.Add({});
        
        auto& memory = prometheus::BuildGauge()
            .Name("redis_used_memory_bytes")
            .Help("Redis used memory in bytes")
            .Register(*registry_);
            
        memory_gauge_ = &memory.Add({});
    }
    
    void record_message() {
        message_counter_->Increment();
    }
    
    void record_latency(int64_t latency_us) {
        latency_histogram_->Observe(latency_us);
    }
    
    void set_queue_depth(double depth) {
        queue_depth_gauge_->Set(depth);
    }
    
    void update_redis_stats(const std::string& info) {
        static const std::regex ops_re(R"(instantaneous_ops_per_sec:(\d+))");
        static const std::regex mem_re(R"(used_memory:(\d+))");
        
        std::smatch match;
        
        // Parse ops/sec
        if (std::regex_search(info, match, ops_re)) {
            ops_gauge_->Set(std::stod(match[1]));
        }
        
        // Parse memory usage
        if (std::regex_search(info, match, mem_re)) {
            memory_gauge_->Set(std::stod(match[1]));
        }
    }
    
    // Get current metrics snapshot
    std::unordered_map<std::string, double> get_snapshot() const {
        return {
            {"messages_total", message_counter_->Value()},
            {"queue_depth", queue_depth_gauge_->Value()},
            {"ops_per_sec", ops_gauge_->Value()},
            {"used_memory_bytes", memory_gauge_->Value()}
        };
    }
    
    // Alert thresholds
    bool should_alert() const {
        const double MAX_QUEUE_DEPTH = 1000;
        const double MAX_OPS_RATIO = 0.8;
        const double TARGET_OPS = 10000;
        
        return queue_depth_gauge_->Value() > MAX_QUEUE_DEPTH ||
               ops_gauge_->Value() > TARGET_OPS * MAX_OPS_RATIO;
    }

private:
    std::shared_ptr<prometheus::Registry> registry_;
    prometheus::Exposer exposer_;
    
    prometheus::Counter* message_counter_;
    prometheus::Histogram* latency_histogram_;
    prometheus::Gauge* queue_depth_gauge_;
    prometheus::Gauge* ops_gauge_;
    prometheus::Gauge* memory_gauge_;
};

} // namespace hl 
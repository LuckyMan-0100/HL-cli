#include <iostream>
#include <vector>
#include <chrono>
#include <thread>
#include <atomic>
#include <cstring>
#include <lightgbm/c_api.h>
#include "onload_util.hpp"
#ifdef __linux__
#include "platform_util.hpp"
#include <sched.h>
#endif
#include <sys/mman.h>
#include "ring_buffer.hpp"
#include <cstdint> // for int64_t

// Constants
constexpr int MODEL_INPUT_SIZE = 50;  // Number of features
constexpr int RING_BUFFER_SIZE = 1024;
constexpr int HUGEPAGE_SIZE = 2 * 1024 * 1024;  // 2MB huge pages

// Shared memory ring buffer for market data
struct MarketData {
    double timestamp;
    double features[MODEL_INPUT_SIZE];
    double bid_price;
    double ask_price;
    double bid_size;
    double ask_size;
};

// Ring buffer for passing data between threads
RingBuffer<MarketData, RING_BUFFER_SIZE> market_data_buffer;

class LowLatencyPredictor {
public:
    LowLatencyPredictor(const char* model_path) : running_(false) {
        // Initialize LightGBM
        #if LGBM_VERSION_MAJOR > 3
        int n_iters_64 = 0;
        int ret = LGBM_BoosterCreateFromModelfile(
            model_path,
            &n_iters_64,
            &booster_
        );
        #else
        int ret = LGBM_BoosterCreateFromModelfile(
            model_path,
            &booster_
        );
        #endif
        if (ret != 0) {
            throw std::runtime_error("Failed to load model");
        }
        
        // Allocate huge pages for feature matrix
        #ifdef __linux__
        features_ = static_cast<double*>(platform_util::mmap_huge(
            nullptr,
            MODEL_INPUT_SIZE * sizeof(double),
            PROT_READ | PROT_WRITE
        ));
        #else
        features_ = static_cast<double*>(mmap(
            nullptr,
            MODEL_INPUT_SIZE * sizeof(double),
            PROT_READ | PROT_WRITE,
            MAP_PRIVATE | MAP_ANONYMOUS,
            -1,
            0
        ));
        #endif
        
        if (features_ == MAP_FAILED) {
            throw std::runtime_error("Failed to allocate huge pages");
        }
        
        // Pin thread and set high priority on Linux
        #ifdef __linux__
        platform_util::pin_to_cpu(2);
        struct sched_param param;
        param.sched_priority = sched_get_priority_max(SCHED_FIFO);
        if (sched_setscheduler(0, SCHED_FIFO, &param) != 0) {
            throw std::runtime_error("Failed to set thread priority");
        }
        #endif
        
        // Initialize Solarflare Onload
        #ifdef __linux__
        if (onload_util::is_present()) {
            onload_util::thread_set_spin(1);  // Enable spinning
        }
        #endif
    }
    
    ~LowLatencyPredictor() {
        if (features_) {
            munmap(features_, MODEL_INPUT_SIZE * sizeof(double));
        }
        if (booster_) {
            LGBM_BoosterFree(booster_);
        }
    }
    
    void start() {
        running_ = true;
        inference_thread_ = std::thread(&LowLatencyPredictor::inference_loop, this);
    }
    
    void stop() {
        running_ = false;
        if (inference_thread_.joinable()) {
            inference_thread_.join();
        }
    }

private:
    void inference_loop() {
        std::vector<double> out_result;
        int out_len;
        
        while (running_) {
            // Try to read from ring buffer
            MarketData data;
            if (!market_data_buffer.try_dequeue(data)) {
                // Spin if no data
                continue;
            }
            
            // Copy features to huge page memory
            std::memcpy(features_, data.features, MODEL_INPUT_SIZE * sizeof(double));
            
            // Get prediction
            auto start = std::chrono::high_resolution_clock::now();
            
            #if LGBM_VERSION_MAJOR > 3
            int64_t out_len_64 = 0;
            int ret = LGBM_BoosterPredictForMat(
                booster_,
                features_,
                C_API_DTYPE_FLOAT64,
                1,
                MODEL_INPUT_SIZE,
                1,
                C_API_PREDICT_NORMAL,
                /* num_iteration */ 0,
                /* start_iteration */ 0,
                /* parameter */ nullptr,
                &out_len_64,
                out_result.data()
            );
            #else
            int out_len_32 = 0;
            int ret = LGBM_BoosterPredictForMat(
                booster_,
                features_,
                C_API_DTYPE_FLOAT64,
                1,
                MODEL_INPUT_SIZE,
                1,
                C_API_PREDICT_NORMAL,
                &out_len_32,
                out_result.data()
            );
            #endif
            
            auto end = std::chrono::high_resolution_clock::now();
            auto latency = std::chrono::duration_cast<std::chrono::microseconds>(
                end - start
            ).count();
            
            // Process prediction result
            if (ret == 0 && out_len > 0) {
                process_prediction(data, out_result, latency);
            }
        }
    }
    
    void process_prediction(
        const MarketData& data,
        const std::vector<double>& pred,
        int64_t latency
    ) {
        // Implementation-specific logic for handling predictions
        // This could involve sending orders, updating state, etc.
    }
    
    BoosterHandle booster_;
    double* features_;
    std::atomic<bool> running_;
    std::thread inference_thread_;
};

int main() {
    try {
        // Load model and start predictor
        LowLatencyPredictor predictor("model.txt");
        predictor.start();
        
        // Main loop would go here
        // This could involve receiving market data and enqueueing to buffer
        
        predictor.stop();
        return 0;
        
    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }
} 
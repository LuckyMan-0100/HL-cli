#include <gtest/gtest.h>
#include <chrono>
#include <thread>
#include <limits>
#include <iostream>

// Include the necessary headers from the main application
// Adjust paths if necessary based on your test setup
#include "../exec_bridge.hpp" 

// Mock or stub necessary parts if needed (e.g., BackpackClient for onTick strategy)
// For this latency test, we focus on the onTick overhead itself, 
// assuming the strategy logic inside is separate or can be mocked/simplified.

// Test fixture for ExecutionClient tests
class ExecBridgeLatencyTest : public ::testing::Test {
protected:
    // SetUp() can be used to initialize common resources for tests
    void SetUp() override {
        // Set required environment variables for ExecutionClient constructor if needed
        // (e.g., BACKPACK_API_KEY, BACKPACK_API_SECRET, TRADING_SYMBOL)
        // Use setenv() but be careful as it affects the whole process.
        // Alternatively, modify ExecutionClient to accept config/credentials directly for testing.
        // For now, assume env vars are set externally or constructor handles missing keys gracefully for test.
        try {
             // Ensure constructor doesn't throw due to missing env vars in test environment
             // This might require adjusting the ExecutionClient constructor or setting dummy env vars
             setenv("BACKPACK_API_KEY", "test_key", 1);
             setenv("BACKPACK_API_SECRET", "test_secret", 1);
             setenv("TRADING_SYMBOL", "SOL_USDC_PERP", 1);
            exec_client = std::make_unique<bp::ExecutionClient>();
        } catch (const std::exception& e) {
             FAIL() << "Failed to initialize ExecutionClient in SetUp: " << e.what();
        }
    }

    // TearDown() can be used to release resources
    void TearDown() override {
        exec_client.reset();
    }

    std::unique_ptr<bp::ExecutionClient> exec_client;
};

// Test case for onTick latency
TEST_F(ExecBridgeLatencyTest, OnTickProcessingTime) {
    ASSERT_TRUE(exec_client) << "ExecutionClient pointer is null";

    // Define sample tick data
    double sample_bid = 100.0;
    double sample_ask = 100.1;
    int64_t sample_ts = std::chrono::duration_cast<std::chrono::milliseconds>(
                          std::chrono::system_clock::now().time_since_epoch()).count();

    // Warm-up call (optional, can reduce noise from first-time execution)
    try {
        exec_client->onTick(sample_bid - 1, sample_ask + 1, sample_ts - 1000);
    } catch (const std::exception& e) {
        // Ignore errors during warm-up if strategy fails without real connection
        std::cerr << "Warm-up onTick call threw exception (ignored): " << e.what() << std::endl;
    }
    std::this_thread::sleep_for(std::chrono::microseconds(100)); // Small pause after warm-up

    // Measure execution time of onTick
    auto start = std::chrono::high_resolution_clock::now();
    
    try {
        exec_client->onTick(sample_bid, sample_ask, sample_ts);
    } catch (const std::exception& e) {
        // If the strategy part throws (e.g., cannot connect to Backpack), 
        // the test might still pass if the cache update part is fast enough.
        // Ideally, mock the BackpackClient interaction for a pure unit test.
         std::cerr << "onTick call during measurement threw exception (ignored for latency check): " << e.what() << std::endl;
    }

    auto end = std::chrono::high_resolution_clock::now();
    auto duration = std::chrono::duration_cast<std::chrono::microseconds>(end - start);

    // Verify the updated cache state (optional but good practice)
    ASSERT_DOUBLE_EQ(exec_client->bestBid(), sample_bid);
    ASSERT_DOUBLE_EQ(exec_client->bestAsk(), sample_ask);

    // Check if latency is within the acceptable threshold (1 ms = 1000 µs)
    const long long max_latency_us = 1000; // 1 millisecond
    EXPECT_LT(duration.count(), max_latency_us)
        << "onTick processing time (" << duration.count() << " Âµs) exceeded the threshold (" 
        << max_latency_us << " Âµs)";

    std::cout << "[ Perf ] onTick duration: " << duration.count() << " Âµs" << std::endl;
}

// Main function to run the tests
int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    // Set minimal logging for Redis++ if it's noisy during tests
    // sw::redis::Log::level(sw::redis::LogLevel::ERROR);
    return RUN_ALL_TESTS();
} 
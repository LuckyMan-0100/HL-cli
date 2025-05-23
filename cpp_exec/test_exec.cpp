#include "exec_bridge.hpp"
#include <iostream>
#include <thread>
#include <chrono>
#include <atomic>
#include <cassert>

// Test callback to verify L1 data handling
void test_l1_callback(const bp::BookTicker& ticker) {
    std::cout << "L1 Update received:" << std::endl
              << "  Symbol: " << ticker.symbol << std::endl
              << "  Bid: " << ticker.bid_price << std::endl
              << "  Ask: " << ticker.ask_price << std::endl
              << "  BidQty: " << ticker.bid_qty << std::endl
              << "  AskQty: " << ticker.ask_qty << std::endl
              << "  Timestamp: " << ticker.timestamp << std::endl;
}

int main() {
    try {
        // Create execution client instance with test credentials
        bp::DefaultExecutionClient client(
            "test_api_key",
            "test_private_key",
            "SOL-PERP",  // Example trading symbol
            0.02        // Max daily drawdown percentage
        );

        // Setup signal handler for graceful shutdown
        client.setupSignalHandler();

        // Register L1 callback
        client.registerL1Callback(test_l1_callback);

        // Test L1 data handling
        std::cout << "Testing L1 data handling..." << std::endl;
        
        // Simulate an L1 update
        client.onTick("SOL-PERP", 100.0, 100.1, 10.0, 15.0, 
                     std::chrono::system_clock::now().time_since_epoch().count());

        // Verify best bid/ask cache
        assert(client.bestBid() == 100.0);
        assert(client.bestAsk() == 100.1);
        assert(std::abs(client.mid() - 100.05) < 0.0001);

        // Test post-only maker order
        std::cout << "Testing post-only maker order..." << std::endl;
        
        // Should fail (would cross the book)
        auto result = client.postOnlyMaker(true, 1.0, 100.2);
        assert(result.empty());

        // Should succeed
        result = client.postOnlyMaker(true, 1.0, 99.9);
        assert(!result.empty());

        std::cout << "All tests passed successfully!" << std::endl;
        return 0;

    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }
} 
#include "exec_bridge.hpp"
#include <spdlog/spdlog.h>
#include <spdlog/sinks/stdout_color_sinks.h>
#include <chrono>
#include <thread>
#include <iostream>

using namespace bp;

int main() {
    try {
        // Set up logging
        spdlog::set_level(spdlog::level::info);
        auto console = spdlog::stdout_color_mt("console");
        spdlog::set_default_logger(console);
        
        spdlog::info("=== Collateral Monitoring Test ===");
        
        // Get credentials from environment
        std::string api_key = std::getenv("BACKPACK_API_KEY") ? std::getenv("BACKPACK_API_KEY") : "";
        std::string private_key = std::getenv("BACKPACK_PRIVATE_KEY") ? std::getenv("BACKPACK_PRIVATE_KEY") : "";
        
        if (api_key.empty() || private_key.empty()) {
            spdlog::error("Please set BACKPACK_API_KEY and BACKPACK_PRIVATE_KEY environment variables");
            return 1;
        }
        
        spdlog::info("Creating DefaultExecutionClient for collateral testing...");
        
        // Create execution client with minimal setup
        DefaultExecutionClient client(api_key, private_key, "SOL_USDC_PERP", 0.02, "");
        
        spdlog::info("Client created successfully. Testing collateral query...");
        
        // Test 1: Direct collateral query
        spdlog::info("\n--- Test 1: Direct Collateral Query ---");
        try {
            auto collateral_data = client.query_collateral();
            spdlog::info("Raw collateral response: {}", collateral_data.dump(2));
            
            // Parse and display key metrics
            double total = collateral_data.value("totalCollateral", 0.0);
            double available = collateral_data.value("availableCollateral", 0.0);
            double used = collateral_data.value("usedCollateral", 0.0);
            
            if (total > 0.0) {
                double utilization = (used / total) * 100.0;
                spdlog::info("Parsed Collateral Metrics:");
                spdlog::info("  Total Collateral: ${:.2f}", total);
                spdlog::info("  Available Collateral: ${:.2f}", available);
                spdlog::info("  Used Collateral: ${:.2f}", used);
                spdlog::info("  Utilization: {:.1f}%", utilization);
            } else {
                spdlog::warn("No collateral data returned or total is zero");
            }
            
        } catch (const std::exception& e) {
            spdlog::error("Direct collateral query failed: {}", e.what());
        }
        
        // Test 2: Collateral cache update
        spdlog::info("\n--- Test 2: Collateral Cache Update ---");
        try {
            auto collateral_data = client.query_collateral();
            client.update_collateral_cache(collateral_data);
            client.log_collateral_status();
            
            // Access cached values
            double cached_total = client.total_collateral_.load(std::memory_order_relaxed);
            double cached_available = client.available_collateral_.load(std::memory_order_relaxed);
            double cached_utilization = client.collateral_utilization_pct_.load(std::memory_order_relaxed);
            
            spdlog::info("Cached values after update:");
            spdlog::info("  Cached Total: ${:.2f}", cached_total);
            spdlog::info("  Cached Available: ${:.2f}", cached_available);
            spdlog::info("  Cached Utilization: {:.1f}%", cached_utilization);
            
        } catch (const std::exception& e) {
            spdlog::error("Collateral cache update failed: {}", e.what());
        }
        
        // Test 3: Risk manager collateral integration
        spdlog::info("\n--- Test 3: Risk Manager Integration ---");
        try {
            double test_price = 100.0; // Test price for position sizing
            double max_position_size = client.risk_manager_->get_max_position_size(test_price);
            bool has_sufficient = client.risk_manager_->has_sufficient_collateral(500.0); // Test $500 position
            
            spdlog::info("Risk Manager Collateral Tests:");
            spdlog::info("  Max position size at ${:.2f}: {:.6f} units", test_price, max_position_size);
            spdlog::info("  Has sufficient collateral for $500 position: {}", has_sufficient ? "YES" : "NO");
            
        } catch (const std::exception& e) {
            spdlog::error("Risk manager integration test failed: {}", e.what());
        }
        
        // Test 4: Monitoring thread (short duration)
        spdlog::info("\n--- Test 4: Collateral Monitoring Thread (30 seconds) ---");
        spdlog::info("Starting collateral monitoring thread for 30 seconds...");
        
        // The monitoring thread is already started in the constructor
        // Let it run for 30 seconds to see multiple updates
        for (int i = 0; i < 6; i++) {
            std::this_thread::sleep_for(std::chrono::seconds(5));
            spdlog::info("Monitoring test progress: {} seconds elapsed...", (i + 1) * 5);
        }
        
        spdlog::info("=== Test Complete ===");
        spdlog::info("Shutting down client...");
        
        // Clean shutdown
        client.stop();
        
        return 0;
        
    } catch (const std::exception& e) {
        spdlog::error("Test failed with exception: {}", e.what());
        return 1;
    } catch (...) {
        spdlog::error("Test failed with unknown exception");
        return 1;
    }
} 
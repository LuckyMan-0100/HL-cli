#include "risk_manager.hpp"
#include <iostream>
#include <cmath>
#include <chrono>

namespace bp {

RiskManager::RiskManager(double max_daily_drawdown_pct)
    : max_daily_drawdown_pct_(max_daily_drawdown_pct)
{
    try {
        redis_client_ = std::make_unique<sw::redis::Redis>("tcp://127.0.0.1:6379");
        
        // Initialize equity metrics
        updateEquityMetrics();
        
        // Reset daily metrics at start
        resetDailyMetrics();
        
    } catch (const std::exception& e) {
        std::cerr << "Failed to initialize RiskManager: " << e.what() << std::endl;
        throw;
    }
}

bool RiskManager::checkRiskLimits() {
    if (trading_halted_.load()) {
        return false;
    }

    try {
        updateEquityMetrics();
        
        // Calculate current drawdown
        double drawdown = getCurrentDrawdown();
        
        // Check if drawdown exceeds limit
        if (drawdown > max_daily_drawdown_pct_) {
            std::cerr << "Daily drawdown limit exceeded: " << drawdown << "% > " 
                      << max_daily_drawdown_pct_ << "%" << std::endl;
            trading_halted_.store(true);
            return false;
        }
        
        return true;
        
    } catch (const std::exception& e) {
        std::cerr << "Error checking risk limits: " << e.what() << std::endl;
        return false;
    }
}

void RiskManager::sleepOnDrawdown(std::chrono::seconds duration) {
    if (!trading_halted_.load()) {
        return;
    }

    std::cerr << "Trading halted due to drawdown. Sleeping for " 
              << duration.count() << " seconds." << std::endl;
    
    // Cancel all orders (this should be done by the ExecutionClient)
    
    // Sleep for specified duration
    std::this_thread::sleep_for(duration);
    
    // Reset trading halt flag
    trading_halted_.store(false);
    
    // Reset daily metrics
    resetDailyMetrics();
}

double RiskManager::getDailyPnL() const {
    double current = getCurrentEquity();
    double initial = initial_equity_.load();
    if (initial <= 0) return 0.0;
    return ((current - initial) / initial) * 100.0;
}

double RiskManager::getCurrentDrawdown() const {
    double peak = peak_equity_.load();
    double current = getCurrentEquity();
    if (peak <= 0) return 0.0;
    return ((peak - current) / peak) * 100.0;
}

double RiskManager::getCurrentEquity() const {
    try {
        auto val = redis_client_->get(EQUITY_KEY);
        if (val) {
            return std::stod(*val);
        }
    } catch (const std::exception& e) {
        std::cerr << "Error getting current equity: " << e.what() << std::endl;
    }
    return 0.0;
}

void RiskManager::updateEquityMetrics() {
    double current = getCurrentEquity();
    if (current <= 0) return;

    // Update peak equity if needed
    double peak = peak_equity_.load();
    if (current > peak) {
        peak_equity_.store(current);
        try {
            redis_client_->set(PEAK_EQUITY_KEY, std::to_string(current));
        } catch (const std::exception& e) {
            std::cerr << "Error updating peak equity: " << e.what() << std::endl;
        }
    }
}

void RiskManager::resetDailyMetrics() {
    double current = getCurrentEquity();
    if (current <= 0) return;

    // Store initial equity for the day
    initial_equity_.store(current);
    peak_equity_.store(current);

    try {
        redis_client_->set(INITIAL_EQUITY_KEY, std::to_string(current));
        redis_client_->set(PEAK_EQUITY_KEY, std::to_string(current));
    } catch (const std::exception& e) {
        std::cerr << "Error resetting daily metrics: " << e.what() << std::endl;
    }
}

} // namespace bp 
#include "risk_manager.hpp"
#include <iostream>
#include <cmath>
#include <chrono>
#include <spdlog/spdlog.h>

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
    std::lock_guard<std::mutex> lock(mutex_);
    
    // Check daily PnL limit
    if (daily_pnl_ < -getMaxDailyLoss()) {
        spdlog::error("Daily loss limit exceeded: {} < -{}", daily_pnl_, getMaxDailyLoss());
        trading_halted_ = true;
        return false;
    }

    // Check drawdown limit
    if (current_drawdown_ > max_daily_drawdown_pct_) {
        spdlog::error("Max drawdown exceeded: {} > {}", current_drawdown_, max_daily_drawdown_pct_);
        trading_halted_ = true;
        return false;
    }

    return true;
}

bool RiskManager::checkRiskLimits(bool is_buy, double size, double price) {
    std::lock_guard<std::mutex> lock(mutex_);
    
    // First check basic risk limits
    if (!checkRiskLimits()) {
        return false;
    }

    // Check position size limit
    if (size > max_position_size_) {
        spdlog::error("Position size exceeds limit: {} > {}", size, max_position_size_);
        return false;
    }

    // Check notional value limit (size * price)
    double notional = size * price;
    double max_notional = max_position_size_ * price;
    if (notional > max_notional) {
        spdlog::error("Notional value exceeds limit: {} > {}", notional, max_notional);
        return false;
    }

    // Check if we're in drawdown sleep mode
    if (is_sleeping_) {
        spdlog::warn("Trading halted during drawdown sleep period");
        return false;
    }

    return true;
}

void RiskManager::sleepOnDrawdown(std::chrono::seconds duration) {
    if (is_sleeping_) {
        spdlog::warn("Already in drawdown sleep mode");
        return;
    }
    
    is_sleeping_ = true;
    spdlog::info("Entering drawdown sleep for {} seconds", duration.count());
    
    try {
        // Reset metrics before sleeping
        resetRiskMetrics();
        
        // Sleep for the specified duration
        std::this_thread::sleep_for(duration);
        
    } catch (const std::exception& e) {
        spdlog::error("Error during drawdown sleep: {}", e.what());
    }
    
    is_sleeping_ = false;
    spdlog::info("Drawdown sleep completed");
}

double RiskManager::getDailyPnL() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return daily_pnl_;
}

double RiskManager::getCurrentDrawdown() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return current_drawdown_;
}

double RiskManager::getCurrentEquity() const {
    if (!redis_client_) return initial_equity_;
    
    try {
        auto equity_str = redis_client_->get(EQUITY_KEY);
        return equity_str ? std::stod(*equity_str) : initial_equity_;
    } catch (const std::exception& e) {
        spdlog::error("Error getting current equity: {}", e.what());
        return initial_equity_;
    }
}

void RiskManager::updateEquityMetrics() {
    if (!redis_client_) return;
    
    try {
        double current_equity = getCurrentEquity();
        
        // Update peak equity if needed
        if (current_equity > peak_equity_) {
            peak_equity_ = current_equity;
            redis_client_->set(PEAK_EQUITY_KEY, std::to_string(current_equity));
        }
        
        // Calculate and update drawdown
        if (peak_equity_ > 0) {
            current_drawdown_ = (peak_equity_ - current_equity) / peak_equity_;
        }
        
    } catch (const std::exception& e) {
        spdlog::error("Error updating equity metrics: {}", e.what());
    }
}

void RiskManager::resetDailyMetrics() {
    std::lock_guard<std::mutex> lock(mutex_);
    daily_pnl_ = 0.0;
    current_drawdown_ = 0.0;
    
    if (redis_client_) {
        try {
            // Store current equity as initial equity for the new day
            double current_equity = getCurrentEquity();
            redis_client_->set(INITIAL_EQUITY_KEY, std::to_string(current_equity));
            initial_equity_ = current_equity;
        } catch (const std::exception& e) {
            spdlog::error("Error resetting daily metrics: {}", e.what());
        }
    }
}

void RiskManager::updateDailyPnL(double pnl) {
    std::lock_guard<std::mutex> lock(mutex_);
    daily_pnl_ = pnl;
    if (daily_pnl_ > max_daily_equity_) {
        max_daily_equity_ = daily_pnl_;
    }
    updateDrawdown();
}

} // namespace bp 
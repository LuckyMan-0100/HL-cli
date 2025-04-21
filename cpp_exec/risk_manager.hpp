#pragma once

#include <memory>
#include <chrono>
#include <thread>
#include <atomic>
#include <sw/redis++/redis++.h>
#include <mutex>

namespace bp {

class RiskManager {
public:
    explicit RiskManager(double max_daily_drawdown_pct = 0.02)
        : max_daily_drawdown_pct_(max_daily_drawdown_pct)
        , daily_pnl_(0.0)
        , current_drawdown_(0.0)
        , is_sleeping_(false) {}

    // Disable copy/move
    RiskManager(const RiskManager&) = delete;
    RiskManager& operator=(const RiskManager&) = delete;
    RiskManager(RiskManager&&) = delete;
    RiskManager& operator=(RiskManager&&) = delete;

    // Core risk checks
    bool checkRiskLimits() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return !is_sleeping_ && current_drawdown_ <= max_daily_drawdown_pct_;
    }

    void sleepOnDrawdown(std::chrono::seconds duration) {
        std::lock_guard<std::mutex> lock(mutex_);
        is_sleeping_ = true;
        std::this_thread::sleep_for(duration);
        resetRiskMetrics();
        is_sleeping_ = false;
    }

    // Accessors
    double getDailyPnL() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return daily_pnl_;
    }

    double getCurrentDrawdown() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return current_drawdown_;
    }

    bool isHalted() const { return trading_halted_.load(); }

    void updatePnL(double pnl_change) {
        std::lock_guard<std::mutex> lock(mutex_);
        daily_pnl_ += pnl_change;
        
        // Update drawdown if PnL decreased
        if (pnl_change < 0) {
            double new_drawdown = -pnl_change / std::abs(daily_pnl_);
            current_drawdown_ = std::max(current_drawdown_, new_drawdown);
        }
    }

    void resetRiskMetrics() {
        std::lock_guard<std::mutex> lock(mutex_);
        daily_pnl_ = 0.0;
        current_drawdown_ = 0.0;
    }

private:
    // Risk parameters
    const double max_daily_drawdown_pct_;
    
    // State
    std::atomic<bool> trading_halted_{false};
    std::atomic<double> initial_equity_{0.0};
    std::atomic<double> peak_equity_{0.0};
    
    // Redis client for equity tracking
    std::unique_ptr<sw::redis::Redis> redis_client_;

    // Helper methods
    double getCurrentEquity() const;
    void updateEquityMetrics();
    void resetDailyMetrics();

    // Constants
    static constexpr const char* EQUITY_KEY = "account:equity";
    static constexpr const char* INITIAL_EQUITY_KEY = "account:initial_equity";
    static constexpr const char* PEAK_EQUITY_KEY = "account:peak_equity";

    double daily_pnl_;
    double current_drawdown_;
    std::atomic<bool> is_sleeping_;
    mutable std::mutex mutex_;
};

} // namespace bp 
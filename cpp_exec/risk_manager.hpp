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
    explicit RiskManager(double max_daily_drawdown_pct = 0.02);

    // Disable copy/move
    RiskManager(const RiskManager&) = delete;
    RiskManager& operator=(const RiskManager&) = delete;
    RiskManager(RiskManager&&) = delete;
    RiskManager& operator=(RiskManager&&) = delete;

    // Core risk checks
    bool checkRiskLimits();
    bool checkRiskLimits(bool is_buy, double size, double price);
    void sleepOnDrawdown(std::chrono::seconds duration);

    // Accessors
    double getDailyPnL() const;
    double getCurrentDrawdown() const;
    bool isHalted() const { return trading_halted_.load(); }

    // Risk limits
    double getMaxDailyLoss() const { return max_daily_drawdown_pct_ * initial_equity_; }
    double getMaxDrawdown() const { return max_daily_drawdown_pct_; }
    double getMaxPositionSize() const { return max_position_size_; }

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

    // PnL tracking
    void updateDailyPnL(double pnl);

private:
    void updateDrawdown() {
        if (max_daily_equity_ > 0) {
            current_drawdown_ = (max_daily_equity_ - daily_pnl_) / max_daily_equity_;
        }
    }

    // Risk parameters
    const double max_daily_drawdown_pct_;
    
    // State
    std::atomic<bool> trading_halted_{false};
    double initial_equity_{100000.0};  // Default initial equity
    double peak_equity_{0.0};
    
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
    static constexpr const char* REDIS_HOST = "localhost";
    static constexpr int REDIS_PORT = 6970;

    double daily_pnl_{0.0};
    double max_daily_equity_{0.0};
    double current_drawdown_{0.0};
    std::atomic<bool> is_sleeping_{false};
    double max_position_size_{1000.0}; // Default max position size
    mutable std::mutex mutex_;
};

} // namespace bp 
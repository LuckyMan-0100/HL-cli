#pragma once

#include <string>
#include <memory>
#include <atomic>
#include <sw/redis++/redis++.h>
#include "exec_bridge.hpp"

namespace bp {

class RedisSubscriber {
public:
    explicit RedisSubscriber(ExecutionClient& exec_client);
    ~RedisSubscriber();

    // Disable copy/move
    RedisSubscriber(const RedisSubscriber&) = delete;
    RedisSubscriber& operator=(const RedisSubscriber&) = delete;
    RedisSubscriber(RedisSubscriber&&) = delete;
    RedisSubscriber& operator=(RedisSubscriber&&) = delete;

    void start();
    void stop();

private:
    void handleBookTickerMessage(const std::string& msg);
    void handleTradeMessage(const std::string& msg);
    void handleKlineMessage(const std::string& msg);

    ExecutionClient& exec_client_;
    std::unique_ptr<sw::redis::Subscriber> subscriber_;
    std::atomic<bool> running_{false};
};

} // namespace bp 
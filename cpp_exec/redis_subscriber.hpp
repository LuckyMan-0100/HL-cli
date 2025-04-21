#ifndef CPP_EXEC_REDIS_SUBSCRIBER_HPP
#define CPP_EXEC_REDIS_SUBSCRIBER_HPP

#include <atomic>
#include <thread>
#include <string>

// Forward declare ExecutionClient to avoid circular dependency
namespace bp {
    class ExecutionClient; 
}

namespace bp {

class RedisSubscriber {
public:
    // Constructor takes a reference to the ExecutionClient it will notify
    RedisSubscriber(ExecutionClient& exec_client);
    ~RedisSubscriber(); // Destructor to manage thread

    // Start the subscriber thread
    void start();

    // Stop the subscriber thread
    void stop();

private:
    // The main loop executed by the subscriber thread
    void run();

    ExecutionClient& exec_client_; // Reference to the client to call onTick
    std::atomic<bool> running_;    // Flag to control the subscriber loop
    std::thread subscriber_thread_; // The thread running the Redis subscription loop
};

} // namespace bp

#endif // CPP_EXEC_REDIS_SUBSCRIBER_HPP 
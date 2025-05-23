#pragma once

#include <string>
#include <cstdint>
#include <memory>

namespace backpack {

enum class OrderSide {
    BUY,
    SELL
};

enum class OrderType {
    MARKET,
    LIMIT
};

enum class TimeInForce {
    GTC,    // Good Till Cancel
    IOC,    // Immediate or Cancel
    FOK,    // Fill or Kill
    GTX,    // Good Till Crossing
    POST_ONLY // Post Only - Maker Only Order
};

struct Trade {
    std::string id;
    std::string symbol;
    double price;
    double quantity;
    bool is_buyer_maker;
    uint64_t timestamp;
    double commission;
    std::string commission_asset;
};

struct OrderRequest {
    std::string symbol;
    OrderSide side;
    OrderType type;
    double quantity;
    double price;
    TimeInForce time_in_force;
};

class BackpackClient {
public:
    virtual ~BackpackClient() = default;

    // Market data methods
    virtual void subscribeToTicker(const std::string& symbol) = 0;
    virtual void subscribeToTrades(const std::string& symbol) = 0;
    virtual void subscribeToKlines(const std::string& symbol, const std::string& interval) = 0;

    // Trading methods
    virtual std::string placeOrder(const OrderRequest& order) = 0;
    virtual bool cancelOrder(const std::string& symbol, const std::string& orderId) = 0;
    virtual int cancelAllOrders(const std::string& symbol = "") = 0;

protected:
    BackpackClient() = default;
};

// Factory function to create BackpackClient instances
std::unique_ptr<BackpackClient> createBackpackClient(const std::string& api_key, const std::string& base64_private_key);

} // namespace backpack 
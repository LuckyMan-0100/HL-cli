#include <pybind11/pybind11.h>
#include <string>
#include <chrono>
#include <iostream>
#include <memory>
#include <backpack/backpack_client.hpp>

namespace py = pybind11;

namespace bp {
    enum class OrderType {
        MARKET,
        LIMIT,
        STOP_LOSS,
        TAKE_PROFIT
    };

    enum class Side { Buy, Sell };

    class ExecutionClient {
    public:
        ExecutionClient() : client_(std::make_unique<backpack::BackpackClient>()) {}

        void set_credentials(const std::string& api_key, const std::string& api_secret) {
            client_->set_credentials(api_key, api_secret);
        }

        void send_market(const std::string& symbol, double quantity, bool is_buy) {
            try {
                backpack::OrderRequest order;
                order.symbol = symbol;
                order.side = is_buy ? backpack::OrderSide::BUY : backpack::OrderSide::SELL;
                order.type = backpack::OrderType::MARKET;
                order.quantity = quantity;

                send_order(order);
            } catch (const std::exception& e) {
                throw std::runtime_error(std::string("Failed to send market order: ") + e.what());
            }
        }

        void send_limit(const std::string& symbol, double quantity, double price, bool is_buy) {
            try {
                backpack::OrderRequest order;
                order.symbol = symbol;
                order.side = is_buy ? backpack::OrderSide::BUY : backpack::OrderSide::SELL;
                order.type = backpack::OrderType::LIMIT;
                order.quantity = quantity;
                order.price = price;

                send_order(order);
            } catch (const std::exception& e) {
                throw std::runtime_error(std::string("Failed to send limit order: ") + e.what());
            }
        }

        void send_stop_loss(const std::string& symbol, double quantity, double price, bool is_buy) {
            try {
                backpack::OrderRequest order;
                order.symbol = symbol;
                order.side = is_buy ? backpack::OrderSide::BUY : backpack::OrderSide::SELL;
                order.type = backpack::OrderType::STOP_LOSS;
                order.quantity = quantity;
                order.price = price;

                send_order(order);
            } catch (const std::exception& e) {
                throw std::runtime_error(std::string("Failed to send stop loss order: ") + e.what());
            }
        }

        void send_take_profit(const std::string& symbol, double quantity, double price, bool is_buy) {
            try {
                backpack::OrderRequest order;
                order.symbol = symbol;
                order.side = is_buy ? backpack::OrderSide::BUY : backpack::OrderSide::SELL;
                order.type = backpack::OrderType::TAKE_PROFIT;
                order.quantity = quantity;
                order.price = price;

                send_order(order);
            } catch (const std::exception& e) {
                throw std::runtime_error(std::string("Failed to send take profit order: ") + e.what());
            }
        }

    private:
        void send_order(const backpack::OrderRequest& order) {
            // Test order first
            if (!client_->test_order(order)) {
                throw std::runtime_error("Order validation failed");
            }

            // Place the actual order
            auto placed_order = client_->create_order(order);
            std::cout << "Order placed: ID=" << placed_order.id 
                     << ", Status=" << backpack::order_status_to_string(placed_order.status) 
                     << std::endl;
        }

        std::unique_ptr<backpack::BackpackClient> client_;
    };
}

PYBIND11_MODULE(exec_bridge, m) {
    py::class_<bp::ExecutionClient>(m, "ExecutionClient")
        .def(py::init<>())
        .def("set_credentials", &bp::ExecutionClient::set_credentials,
             py::arg("api_key"), py::arg("api_secret"))
        .def("send_market", &bp::ExecutionClient::send_market,
             py::arg("symbol"), py::arg("quantity"), py::arg("is_buy"))
        .def("send_limit", &bp::ExecutionClient::send_limit,
             py::arg("symbol"), py::arg("quantity"), py::arg("price"), py::arg("is_buy"))
        .def("send_stop_loss", &bp::ExecutionClient::send_stop_loss,
             py::arg("symbol"), py::arg("quantity"), py::arg("price"), py::arg("is_buy"))
        .def("send_take_profit", &bp::ExecutionClient::send_take_profit,
             py::arg("symbol"), py::arg("quantity"), py::arg("price"), py::arg("is_buy"));

    py::enum_<bp::Side>(m, "Side")
        .value("Buy", bp::Side::Buy)
        .value("Sell", bp::Side::Sell);

    py::enum_<bp::OrderType>(m, "OrderType")
        .value("Market", bp::OrderType::MARKET)
        .value("Limit", bp::OrderType::LIMIT)
        .value("StopLoss", bp::OrderType::STOP_LOSS)
        .value("TakeProfit", bp::OrderType::TAKE_PROFIT);
}
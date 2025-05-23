#include <pybind11/pybind11.h>
#include <pybind11/stl.h> // For automatic conversion of STL containers
#include <pybind11/chrono.h> // For automatic conversion of std::chrono types
#include "include/pybind11_json.hpp" // Use the local copy of the json caster
#include "exec_bridge.hpp"   // Assuming DefaultExecutionClient is declared here
// #include "../backpack-cpp-sdk/include/backpack/types.hpp" // Removed to prevent redefinitions

namespace py = pybind11;

PYBIND11_MODULE(exec_bridge, m) {
    m.doc() = "pybind11 plugin for Hyperliquid C++ execution client";

    // Expose OrderSide enum
    py::enum_<bp::OrderSide>(m, "OrderSide")
        .value("BUY", bp::OrderSide::BUY)
        .value("SELL", bp::OrderSide::SELL)
        .export_values();

    // Expose OrderType enum
    py::enum_<bp::OrderType>(m, "OrderType")
        .value("LIMIT", bp::OrderType::LIMIT)
        .value("MARKET", bp::OrderType::MARKET)
        // Add other order types if they exist and are needed
        .export_values();

    // Expose TimeInForce enum
    py::enum_<bp::TimeInForce>(m, "TimeInForce")
        .value("GTC", bp::TimeInForce::GTC)
        .value("IOC", bp::TimeInForce::IOC)
        .value("FOK", bp::TimeInForce::FOK)
        .export_values();

    // Expose OrderRequest struct
    py::class_<bp::OrderRequest>(m, "OrderRequest")
        .def(py::init<>())
        .def_readwrite("symbol", &bp::OrderRequest::symbol)
        .def_readwrite("side", &bp::OrderRequest::side)
        .def_readwrite("type", &bp::OrderRequest::type)
        .def_readwrite("quantity", &bp::OrderRequest::quantity)
        .def_readwrite("price", &bp::OrderRequest::price)
        .def_readwrite("time_in_force", &bp::OrderRequest::time_in_force)
        .def_readwrite("client_order_id", &bp::OrderRequest::client_order_id);
        // .def_readwrite("quote_quantity", &bp::OrderRequest::quote_quantity); // Removed, does not exist
        // Add other fields if present in your OrderRequest definition

    // Expose OrderFlags struct
    py::class_<bp::OrderFlags>(m, "OrderFlags")
        .def(py::init<>())
        .def_readwrite("post_only", &bp::OrderFlags::post_only)
        .def_readwrite("reduce_only", &bp::OrderFlags::reduce_only)
        .def_readwrite("auto_borrow", &bp::OrderFlags::auto_borrow)
        // self_trade_prevention would need its enum exposed too if used directly from Python
        ;

    // Expose ConditionalOrderParams struct
    py::class_<bp::ConditionalOrderParams>(m, "ConditionalOrderParams")
        .def(py::init<>())
        .def_readwrite("stop_loss_trigger_price", &bp::ConditionalOrderParams::stop_loss_trigger_price)
        .def_readwrite("take_profit_trigger_price", &bp::ConditionalOrderParams::take_profit_trigger_price)
        ;

    // Expose DefaultExecutionClient class
    py::class_<bp::DefaultExecutionClient> cl(m, "DefaultExecutionClient");

    cl.def(py::init<const std::string&, const std::string&, const std::string&, double, const std::string&>(),
           py::arg("api_key"),
           py::arg("base64_private_key"),
           py::arg("symbol"),
           py::arg("max_daily_drawdown_pct") = 0.02,
           py::arg("signal_file") = "signal.json",
           "Constructor for DefaultExecutionClient");

    // Bind methods
    cl.def("query_balances", &bp::DefaultExecutionClient::query_balances,
           "Queries and returns account balances.");

    // send_order(const OrderRequest& order, const OrderFlags& flags = OrderFlags(), const ConditionalOrderParams& cond_params = {});
    cl.def("send_order", &bp::DefaultExecutionClient::send_order,
        py::arg("order"),
        py::arg("flags") = bp::OrderFlags{},
        py::arg("cond_params") = bp::ConditionalOrderParams{},
        py::arg("model_id") = std::string(""),
        py::arg("associated_entry_price") = std::optional<double>{},
        "Sends an order with optional flags, conditional parameters, model_id, and associated entry price.");

    // send_market(const std::string& symbol, double quantity, bool is_buy, const OrderFlags& flags = OrderFlags(), const ConditionalOrderParams& cond_params = {});
    cl.def("send_market", &bp::DefaultExecutionClient::send_market,
        py::arg("symbol"),
        py::arg("quantity"),
        py::arg("is_buy"),
        py::arg("flags") = bp::OrderFlags{},
        py::arg("cond_params") = bp::ConditionalOrderParams{},
        py::arg("model_id") = std::string(""),
        py::arg("associated_entry_price") = std::optional<double>{},
        "Sends a market order with optional flags, conditional parameters, model_id, and associated entry price.");

    // send_limit(const std::string& symbol, double quantity, double price, bool is_buy, TimeInForce tif = TimeInForce::GTC, const OrderFlags& flags = OrderFlags(), const ConditionalOrderParams& cond_params = {});
    cl.def("send_limit", &bp::DefaultExecutionClient::send_limit,
        py::arg("symbol"),
        py::arg("quantity"),
        py::arg("price"),
        py::arg("is_buy"),
        py::arg("time_in_force") = bp::TimeInForce::GTC,
        py::arg("flags") = bp::OrderFlags{},
        py::arg("cond_params") = bp::ConditionalOrderParams{},
        py::arg("model_id") = std::string(""),
        py::arg("associated_entry_price") = std::optional<double>{},
        "Sends a limit order with optional flags, conditional parameters, model_id, and associated entry price.");

    // bool cancel_order(const std::string& symbol, const std::string& order_id);
    cl.def("cancel_order", &bp::DefaultExecutionClient::cancel_order,
        py::arg("symbol"),
        py::arg("order_id"),
        "Cancels a specific order by symbol and order ID.");

    // int cancel_all_orders(const std::string& symbol = "");
    cl.def("cancel_all_orders", &bp::DefaultExecutionClient::cancel_all_orders,
        py::arg("symbol") = "",
        "Cancels all open orders, optionally filtered by symbol.");

    // L1 data accessors
    cl.def("best_bid", &bp::DefaultExecutionClient::bestBid, "Get the current best bid price.");
    cl.def("best_ask", &bp::DefaultExecutionClient::bestAsk, "Get the current best ask price.");
    cl.def("mid", &bp::DefaultExecutionClient::mid, "Get the current mid price.");

    // Add other methods you need to expose
    // cl.def("get_open_orders", &bp::DefaultExecutionClient::get_open_orders, 
    //    py::arg("symbol"),
    //    "Get all open orders for a given symbol (or all if symbol is empty).");

    // Example: If you had a method in DefaultExecutionClient like:
    // std::vector<bp::Order> get_filled_orders(const std::string& symbol);
    // You would bind it as:
    // cl.def("get_filled_orders", &bp::DefaultExecutionClient::get_filled_orders, py::arg("symbol"));
} 
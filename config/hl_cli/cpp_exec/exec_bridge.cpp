#include <pybind11/pybind11.h>
#include <string>
#include <chrono>
#include <iostream>

namespace py = pybind11;

namespace bp {
    enum class Side { Bid, Ask };

    void send_market(const std::string& sym, double qty, Side side) {
        // TODO: replace with real backpack-cpp-sdk call
        auto now = std::chrono::system_clock::now().time_since_epoch();
        std::cout << "[MOCK] send_market " << sym << " qty=" << qty
                  << " side=" << (side==Side::Bid?"Bid":"Ask") << std::endl;
    }
}

PYBIND11_MODULE(exec_bridge, m) {
    py::enum_<bp::Side>(m, "Side")
        .value("Bid", bp::Side::Bid)
        .value("Ask", bp::Side::Ask);

    m.def("send_market", &bp::send_market,
          py::arg("symbol"), py::arg("quantity"), py::arg("side"));
}
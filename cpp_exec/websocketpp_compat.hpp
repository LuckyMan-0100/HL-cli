#pragma once

#include <memory>
#include <boost/asio.hpp>

namespace websocketpp {
namespace lib {
namespace asio {
    using io_service = boost::asio::io_context;
    using io_service_ptr = std::shared_ptr<io_service>;
    using strand = boost::asio::strand<boost::asio::io_context::executor_type>;
    using strand_ptr = std::shared_ptr<strand>;
} // namespace asio
} // namespace lib
} // namespace websocketpp 
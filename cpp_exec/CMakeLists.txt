cmake_minimum_required(VERSION 3.18)
project(cpp_exec CXX)

# Set C++ standard to C++20
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find required packages
# find_package(pybind11 REQUIRED) # Removed: No longer a Python module
find_package(Threads REQUIRED)
find_package(OpenSSL REQUIRED)
find_package(CURL REQUIRED)
# Boost needed by backpack_sdk (if it uses Asio)
find_package(Boost 1.71.0 REQUIRED COMPONENTS system thread) # Specify components if known
find_package(nlohmann_json 3.11.2 REQUIRED) # Already present
find_package(redis++ CONFIG REQUIRED) # Updated Redis++ package name
find_package(spdlog REQUIRED)

# Add Backpack SDK (Assuming it builds a library target like 'backpack_sdk')
# Ensure the SDK is compatible with C++20 or adjust build settings if needed
add_subdirectory(vendor/backpack-cpp-sdk)

# Create our library
add_library(cpp_exec STATIC
    exec_bridge.cpp
    redis_subscriber.cpp
    indicators.cpp
)

# Include directories
target_include_directories(cpp_exec PUBLIC 
    # ${PYBIND11_INCLUDE_DIRS} # Removed
    ${OPENSSL_INCLUDE_DIR}
    ${CURL_INCLUDE_DIRS}
    ${Boost_INCLUDE_DIRS}
    ${redis++_INCLUDE_DIRS} # Add redis++ include directory
    ${nlohmann_json_INCLUDE_DIRS} # Add nlohmann_json include dir if needed
    ${spdlog_INCLUDE_DIRS}
    vendor/backpack-cpp-sdk/include # Keep SDK include
    . # Include current directory for headers like exec_bridge.hpp
)

# Link libraries
target_link_libraries(cpp_exec PUBLIC 
    # pybind11::module # Removed
    Threads::Threads        # Link pthreads
    OpenSSL::SSL
    OpenSSL::Crypto
    CURL::libcurl
    Boost::system
    Boost::thread           # Link Boost thread
    nlohmann_json::nlohmann_json # Link nlohmann json
    redis++::redis++        # Link redis++
    spdlog::spdlog
    backpack_sdk            # Link the Backpack SDK library
)

# Set properties (Removed shared library specific properties)
# set_target_properties(exec_bridge PROPERTIES 
#     PREFIX ""
#     SUFFIX ".so"
#     CXX_STANDARD 17
#     CXX_STANDARD_REQUIRED ON
# )

# Add compiler flags if needed (e.g., for warnings or specific features)
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    # Keep existing flags or add new ones like -O2 for release
    target_compile_options(cpp_exec PRIVATE -Wno-deprecated-declarations)
    # Consider adding -Wall -Wextra for more warnings
    target_compile_options(cpp_exec PRIVATE -Wall -Wextra -Wpedantic)
endif()

# Optional: Add install rules if needed
# install(TARGETS exec_bridge DESTINATION bin)
cmake_minimum_required(VERSION 3.18)
project(exec_bridge)

# Set C++ standard
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find required packages
find_package(pybind11 REQUIRED)
find_package(OpenSSL REQUIRED)
find_package(CURL REQUIRED)
find_package(Boost 1.88.0 REQUIRED COMPONENTS system)
find_package(nlohmann_json 3.11.2 REQUIRED)

# Add Backpack SDK
add_subdirectory(vendor/backpack-cpp-sdk)

# Create our library
add_library(exec_bridge SHARED exec_bridge.cpp)

# Include directories
target_include_directories(exec_bridge PRIVATE 
    ${PYBIND11_INCLUDE_DIRS}
    ${OPENSSL_INCLUDE_DIR}
    ${CURL_INCLUDE_DIRS}
    vendor/backpack-cpp-sdk/include
)

# Link libraries
target_link_libraries(exec_bridge PRIVATE 
    pybind11::module
    backpack_sdk
)

# Set properties
set_target_properties(exec_bridge PROPERTIES 
    PREFIX ""
    SUFFIX ".so"
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
)

# Add compiler flags for modern Boost.Asio
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(exec_bridge PRIVATE -Wno-deprecated-declarations)
endif()
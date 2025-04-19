cmake_minimum_required(VERSION 3.18)
project(exec_bridge)

find_package(pybind11 REQUIRED)
add_library(exec_bridge SHARED exec_bridge.cpp)

# Backpack SDK headers + libs should be in system path or specify via -I / -L
target_include_directories(exec_bridge PRIVATE ${PYBIND11_INCLUDE_DIRS})
target_link_libraries(exec_bridge PRIVATE pybind11::module)
set_target_properties(exec_bridge PROPERTIES PREFIX "" SUFFIX ".so")
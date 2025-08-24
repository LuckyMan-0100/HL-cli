#!/bin/bash

# Clean potential stray CMake artifacts from source directories
rm -f CMakeCache.txt
rm -rf CMakeFiles
rm -f vendor/backpack-cpp-sdk/CMakeCache.txt
rm -rf vendor/backpack-cpp-sdk/CMakeFiles

# Clean build directory
rm -rf build
mkdir build
cd build

# Configure with CMake
cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_COMPILER=/usr/bin/c++ ..

# Build
make -j$(sysctl -n hw.ncpu) 
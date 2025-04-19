FROM python:3.10-slim

WORKDIR /app

# Install OS dependencies
# - build-essential & cmake for C++ extension compilation
# - ta-lib dependencies (check ta-lib docs for specifics on Debian/Ubuntu)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    wget \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install ta-lib C library
RUN wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz && \
    tar -xzf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib/ && \
    ./configure --prefix=/usr && \
    make && \
    make install && \
    cd .. && \
    rm -rf ta-lib ta-lib-0.4.0-src.tar.gz

# Copy dependency definition
COPY requirements.txt .

# Install Python dependencies
# We install pybind11 here so CMake can find it during build
RUN pip install --no-cache-dir -r requirements.txt

# Copy C++ source code and SDK
COPY cpp_exec/ cpp_exec/
# Ensure the backpack-cpp-sdk is available inside cpp_exec/vendor/
# If using git submodule, you'd need to initialize it before/during build

# Build C++ extension
RUN cd cpp_exec && \
    mkdir build && cd build && \
    cmake .. -DCMAKE_BUILD_TYPE=Release -DPYTHON_EXECUTABLE=$(which python) && \
    make && \
    # Ensure the output .so file is placed where the strategy module can find it
    cp src/_cpp_exec*.so /app/strategy/ && \
    cd /app && rm -rf cpp_exec/build

# Copy the rest of the application code
COPY . .

# Expose ports if necessary (e.g., for Airflow UI or custom API)
# EXPOSE 8080

# Set environment variables from .env file or build args if needed
# ARG BACKPACK_API_KEY
# ENV BACKPACK_API_KEY=${BACKPACK_API_KEY}
# ... (load other ENV vars)

# Default command (can be overridden)
CMD ["python", "-m", "strategy.main_loop"] 
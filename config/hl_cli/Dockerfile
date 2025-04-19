FROM python:3.11-slim

WORKDIR /app
COPY . /app

RUN apt-get update && apt-get install -y \
        build-essential cmake git && \
    pip install --no-cache-dir -r requirements.txt

RUN cmake -S cpp_exec -B cpp_exec/build && \
    cmake --build cpp_exec/build --config Release && \
    cp cpp_exec/build/libexec_bridge.so /usr/local/lib/

ENV PYTHONPATH=/app
CMD ["python", "-m", "strategy.strategy_loop"]
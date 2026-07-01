FROM ubuntu:24.04

ARG LLAMA_CPP_REF=master

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /opt

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        cmake \
        curl \
        g++ \
        git \
        libcurl4-openssl-dev \
        make \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/ggml-org/llama.cpp.git /opt/llama.cpp \
    && cd /opt/llama.cpp \
    && git checkout "${LLAMA_CPP_REF}" \
    && cmake -B build \
        -DGGML_RPC=ON \
        -DLLAMA_BUILD_TESTS=OFF \
        -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build --config Release --target llama-server -j"$(nproc)"

ENV LD_LIBRARY_PATH=/opt/llama.cpp/build/bin:/opt/llama.cpp/build/src:/opt/llama.cpp/build/ggml/src
EXPOSE 8080

ENTRYPOINT ["/bin/bash", "-lc"]
CMD ["/opt/llama.cpp/build/bin/llama-server --host 0.0.0.0 --port 8080 -m \"${MODEL_PATH}\" -ngl \"${N_GPU_LAYERS:-99}\" --ctx-size \"${CTX_SIZE:-8192}\" --rpc \"${RPC_ENDPOINTS}\""]

ARG OLLAMA_VERSION=v0.35.1
ARG LLAMACPP_COMMIT=836d57176dc699a726c55418e4f96b8ca628e1bf

FROM debian:bookworm-slim AS source
ARG OLLAMA_VERSION
ARG LLAMACPP_COMMIT
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git clone --branch "${OLLAMA_VERSION}" --depth 1 https://github.com/ollama/ollama.git .
COPY ollama-custom/ollama-b11381-num-ubatch.patch /tmp/ollama.patch
RUN git apply --unidiff-zero /tmp/ollama.patch \
    && printf '%s\n' "${LLAMACPP_COMMIT}" > LLAMA_CPP_VERSION

FROM golang:1.26-bookworm AS go-build
WORKDIR /src
COPY --from=source /src .
RUN --mount=type=cache,target=/go/pkg/mod go mod download
RUN --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=1 go build -trimpath -buildmode=pie \
        -ldflags='-w -s -X github.com/ollama/ollama/version.Version=0.35.1-custom-b11381' \
        -o /bin/ollama .

FROM ubuntu:24.04 AS llama-cpu
ARG CMAKE_VERSION=3.31.2
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl git libcurl4-openssl-dev ninja-build \
    && curl -fsSL "https://github.com/Kitware/CMake/releases/download/v${CMAKE_VERSION}/cmake-${CMAKE_VERSION}-linux-x86_64.tar.gz" \
        | tar xz -C /usr/local --strip-components 1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY --from=source /src .
RUN --mount=type=cache,target=/root/.cache/ccache \
    cmake -S llama/server --preset cpu \
    && cmake --build build/llama-server-cpu --parallel "$(nproc)" \
    && cmake --install build/llama-server-cpu --component llama-server --strip

FROM nvidia/cuda:13.0.2-devel-ubuntu24.04 AS llama-cuda
ARG CMAKE_VERSION=3.31.2
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl git libcurl4-openssl-dev ninja-build \
    && curl -fsSL "https://github.com/Kitware/CMake/releases/download/v${CMAKE_VERSION}/cmake-${CMAKE_VERSION}-linux-x86_64.tar.gz" \
        | tar xz -C /usr/local --strip-components 1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY --from=source /src .
RUN --mount=type=cache,target=/root/.cache/ccache \
    cmake -S llama/server --preset llama_cuda_v13_user_arch \
        -DCMAKE_CUDA_ARCHITECTURES=86 \
    && cmake --build build/llama-server-cuda_v13 --parallel "$(nproc)" \
    && cmake --install build/llama-server-cuda_v13 --component llama-server --strip

FROM ubuntu:24.04
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libopenblas0 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=go-build /bin/ollama /usr/bin/ollama
COPY --from=llama-cpu /src/dist/lib/ollama /usr/lib/ollama
COPY --from=llama-cuda /src/dist/lib/ollama /usr/lib/ollama
COPY --from=llama-cuda /usr/lib/x86_64-linux-gnu/libnccl.so.2* /usr/lib/ollama/cuda_v13/
ENV OLLAMA_HOST=0.0.0.0:11434
ENV LD_LIBRARY_PATH=/usr/local/nvidia/lib:/usr/local/nvidia/lib64
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility
ENV NVIDIA_VISIBLE_DEVICES=all
EXPOSE 11434
ENTRYPOINT ["/usr/bin/ollama"]
CMD ["serve"]

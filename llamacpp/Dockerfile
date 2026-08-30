# llama.cpp build para GLM-5-Next (GLM-5.3-Flash) desde el PR ggml-org/llama.cpp#27754
# Fork/rama: unslothai/llama.cpp @ glm5next/upstream
#
# Target: 4x RTX 3090 (Ampere, sm_86), driver 595.71.05 en octoserver.
# CUDA 12.6 devel es compatible con ese driver. Ampere -> CUDA_ARCH 86.

ARG CUDA_VERSION=12.6.3
ARG UBUNTU_VERSION=24.04

FROM nvidia/cuda:${CUDA_VERSION}-devel-ubuntu${UBUNTU_VERSION} AS build

ARG LLAMACPP_REPO=https://github.com/unslothai/llama.cpp
ARG LLAMACPP_REF=glm5next/upstream
# Fijar el commit del PR para builds reproducibles.
ARG LLAMACPP_COMMIT=2e0e57f1008053bae4902a772da85e3eb99d4aff
# Ampere (RTX 3090) = 86.
ARG CUDA_ARCH=86

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        git cmake ninja-build build-essential \
        libcurl4-openssl-dev ca-certificates pkg-config \
    && rm -rf /var/lib/apt/lists/*

# El stub del Driver API vive en .../stubs/libcuda.so con SONAME libcuda.so.1,
# pero el archivo libcuda.so.1 no existe ahi, y el linker de este PR lo pide por
# ese nombre. Se crea el symlink para que ld resuelva cuMem*/cuDevice* al stub.
# En runtime el driver real del host provee el libcuda.so.1 verdadero.
ENV CUDA_STUBS=/usr/local/cuda/lib64/stubs
RUN ln -sf "${CUDA_STUBS}/libcuda.so" "${CUDA_STUBS}/libcuda.so.1"

WORKDIR /src
RUN git clone --recurse-submodules "${LLAMACPP_REPO}" llama.cpp \
    && cd llama.cpp \
    && git fetch origin "${LLAMACPP_REF}" \
    && git checkout "${LLAMACPP_COMMIT}" \
    && git submodule update --init --recursive

WORKDIR /src/llama.cpp
RUN cmake -B build -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DGGML_CUDA=ON \
        -DCMAKE_CUDA_ARCHITECTURES=${CUDA_ARCH} \
        -DGGML_NATIVE=OFF \
        -DLLAMA_CURL=ON \
        -DLLAMA_BUILD_TESTS=OFF \
        -DLLAMA_BUILD_EXAMPLES=OFF \
        -DLLAMA_BUILD_SERVER=ON \
        -DCMAKE_EXE_LINKER_FLAGS="-L${CUDA_STUBS} -Wl,-rpath-link,${CUDA_STUBS}" \
        -DCMAKE_SHARED_LINKER_FLAGS="-L${CUDA_STUBS} -Wl,-rpath-link,${CUDA_STUBS}" \
    && cmake --build build --config Release -j "$(nproc)" \
    && cmake --install build --prefix /opt/llama.cpp

# ---- runtime ----
FROM nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu${UBUNTU_VERSION} AS runtime

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        libcurl4-openssl-dev libgomp1 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /opt/llama.cpp /opt/llama.cpp
COPY entrypoint-kv-cache.sh /opt/llama.cpp/entrypoint.sh
RUN chmod +x /opt/llama.cpp/entrypoint.sh
ENV PATH=/opt/llama.cpp/bin:${PATH}
ENV LD_LIBRARY_PATH=/opt/llama.cpp/lib:${LD_LIBRARY_PATH}

# Flags de correccion obligatorios para GLM-5-Next (ver descripcion del PR):
#  - NVIDIA_TF32_OVERRIDE=0: evita que los GEMM fp32 corran a 10 bits de mantisa.
#  - el -fa off se pasa en el comando del server (flash-attn castea el latente MLA a F16).
ENV NVIDIA_TF32_OVERRIDE=0
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility

EXPOSE 8080
ENTRYPOINT ["/opt/llama.cpp/entrypoint.sh"]

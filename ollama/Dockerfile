FROM golang:1.26-bookworm AS build

ARG OLLAMA_VERSION=v0.32.13
WORKDIR /src

RUN apt-get update \
    && apt-get install -y --no-install-recommends patch \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL "https://github.com/ollama/ollama/archive/refs/tags/${OLLAMA_VERSION}.tar.gz" \
    | tar xz --strip-components=1
COPY scheduler-vram-headroom.patch /tmp/scheduler-vram-headroom.patch
RUN patch -p1 < /tmp/scheduler-vram-headroom.patch
RUN CGO_ENABLED=1 go build -trimpath -buildmode=pie \
    -ldflags="-w -s -X github.com/ollama/ollama/version.Version=${OLLAMA_VERSION#v}" \
    -o /out/ollama .

FROM ubuntu:24.04

ARG OLLAMA_VERSION=v0.32.13
ARG OLLAMA_LINUX_AMD64_SHA256=0fd1dece38a1c6242e8013ce20b597345c5de072ae6b320160edb0e729ef1de1
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl libopenblas0 libvulkan1 zstd \
    && curl -fsSL \
        "https://github.com/ollama/ollama/releases/download/${OLLAMA_VERSION}/ollama-linux-amd64.tar.zst" \
        -o /tmp/ollama-linux-amd64.tar.zst \
    && echo "${OLLAMA_LINUX_AMD64_SHA256}  /tmp/ollama-linux-amd64.tar.zst" | sha256sum -c - \
    && tar --zstd -xf /tmp/ollama-linux-amd64.tar.zst -C /usr \
    && rm -f /tmp/ollama-linux-amd64.tar.zst \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /out/ollama /usr/bin/ollama

ENV LD_LIBRARY_PATH=/usr/local/nvidia/lib:/usr/local/nvidia/lib64
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility
ENV NVIDIA_VISIBLE_DEVICES=all
ENV OLLAMA_HOST=0.0.0.0:11434
EXPOSE 11434
ENTRYPOINT ["/usr/bin/ollama"]
CMD ["serve"]

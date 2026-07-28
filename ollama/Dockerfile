FROM golang:1.26-bookworm AS build

ARG OLLAMA_VERSION=v0.32.5
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

FROM ollama/ollama:0.32.5

COPY --from=build /out/ollama /usr/bin/ollama

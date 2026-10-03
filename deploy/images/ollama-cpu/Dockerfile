# Ollama for CPU-only boxes: the official release without its GPU libraries.
# The official image is 9.4 GB, mostly CUDA; the edge box has no GPU.
FROM debian:bookworm-slim AS fetch
ARG OLLAMA_VERSION=v0.35.1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl zstd \
    && mkdir -p /opt/ollama \
    && curl -fsSL "https://github.com/ollama/ollama/releases/download/${OLLAMA_VERSION}/ollama-linux-amd64.tar.zst" \
       | zstd -d | tar -x -C /opt/ollama \
    && find /opt/ollama/lib/ollama -mindepth 1 -maxdepth 1 -type d \
       \( -iname '*cuda*' -o -iname '*rocm*' -o -iname '*vulkan*' -o -iname '*mlx*' \) -exec rm -rf {} + \
    && du -sh /opt/ollama

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=fetch /opt/ollama /usr
ENV OLLAMA_HOST=0.0.0.0:11434
EXPOSE 11434
ENTRYPOINT ["/usr/bin/ollama"]
CMD ["serve"]

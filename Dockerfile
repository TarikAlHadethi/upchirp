# Upchirp app image: Python services plus the built UI. Multi-arch (the demo server is ARM).

FROM node:20-slim AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install ".[agent,platform]"
COPY docs/ docs/
COPY --from=ui /ui/dist ui/dist
COPY deploy/demo/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && useradd --create-home upchirp && mkdir -p /data \
    && chown upchirp /data
USER upchirp
ENV UPCHIRP_DATA_DIR=/data UPCHIRP_DOCS_DIR=/app/docs UPCHIRP_UI_DIST=/app/ui/dist
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]

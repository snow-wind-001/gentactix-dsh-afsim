ARG NODE_IMAGE=node:22-bookworm-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d
ARG PYTHON_IMAGE=python:3.11-slim-bookworm@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39
FROM ${NODE_IMAGE} AS frontend
ENV ELECTRON_SKIP_BINARY_DOWNLOAD=1
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/src ./src
COPY frontend/public ./public
COPY frontend/index.html frontend/tsconfig*.json frontend/vite.config.ts ./
COPY docker/container-config.js ./public/container-config.js
COPY gentactix/military_symbols.json gentactix/unit_types.json /gentactix/
ARG APP_VERSION=3.7.6-beta.1
RUN node -e "const f=require('fs');const p=JSON.parse(f.readFileSync('package.json'));p.version=process.env.APP_VERSION;f.writeFileSync('package.json',JSON.stringify(p));"
RUN node -e "const f=require('fs');const p='index.html';const s=f.readFileSync(p,'utf8');f.writeFileSync(p,s.replace('<div id=\"app\"></div>','<div id=\"app\"></div><script src=\"./container-config.js\"></script>'));" \
    && npm run typecheck && npm run build

FROM ${PYTHON_IMAGE} AS core
ARG APP_VERSION=3.7.6-beta.1
ARG SOURCE_REVISION=unknown
LABEL org.opencontainers.image.title="GenTactix DSH teaching workbench" \
      org.opencontainers.image.source="https://github.com/snow-wind-001/gentactix-dsh-afsim" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.licenses="MIT"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 GENTACTIX_PROJECT_ROOT=/app \
    GENTACTIX_SESSION_DIR=/data/sessions GENTACTIX_TRACE_DIR=/data/trajectories \
    GENTACTIX_ROLE_INDEX=/data/roles.json GENTACTIX_DSH_HOME=/data/dsh-home \
    GENTACTIX_DSH_WORKSPACE=/data/dsh-workspace GENTACTIX_LLM_CONFIG=/data/config/llm.enc \
    GENTACTIX_VAULT_KEY_FILE=/data/config/vault.key XDG_CACHE_HOME=/data/cache \
    XDG_CONFIG_HOME=/data/config GENTACTIX_LLM_MAX_TOKENS=65536 \
    GENTACTIX_CONTEXT_WINDOW=262144 GENTACTIX_MAX_RUNTIME_STEPS=32 \
    GENTACTIX_REQUEST_TIMEOUT_SECONDS=1800
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates libstdc++6 nginx-light tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin gentactix
WORKDIR /app
COPY docker/requirements.txt docker/sdk-wheels.json docker/fetch_sdk.py ./docker/
RUN --mount=type=bind,source=docker/wheels,target=/wheels,readonly \
    python docker/fetch_sdk.py --directory /wheels --verify-only \
    && pip install --no-cache-dir --find-links=/wheels -r docker/requirements.txt && pip check
COPY backend ./backend
COPY gentactix ./gentactix
COPY corpus ./corpus
COPY adjudication ./adjudication
COPY data ./data
COPY plugins ./plugins
COPY tools ./tools
COPY vendor ./vendor
COPY LICENSE NOTICE.md ./
COPY docker/container-config.js docker/entrypoint.py docker/healthcheck.py docker/nginx.conf ./docker/
COPY docker/licenses ./docker/licenses
COPY --from=frontend /build/dist ./frontend-dist
RUN mkdir -p /data/cache /data/config /data/sessions /data/trajectories /data/dsh-home \
    /data/dsh-workspace /data/afsim/state /data/afsim/workspace /data/afsim/wineprefix \
    vendor/afsim/local/afsim/runtime/afsim-2.9.0-win64 \
    && ln -s /data/cache /app/.cache \
    && ln -s /data/cache /home/gentactix/.cache \
    && ln -s /data/afsim/state vendor/afsim/local/afsim/state \
    && ln -s /data/afsim/workspace vendor/afsim/local/afsim/workspace \
    && ln -s /data/afsim/wineprefix vendor/afsim/local/afsim/wineprefix \
    && chmod 700 /data/cache /data/config /data/dsh-home /data/dsh-workspace \
    && chown -R 10001:10001 /data /home/gentactix
ENV TMPDIR=/data/cache
USER 10001:10001
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=8s --start-period=45s --retries=3 CMD ["python", "/app/docker/healthcheck.py"]
ENTRYPOINT ["tini", "-g", "--", "python", "/app/docker/entrypoint.py"]

# Self-contained authorized teaching runtime. AFSIM retains its original notices.
# The runtime directory is private build input, never committed to Git.
FROM core AS afsim
LABEL org.opencontainers.image.licenses="MIT AND LicenseRef-AFSIM-authorized-distribution"
USER root
COPY --chown=0:0 afsim-runtime/ /app/vendor/afsim/local/afsim/runtime/afsim-2.9.0-win64/
RUN apt-get update && apt-get install -y --no-install-recommends wine64 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /app/vendor/afsim/local/afsim/compat/usr/lib/wine \
      /app/vendor/afsim/local/afsim/compat/usr/lib/x86_64-linux-gnu/wine \
    && ln -s /usr/lib/wine/wine64 /app/vendor/afsim/local/afsim/compat/usr/lib/wine/wine64 \
    && ln -s /usr/lib/x86_64-linux-gnu/wine/x86_64-unix /app/vendor/afsim/local/afsim/compat/usr/lib/x86_64-linux-gnu/wine/x86_64-unix \
    && ln -s /usr/lib/x86_64-linux-gnu/wine/x86_64-windows /app/vendor/afsim/local/afsim/compat/usr/lib/x86_64-linux-gnu/wine/x86_64-windows \
    && ln -s /usr/lib/x86_64-linux-gnu/wine/x86_64-windows/zlib1.dll /app/vendor/afsim/local/afsim/compat/usr/lib/x86_64-linux-gnu/zlib1.dll
# Preserve original runtime and third-party license notices at their source paths.
COPY --chown=0:0 afsim-notices/ /app/vendor/afsim/local/afsim/runtime/afsim-2.9.0-win64/
USER 10001:10001

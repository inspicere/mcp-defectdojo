FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy project files
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/ ./src/

# Install dependencies, then remove all caches before switching to non-root
RUN uv sync --frozen --no-dev && rm -rf /tmp/uv-cache /root/.cache/uv

RUN adduser --disabled-password --gecos "" --no-create-home appuser
USER appuser

# Disable uv cache at runtime — deps already installed
ENV UV_NO_CACHE=1

EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)"]

ENTRYPOINT ["uv", "run", "--no-sync", "mcp-defectdojo"]

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy project files
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

# Install dependencies, then remove all caches before switching to non-root
RUN uv sync --frozen --no-dev && rm -rf /tmp/uv-cache /root/.cache/uv

RUN adduser --disabled-password --gecos "" --no-create-home appuser
USER appuser

# Disable uv cache at runtime — deps already installed
ENV UV_NO_CACHE=1

# Set entrypoint (--no-sync: deps already installed during build)
ENTRYPOINT ["uv", "run", "--no-sync", "mcp-defectdojo"]

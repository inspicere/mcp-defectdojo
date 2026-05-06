FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Disable cache for cleaner images in CI/CD environments
ENV UV_CACHE_DIR=/tmp/uv-cache

# Copy project files
COPY pyproject.toml uv.lock ./
COPY src/ ./src/

# Install dependencies and the project
RUN uv sync --frozen --no-dev

RUN adduser --disabled-password --gecos "" --no-create-home appuser
USER appuser

# Set entrypoint
ENTRYPOINT ["uv", "run", "mcp-defectdojo"]

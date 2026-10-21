
FROM python:3.13-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=1999 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

# Working directory
WORKDIR /app

# Copy dependency definitions first for caching
COPY pyproject.toml uv.lock ./

# Install production dependencies only
RUN uv sync --locked --no-dev --no-install-project

# Copy application code
COPY ./backend ./

# Create directories and non-root user
RUN useradd -m appuser && \
    mkdir -p /app/results && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose Flask port
EXPOSE $PORT

# Run the application
CMD ["python", "app.py"]

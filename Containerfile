# Stage 1: Build Python dependencies
# Set the base image using Python 3.13 and Debian Bookworm
FROM python:3.13-slim-bookworm  as builder

WORKDIR /app

# Install system dependencies (required for some Python packages)
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Create and activate virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY pyproject.toml .
COPY Readme.md .
COPY LICENSE .
COPY src/ ./src/
RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir .  # Installs your project in editable mode

# Stage 2: Runtime image
FROM python:3.13-slim-bookworm

WORKDIR /app

# Copy virtual env from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Run as non-root user
# Create user and prepare config directory
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app && \
    chmod -R 755 /app

USER appuser

# Run the app
CMD ["start-modbus-service"]

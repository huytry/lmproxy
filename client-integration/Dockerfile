# Dockerfile for LMArenaBridge Client with Platform Integration
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 lmarena && \
    chown -R lmarena:lmarena /app

# Copy requirements first for better caching
COPY requirements.txt requirements_platform.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -r requirements_platform.txt

# Clone LMArenaBridge repository
RUN git clone https://github.com/Lianues/LMArenaBridge.git /tmp/lmarena && \
    cp -r /tmp/lmarena/* /app/ && \
    rm -rf /tmp/lmarena

# Copy platform integration files
COPY lmarena_platform_integration.py ./
COPY config.jsonc ./

# Create necessary directories
RUN mkdir -p /app/data /app/logs /app/storage && \
    chown -R lmarena:lmarena /app

# Switch to non-root user
USER lmarena

# Expose ports
EXPOSE 5102 5103

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5102/health || exit 1

# Default command
CMD ["python", "api_server.py"]

# AlphaCopilot Server Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY apps/alphacopilot-server/requirements.txt /app/apps/alphacopilot-server/
RUN pip install --no-cache-dir -r /app/apps/alphacopilot-server/requirements.txt

# Copy shared modules
COPY shared/ /app/shared/

# Copy quant-stream (symlinked in dev, copied in docker)
COPY quant-stream/ /app/quant-stream/

# Install quant-stream
RUN pip install -e /app/quant-stream

# Copy alphacopilot-server
COPY apps/alphacopilot-server/ /app/apps/alphacopilot-server/

# Create data directory for market data
RUN mkdir -p /app/data

# Set Python path
ENV PYTHONPATH=/app:/app/shared/py:/app/quant-stream

# Expose port
EXPOSE 8069

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8069/health || exit 1

# Run server
CMD ["python", "-m", "uvicorn", "apps.alphacopilot-server.main:app", "--host", "0.0.0.0", "--port", "8069"]




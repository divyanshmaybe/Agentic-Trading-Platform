# AlphaCopilot Server Dockerfile
# Build from monorepo root: docker build -f apps/alphacopilot-server/Dockerfile -t alphacopilot_server .

FROM python:3.11-slim AS builder

WORKDIR /app

# Install system dependencies for building
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY apps/alphacopilot-server/requirements.txt /app/requirements.alphacopilot.txt
COPY quant-stream/requirements.txt /app/requirements.quantstream.txt

# Filter out editable installs from quant-stream requirements (they'll be installed later)
RUN grep -v "^-e" /app/requirements.quantstream.txt > /app/requirements.quantstream.filtered.txt || true

# Install Python dependencies (excluding editable installs)
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.alphacopilot.txt \
    && pip install --no-cache-dir -r /app/requirements.quantstream.filtered.txt

# Copy only necessary source code (not data files - those are mounted as volumes)
COPY shared/py /app/shared/py
COPY quant-stream/alphacopilot /app/quant-stream/alphacopilot
COPY quant-stream/quant_stream /app/quant-stream/quant_stream
COPY quant-stream/pyproject.toml /app/quant-stream/pyproject.toml
COPY apps/alphacopilot-server /app/apps/alphacopilot-server

# Copy Prisma schema, generate Python client, and fetch binaries
COPY apps/portfolio-server/prisma /app/apps/portfolio-server/prisma
RUN cd /app/apps/portfolio-server && prisma generate && prisma py fetch

# Install quant-stream as editable (this installs the local package)
RUN pip install -e /app/quant-stream

# Runtime stage
FROM python:3.11-slim AS runtime

WORKDIR /app

# Install runtime dependencies only
# libgomp1 is needed for LightGBM and other ML libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy Prisma binaries from builder
COPY --from=builder /root/.cache/prisma-python /root/.cache/prisma-python

# Copy application code
COPY --from=builder /app /app

# Create data directory (will be mounted as volume)
RUN mkdir -p /app/data /app/quant-stream/.data

# Set Python path
ENV PYTHONPATH=/app:/app/shared/py:/app/quant-stream:/app/apps/alphacopilot-server
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8069

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8069/health || exit 1

# Set working directory to alphacopilot-server
WORKDIR /app/apps/alphacopilot-server

# Run server
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8069"]




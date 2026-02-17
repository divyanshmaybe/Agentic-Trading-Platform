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

# Filter out editable installs and torch from quant-stream requirements
# We'll install CPU-only torch separately
RUN grep -v "^-e" /app/requirements.quantstream.txt | grep -v "^torch" | grep -v "^torchvision" > /app/requirements.quantstream.filtered.txt || true
RUN grep -v "^torch" /app/requirements.alphacopilot.txt > /app/requirements.alphacopilot.filtered.txt || true

# Install CPU-only PyTorch first (saves ~6GB vs GPU version)
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r /app/requirements.alphacopilot.filtered.txt \
    && pip install --no-cache-dir -r /app/requirements.quantstream.filtered.txt

# Remove unnecessary GPU-related packages that may have been pulled as dependencies
RUN pip uninstall -y nvidia-cublas-cu12 nvidia-cuda-cupti-cu12 nvidia-cuda-nvrtc-cu12 \
    nvidia-cuda-runtime-cu12 nvidia-cudnn-cu12 nvidia-cufft-cu12 nvidia-curand-cu12 \
    nvidia-cusolver-cu12 nvidia-cusparse-cu12 nvidia-nccl-cu12 nvidia-nvtx-cu12 \
    nvidia-nvjitlink-cu12 triton cusparselt 2>/dev/null || true \
    && rm -rf /root/.cache/pip

# Copy only necessary source code (not data files - those are mounted as volumes)
COPY shared/py /app/shared/py
COPY middleware/py /app/middleware/py
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

# Copy installed packages from builder (excluding GPU libs which were already removed)
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Final cleanup of any remaining GPU packages in runtime
RUN pip uninstall -y nvidia-cublas-cu12 nvidia-cuda-cupti-cu12 nvidia-cuda-nvrtc-cu12 \
    nvidia-cuda-runtime-cu12 nvidia-cudnn-cu12 nvidia-cufft-cu12 nvidia-curand-cu12 \
    nvidia-cusolver-cu12 nvidia-cusparse-cu12 nvidia-nccl-cu12 nvidia-nvtx-cu12 \
    nvidia-nvjitlink-cu12 triton cusparselt 2>/dev/null || true \
    && rm -rf /usr/local/lib/python3.11/site-packages/nvidia* \
    && rm -rf /usr/local/lib/python3.11/site-packages/triton* \
    && rm -rf /usr/local/lib/python3.11/site-packages/cusparselt* \
    && rm -rf /root/.cache/pip

# Copy Prisma binaries from builder
COPY --from=builder /root/.cache/prisma-python /root/.cache/prisma-python

# Copy application code
COPY --from=builder /app /app

# Create data directory (will be mounted as volume)
RUN mkdir -p /app/data /app/quant-stream/.data

# Set Python path
ENV PYTHONPATH=/app:/app/shared/py:/app/middleware/py:/app/quant-stream:/app/apps/alphacopilot-server
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




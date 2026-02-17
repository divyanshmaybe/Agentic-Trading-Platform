ARG PYTHON_VERSION=3.11-slim

FROM python:${PYTHON_VERSION} AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:${PATH}"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    libffi-dev \
    libssl-dev \
    libblas-dev \
    liblapack-dev \
    gfortran \
    pkg-config \
    git \
    curl \
    bash \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv

COPY apps/portfolio-server/requirements.txt /tmp/requirements.portfolio.txt
COPY shared/py/requirements.txt /tmp/requirements.shared.txt
COPY quant-stream/requirements.txt /tmp/requirements.quantstream.txt

# Filter out torch and editable installs from requirements (we'll install CPU-only version)
RUN grep -v "^torch" /tmp/requirements.portfolio.txt | grep -v "^-e" > /tmp/requirements.portfolio.filtered.txt || cp /tmp/requirements.portfolio.txt /tmp/requirements.portfolio.filtered.txt
RUN grep -v "^torch" /tmp/requirements.shared.txt | grep -v "^-e" > /tmp/requirements.shared.filtered.txt || cp /tmp/requirements.shared.txt /tmp/requirements.shared.filtered.txt
RUN grep -v "^torch" /tmp/requirements.quantstream.txt | grep -v "^-e" > /tmp/requirements.quantstream.filtered.txt || true

# Install CPU-only PyTorch first (saves ~5GB vs GPU version)
RUN pip install --upgrade pip \
    && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r /tmp/requirements.portfolio.filtered.txt \
    && pip install --no-cache-dir -r /tmp/requirements.shared.filtered.txt \
    && pip install --no-cache-dir -r /tmp/requirements.quantstream.filtered.txt || true

# Remove unnecessary GPU-related packages that may have been pulled as dependencies
RUN pip uninstall -y nvidia-cublas-cu12 nvidia-cuda-cupti-cu12 nvidia-cuda-nvrtc-cu12 \
    nvidia-cuda-runtime-cu12 nvidia-cudnn-cu12 nvidia-cufft-cu12 nvidia-curand-cu12 \
    nvidia-cusolver-cu12 nvidia-cusparse-cu12 nvidia-nccl-cu12 nvidia-nvtx-cu12 \
    nvidia-nvjitlink-cu12 triton cusparselt 2>/dev/null || true \
    && rm -rf /root/.cache/pip

# Copy shared libs and application source
COPY shared/py /app/shared/py
COPY middleware /app/middleware
COPY apps/portfolio-server /app/apps/portfolio-server

# Copy quant-stream for factor calculation in Celery workers
COPY quant-stream/quant_stream /app/quant-stream/quant_stream
COPY quant-stream/alphacopilot /app/quant-stream/alphacopilot
COPY quant-stream/pyproject.toml /app/quant-stream/pyproject.toml
COPY quant-stream/update_indian_market_data.py /app/quant-stream/update_indian_market_data.py
COPY quant-stream/.data/indian_stock_market_nifty500.csv /app/quant-stream/.data/indian_stock_market_nifty500.csv

# Install quant-stream as editable package
RUN pip install -e /app/quant-stream

WORKDIR /app/apps/portfolio-server

RUN python -m prisma generate

FROM python:${PYTHON_VERSION} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH="/app:/app/apps/portfolio-server:/app/shared/py:/app/middleware:/app/middleware/py:/app/quant-stream" \
    PORT=8000 \
    DATABASE_URL="postgresql://auth_user:auth_password@postgres:5432/auth_db"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libffi8 \
    libssl3 \
    libblas3 \
    liblapack3 \
    libgfortran5 \
    libatomic1 \
    libgcc-s1 \
    libstdc++6 \
    libc6 \
    libgomp1 \
    git \
    curl \
    bash \
    ca-certificates \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/shared /app/shared
COPY --from=builder /app/middleware /app/middleware
COPY --from=builder /app/apps/portfolio-server /app/apps/portfolio-server
COPY --from=builder /app/quant-stream /app/quant-stream

# Final cleanup of any remaining GPU packages in runtime
RUN rm -rf /opt/venv/lib/python3.11/site-packages/nvidia* \
    && rm -rf /opt/venv/lib/python3.11/site-packages/triton* \
    && rm -rf /opt/venv/lib/python3.11/site-packages/cusparselt*

WORKDIR /app/apps/portfolio-server

# Fetch Prisma query engine binaries so the app can start without needing
# network access or additional manual steps.
RUN python -m prisma py fetch

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

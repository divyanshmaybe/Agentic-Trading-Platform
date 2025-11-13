FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/root/.local/bin:${PATH}"

WORKDIR /app

# System dependencies for scientific Python stack and Celery
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    libffi-dev \
    libssl-dev \
    libblas-dev \
    liblapack-dev \
    libatlas-base-dev \
    gfortran \
    pkg-config \
    git \
    curl \
    bash \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY apps/portfolio-server/requirements.txt /tmp/requirements.portfolio.txt
COPY shared/py/requirements.txt /tmp/requirements.shared.txt

RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements.portfolio.txt \
    && pip install --no-cache-dir -r /tmp/requirements.shared.txt

# Copy application source
COPY shared/py /app/shared/py
COPY middleware/py /app/middleware/py
COPY apps/portfolio-server /app/apps/portfolio-server

# Environment setup
ENV PYTHONPATH="/app/apps/portfolio-server:/app/shared/py:/app/middleware/py"
ENV DATABASE_URL="postgresql://auth_user:auth_password@postgres:5432/auth_db"

WORKDIR /app/apps/portfolio-server

# Generate Prisma client at build time to speed up container startup
RUN python -m prisma generate

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libblas-dev \
    liblapack-dev \
    libgfortran5 \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY apps/portfolio-server/requirements.txt ./apps/portfolio-server/requirements.txt

RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r apps/portfolio-server/requirements.txt

COPY shared/py ./shared/py
COPY middleware/py ./middleware/py
COPY apps/portfolio-server ./apps/portfolio-server

ENV PYTHONPATH=/app:/app/apps/portfolio-server:/app/shared/py:/app/middleware/py

WORKDIR /app/apps/portfolio-server

RUN prisma generate

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]


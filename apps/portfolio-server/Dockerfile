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

RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements.portfolio.txt \
    && pip install --no-cache-dir -r /tmp/requirements.shared.txt

# Copy only Python directories and create package structure
COPY shared/py /app/shared/py
COPY middleware/py /app/middleware/py
COPY apps/portfolio-server /app/apps/portfolio-server

# Create __init__.py files for package imports
RUN mkdir -p /app/shared /app/middleware && \
    touch /app/shared/__init__.py /app/middleware/__init__.py

WORKDIR /app/apps/portfolio-server

RUN python -m prisma generate

FROM python:${PYTHON_VERSION} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH="/app:/app/apps/portfolio-server:/app/shared/py:/app/middleware/py" \
    PORT=8000 \
    DATABASE_URL="postgresql://auth_user:auth_password@postgres:5432/auth_db"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libffi8 \
    libssl3 \
    libblas3 \
    liblapack3 \
    libgfortran5 \
    git \
    curl \
    bash \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/shared /app/shared
COPY --from=builder /app/middleware /app/middleware
COPY --from=builder /app/apps/portfolio-server /app/apps/portfolio-server

WORKDIR /app/apps/portfolio-server

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

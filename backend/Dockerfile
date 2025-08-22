FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps (build tools kept minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

# ---- Dependencies layer (cache-friendly) ----
# If you keep requirements.txt pinned, this layer will cache well.
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip \
 && pip install -r /app/requirements.txt

# ---- App code ----
COPY . /app

# Uvicorn on 8000 (matches frontend config)
EXPOSE 8000

# Health: prefer explicit module path
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]

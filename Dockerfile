# Builder stage
FROM python:3.11-slim-bookworm as builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    libpq-dev \
    libffi-dev \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    libjpeg-dev \
    libssl-dev \
    python3-dev \
    gettext \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels whitenoise==6.6.0


# Final stage
FROM python:3.11-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gettext \
    netcat-openbsd \
    ffmpeg \
    libglib2.0-0 \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/wheels /wheels
COPY --from=builder /app/requirements.txt .

RUN pip install --no-cache /wheels/*

COPY . .

# Cleanup
RUN find /app -name "*.pyc" -delete \
 && find /app -name "__pycache__" -delete

# Convert entrypoint to unix style just in case of Windows usage
RUN sed -i 's/\r$//' /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["sh", "/app/entrypoint.sh"]
CMD ["gunicorn", "src.wsgi:application", "--bind", "0.0.0.0:8000"]


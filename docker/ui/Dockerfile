FROM python:3.13-slim

WORKDIR /app

# Install only what we need
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 appuser

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY scanner/ scanner/
COPY ui/app/ ui/app/

# Change ownership
RUN chown -R appuser:appuser /app

USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8080), timeout=2).close()" || exit 1

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "ui.app.main:app", "--host", "0.0.0.0", "--port", "8080"]

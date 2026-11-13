FROM python:3.13-slim

WORKDIR /app

# Create non-root user
RUN useradd -m -u 1000 appuser

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application (root-owned, read-only to appuser)
COPY llm_client/ llm_client/

USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=5)" || exit 1

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "--factory", "llm_client.app:create_app_from_env", "--host", "0.0.0.0", "--port", "8000"]

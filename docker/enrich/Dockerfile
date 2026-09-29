FROM python:3.13-slim

WORKDIR /app

# Non-root user
RUN useradd -m -u 1000 appuser

# Environment setup
ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY scanner/ ./scanner/
COPY enrich.py conclude.py final_report.py graph_sync.py ./
COPY config/ ./config/

# Permissions
RUN chown -R appuser:appuser /app
USER appuser

ENTRYPOINT ["python", "enrich.py"]

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
COPY portfolio.py .

# Permissions
RUN chown -R appuser:appuser /app
USER appuser

ENTRYPOINT ["python", "portfolio.py"]

FROM python:3.13-slim

WORKDIR /app

# Non-root user
RUN useradd -m -u 1000 appuser

# Environment setup
ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    USE_TF=0 \
    LAYA_PRELOAD=1 \
    LAYA_DEVICE=cpu

# Install CPU-only torch and Laya with serve backend
RUN pip install --no-cache-dir \
    torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir "laya[serve]>=0.3.21"

# Laya weights cache
RUN mkdir -p /root/.cache/huggingface && \
    chown -R appuser:appuser /root/.cache

# Permissions
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()" || exit 1

ENTRYPOINT ["laya-serve"]

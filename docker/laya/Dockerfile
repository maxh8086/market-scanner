FROM python:3.13-slim

WORKDIR /app
RUN useradd -m -u 1000 appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    USE_TF=0 \
    LAYA_PRELOAD=1 \
    LAYA_DEVICE=cpu \
    HF_HOME=/home/appuser/.cache/huggingface

# CPU-only torch first, so laya's torch requirement is already satisfied and
# pip does not pull the multi-GB CUDA build from PyPI.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir "laya[serve]>=0.3.21"

# Weights (~808 MB English) are NOT baked in: they download on first start into
# this cache, which compose mounts as a named volume so it happens once. The
# directory is created here, owned by appuser, so the volume inherits that.
RUN mkdir -p /home/appuser/.cache/huggingface && \
    chown -R appuser:appuser /home/appuser/.cache
USER appuser

EXPOSE 8000

# start-period covers the first-run weight download.
HEALTHCHECK --interval=10s --timeout=5s --start-period=600s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()" || exit 1

ENTRYPOINT ["laya-serve"]

# enrich with the TimesFM forecaster: `enrich.py --report --timesfm`.
# Separate from the light enrich image on purpose: torch + the 200M checkpoint are
# ~2 GB of dependencies that the everyday run does not need. CPU only; the model is
# small enough that a GPU buys nothing here. Weights download on first use into the
# huggingface_cache volume, never at build time.
FROM python:3.13-slim

WORKDIR /app

RUN useradd -m -u 1000 appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    HF_HOME=/home/appuser/.cache/huggingface

# CPU wheels first so pip does not resolve the multi-GB CUDA build.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir "timesfm[torch]==3.0.2"

COPY scanner/ ./scanner/
COPY enrich.py .

RUN mkdir -p /home/appuser/.cache/huggingface \
    && chown -R appuser:appuser /app /home/appuser/.cache
USER appuser

ENTRYPOINT ["python", "enrich.py"]
CMD ["--report", "--timesfm"]

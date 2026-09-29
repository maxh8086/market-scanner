# Serves a large open model through AirLLM (layer-by-layer streaming from disk) so it
# runs on a small GPU. Slow by design: every generated token re-reads the weights, so
# this trades speed for VRAM. Profile `airllm`; the `conclude` stage reaches it as
# http://airllm:8000 (same /v1/chat/completions shape as the vllm service).
# No credentials go in or out: the models are public and the container gets no env_file.
FROM pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime

# transformers 5.x fuses MoE experts into one module, which AirLLM's per-expert layer
# loader cannot fill (AttributeError: 'Qwen2MoeExperts' has no attribute '0'), so the
# 2024 MoE models (Qwen1.5-MoE, DeepSeekMoE) need 4.x. Qwen3.8-Flash-Next needs a
# build with in-tree `qwen4_exp`: build with --build-arg TRANSFORMERS_SPEC="git+https://github.com/huggingface/transformers.git".
ARG TRANSFORMERS_SPEC="transformers>=4.51,<5"
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir airllm bitsandbytes accelerate huggingface_hub sentencepiece \
    && pip install --no-cache-dir "${TRANSFORMERS_SPEC}"

ENV MODEL=Qwen/Qwen1.5-MoE-A2.7B-Chat \
    SERVED_NAME=airllm-model \
    COMPRESSION=4bit \
    MAX_INPUT_TOKENS=3500 \
    HF_HOME=/root/.cache/huggingface \
    LAYER_SHARDS=/root/.cache/huggingface/airllm_shards \
    PYTHONUNBUFFERED=1

COPY docker/airllm/server.py /server.py
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=3600s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)"
ENTRYPOINT ["python", "/server.py"]

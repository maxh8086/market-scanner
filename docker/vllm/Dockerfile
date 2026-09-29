# Serves microsoft/Phi-4-mini-instruct through vLLM's OpenAI-compatible API.
# Needs an NVIDIA GPU and the NVIDIA container runtime. The `conclude` stage talks
# to it as http://vllm:8000/v1/chat/completions. No credentials go in or out: the
# model is public (MIT) and the container gets no env_file.
#
# Runs as the upstream image's user (root): the base image's cache paths and CUDA
# stack assume it, and the container is published on 127.0.0.1 only. Weights
# (~7.7 GB) download on first start into the huggingface_vllm volume.
ARG VLLM_IMAGE=vllm/vllm-openai:v0.30.0
FROM ${VLLM_IMAGE}

ENV MODEL=microsoft/Phi-4-mini-instruct \
    SERVED_NAME=phi-4-mini \
    MAX_MODEL_LEN=4096 \
    GPU_MEMORY_UTILIZATION=0.80 \
    MAX_NUM_SEQS=8 \
    MAX_NUM_BATCHED_TOKENS=2048 \
    QUANTIZATION=mxfp4 \
    KV_CACHE_DTYPE=fp8 \
    HF_HOME=/root/.cache/huggingface

COPY docker/vllm/serve.sh /serve.sh
RUN sed -i 's/\r$//' /serve.sh && chmod +x /serve.sh

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=900s --retries=5 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)"

ENTRYPOINT ["/bin/bash", "/serve.sh"]

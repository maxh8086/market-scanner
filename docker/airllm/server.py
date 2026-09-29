"""OpenAI-style /v1/chat/completions over an AirLLM model, plus a --bench mode.

    python /server.py            # serve on :8000 (env: MODEL, COMPRESSION, ...)
    python /server.py --bench    # load, time one prompt, print numbers, exit

AirLLM has no guided decoding, so JSON is requested in the prompt only; the caller
(scanner/conclude.py) parses the reply and rejects anything that does not validate.
One GPU stream: requests are answered one at a time.
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import torch
from airllm import AutoModel
from transformers import AutoTokenizer

MODEL = os.environ["MODEL"]
SERVED = os.environ.get("SERVED_NAME", "airllm-model")
COMPRESSION = os.environ.get("COMPRESSION") or None
MAX_INPUT = int(os.environ.get("MAX_INPUT_TOKENS", "3500"))

_lock = threading.Lock()
_ready = False
tok = model = None


def load():
    global tok, model, _ready
    t = time.time()
    tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    kw = {"compression": COMPRESSION} if COMPRESSION else {}
    model = AutoModel.from_pretrained(MODEL, layer_shards_saving_path=os.environ.get("LAYER_SHARDS"), **kw)
    _ready = True
    print(f"loaded {MODEL} compression={COMPRESSION} in {time.time() - t:.0f}s", flush=True)


def complete(messages, max_tokens, json_schema=None):
    if json_schema:
        messages = [dict(m) for m in messages]
        messages[0]["content"] += ("\nReply with one JSON object only, matching this schema, no prose "
                                   "outside it:\n" + json.dumps(json_schema))
    ids = tok.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt",
                                  return_dict=True)["input_ids"]
    if ids.shape[1] > MAX_INPUT:
        raise ValueError(f"prompt is {ids.shape[1]} tokens, limit {MAX_INPUT}")
    with _lock:
        out = model.generate(ids.cuda(), max_new_tokens=max_tokens, use_cache=True,
                             return_dict_in_generate=True)
    new = out.sequences[0][ids.shape[1]:]
    return tok.decode(new, skip_special_tokens=True), ids.shape[1], len(new)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200 if _ready else 503, {"ready": _ready})
        if self.path == "/v1/models":
            return self._send(200, {"data": [{"id": SERVED}]})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            return self._send(404, {"error": "not found"})
        try:
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            schema = ((req.get("response_format") or {}).get("json_schema") or {}).get("schema")
            text, n_in, n_out = complete(req["messages"], int(req.get("max_tokens", 512)), schema)
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": {"message": f"{type(e).__name__}: {e}"}})
        self._send(200, {"model": SERVED,
                         "choices": [{"index": 0, "finish_reason": "stop",
                                      "message": {"role": "assistant", "content": text}}],
                         "usage": {"prompt_tokens": n_in, "completion_tokens": n_out}})

    def log_message(self, *a):
        pass


def bench():
    load()
    msgs = [{"role": "system", "content": "You are a careful equity analyst."},
            {"role": "user", "content": "Summarise in two sentences: " + "Revenue grew 12% and margins held. " * 150}]
    for n in (1, 16):
        torch.cuda.reset_peak_memory_stats()
        t = time.time()
        text, n_in, n_out = complete(msgs, n)
        dt = time.time() - t
        print(f"BENCH max_new={n} prompt_tokens={n_in} out_tokens={n_out} seconds={dt:.1f} "
              f"peak_vram_gb={torch.cuda.max_memory_allocated() / 1e9:.2f}", flush=True)
    print("SAMPLE:", text[:200].replace("\n", " "), flush=True)


if __name__ == "__main__":
    if "--bench" in sys.argv:
        bench()
    else:
        threading.Thread(target=load, daemon=True).start()
        print("serving on :8000 (loading model in background)", flush=True)
        ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()

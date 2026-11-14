"""
Local image service for cafeteria-ops -- the Menu Designer's meal pictures,
generated on this machine's GPU with FLUX.1-schnell (Apache 2.0) instead of a
paid API. llm_utils.generate_image_sync tries it first (LOCAL_IMAGE_URL).

Runs in its own Python environment, outside the OneDrive-synced repo (it
needs PyTorch with CUDA, several GB): see run_image_server.ps1. The model
(~34 GB download, Hugging Face cache) is loaded once at startup, quantized to
4-bit, and kept on the GPU (~11 GB) -- small enough to share the card with
Ollama's chat model.

    POST /generate  {"prompt": "...", "width": 512, "height": 512}
        -> {"image": "data:image/jpeg;base64,..."}
    GET  /health    -> {"ready": true|false, "model": "..."}

Port: 8320 (127.0.0.1 only)
"""

import base64
import io
import logging
import os
import queue
import threading
import time

from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("image_server")

MODEL_ID = os.getenv("LOCAL_IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell")
PORT = int(os.getenv("LOCAL_IMAGE_PORT", "8320"))
# schnell is distilled for 1-4 steps; 4 is its recommended quality setting.
STEPS = int(os.getenv("LOCAL_IMAGE_STEPS", "4"))
MAX_SIDE = 1024
# Requests that arrive together are drawn as one batch -- the Menu Designer
# asks for every day's picture at once (RTX 5090, 400x400, 4-bit: 1 picture
# 0.5s, a batch of 5 in 1.7s).
BATCH_WINDOW_S = float(os.getenv("LOCAL_IMAGE_BATCH_WINDOW", "0.5"))
MAX_BATCH = int(os.getenv("LOCAL_IMAGE_MAX_BATCH", "8"))

app = Flask(__name__)
_pipe = None
_load_error = ""
_jobs: "queue.Queue[dict]" = queue.Queue()


def _load() -> None:
    global _pipe, _load_error
    try:
        import torch
        from diffusers import BitsAndBytesConfig as DiffusersBnb, FluxPipeline, FluxTransformer2DModel
        from transformers import BitsAndBytesConfig as TransformersBnb, T5EncoderModel

        started = time.time()
        # In bf16 the pipeline is ~34 GB: more than the card, and with
        # Ollama's chat model (~15 GB) also resident it spilled into shared
        # memory -- over a minute per step, live. 4-bit NF4 for the two big
        # parts (the transformer and the T5 text encoder) brings the whole
        # pipeline to ~11 GB, so it stays on the GPU next to Ollama.
        nf4 = dict(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16)
        transformer = FluxTransformer2DModel.from_pretrained(
            MODEL_ID, subfolder="transformer", quantization_config=DiffusersBnb(**nf4), torch_dtype=torch.bfloat16)
        text_encoder_2 = T5EncoderModel.from_pretrained(
            MODEL_ID, subfolder="text_encoder_2", quantization_config=TransformersBnb(**nf4), torch_dtype=torch.bfloat16)
        pipe = FluxPipeline.from_pretrained(
            MODEL_ID, transformer=transformer, text_encoder_2=text_encoder_2, torch_dtype=torch.bfloat16)
        pipe.to("cuda")
        # The first call is slower (CUDA kernels compiling) -- pay that now,
        # not on the first menu.
        pipe("a plate of food", width=256, height=256, num_inference_steps=1, guidance_scale=0.0, max_sequence_length=64)
        _pipe = pipe
        logger.info("Loaded %s in %.0fs", MODEL_ID, time.time() - started)
    except Exception as e:  # reported by /health and /generate
        _load_error = f"{type(e).__name__}: {e}"
        logger.exception("Could not load %s", MODEL_ID)


def _side(value, default: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(256, min(MAX_SIDE, n - n % 16))  # FLUX needs multiples of 16


@app.get("/health")
def health():
    return jsonify({"ready": _pipe is not None, "model": MODEL_ID, "error": _load_error})


def _draw(batch: list[dict]) -> None:
    """One pipeline call for every job in ``batch`` (all the same size)."""
    import torch

    width, height = batch[0]["width"], batch[0]["height"]
    started = time.time()
    try:
        images = _pipe(
            [job["prompt"] for job in batch],
            width=width,
            height=height,
            num_inference_steps=STEPS,
            guidance_scale=0.0,  # schnell is guidance-distilled
            max_sequence_length=256,
            generator=[torch.Generator("cpu").manual_seed(job["seed"]) for job in batch],
        ).images
        for job, image in zip(batch, images):
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="JPEG", quality=85)
            job["image"] = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
        logger.info("Generated %d picture(s) at %dx%d in %.1fs", len(batch), width, height, time.time() - started)
    except Exception as e:
        logger.exception("Generation failed")
        for job in batch:
            job["error"] = f"{type(e).__name__}: {e}"
    finally:
        for job in batch:
            job["done"].set()


def _worker() -> None:
    """Takes the first waiting job, gathers whatever else arrives within
    BATCH_WINDOW_S, and draws them -- one batch per picture size."""
    while True:
        jobs = [_jobs.get()]
        deadline = time.time() + BATCH_WINDOW_S
        while len(jobs) < MAX_BATCH:
            try:
                jobs.append(_jobs.get(timeout=max(0.0, deadline - time.time())))
            except queue.Empty:
                break
        by_size: dict = {}
        for job in jobs:
            by_size.setdefault((job["width"], job["height"]), []).append(job)
        for batch in by_size.values():
            _draw(batch)


@app.post("/generate")
def generate():
    if _pipe is None:
        return jsonify({"error": _load_error or "model still loading"}), 503
    body = request.get_json(silent=True) or {}
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400
    job = {
        "prompt": prompt,
        "width": _side(body.get("width"), 512),
        "height": _side(body.get("height"), 512),
        "seed": int(body.get("seed") or time.time_ns() % 2**31),
        "done": threading.Event(),
    }
    _jobs.put(job)
    job["done"].wait()
    if "error" in job:
        return jsonify({"error": job["error"]}), 500
    return jsonify({"image": job["image"]})


if __name__ == "__main__":
    threading.Thread(target=_load, daemon=True).start()
    threading.Thread(target=_worker, daemon=True).start()
    app.run(host="127.0.0.1", port=PORT, threaded=True)

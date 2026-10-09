"""
Wardrobe-AI virtual try-on GPU server - Kaggle script kernel.

Runs FASHN VTON v1.5 (Apache-2.0, the same model as the public
fashn-ai/fashn-vton-1.5 Space) on a free Kaggle GPU and exposes the
SAME Gradio endpoint the backend already calls (/try_on), through a
temporary HTTPS tunnel.

Pushed and started by `python -m backend.kaggle_tryon start`, which
also reads the tunnel address back and writes it into .env as
TRYON_FALLBACK_URL. You do not need to open Kaggle in a browser.

The address is published to a private ntfy.sh topic whose random name
is generated per launch (__NTFY_TOPIC__ below is replaced at push
time). Nothing else is sent anywhere.

The session stops itself after SESSION_HOURS so it does not burn the
weekly free GPU allowance while nobody is using it.
"""

import os
import re
import subprocess
import sys
import threading
import time
import urllib.request

NTFY_TOPIC = "__NTFY_TOPIC__"
SESSION_HOURS = float("__SESSION_HOURS__")
PORT = 7860
STARTED = time.time()


def log(*parts):
    print(f"[{time.time() - STARTED:7.1f}s]", *parts, flush=True)


def publish(message):
    """Send a status line / the URL to the launcher. Never fatal."""
    for _ in range(5):
        try:
            urllib.request.urlopen(
                urllib.request.Request(
                    f"https://ntfy.sh/{NTFY_TOPIC}",
                    data=message.encode(),
                    method="POST",
                ),
                timeout=20,
            ).read()
            return
        except Exception as error:  # noqa: BLE001
            log("publish failed:", type(error).__name__, error)
            time.sleep(3)


def sh(command):
    log("$", command)
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        log(result.stdout[-2000:], result.stderr[-3000:])
        raise SystemExit(f"command failed: {command}")
    return result.stdout


publish("status:booting")

# ---------------------------------------------------------------- GPU
gpu = subprocess.run(["nvidia-smi"], capture_output=True, text=True)
if gpu.returncode != 0:
    publish("error:no-gpu")
    raise SystemExit("No GPU in this session (enable_gpu must be true).")
log(gpu.stdout)

# ------------------------------------------------------------ install
sh(
    f"{sys.executable} -m pip install -q --no-deps "
    "git+https://github.com/fashn-AI/fashn-vton-1.5.git"
)
sh(
    f"{sys.executable} -m pip install -q einops safetensors "
    "fashn-human-parser 'gradio>=6,<7' onnxruntime-gpu"
)
publish("status:installed")

# ------------------------------------------------------------ weights
from huggingface_hub import hf_hub_download  # noqa: E402

WEIGHTS = "/kaggle/working/weights"
os.makedirs(f"{WEIGHTS}/dwpose", exist_ok=True)
hf_hub_download("fashn-ai/fashn-vton-1.5", "model.safetensors", local_dir=WEIGHTS)
for name in ("yolox_l.onnx", "dw-ll_ucoco_384.onnx"):
    hf_hub_download("fashn-ai/DWPose", name, local_dir=f"{WEIGHTS}/dwpose")
log("weights ready")

import torch  # noqa: E402
from PIL import Image  # noqa: E402
from fashn_vton import TryOnPipeline  # noqa: E402

log("torch", torch.__version__, "cuda", torch.cuda.is_available(),
    torch.cuda.get_device_name(0) if torch.cuda.is_available() else "-")
pipeline = TryOnPipeline(weights_dir=WEIGHTS, device="cuda")

# Pick the fastest dtype this card really supports. bf16 is native only
# from Ampere (compute 8.x); on a T4/P100 torch may *report* bf16 support
# through slow emulation, which makes one try-on take many minutes.
# Turing (T4, 7.5) has fast fp16 tensor cores; Pascal (P100) runs fp32.
major, minor = torch.cuda.get_device_capability(0)
if major >= 8:
    chosen = torch.bfloat16
elif major >= 7:
    chosen = torch.float16
else:
    chosen = torch.float32
if chosen != pipeline.inference_dtype:
    pipeline.tryon_model.to(dtype=chosen)
    pipeline.inference_dtype = chosen
GPU_NAME = torch.cuda.get_device_name(0)
log("pipeline loaded on", GPU_NAME, f"sm_{major}{minor}", "dtype", pipeline.inference_dtype)
publish(f"status:model-loaded {GPU_NAME} sm_{major}{minor} {str(chosen).split('.')[-1]}")

# Warm-up so the first real user does not pay for CUDA initialisation.
try:
    t = time.time()
    pipeline(
        person_image=Image.new("RGB", (576, 864), (150, 150, 150)),
        garment_image=Image.new("RGB", (576, 864), (200, 60, 60)),
        category="tops", segmentation_free=True, num_timesteps=4,
    )
    log(f"warm-up {time.time() - t:.1f}s")
except Exception as error:  # noqa: BLE001 - a grey box is not a person
    log("warm-up raised", type(error).__name__, "(fine)")

# ------------------------------------------------------------ gradio
import gradio as gr  # noqa: E402

CATEGORIES = ["tops", "bottoms", "one-pieces"]
PHOTO_TYPES = ["model", "flat-lay"]
LOCK = threading.Lock()


def try_on(person_image, garment_image, category, garment_photo_type="flat-lay",
           segmentation_free=False):
    # segmentation_free=False: the person's current garment is masked out
    # first, so a longer/untucked original shirt can't show under the new
    # top. True keeps the old behaviour (draw over the original clothes).
    if person_image is None or garment_image is None:
        raise gr.Error("A person photo and a garment image are both required.")
    if category not in CATEGORIES:
        raise gr.Error(f"Category must be one of {CATEGORIES}.")
    if garment_photo_type not in PHOTO_TYPES:
        garment_photo_type = "flat-lay"
    with LOCK:  # one generation at a time on a 16 GB card
        started = time.time()
        publish(f"run:start {category}")
        try:
            result = _generate(
                person_image=person_image.convert("RGB"),
            garment_image=garment_image.convert("RGB"),
            category=category,
            garment_photo_type=garment_photo_type,
            num_samples=1,
            num_timesteps=30,
            guidance_scale=1.5,
            seed=42,
            segmentation_free=bool(segmentation_free),
            )
        except Exception as error:  # noqa: BLE001
            publish(f"run:error {type(error).__name__}: {str(error)[:200]}")
            raise
        image = result.images[0]
        extrema = image.convert("L").getextrema()
        took = time.time() - started
        log(f"try_on {category}/{garment_photo_type} in {took:.1f}s extrema={extrema}")
        publish(f"run:done {category} {took:.1f}s size={image.size} extrema={extrema}")
        if extrema[0] == extrema[1]:
            raise gr.Error("The model produced a blank image.")
    return image


def _generate(**kwargs):
    """Runs the pipeline; if fp16 overflows into a blank image, retry in fp32."""
    result = pipeline(**kwargs)
    image = result.images[0]
    lo, hi = image.convert("L").getextrema()
    if lo == hi and pipeline.inference_dtype == torch.float16:
        publish("status:fp16-blank-switching-to-fp32")
        pipeline.tryon_model.to(dtype=torch.float32)
        pipeline.inference_dtype = torch.float32
        result = pipeline(**kwargs)
    return result


with gr.Blocks(title="Wardrobe-AI Try-On (Kaggle)") as demo:
    gr.Markdown("## Wardrobe-AI virtual try-on - FASHN VTON v1.5 on Kaggle GPU")
    with gr.Row():
        person = gr.Image(type="pil", label="Person")
        garment = gr.Image(type="pil", label="Garment")
        output = gr.Image(type="pil", format="png", label="Result")
    category = gr.Dropdown(CATEGORIES, value="tops", label="Category")
    photo_type = gr.Dropdown(PHOTO_TYPES, value="flat-lay", label="Garment photo type")
    seg_free = gr.Checkbox(value=False, label="Segmentation free (keep original clothes)")
    gr.Button("Try on").click(
        try_on, inputs=[person, garment, category, photo_type, seg_free],
        outputs=output, api_name="try_on",
    )

# Requests wait their turn (default_concurrency_limit=1) instead of
# being refused, so two accounts trying on at once both succeed.
demo.queue(max_size=20, default_concurrency_limit=1)
demo.launch(server_name="127.0.0.1", server_port=PORT, prevent_thread_lock=True,
            show_error=True, quiet=True)
log("gradio listening on", PORT)

# ------------------------------------------------------------ tunnel
url = None
try:
    sh(
        "wget -q -O /kaggle/working/cloudflared "
        "https://github.com/cloudflare/cloudflared/releases/latest/download/"
        "cloudflared-linux-amd64 && chmod +x /kaggle/working/cloudflared"
    )
    tunnel = subprocess.Popen(
        ["/kaggle/working/cloudflared", "tunnel", "--no-autoupdate",
         "--url", f"http://127.0.0.1:{PORT}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    deadline = time.time() + 90
    while time.time() < deadline and url is None:
        line = tunnel.stdout.readline()
        if not line:
            time.sleep(0.5)
            continue
        match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
        if match:
            url = match.group(0)
    if url:
        threading.Thread(target=lambda: [None for _ in tunnel.stdout], daemon=True).start()
except SystemExit:
    url = None

if not url:
    log("cloudflared failed - trying a gradio share link")
    publish("status:cloudflared-failed")
    try:
        _, _, url = demo.launch(server_name="127.0.0.1", server_port=PORT,
                                share=True, prevent_thread_lock=True,
                                show_error=True, quiet=True)
    except Exception as error:  # noqa: BLE001
        log("gradio share failed:", type(error).__name__, error)
        url = None

if not url:
    # Last resort: an SSH reverse tunnel over port 443 (pinggy.io free
    # tier - tunnels last 60 minutes).
    log("trying an ssh tunnel over port 443")
    publish("status:gradio-share-failed")
    pinggy = subprocess.Popen(
        ["ssh", "-p", "443", "-o", "StrictHostKeyChecking=no",
         "-o", "ServerAliveInterval=30", f"-R0:127.0.0.1:{PORT}", "a.pinggy.io"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True,
    )
    deadline = time.time() + 60
    while time.time() < deadline and not url:
        line = pinggy.stdout.readline()
        match = re.search(r"https://[a-z0-9.-]+\.pinggy\.link", line or "")
        if match:
            url = match.group(0)
    if url:
        threading.Thread(target=lambda: [None for _ in pinggy.stdout], daemon=True).start()

if not url:
    publish("error:no-tunnel")
    raise SystemExit("No tunnel could be opened from this Kaggle session.")

# Give the tunnel a moment to become routable, then check it end to end.
for _ in range(20):
    try:
        urllib.request.urlopen(f"{url}/config", timeout=15).read()
        break
    except Exception:  # noqa: BLE001
        time.sleep(3)

log("PUBLIC URL", url)
publish(f"url:{url}")

# ------------------------------------------------------------ stay up
end = STARTED + SESSION_HOURS * 3600
while time.time() < end:
    time.sleep(60)
publish("status:stopped")
log("session time limit reached - stopping to save the weekly GPU allowance")

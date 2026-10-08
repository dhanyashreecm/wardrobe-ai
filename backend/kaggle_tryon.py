"""
Start the free Kaggle GPU that generates virtual try-ons, and point the
backend at it - one command, no browser.

    python -m backend.kaggle_tryon start          # 4-hour session (default)
    python -m backend.kaggle_tryon start --hours 8
    python -m backend.kaggle_tryon status
    python -m backend.kaggle_tryon stop           # stop it early, save GPU hours

WHY THIS EXISTS
---------------
The public FASHN VTON Space runs on Hugging Face ZeroGPU, whose free
allowance belongs to the CALLER. The backend is one caller for every
user, so the whole app gets a handful of runs a day - anonymously it is
often zero ("You have exceeded your ZeroGPU runs limit"). Five try-ons
per user per day cannot come from there.

Kaggle gives a phone-verified free account about 30 GPU-hours a week.
The same model (FASHN VTON v1.5, Apache-2.0) takes roughly 15-40 s per
try-on on a T4, so one session covers hundreds of try-ons.

WHAT "start" DOES
-----------------
1. Pushes spaces/tryon/kaggle_kernel/wardrobe_tryon_kernel.py to YOUR
   Kaggle account as a PRIVATE script kernel with a T4 GPU and internet.
2. The kernel installs FASHN VTON, downloads the weights, warms the
   model up, serves the /try_on endpoint the backend already uses, and
   opens a temporary https tunnel to it.
3. The tunnel address comes back over a one-off random ntfy.sh topic.
4. This script checks the address answers, then writes
   TRYON_FALLBACK_URL and TRYON_PROVIDERS into .env (previous .env kept
   as a backup). Restart the backend to pick it up.

The kernel stops itself after --hours so it does not quietly use the
weekly allowance. The tunnel address is unguessable but public while it
lasts: do not post it anywhere.

Needs the `kaggle` package (pip install kaggle) and your Kaggle API
credentials in ~/.kaggle (kaggle.json or access_token).
"""

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
KERNEL_SOURCE = os.path.join(
    PROJECT_ROOT, "spaces", "tryon", "kaggle_kernel", "wardrobe_tryon_kernel.py"
)
STATE_PATH = os.path.join(PROJECT_ROOT, "spaces", "tryon", "kaggle_kernel", ".last_launch.json")
KERNEL_SLUG = "wardrobe-ai-tryon-gpu"
PROVIDER_ORDER = "self_hosted,fashn_space"


PLACEHOLDER_USERNAMES = {"", "YOUR_USERNAME", "your_username", "username"}


def _credentials_env():
    """
    Environment for the kaggle CLI. Kaggle's newer API tokens (the ones
    "Generate New Token" gives today) are not legacy username/key pairs:
    if ~/.kaggle/kaggle.json holds one of those under "key" with a
    placeholder username, hand it to the CLI as KAGGLE_API_TOKEN, which
    is how the CLI expects a new-style token.
    """
    env = dict(os.environ)
    path = os.path.expanduser("~/.kaggle/kaggle.json")
    if "KAGGLE_API_TOKEN" not in env and os.path.isfile(path):
        try:
            data = json.load(open(path))
        except ValueError:
            data = {}
        key = str(data.get("key", ""))
        legacy = len(key) == 32 and all(c in "0123456789abcdef" for c in key)
        if key and not legacy:
            env["KAGGLE_API_TOKEN"] = key
    return env


def _kaggle(*args):
    exe = shutil.which("kaggle") or os.path.join(os.path.dirname(sys.executable), "kaggle")
    if not os.path.exists(exe):
        raise SystemExit("The kaggle package is missing: "
                         f"{sys.executable} -m pip install kaggle")
    result = subprocess.run([exe, *args], capture_output=True, text=True,
                            env=_credentials_env())
    return result.returncode, (result.stdout + result.stderr).strip()


def _username(explicit=""):
    if explicit:
        return explicit
    if os.environ.get("KAGGLE_USERNAME"):
        return os.environ["KAGGLE_USERNAME"]
    path = os.path.expanduser("~/.kaggle/kaggle.json")
    if os.path.isfile(path):
        name = str(json.load(open(path)).get("username", ""))
        if name not in PLACEHOLDER_USERNAMES:
            return name
    code, out = _kaggle("config", "view")
    for line in out.splitlines():
        if line.strip().startswith("- username:"):
            name = line.split(":", 1)[1].strip()
            if name not in PLACEHOLDER_USERNAMES and name != "None":
                return name
    # Token-only credentials: ask Kaggle who we are via our own kernels/datasets.
    for listing in (("kernels", "list", "--mine", "--csv", "--page-size", "5"),
                    ("datasets", "list", "--mine", "--csv")):
        code, out = _kaggle(*listing)
        for line in out.splitlines()[1:]:
            ref = line.split(",", 1)[0].strip()
            if "/" in ref:
                return ref.split("/", 1)[0]
    raise SystemExit("Couldn't tell your Kaggle username - pass it: "
                     "python -m backend.kaggle_tryon start --user <your-kaggle-username>")


def set_env(values):
    """Upsert KEY=VALUE lines in .env, keeping everything else as-is."""
    lines = open(ENV_PATH, encoding="utf-8").read().splitlines() if os.path.isfile(ENV_PATH) else []
    if lines:
        shutil.copy2(ENV_PATH, f"{ENV_PATH}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    seen = set()
    for index, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in values and "=" in line and not line.lstrip().startswith("#"):
            lines[index] = f"{key}={values[key]}"
            seen.add(key)
    for key, value in values.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    with open(ENV_PATH, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _ntfy_messages(topic):
    url = f"https://ntfy.sh/{topic}/json?poll=1&since=all"
    try:
        body = urllib.request.urlopen(url, timeout=20).read().decode()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for line in body.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("event") == "message":
            out.append(event.get("message", ""))
    return out


def _answers(url):
    try:
        urllib.request.urlopen(f"{url}/config", timeout=20).read()
        return True
    except Exception:  # noqa: BLE001
        return False


def start(hours, wait_minutes, accelerator, user=""):
    user = _username(user)

    topic = "wardrobe-ai-" + secrets.token_hex(12)
    work = tempfile.mkdtemp(prefix="wardrobe_kaggle_")
    script = open(KERNEL_SOURCE, encoding="utf-8").read()
    script = script.replace("__NTFY_TOPIC__", topic).replace("__SESSION_HOURS__", str(hours))
    with open(os.path.join(work, "wardrobe_tryon_kernel.py"), "w") as handle:
        handle.write(script)
    with open(os.path.join(work, "kernel-metadata.json"), "w") as handle:
        json.dump({
            "id": f"{user}/{KERNEL_SLUG}",
            "title": KERNEL_SLUG,
            "code_file": "wardrobe_tryon_kernel.py",
            "language": "python",
            "kernel_type": "script",
            "is_private": True,
            "enable_gpu": True,
            "enable_internet": True,
            "machine_shape": accelerator,
            "dataset_sources": [],
            "competition_sources": [],
            "kernel_sources": [],
            "model_sources": [],
        }, handle, indent=2)

    print(f"Pushing a private GPU kernel to Kaggle as {user}/{KERNEL_SLUG} ...")
    push = ["kernels", "push", "-p", work, "-t", str(int(hours * 3600) + 1800)]
    if "--accelerator" in _kaggle("kernels", "push", "-h")[1]:
        push += ["--accelerator", accelerator]   # older CLIs only read machine_shape
    code, out = _kaggle(*push)
    print(out)
    if code != 0:
        raise SystemExit("Kaggle refused the push (see above).")

    json.dump({"topic": topic, "user": user, "started": time.time(), "hours": hours},
              open(STATE_PATH, "w"))

    print("Waiting for the GPU to boot, install and load the model "
          "(usually 4-8 minutes) ...")
    deadline = time.time() + wait_minutes * 60
    last = ""
    while time.time() < deadline:
        messages = _ntfy_messages(topic)
        if messages and messages[-1] != last:
            last = messages[-1]
            print("  kernel:", last)
        urls = [m[4:] for m in messages if m.startswith("url:")]
        if urls and _answers(urls[-1]):
            set_env({"TRYON_FALLBACK_URL": urls[-1], "TRYON_PROVIDERS": PROVIDER_ORDER})
            print("\nReady. .env now points TRYON_FALLBACK_URL at the Kaggle GPU.")
            print(f"It stays up for {hours} h. Restart the backend to pick it up:")
            print("    ./ai_env312/bin/python -m backend.app")
            return urls[-1]
        if any(m.startswith("error:") for m in messages):
            raise SystemExit(f"The kernel reported {last}. "
                             "Check `python -m backend.kaggle_tryon status`.")
        code, out = _kaggle("kernels", "status", f"{user}/{KERNEL_SLUG}")
        if "error" in out.lower() or "cancel" in out.lower():
            raise SystemExit(f"Kaggle kernel stopped: {out}")
        time.sleep(15)
    raise SystemExit("The kernel did not come up in time. "
                     "Check `python -m backend.kaggle_tryon status`.")


def status(user=""):
    user = _username(user)
    code, out = _kaggle("kernels", "status", f"{user}/{KERNEL_SLUG}")
    print(out)
    if os.path.isfile(STATE_PATH):
        state = json.load(open(STATE_PATH))
        messages = _ntfy_messages(state["topic"])
        print("last kernel message:", messages[-1] if messages else "(none)")


def stop(user=""):
    """Push a tiny CPU script under the same slug, which ends the GPU run."""
    user = _username(user)
    work = tempfile.mkdtemp(prefix="wardrobe_kaggle_stop_")
    with open(os.path.join(work, "stop.py"), "w") as handle:
        handle.write("print('stopped')\n")
    with open(os.path.join(work, "kernel-metadata.json"), "w") as handle:
        json.dump({"id": f"{user}/{KERNEL_SLUG}", "title": KERNEL_SLUG,
                   "code_file": "stop.py", "language": "python",
                   "kernel_type": "script", "is_private": True,
                   "enable_gpu": False, "enable_internet": False}, handle)
    code, out = _kaggle("kernels", "push", "-p", work)
    print(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    go = sub.add_parser("start")
    go.add_argument("--hours", type=float, default=4.0)
    go.add_argument("--wait-minutes", type=float, default=20.0)
    go.add_argument("--accelerator", default="NvidiaTeslaT4")
    go.add_argument("--user", default="")
    for name in ("status", "stop"):
        sub.add_parser(name).add_argument("--user", default="")
    args = parser.parse_args()
    if args.command == "start":
        start(args.hours, args.wait_minutes, args.accelerator, args.user)
    elif args.command == "status":
        status(args.user)
    else:
        stop(args.user)


if __name__ == "__main__":
    main()

"""
Deploy the backend to a free Hugging Face Docker Space, so the phone app
(APK) has a permanent https server.

    ./ai_env312/bin/python -m scripts.deploy_hf_space

You type your Hugging Face access token (with WRITE permission) when
asked - it is used only for this upload and is not saved. The script:
  1. creates (or updates) the public Space <you>/wardrobe-ai
  2. copies this machine's .env values into the Space as SECRETS
     (never into the code)
  3. uploads the backend + Dockerfile; Hugging Face then builds it
  4. prints the server address to put in the app
"""
import getpass
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPACE_NAME = "wardrobe-ai"
SECRET_KEYS = [
    "MONGODB_URI", "MONGODB_DB_NAME", "JWT_SECRET_KEY",
    "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET",
    "OPENWEATHER_API_KEY", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_HOST", "SMTP_PORT",
    "SMTP_FROM_NAME", "TRYON_SPACE_ID", "TRYON_PROVIDERS", "TRYON_FALLBACK_URL",
    "TRYON_DAILY_LIMIT", "TRYON_SEGMENTATION_FREE", "SERPAPI_API_KEY", "PINTEREST_ACCESS_TOKEN",
]
SKIP_DIRS = {"uploads", "__pycache__", "tests"}


def read_env():
    values = {}
    path = os.path.join(ROOT, ".env")
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def stage():
    work = tempfile.mkdtemp(prefix="wardrobe_space_")
    for name in ("Dockerfile", "README.md", "requirements-server.txt"):
        shutil.copy(os.path.join(ROOT, "deploy", "hf_space", name), work)

    def ignore(folder, names):
        return [n for n in names if n in SKIP_DIRS or n.endswith((".pyc", ".log"))
                or "_backup" in n or n.startswith("make_")]
    shutil.copytree(os.path.join(ROOT, "backend"), os.path.join(work, "backend"), ignore=ignore)
    return work


def main():
    try:
        from huggingface_hub import HfApi
    except ImportError:
        sys.exit("Install it first: ./ai_env312/bin/python -m pip install huggingface_hub")

    token = os.environ.get("HF_TOKEN") or getpass.getpass(
        "Paste your Hugging Face access token (WRITE), then press Enter (it stays hidden): ").strip()
    api = HfApi(token=token)
    user = api.whoami()["name"]
    repo_id = f"{user}/{SPACE_NAME}"
    print(f"Signed in as {user}. Creating/updating the Space {repo_id} ...")
    api.create_repo(repo_id, repo_type="space", space_sdk="docker", exist_ok=True, private=False)

    env = read_env()
    for key in SECRET_KEYS:
        if env.get(key):
            api.add_space_secret(repo_id, key, env[key])
    api.add_space_variable(repo_id, "TRYON_GPU_URL_FROM_DB", "true")
    print(f"Copied {sum(1 for k in SECRET_KEYS if env.get(k))} settings as private Space secrets.")

    folder = stage()
    api.upload_folder(folder_path=folder, repo_id=repo_id, repo_type="space",
                      commit_message="Deploy Wardrobe AI backend")
    shutil.rmtree(folder, ignore_errors=True)

    url = f"https://{user.lower().replace('_', '-')}-{SPACE_NAME}.hf.space"
    print("\nUploaded. Hugging Face is now building the server (about 5-10 minutes).")
    print(f"Watch it here: https://huggingface.co/spaces/{repo_id}")
    print(f"\nSERVER ADDRESS FOR THE APP:  {url}")
    with open(os.path.join(ROOT, "backups", "_claude_tmp", "server_url.txt"), "w") as handle:
        handle.write(url + "\n")


if __name__ == "__main__":
    main()

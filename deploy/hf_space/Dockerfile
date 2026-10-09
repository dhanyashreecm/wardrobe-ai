# Wardrobe AI backend for the phone app - Hugging Face Docker Space.
# Free CPU Space: 2 vCPU / 16 GB RAM, enough for TensorFlow (auto
# category, wardrobe matching) and rembg (background removal). The
# heavy try-on model still runs on the Kaggle GPU / FASHN Space.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    TRYON_GPU_URL_FROM_DB=true \
    HOME=/home/user U2NET_HOME=/home/user/.u2net

RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/* && useradd -m -u 1000 user

WORKDIR /app
COPY requirements-server.txt .
RUN pip install -r requirements-server.txt

COPY --chown=user backend ./backend
RUN mkdir -p /app/backend/uploads && chown -R user /app
USER user

EXPOSE 7860
# One process (try-on jobs run on background threads inside it), many threads.
CMD ["gunicorn", "-w", "1", "--threads", "8", "-t", "600", "-b", "0.0.0.0:7860", "backend.app:app"]

---
title: Wardrobe-AI Try-On
emoji: 👕
colorFrom: indigo
colorTo: pink
sdk: gradio
app_file: app.py
pinned: false
suggested_hardware: zero-a10g
license: apache-2.0
---

# Wardrobe-AI virtual try-on

The GPU half of [Wardrobe-AI](https://github.com/). Puts one garment
onto one person and returns the image. The Wardrobe-AI Flask backend
calls it over the Gradio API; the interface exists so it can also be
tested by hand.

**Model:** [FASHN VTON v1.5](https://huggingface.co/fashn-ai/fashn-vton-1.5),
Apache-2.0. Chosen over the better-known IDM-VTON, CatVTON and
OOTDiffusion because those are CC BY-NC-SA 4.0 and forbid commercial
use. It is maskless, so pose detection, segmentation, warping,
occlusion and lighting all happen inside the pipeline.

## API

One endpoint, `/try_on`:

| Input | Type | Values |
|---|---|---|
| `person_image` | image | a photo of one person, upright, full body preferred |
| `garment_image` | image | the garment, flat-lay or worn |
| `category` | string | `tops`, `bottoms` or `one-pieces` |

Returns one image.

```python
from gradio_client import Client, handle_file

client = Client("your-name/your-space", hf_token="hf_...")

result = client.predict(
    person_image=handle_file("me.jpg"),
    garment_image=handle_file("shirt.jpg"),
    category="tops",
    api_name="/try_on",
)
```

## If your Hugging Face account is less than 30 days old

ZeroGPU requires an account older than 30 days, so a new account cannot
host this. Use `colab_tryon.ipynb` in this folder instead: it runs the
same model on Colab's free GPU and prints a public address the backend
can call. Same model, same API, no waiting and no cost.

The only differences are that the address changes every time you run
the notebook, and Colab stops an idle notebook after about 90 minutes -
so start it shortly before you need it.

## Deploying

Create a Space with SDK **Gradio** and hardware **ZeroGPU**, then
upload `app.py`, `requirements.txt` and this file. The first build
downloads roughly 2 GB of weights, so give it time.

A free Hugging Face account can host up to 2 ZeroGPU Spaces and gets
5 GPU-minutes per day, which is enough for development and a demo but
not for many simultaneous users.

## Limits worth knowing

One garment per call. A full outfit is two calls - bottom, then top
applied to that result - which doubles both the wait and the GPU
allowance used.

Footwear and accessories are not supported, by this model or any other
currently available. Wardrobe-AI shows them beside the result instead
of pretending they were worn.

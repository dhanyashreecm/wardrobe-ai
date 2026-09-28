"""
The GPU half of Wardrobe-AI's virtual try-on.

This file does not run on either developer's laptop. It runs as a
Hugging Face Space on a ZeroGPU slice, because the model it loads
needs a CUDA GPU and neither of this project's machines has one. The
Flask backend in backend/virtual_tryon.py calls it over the Gradio
API.

WHY WE HOST OUR OWN SPACE RATHER THAN CALLING SOMEONE ELSE'S

Two reasons, both about not building on sand. A Space someone else
owns can change its inputs, be renamed, or be deleted, and our backend
would break with no warning. And the GPU allowance is charged to
whoever owns the Space, so running our own is what gives the project
its own free quota instead of sharing an anonymous pool.

Because the Space is ours, the API contract below is fixed and the
backend can rely on it: one endpoint named try_on, three inputs
(person image, garment image, category), one image out.

THE MODEL

FASHN VTON v1.5 - Apache-2.0, so no non-commercial restriction, unlike
IDM-VTON, CatVTON, OOTDiffusion, StableVITON and VITON-HD which are
all CC BY-NC-SA. It is maskless: pose detection (DWPose), garment
segmentation, warping, occlusion and lighting are handled inside the
pipeline, which is why nothing here preprocesses the images.

    https://huggingface.co/fashn-ai/fashn-vton-1.5

DEPLOYING THIS

  1. Create a Hugging Face Space, SDK "Gradio", hardware "ZeroGPU".
  2. Upload this file, requirements.txt and README.md to it.
  3. Wait for the build - the first one downloads about 2 GB of
     weights and takes a while.
  4. Put the Space's id ("your-name/your-space") into the backend's
     .env as TRYON_SPACE_ID, with a read token as
     HUGGINGFACE_API_TOKEN.
"""

import os

import gradio as gr
import spaces
from huggingface_hub import snapshot_download
from PIL import Image


MODEL_REPO = "fashn-ai/fashn-vton-1.5"

WEIGHTS_DIR = os.environ.get("WEIGHTS_DIR", "./weights")

CATEGORIES = ["tops", "bottoms", "one-pieces"]

# Long enough for a cold pipeline plus one generation, short enough
# that a stuck request gives the GPU slice back instead of burning the
# day's allowance.
GPU_DURATION_SECONDS = 120


_pipeline = None


def get_pipeline():
    """
    Loads the model once, on first use.

    Deliberately lazy rather than at import: a Space that downloads 2 GB
    of weights before Gradio starts looks broken to anyone watching the
    build log, and ZeroGPU wants the heavy work inside the GPU-decorated
    function anyway.
    """
    global _pipeline

    if _pipeline is not None:
        return _pipeline

    from fashn_vton import TryOnPipeline

    snapshot_download(repo_id=MODEL_REPO, local_dir=WEIGHTS_DIR)

    _pipeline = TryOnPipeline(weights_dir=WEIGHTS_DIR)

    return _pipeline


@spaces.GPU(duration=GPU_DURATION_SECONDS)
def try_on(person_image, garment_image, category):
    """
    Puts one garment on one person. One garment, not an outfit: the
    backend chains calls (bottom, then top) to dress someone fully,
    because that is how the model works.
    """
    if person_image is None:
        raise gr.Error("No photo of the person was supplied.")

    if garment_image is None:
        raise gr.Error("No garment image was supplied.")

    if category not in CATEGORIES:
        raise gr.Error(
            f"Category must be one of {', '.join(CATEGORIES)} - got "
            f"'{category}'."
        )

    person = person_image.convert("RGB")
    garment = garment_image.convert("RGB")

    pipeline = get_pipeline()

    result = pipeline(
        person_image=person,
        garment_image=garment,
        category=category,
    )

    return result.images[0]


with gr.Blocks(title="Wardrobe-AI Try-On") as demo:

    gr.Markdown(
        "## Wardrobe-AI virtual try-on\n"
        "One garment onto one person. Called by the Wardrobe-AI backend; "
        "the boxes below are here so it can be tested by hand too.\n\n"
        "Model: [FASHN VTON v1.5](https://huggingface.co/fashn-ai/fashn-vton-1.5)"
        " (Apache-2.0)."
    )

    with gr.Row():
        person_input = gr.Image(label="Person", type="pil")
        garment_input = gr.Image(label="Garment", type="pil")
        output_image = gr.Image(label="Result", type="pil")

    category_input = gr.Dropdown(
        CATEGORIES, value="tops", label="Category"
    )

    run_button = gr.Button("Try on", variant="primary")

    # api_name fixes the endpoint the backend calls. Changing it breaks
    # backend/virtual_tryon.py, which asks for "/try_on" by name.
    run_button.click(
        fn=try_on,
        inputs=[person_input, garment_input, category_input],
        outputs=output_image,
        api_name="try_on",
    )


if __name__ == "__main__":
    demo.queue().launch()

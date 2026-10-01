"""
A segmentation benchmark with EXACT ground truth.

These are composites, not phone photographs - and that is the point:
the garment shape is known to the pixel, so a mask can be scored
honestly instead of eyeballed. Each one reproduces a condition the
real pipeline has to survive: tiled floor, wooden floor, a bedsheet
with folds, a patterned throw, white-on-white, dark-on-dark, plus
phone-camera blur, shadow and sensor noise.
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

rng = np.random.default_rng(7)
W, H = 768, 1024


# ---------------------------------------------------------------
# Garment silhouettes (ground truth)
# ---------------------------------------------------------------

def tshirt_mask(size=(W, H)):
    w, h = size
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    cx = w // 2
    body_w, body_h = int(w * 0.46), int(h * 0.42)
    top = int(h * 0.26)
    # body
    d.polygon([(cx - body_w // 2, top + int(h * 0.05)),
               (cx + body_w // 2, top + int(h * 0.05)),
               (cx + body_w // 2 + int(w * 0.02), top + body_h),
               (cx - body_w // 2 - int(w * 0.02), top + body_h)], fill=255)
    # shoulders / sleeves
    d.polygon([(cx - body_w // 2, top + int(h * 0.05)),
               (cx - body_w // 2 - int(w * 0.17), top + int(h * 0.13)),
               (cx - body_w // 2 - int(w * 0.13), top + int(h * 0.20)),
               (cx - body_w // 2, top + int(h * 0.14))], fill=255)
    d.polygon([(cx + body_w // 2, top + int(h * 0.05)),
               (cx + body_w // 2 + int(w * 0.17), top + int(h * 0.13)),
               (cx + body_w // 2 + int(w * 0.13), top + int(h * 0.20)),
               (cx + body_w // 2, top + int(h * 0.14))], fill=255)
    # neckline cut out
    d.ellipse([cx - int(w * 0.08), top - int(h * 0.01),
               cx + int(w * 0.08), top + int(h * 0.055)], fill=0)
    return m


def jeans_mask(size=(W, H)):
    w, h = size
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    cx = w // 2
    top, bottom = int(h * 0.15), int(h * 0.88)
    hip = int(w * 0.30)
    d.polygon([(cx - hip, top), (cx + hip, top),
               (cx + int(w * 0.22), bottom), (cx + int(w * 0.06), bottom),
               (cx, int(h * 0.52)),
               (cx - int(w * 0.06), bottom), (cx - int(w * 0.22), bottom)], fill=255)
    return m


def dress_mask(size=(W, H)):
    w, h = size
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    cx = w // 2
    top = int(h * 0.14)
    d.polygon([(cx - int(w * 0.16), top), (cx + int(w * 0.16), top),
               (cx + int(w * 0.19), int(h * 0.40)),
               (cx + int(w * 0.33), int(h * 0.90)),
               (cx - int(w * 0.33), int(h * 0.90)),
               (cx - int(w * 0.19), int(h * 0.40))], fill=255)
    d.ellipse([cx - int(w * 0.07), top - int(h * 0.008),
               cx + int(w * 0.07), top + int(h * 0.035)], fill=0)
    return m


# ---------------------------------------------------------------
# Backdrops
# ---------------------------------------------------------------

def tiled_floor():
    img = Image.new("RGB", (W, H), (208, 202, 192))
    d = ImageDraw.Draw(img)
    step = 150
    for x in range(0, W + step, step):
        d.line([(x, 0), (x, H)], fill=(176, 169, 158), width=5)
    for y in range(0, H + step, step):
        d.line([(0, y), (W, y)], fill=(176, 169, 158), width=5)
    a = np.asarray(img).astype(np.float32)
    a += rng.normal(0, 4, a.shape)          # grout speckle
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def wooden_floor():
    a = np.zeros((H, W, 3), np.float32)
    for y in range(H):
        plank = (y // 110) % 2
        base = np.array([150, 108, 70]) if plank else np.array([161, 118, 78])
        a[y] = base + np.sin(y * 0.9) * 5
    a += rng.normal(0, 6, a.shape)
    for y in range(0, H, 110):                # plank seams
        a[y:y + 3] *= 0.75
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def bedsheet():
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    folds = (np.sin(xx / 70 + np.sin(yy / 160)) * 16
             + np.sin(yy / 95) * 11)
    a = np.dstack([225 + folds, 222 + folds, 214 + folds]).astype(np.float32)
    a += rng.normal(0, 3, a.shape)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def patterned_throw():
    img = Image.new("RGB", (W, H), (196, 86, 72))
    d = ImageDraw.Draw(img)
    for y in range(-40, H + 40, 72):
        for x in range(-40, W + 40, 72):
            d.ellipse([x, y, x + 46, y + 46], fill=(232, 206, 150))
            d.rectangle([x + 20, y + 20, x + 32, y + 32], fill=(70, 96, 120))
    a = np.asarray(img).astype(np.float32) + rng.normal(0, 5, (H, W, 3))
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def near_white_surface():
    a = np.full((H, W, 3), 243, np.float32) + rng.normal(0, 3, (H, W, 3))
    yy = np.mgrid[0:H, 0:W][0].astype(np.float32)
    a -= ((yy / H) * 7)[:, :, None]          # gentle light falloff
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def dark_surface():
    a = np.full((H, W, 3), 38, np.float32) + rng.normal(0, 4, (H, W, 3))
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


# ---------------------------------------------------------------
# Garment appearance
# ---------------------------------------------------------------

def fabric(colour, pattern=None, wrinkle=14.0):
    a = np.zeros((H, W, 3), np.float32)
    a[:] = colour
    if pattern == "stripes":
        yy = np.mgrid[0:H, 0:W][0]
        a[(yy // 26) % 2 == 0] *= 0.72
    elif pattern == "floral":
        img = Image.fromarray(a.astype(np.uint8))
        d = ImageDraw.Draw(img)
        for y in range(0, H, 58):
            for x in range(0, W, 58):
                d.ellipse([x, y, x + 26, y + 26],
                          fill=tuple(int(c * 0.55) for c in colour))
        a = np.asarray(img).astype(np.float32)
    elif pattern == "logo":
        img = Image.fromarray(a.astype(np.uint8))
        d = ImageDraw.Draw(img)
        d.rectangle([W // 2 - 90, H // 2 - 50, W // 2 + 90, H // 2 + 50],
                    fill=tuple(int(255 - c) for c in colour))
        a = np.asarray(img).astype(np.float32)
    # wrinkle shading: low-frequency noise, so the garment is not flat
    noise = rng.normal(0, 1, (H // 16, W // 16))
    noise = np.asarray(Image.fromarray(noise.astype(np.float32), "F")
                       .resize((W, H), Image.BICUBIC))
    a += (noise * wrinkle)[:, :, None]
    a += rng.normal(0, 3, a.shape)
    return np.clip(a, 0, 255)


def compose(backdrop, mask_img, garment_rgb, shadow=True, blur=0.6,
            noise=3.0, brightness=1.0):
    bg = np.asarray(backdrop).astype(np.float32)
    m = np.asarray(mask_img).astype(np.float32) / 255.0

    if shadow:
        soft = np.asarray(mask_img.filter(ImageFilter.GaussianBlur(22))).astype(np.float32) / 255.0
        shifted = np.roll(np.roll(soft, 16, axis=0), 12, axis=1)
        bg *= (1 - 0.30 * np.clip(shifted - m, 0, 1))[:, :, None]

    out = bg * (1 - m[:, :, None]) + garment_rgb * m[:, :, None]
    out *= brightness
    out += rng.normal(0, noise, out.shape)
    img = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    return img


CASES = [
    # name, garment mask, backdrop, fabric colour, pattern, kwargs
    ("tshirt_tiled_floor",      tshirt_mask, tiled_floor,       (60, 110, 180),  None,     {}),
    ("tshirt_on_bed",           tshirt_mask, bedsheet,          (190, 70,  80),  None,     {}),
    ("tshirt_wooden_floor",     tshirt_mask, wooden_floor,      (235, 235, 232), None,     {}),
    ("tshirt_patterned_throw",  tshirt_mask, patterned_throw,   (40,  130, 110), None,     {}),
    ("tshirt_striped_floor",    tshirt_mask, tiled_floor,       (225, 225, 220), "stripes", {}),
    ("tshirt_logo_bed",         tshirt_mask, bedsheet,          (45,  45,  55),  "logo",   {}),
    ("white_tshirt_white_bed",  tshirt_mask, near_white_surface,(248, 248, 246), None,     {}),
    ("black_tshirt_dark_floor", tshirt_mask, dark_surface,      (28,  28,  32),  None,     {}),
    ("jeans_tiled_floor",       jeans_mask,  tiled_floor,       (58,  78,  118), None,     {}),
    ("jeans_wooden_floor",      jeans_mask,  wooden_floor,      (36,  48,  74),  None,     {}),
    ("dress_floral_bed",        dress_mask,  bedsheet,          (150, 60,  140), "floral", {}),
    ("dress_patterned_throw",   dress_mask,  patterned_throw,   (240, 215, 90),  None,     {}),
    ("tshirt_dim_light",        tshirt_mask, wooden_floor,      (90,  140, 200), None,
     {"brightness": 0.42, "noise": 7.0}),
    ("tshirt_phone_blur",       tshirt_mask, tiled_floor,       (200, 110, 60),  None,
     {"blur": 3.2, "noise": 6.0}),
]


def build(out_dir="bench"):
    import os
    os.makedirs(out_dir, exist_ok=True)
    made = []
    for name, mask_fn, bg_fn, colour, pattern, kwargs in CASES:
        mask = mask_fn()
        photo = compose(bg_fn(), mask, fabric(colour, pattern), **kwargs)
        photo.save(f"{out_dir}/{name}.png")
        mask.save(f"{out_dir}/{name}_truth.png")
        made.append(name)
    return made


if __name__ == "__main__":
    names = build()
    print(f"{len(names)} benchmark images written to bench/")
    for n in names:
        print("  ", n)

/*
 * PHOTOS FROM THE PHONE - one place for camera, gallery and checks.
 *
 * Inside the installed app (Capacitor) the phone's own camera and photo
 * picker are used: the rear camera opens by default, and the gallery
 * picker lets you tick several photos in one go. In a browser the same
 * functions fall back to ordinary file inputs, which the calling
 * component renders (a browser only opens a file picker from a real
 * tap, so the input has to live in the page).
 *
 * Every photo then goes through preparePhoto(): it must be an image,
 * not absurdly large, and is turned into an upright JPEG no bigger than
 * MAX_SIDE on its longest edge. That keeps uploads quick on mobile data
 * and means iPhone HEIC photos (which Safari can decode) arrive at the
 * server as JPEG. If the browser can't decode a file we keep the
 * original when it is a format the server accepts, and refuse it with
 * a clear message otherwise.
 */

import { IS_NATIVE_APP } from "../config";

export const MAX_PHOTOS = 10;               // per gallery pick / batch
export const MAX_SIDE = 2048;               // px, longest edge after preparing
export const MAX_INPUT_BYTES = 40 * 1024 * 1024; // refuse anything bigger outright
export const SERVER_MAX_BYTES = 15 * 1024 * 1024;
const JPEG_QUALITY = 0.9;
const SERVER_TYPES = ["image/jpeg", "image/png", "image/webp"];

let counter = 0;
const uid = () => `p${Date.now().toString(36)}${(counter += 1)}`;

export function isNative() {
  return IS_NATIVE_APP;
}

async function webPathToFile(webPath, format, name) {
  const res = await fetch(webPath);
  const blob = await res.blob();
  const ext = (format || "jpeg").toLowerCase().replace("jpg", "jpeg");
  const type = blob.type && blob.type.startsWith("image/") ? blob.type : `image/${ext}`;
  return new File([blob], `${name}.${ext === "jpeg" ? "jpg" : ext}`, { type });
}

// Native rear camera. Returns a File, or null if the user backed out.
export async function nativeTakePhoto({ front = false } = {}) {
  const { Camera, CameraSource, CameraResultType, CameraDirection } = await import("@capacitor/camera");
  try {
    const photo = await Camera.getPhoto({
      source: CameraSource.Camera,
      direction: front ? CameraDirection.Front : CameraDirection.Rear,
      resultType: CameraResultType.Uri,
      quality: 90,
      width: MAX_SIDE,
      correctOrientation: true,
      saveToGallery: false,
    });
    return webPathToFile(photo.webPath, photo.format, `camera-${Date.now()}`);
  } catch (err) {
    if (isCancel(err)) return null;
    throw friendlyNativeError(err);
  }
}

// Native multi-select gallery picker. Returns File[] (possibly empty).
export async function nativePickPhotos(limit = MAX_PHOTOS) {
  const { Camera } = await import("@capacitor/camera");
  try {
    const result = await Camera.pickImages({ quality: 90, width: MAX_SIDE, correctOrientation: true, limit });
    const photos = (result.photos || []).slice(0, limit);
    return Promise.all(photos.map((p, i) => webPathToFile(p.webPath, p.format, `gallery-${Date.now()}-${i}`)));
  } catch (err) {
    if (isCancel(err)) return [];
    throw friendlyNativeError(err);
  }
}

function isCancel(err) {
  const msg = String((err && err.message) || err || "").toLowerCase();
  return msg.includes("cancel") || msg.includes("no image picked") || msg.includes("no images picked");
}

function friendlyNativeError(err) {
  const msg = String((err && err.message) || err || "").toLowerCase();
  if (msg.includes("denied") || msg.includes("permission")) {
    return new Error("Camera or photo access is turned off for Wardrobe AI. Allow it in your phone's Settings → Apps → Wardrobe AI → Permissions.");
  }
  return new Error("Couldn't open the camera or gallery. Please try again.");
}

// ---------------------------------------------------------------------

function decode(file) {
  // createImageBitmap honours EXIF rotation with imageOrientation; not
  // available in old browsers (or tests) - then the caller keeps the file.
  if (typeof createImageBitmap !== "function") return Promise.resolve(null);
  return createImageBitmap(file, { imageOrientation: "from-image" }).catch(() =>
    createImageBitmap(file).catch(() => null));
}

/*
 * Returns { ok, file, width, height, warnings[], error }.
 * Never throws.
 */
export async function preparePhoto(file) {
  const warnings = [];
  if (!file) return { ok: false, error: "No photo was chosen." };
  const looksImage = (file.type || "").startsWith("image/") || /\.(heic|heif|jpe?g|png|webp)$/i.test(file.name || "");
  if (!looksImage) return { ok: false, error: `“${file.name || "That file"}” isn't a photo. Please choose a JPG, PNG, WEBP or HEIC image.` };
  if (file.size > MAX_INPUT_BYTES) return { ok: false, error: "That photo is over 40 MB. Please choose a smaller copy." };

  const bitmap = await decode(file);
  if (!bitmap) {
    // Couldn't decode here: send as-is if the server can read it.
    if (SERVER_TYPES.includes(file.type) && file.size <= SERVER_MAX_BYTES) return { ok: true, file, warnings };
    return { ok: false, error: "This photo format can't be opened on this device. Please choose a JPG or PNG." };
  }
  const { width: w0, height: h0 } = bitmap;
  const scale = Math.min(1, MAX_SIDE / Math.max(w0, h0));
  const needsWork = scale < 1 || !SERVER_TYPES.includes(file.type) || file.size > 4 * 1024 * 1024;
  if (Math.min(w0, h0) < 400) warnings.push("This photo is quite small, so details may be lost.");
  if (!needsWork) {
    bitmap.close && bitmap.close();
    return { ok: true, file, width: w0, height: h0, warnings };
  }
  try {
    const width = Math.round(w0 * scale);
    const height = Math.round(h0 * scale);
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(bitmap, 0, 0, width, height);
    bitmap.close && bitmap.close();
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", JPEG_QUALITY));
    if (!blob) throw new Error("encode");
    const base = (file.name || "photo").replace(/\.[^.]+$/, "") || "photo";
    return { ok: true, file: new File([blob], `${base}.jpg`, { type: "image/jpeg" }), width, height, warnings };
  } catch {
    if (SERVER_TYPES.includes(file.type) && file.size <= SERVER_MAX_BYTES) return { ok: true, file, warnings };
    return { ok: false, error: "Couldn't prepare this photo. Please try another one." };
  }
}

// Wraps a File into an entry for a selection tray.
export function makeEntry(file) {
  return { id: uid(), file, original: file, url: URL.createObjectURL(file), status: "ready", progress: 0, error: "", warnings: [] };
}

/*
 * Rotate (multiples of 90°) and/or crop an image into a new JPEG File.
 * `area` is in pixels of the ROTATED image (react-easy-crop's output
 * when its `rotation` prop is used).
 */
export async function renderEdit(src, { area, rotation = 0, name = "photo" }) {
  const img = await new Promise((resolve, reject) => {
    const el = new Image();
    el.onload = () => resolve(el);
    el.onerror = () => reject(new Error("This photo can't be edited on this device. Use it as it is, or choose another."));
    el.src = src;
  });
  const rad = (rotation * Math.PI) / 180;
  const sin = Math.abs(Math.sin(rad));
  const cos = Math.abs(Math.cos(rad));
  const rw = Math.round(img.naturalWidth * cos + img.naturalHeight * sin);
  const rh = Math.round(img.naturalWidth * sin + img.naturalHeight * cos);
  const full = document.createElement("canvas");
  full.width = rw;
  full.height = rh;
  const fctx = full.getContext("2d");
  fctx.translate(rw / 2, rh / 2);
  fctx.rotate(rad);
  fctx.drawImage(img, -img.naturalWidth / 2, -img.naturalHeight / 2);
  const a = area || { x: 0, y: 0, width: rw, height: rh };
  const out = document.createElement("canvas");
  out.width = Math.max(1, Math.round(a.width));
  out.height = Math.max(1, Math.round(a.height));
  out.getContext("2d").drawImage(full, a.x, a.y, a.width, a.height, 0, 0, out.width, out.height);
  const blob = await new Promise((resolve) => out.toBlob(resolve, "image/jpeg", 0.92));
  if (!blob) throw new Error("Couldn't save the edit - try again.");
  const base = (name || "photo").replace(/\.[^.]+$/, "") || "photo";
  return new File([blob], `${base}.jpg`, { type: "image/jpeg" });
}

/*
 * Quick, local checks for a try-on photo: too dark, too bright, sideways,
 * too small. Advice only - the server does the real check.
 */
export async function checkPersonPhoto(file) {
  const notes = [];
  const bitmap = await decode(file);
  if (!bitmap) return notes;
  const { width, height } = bitmap;
  if (width > height * 1.05) notes.push("This photo is sideways (landscape). A tall, portrait photo of your whole body works much better.");
  if (Math.min(width, height) < 512) notes.push("This photo is small - the try-on will look blurry. Use a sharper photo if you can.");
  try {
    const c = document.createElement("canvas");
    c.width = 48;
    c.height = 64;
    const ctx = c.getContext("2d");
    ctx.drawImage(bitmap, 0, 0, 48, 64);
    const { data } = ctx.getImageData(0, 0, 48, 64);
    let sum = 0;
    for (let i = 0; i < data.length; i += 4) sum += 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2];
    const mean = sum / (data.length / 4);
    if (mean < 70) notes.push("It looks quite dark. Face a window or turn on a light, then retake.");
    else if (mean > 225) notes.push("It looks very bright or washed out. Move away from direct sunlight behind you.");
  } catch { /* canvas not available - skip */ }
  bitmap.close && bitmap.close();
  return notes;
}

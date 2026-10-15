import { useRef, useState } from "react";
import { isNative, nativePickPhotos, nativeTakePhoto, MAX_PHOTOS } from "../lib/photos";
import { CameraIcon, GalleryIcon } from "./Icons";

/*
 * Two big buttons: "Take photo" and "Choose from gallery".
 *
 *   app      - the phone's own rear camera / multi-select photo picker
 *   browser  - <input capture="environment"> (rear camera on phones)
 *              and <input multiple> for the gallery
 *
 * onFiles(File[]) receives whatever was picked (already capped to
 * `limit`). Pass onCamera to replace the camera button's behaviour
 * (Virtual Try-On uses its in-app camera with a timer in browsers).
 */
export default function PhotoSource({
  onFiles, multiple = false, limit = MAX_PHOTOS, disabled = false, onCamera,
  cameraLabel = "Take photo", cameraHint = "Rear camera",
  galleryLabel = multiple ? "Choose from gallery" : "Choose a photo",
  galleryHint = multiple ? `Pick up to ${limit} at once` : "From your gallery or files",
  compact = false, inputTestId,
}) {
  const cameraInput = useRef(null);
  const galleryInput = useRef(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const deliver = (files) => {
    const list = Array.from(files || []).slice(0, multiple ? limit : 1);
    if (list.length) onFiles(list);
  };

  const run = async (fn) => {
    setError("");
    setBusy(true);
    try { await fn(); } catch (err) { setError(err.message); } finally { setBusy(false); }
  };

  const camera = () => {
    if (onCamera && !isNative()) return onCamera();
    if (isNative()) return run(async () => { const f = await nativeTakePhoto(); if (f) deliver([f]); });
    return cameraInput.current && cameraInput.current.click();
  };

  const gallery = () => {
    if (isNative()) return run(async () => deliver(await nativePickPhotos(multiple ? limit : 1)));
    return galleryInput.current && galleryInput.current.click();
  };

  const fromInput = (e) => {
    const files = e.target.files;
    deliver(files);
    e.target.value = "";
  };

  return (
    <div className={`ps ${compact ? "ps-compact" : ""}`}>
      <div className="ps-buttons">
        <button type="button" className="ps-btn ps-primary" onClick={camera} disabled={disabled || busy}>
          <span className="ps-ico"><CameraIcon width={26} height={26} /></span>
          <span className="ps-text"><strong>{cameraLabel}</strong>{!compact && <small>{cameraHint}</small>}</span>
        </button>
        <button type="button" className="ps-btn" onClick={gallery} disabled={disabled || busy}>
          <span className="ps-ico"><GalleryIcon width={26} height={26} /></span>
          <span className="ps-text"><strong>{galleryLabel}</strong>{!compact && <small>{galleryHint}</small>}</span>
        </button>
      </div>
      {error && <div className="aw-alert" role="alert">{error}</div>}
      <input ref={cameraInput} type="file" accept="image/*" capture="environment" hidden onChange={fromInput}
        aria-label="Take a photo" data-testid="camera-input" />
      <input ref={galleryInput} type="file" accept="image/*,.heic,.heif" multiple={multiple} hidden onChange={fromInput}
        aria-label="Choose photos" data-testid={inputTestId || "gallery-input"} />
    </div>
  );
}

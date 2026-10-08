import { useCallback, useEffect, useRef, useState } from "react";

/*
 * Take a person photo with the device camera, for Virtual Try-On.
 *
 * Nothing leaves this component until the user presses "Use This
 * Photo": then onUse(file) receives a plain JPEG File, which the page
 * sends through exactly the same upload path as a chosen file. Opening
 * the camera, capturing and retaking never call the server, so they
 * can't use up a try-on.
 *
 * The photo is not filtered, beautified or cropped: the full camera
 * frame is kept (only scaled down if larger than MAX_SIDE), and it is
 * saved un-mirrored - the preview is mirrored only while looking at
 * the front camera, because that is what people expect from a selfie
 * view.
 */

const MAX_SIDE = 2048;      // plenty for the try-on model, keeps uploads sane
const JPEG_QUALITY = 0.92;  // high - VTO quality matters more than bytes

export const CAMERA_UNAVAILABLE =
  "Camera access isn't available. You can upload a photo instead.";

function cameraErrorMessage(err) {
  const name = err && err.name;
  if (name === "NotAllowedError" || name === "SecurityError") {
    return "Camera permission was blocked. You can allow it in your browser's site settings, or upload a photo instead.";
  }
  if (name === "NotFoundError" || name === "OverconstrainedError" || name === "DevicesNotFoundError") {
    return "No camera was found on this device. You can upload a photo instead.";
  }
  if (name === "NotReadableError" || name === "TrackStartError") {
    return "The camera is being used by another app. Close it and try again, or upload a photo instead.";
  }
  return CAMERA_UNAVAILABLE;
}

export function cameraSupported() {
  return Boolean(
    typeof navigator !== "undefined" &&
      navigator.mediaDevices &&
      typeof navigator.mediaDevices.getUserMedia === "function" &&
      (typeof window === "undefined" || window.isSecureContext !== false)
  );
}

export default function CameraCapture({ onUse, onCancel, onUnavailable, disabled }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const timerRef = useRef(null);

  const [facing, setFacing] = useState("user");
  const [starting, setStarting] = useState(true);
  const [error, setError] = useState("");
  const [captured, setCaptured] = useState(null); // { blob, url, width, height }
  const [useTimer, setUseTimer] = useState(true);
  const [countdown, setCountdown] = useState(0);

  const stopStream = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
  }, []);

  const startStream = useCallback(async (mode) => {
    stopStream();
    setStarting(true);
    setError("");
    if (!cameraSupported()) {
      setStarting(false);
      setError(CAMERA_UNAVAILABLE);
      if (onUnavailable) onUnavailable(CAMERA_UNAVAILABLE);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: mode },
          // Ask for portrait at a good size; the browser picks the
          // nearest the camera supports. Nothing is cropped either way.
          width: { ideal: 1080 },
          height: { ideal: 1920 },
        },
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        try { await videoRef.current.play(); } catch (_) { /* autoplay hiccup - stream still shows */ }
      }
      setStarting(false);
    } catch (err) {
      setStarting(false);
      const message = cameraErrorMessage(err);
      setError(message);
      if (onUnavailable) onUnavailable(message);
    }
  }, [onUnavailable, stopStream]);

  useEffect(() => {
    startStream(facing);
    return () => {
      stopStream();
      if (timerRef.current) clearInterval(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [facing]);

  // Free the captured preview's memory when it is replaced or dropped.
  useEffect(() => () => { if (captured) URL.revokeObjectURL(captured.url); }, [captured]);

  const takeShot = () => {
    const video = videoRef.current;
    if (!video || !video.videoWidth || !video.videoHeight) {
      setError("Couldn't capture a photo - the camera isn't ready yet. Please try again.");
      return;
    }
    const scale = Math.min(1, MAX_SIDE / Math.max(video.videoWidth, video.videoHeight));
    const width = Math.round(video.videoWidth * scale);
    const height = Math.round(video.videoHeight * scale);
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(video, 0, 0, width, height); // un-mirrored, uncropped, unfiltered
    canvas.toBlob((blob) => {
      if (!blob || blob.size < 1000) {
        setError("Couldn't capture a photo. Please try again.");
        return;
      }
      setCaptured({ blob, url: URL.createObjectURL(blob), width, height });
      stopStream(); // camera light off while previewing
    }, "image/jpeg", JPEG_QUALITY);
  };

  const capture = () => {
    setError("");
    if (!useTimer) return takeShot();
    let left = 5;
    setCountdown(left);
    timerRef.current = setInterval(() => {
      left -= 1;
      if (left <= 0) {
        clearInterval(timerRef.current);
        timerRef.current = null;
        setCountdown(0);
        takeShot();
      } else {
        setCountdown(left);
      }
    }, 1000);
  };

  const retake = () => {
    setCaptured(null);
    startStream(facing);
  };

  const usePhoto = () => {
    if (!captured) return;
    const file = new File([captured.blob], `camera-${Date.now()}.jpg`, { type: "image/jpeg" });
    stopStream();
    onUse(file);
  };

  const cancel = () => {
    if (timerRef.current) clearInterval(timerRef.current);
    stopStream();
    onCancel();
  };

  return (
    <div className="tryon-camera" data-testid="camera-capture">
      <p className="tryon-camera-title">{captured ? "Your photo" : "Take your photo"}</p>

      {error ? (
        <div className="aw-alert" role="alert" data-testid="camera-error">
          {error}
          <div className="aw-actions-row" style={{ marginTop: 10 }}>
            <button type="button" className="aw-btn aw-btn-soft aw-btn-sm" onClick={() => startStream(facing)}>
              Try camera again
            </button>
            <button type="button" className="aw-btn aw-btn-sm" onClick={cancel}>
              Upload a photo instead
            </button>
          </div>
        </div>
      ) : captured ? (
        <>
          <div className="tryon-camera-frame">
            <img src={captured.url} alt="You, as just captured" data-testid="camera-captured" />
          </div>
          <p className="aw-hint">Check that your whole body and face are clear.</p>
          <div className="tryon-camera-actions">
            <button type="button" className="aw-btn aw-btn-soft" onClick={retake} disabled={disabled}>
              ↺ Retake
            </button>
            <button type="button" className="aw-btn" onClick={usePhoto} disabled={disabled}>
              ✓ Use This Photo
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="tryon-camera-frame">
            <video
              ref={videoRef}
              playsInline
              muted
              autoPlay
              className={facing === "user" ? "mirrored" : ""}
              data-testid="camera-video"
            />
            <div className="tryon-camera-guide" aria-hidden="true" />
            {starting && <div className="tryon-camera-overlay"><span className="aw-spinner" /> Starting camera…</div>}
            {countdown > 0 && <div className="tryon-camera-overlay tryon-camera-count">{countdown}</div>}
          </div>
          <p className="aw-hint">Stand facing the camera and make sure your full body is visible.</p>
          <label className="tryon-camera-timer">
            <input type="checkbox" checked={useTimer} onChange={(e) => setUseTimer(e.target.checked)} />
            5-second timer (time to step back)
          </label>
          <div className="tryon-camera-actions">
            <button type="button" className="aw-btn aw-btn-ghost aw-btn-sm" onClick={cancel}>Cancel</button>
            <button
              type="button"
              className="aw-btn aw-btn-soft aw-btn-sm"
              onClick={() => setFacing((f) => (f === "user" ? "environment" : "user"))}
              disabled={starting || countdown > 0}
            >
              ⇄ Switch camera
            </button>
            <button type="button" className="aw-btn" onClick={capture} disabled={starting || countdown > 0 || disabled}>
              📸 Capture Photo
            </button>
          </div>
        </>
      )}
    </div>
  );
}

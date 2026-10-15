import { useState } from "react";
import Cropper from "react-easy-crop";
import { renderEdit } from "../lib/photos";
import { RotateIcon } from "./Icons";

/*
 * Crop + rotate one photo. Nothing is uploaded here: onDone(file)
 * receives a new JPEG (or the untouched original if nothing changed).
 */
export default function PhotoEditor({
  src, file, onDone, onCancel, shapes = [["whole", "Original"], ["portrait", "3:4"], ["square", "Square"]],
  doneLabel = "Done", cancelLabel = "Cancel", guide = null,
}) {
  const [crop, setCrop] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [natural, setNatural] = useState(3 / 4);
  const [shape, setShape] = useState(shapes[0][0]);
  const [area, setArea] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const rotated = rotation % 180 !== 0;
  const wholeAspect = rotated ? 1 / natural : natural;
  const aspect = shape === "square" ? 1 : shape === "portrait" ? 3 / 4 : wholeAspect;
  const untouched = rotation === 0 && zoom === 1 && shape === shapes[0][0] && shapes[0][0] === "whole";

  const done = async () => {
    if (untouched) return onDone(file);
    setSaving(true);
    setError("");
    try {
      onDone(await renderEdit(src, { area, rotation, name: file && file.name }));
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  };

  return (
    <div className="pe">
      <div className="pe-stage">
        <Cropper image={src} crop={crop} zoom={zoom} rotation={rotation} aspect={aspect}
          onMediaLoaded={(m) => m.naturalWidth && m.naturalHeight && setNatural(m.naturalWidth / m.naturalHeight)}
          onCropChange={setCrop} onCropComplete={(_, px) => setArea(px)} onZoomChange={setZoom}
          objectFit="contain" />
        {guide}
      </div>
      <div className="pe-tools">
        <div className="pe-shapes" role="group" aria-label="Crop shape">
          {shapes.map(([key, label]) => (
            <button type="button" key={key} aria-pressed={shape === key} className={`pe-chip ${shape === key ? "on" : ""}`}
              onClick={() => { setShape(key); setZoom(1); setCrop({ x: 0, y: 0 }); }}>{label}</button>
          ))}
          <button type="button" className="pe-chip pe-rotate" aria-label="Rotate 90 degrees"
            onClick={() => { setRotation((r) => (r + 90) % 360); setCrop({ x: 0, y: 0 }); }}>
            <RotateIcon width={18} height={18} /> Rotate
          </button>
        </div>
        <label className="pe-zoom">
          <span>Zoom</span>
          <input type="range" min="1" max="3" step="0.05" value={zoom} onChange={(e) => setZoom(Number(e.target.value))} />
        </label>
      </div>
      {error && <div className="aw-alert" role="alert">{error}</div>}
      <div className="pe-actions">
        <button type="button" className="aw-btn aw-btn-soft" onClick={onCancel} disabled={saving}>{cancelLabel}</button>
        <button type="button" className="aw-btn" onClick={done} disabled={saving}>{saving ? "Saving…" : doneLabel}</button>
      </div>
    </div>
  );
}

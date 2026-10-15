import { useEffect, useRef, useState, useCallback } from "react";
import axios from "axios";
import { useLocation, useNavigate } from "react-router-dom";
import Layout from "../components/Layout";
import { ProfileChip } from "../components/PageHeader";
import { PlusIcon, SearchIcon, CloseIcon, HeartIcon, CameraIcon } from "../components/Icons";
import PhotoSource from "../components/PhotoSource";
import PhotoEditor from "../components/PhotoEditor";
import { preparePhoto, makeEntry, MAX_PHOTOS } from "../lib/photos";
import "../styles/aw-v2.css";
import "../styles/studio.css";
import { API_URL, assetUrl } from "../config";
import {
  authGet, apiErrorMessage, isAuthError, itemMeta, swatch, OCCASIONS, occasionLabel,
} from "../lib/api";
import { useCategories, hasFlag, groupsFor } from "../lib/categories";

// Category <select> built from the account's own (gender-specific)
// catalogue, grouped Tops / Bottoms / Traditional / Footwear...
function CategoryOptions({ sections, current }) {
  const known = sections.some((s) => s.categories.some((c) => c.value === current));
  return (
    <>
      {sections.map((section) => (
        <optgroup key={section.name} label={section.name}>
          {section.categories.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </optgroup>
      ))}
      {current && !known && <option value={current}>{current} (older category)</option>}
    </>
  );
}

/*
 * MY WARDROBE
 *
 * Upload flow (Add New Item):
 *   1 Photo -> 2 Crop -> 3 Details (category, colour) -> Save
 * The photo, cropped in the browser, is sent to POST /api/wardrobe/add.
 * The backend validates it, recognises the category (when the trained
 * classifier is available), stores the image in Cloudinary and saves the
 * item to the logged-in user's wardrobe, then this page refreshes.
 */

function authHeaders() {
  const token = localStorage.getItem("token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// ---------------------------------------------------------------------
// One upload. Shared by the single-photo and the several-photos flows,
// so both send exactly the same form to POST /api/wardrobe/add.
// ---------------------------------------------------------------------
async function uploadItem(file, fields, onProgress) {
  const form = new FormData();
  form.append("image", file);
  form.append("category", fields.category || "");
  form.append("category_explicit", fields.category ? "true" : "false");
  if ((fields.color || "").trim()) form.append("color", fields.color.trim());
  if ((fields.material || "").trim()) form.append("material", fields.material.trim());
  if (fields.styling) form.append("styling", fields.styling);
  const res = await axios.post(`${API_URL}/api/wardrobe/add`, form, {
    headers: authHeaders(),
    timeout: 180000,
    onUploadProgress: (e) => {
      if (onProgress && e.total) onProgress(Math.min(100, Math.round((e.loaded / e.total) * 100)));
    },
  });
  return res.data;
}

function progressLabel(pct, hasCategory) {
  if (pct < 100) return hasCategory ? `Uploading… ${pct}%` : `Uploading… ${pct}% — then recognising your item`;
  return hasCategory ? "Cleaning background & saving…" : "Cleaning background & recognising your item…";
}

function ProgressBar({ pct, label }) {
  return (
    <div className="up-progress" role="status">
      <div className="up-bar"><span style={{ width: `${pct < 100 ? Math.max(4, pct) : 100}%` }} className={pct >= 100 ? "busy" : ""} /></div>
      <div className="up-label"><span className="aw-spinner" /> {label}</div>
    </div>
  );
}

const STATUS_TEXT = {
  ready: "Ready", uploading: "Uploading", processing: "Processing", done: "Added", failed: "Failed", choose: "Pick the type",
};

function AddItemModal({ onClose, onSaved, sections, autoCategory, categoryError }) {
  // photo -> (one photo) crop -> details
  // photo -> (several)   review -> batch
  const [step, setStep] = useState("photo");
  const [entries, setEntries] = useState([]);
  const [editing, setEditing] = useState(null); // entry id being cropped in the tray
  const [replacing, setReplacing] = useState(null);
  const [preparing, setPreparing] = useState(false);
  const [pickNotes, setPickNotes] = useState([]);

  // single-photo details
  const [category, setCategory] = useState("");
  const [color, setColor] = useState("");
  const [material, setMaterial] = useState("");
  const [styling, setStyling] = useState("");
  const [status, setStatus] = useState("idle"); // idle | saving | saved
  const [pct, setPct] = useState(0);
  const [error, setError] = useState("");
  const busy = useRef(false);
  const [choices, setChoices] = useState([]);
  const [results, setResults] = useState([]);

  useEffect(() => () => entries.forEach((e) => URL.revokeObjectURL(e.url)), []); // eslint-disable-line react-hooks/exhaustive-deps

  const patch = (id, changes) => setEntries((list) => list.map((e) => (e.id === id ? { ...e, ...changes } : e)));

  // Files from the camera / gallery -> checked, resized entries.
  const addFiles = async (files) => {
    setError("");
    setPreparing(true);
    const room = MAX_PHOTOS - (replacing ? entries.length - 1 : entries.length);
    const notes = [];
    if (files.length > room) notes.push(`Only ${room} more photo${room === 1 ? "" : "s"} fit in one go - the rest were left out.`);
    const fresh = [];
    for (const f of files.slice(0, Math.max(0, room))) {
      // eslint-disable-next-line no-await-in-loop
      const ready = await preparePhoto(f);
      if (!ready.ok) notes.push(ready.error);
      else fresh.push({ ...makeEntry(ready.file), warnings: ready.warnings || [], fields: { category: "", color: "", material: "", styling: "" } });
    }
    setPreparing(false);
    setPickNotes(notes);
    if (!fresh.length) {
      if (notes.length) setError(notes[0]);
      return;
    }
    if (replacing) {
      setEntries((list) => list.map((e) => (e.id === replacing ? { ...fresh[0], fields: e.fields } : e)));
      setReplacing(null);
      return;
    }
    const all = [...entries, ...fresh];
    setEntries(all);
    if (step === "photo" && all.length === 1) setStep("crop");
    else setStep("review");
  };

  const removeEntry = (id) => {
    setEntries((list) => {
      const next = list.filter((e) => e.id !== id);
      if (!next.length) setStep("photo");
      return next;
    });
  };

  const single = entries[0];

  const finishSingleCrop = (file) => {
    if (file !== single.file) patch(single.id, { file, url: URL.createObjectURL(file) });
    setStep("details");
  };

  // ---------------- single photo save ----------------
  const save = async () => {
    if (busy.current) return; // never two uploads at once
    if (!single) {
      setError("Please choose a photo first.");
      return;
    }
    if (!category && !autoCategory) {
      setError("Please choose a category.");
      return;
    }
    busy.current = true;
    setStatus("saving");
    setPct(0);
    setError("");
    try {
      const data = await uploadItem(single.file, { category, color, material, styling }, setPct);
      setStatus("saved");
      setTimeout(() => onSaved(data), 900);
    } catch (err) {
      busy.current = false;
      setStatus("idle");
      const body = err?.response?.data;
      if (err?.response?.status === 422 && body?.options?.length) {
        // The AI can only narrow it down: the user picks the exact type.
        setChoices(body.options);
        setCategory(body.guess || "");
        setError(`${body.message} Then press "Add to wardrobe" again.`);
        return;
      }
      setError(apiErrorMessage(err, "Upload"));
      if (isAuthError(err)) setTimeout(() => onSaved(null, "auth"), 1800);
    }
  };

  // ---------------- several photos ----------------
  const uploadAll = async (onlyIds) => {
    if (busy.current) return;
    const todo = entries.filter((e) => (onlyIds ? onlyIds.includes(e.id) : e.status !== "done"));
    const missing = todo.find((e) => !e.fields.category && !autoCategory);
    if (missing) {
      setError("Please choose a category for every photo (automatic recognition isn't available right now).");
      return;
    }
    busy.current = true;
    setError("");
    setStep("batch");
    const done = [];
    for (const entry of todo) {
      patch(entry.id, { status: "uploading", progress: 0, error: "" });
      try {
        // eslint-disable-next-line no-await-in-loop
        const data = await uploadItem(entry.file, entry.fields, (p) => patch(entry.id, { progress: p, status: p >= 100 ? "processing" : "uploading" }));
        patch(entry.id, { status: "done", progress: 100, result: data });
        done.push(data);
      } catch (err) {
        const body = err?.response?.data;
        if (err?.response?.status === 422 && body?.options?.length) {
          patch(entry.id, { status: "choose", options: body.options, error: body.message, fields: { ...entry.fields, category: body.guess || "" } });
        } else {
          patch(entry.id, { status: "failed", error: apiErrorMessage(err, "Upload") });
          if (isAuthError(err)) { busy.current = false; return onSaved(null, "auth"); }
        }
      }
    }
    busy.current = false;
    setResults((r) => [...r, ...done]);
  };

  const setField = (id, key, value) => setEntries((list) => list.map((e) => (e.id === id ? { ...e, fields: { ...e.fields, [key]: value } } : e)));

  const batchRunning = entries.some((e) => e.status === "uploading" || e.status === "processing");
  const batchDone = step === "batch" && !batchRunning && entries.length > 0 && entries.every((e) => e.status === "done");
  const doneCount = entries.filter((e) => e.status === "done").length;
  const redo = entries.filter((e) => e.status === "failed" || e.status === "choose").map((e) => e.id);

  const finishBatch = () => onSaved({ batch: true, count: doneCount, results });

  const stepIndex = { photo: 0, crop: 1, review: 1, details: 2, batch: 2 }[step];
  const saving = status === "saving";
  const locked = saving || batchRunning;
  const editingEntry = entries.find((e) => e.id === editing);
  const close = () => (doneCount && step === "batch" ? finishBatch() : onClose());

  return (
    <div className="aw-overlay center sheet" onClick={() => !locked && close()}>
      <div className="aw-modal aw-add" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Add New Item">
        <div className="sheet-grip" aria-hidden="true" />
        <button type="button" className="aw-close" onClick={close} disabled={locked} aria-label="Close">×</button>
        <h2 className="aw-add-title">{entries.length > 1 ? `Add ${entries.length} items` : "Add New Item"}</h2>
        <ol className="aw-steps">
          {["Photo", entries.length > 1 ? "Review" : "Crop", "Details"].map((label, i) => (
            <li key={label} className={i === stepIndex ? "on" : i < stepIndex ? "done" : ""}>
              <span>{i < stepIndex ? "✓" : i + 1}</span>{label}
            </li>
          ))}
        </ol>

        {step === "photo" && (
          <>
            <PhotoSource multiple onFiles={addFiles} disabled={preparing} />
            {preparing && <div className="aw-progress"><span className="aw-spinner" /> Preparing photos…</div>}
            <ul className="up-tips">
              <li><strong>One garment per photo.</strong> Lay it flat or hang it up.</li>
              <li><strong>Any background is fine</strong> — the floor, bed or a chair. It's removed for you.</li>
              <li><strong>Contrast helps:</strong> put a white top on something darker.</li>
            </ul>
          </>
        )}

        {step === "crop" && single && (
          <PhotoEditor key={single.id} src={single.url} file={single.file} onDone={finishSingleCrop}
            onCancel={() => setStep("details")} cancelLabel="Skip crop" doneLabel="Use this crop" />
        )}

        {step === "review" && !editingEntry && (
          <>
            <p className="up-count"><strong>{entries.length}</strong> of {MAX_PHOTOS} photos selected · tap a photo to crop or rotate it</p>
            <div className="up-tray">
              {entries.map((e, i) => (
                <div key={e.id} className="up-thumb">
                  <button type="button" className="up-thumb-img" onClick={() => setEditing(e.id)} aria-label={`Crop or rotate photo ${i + 1}`}>
                    <img src={e.url} alt={`Selected ${i + 1}`} />
                    <span className="up-num">{i + 1}</span>
                  </button>
                  <button type="button" className="up-x" onClick={() => removeEntry(e.id)} aria-label={`Remove photo ${i + 1}`}><CloseIcon width={16} height={16} /></button>
                  <button type="button" className="up-swap" onClick={() => setReplacing(e.id)}>Replace</button>
                  {e.warnings.length > 0 && <span className="up-warn" title={e.warnings[0]}>!</span>}
                </div>
              ))}
              {entries.length < MAX_PHOTOS && (
                <div className="up-thumb up-add">
                  <PhotoSource multiple compact limit={MAX_PHOTOS - entries.length} onFiles={addFiles}
                    cameraLabel="Camera" galleryLabel="Gallery" disabled={preparing} />
                </div>
              )}
            </div>
            {replacing && (
              <div className="up-replace">
                <p>Replace photo {entries.findIndex((e) => e.id === replacing) + 1} with:</p>
                <PhotoSource onFiles={addFiles} compact cameraLabel="Camera" galleryLabel="Gallery" />
                <button type="button" className="aw-link" onClick={() => setReplacing(null)}>Keep the current photo</button>
              </div>
            )}
            {pickNotes.length > 0 && <div className="aw-note">{pickNotes.map((n) => <div key={n}>{n}</div>)}</div>}
          </>
        )}

        {step === "review" && editingEntry && (
          <PhotoEditor key={editingEntry.id} src={editingEntry.url} file={editingEntry.file}
            onDone={(file) => { if (file !== editingEntry.file) patch(editingEntry.id, { file, url: URL.createObjectURL(file) }); setEditing(null); }}
            onCancel={() => setEditing(null)} />
        )}

        {step === "details" && single && (
          <div className="aw-details">
            <div className="aw-details-imgwrap">
              <img src={single.url} alt="Your item" className="aw-details-img" />
              {!saving && status !== "saved" && (
                <button type="button" className="up-change" onClick={() => setStep("crop")}>Crop / rotate</button>
              )}
            </div>
            <div className="aw-details-fields">
              <label className="aw-label">Category</label>
              <select className="aw-select" value={category} onChange={(e) => setCategory(e.target.value)} disabled={saving}>
                {autoCategory
                  ? <option value="">✨ Let AI recognise it</option>
                  : <option value="">Choose a category…</option>}
                <CategoryOptions sections={sections} />
              </select>
              {!sections.length && (
                <p className="aw-hint" role="status">{categoryError || "Loading your wardrobe categories…"}</p>
              )}
              {choices.length > 0 && (
                <div className="aw-chips" role="group" aria-label="Choose the exact type">
                  {choices.map((c) => (
                    <button type="button" key={c.value}
                      className={`aw-chip ${category === c.value ? "on" : ""}`}
                      onClick={() => setCategory(c.value)} disabled={saving}>{c.label}</button>
                  ))}
                </div>
              )}
              {!autoCategory && (
                <p className="aw-hint">Automatic recognition isn't available right now, so please pick the category.</p>
              )}
              <label className="aw-label">Colour</label>
              <input className="aw-input" placeholder="e.g. black, navy, dusty pink" value={color}
                onChange={(e) => setColor(e.target.value)} disabled={saving} />
              <p className="aw-hint">Leave blank and it's read from the photo.</p>
              {hasFlag(sections, category, "material") && (
                <>
                  <label className="aw-label">Material (optional)</label>
                  <input className="aw-input" placeholder="e.g. leather, gold, wool" value={material}
                    onChange={(e) => setMaterial(e.target.value)} disabled={saving} />
                </>
              )}
              {hasFlag(sections, category, "styling") && (
                <>
                  <label className="aw-label">Styling (optional)</label>
                  <select className="aw-select" value={styling} onChange={(e) => setStyling(e.target.value)} disabled={saving}>
                    <option value="">Not specified</option>
                    <option value="Casual">Casual</option>
                    <option value="Wedding/Festive">Wedding / Festive</option>
                  </select>
                </>
              )}
            </div>
          </div>
        )}

        {step === "batch" && (
          <div className="up-list">
            {entries.map((e, i) => (
              <div key={e.id} className={`up-row ${e.status}`}>
                <img src={e.url} alt={`Item ${i + 1}`} />
                <div className="up-row-body">
                  <div className="up-row-top">
                    <strong>Item {i + 1}</strong>
                    <span className={`up-badge ${e.status}`}>{e.status === "done" ? `✓ ${e.result?.category || "Added"}` : STATUS_TEXT[e.status]}</span>
                  </div>
                  {(e.status === "uploading" || e.status === "processing") && (
                    <ProgressBar pct={e.progress} label={progressLabel(e.progress, Boolean(e.fields.category))} />
                  )}
                  {(e.status === "ready" || e.status === "failed" || e.status === "choose") && (
                    <>
                      <select className="aw-select" value={e.fields.category} aria-label={`Category for item ${i + 1}`}
                        onChange={(ev) => setField(e.id, "category", ev.target.value)}>
                        {autoCategory ? <option value="">✨ Let AI recognise it</option> : <option value="">Choose a category…</option>}
                        <CategoryOptions sections={sections} current={e.fields.category} />
                      </select>
                      <input className="aw-input" placeholder="Colour (optional)" value={e.fields.color}
                        aria-label={`Colour for item ${i + 1}`} onChange={(ev) => setField(e.id, "color", ev.target.value)} />
                    </>
                  )}
                  {e.status === "choose" && e.options && (
                    <div className="aw-chips" role="group" aria-label={`Exact type for item ${i + 1}`}>
                      {e.options.map((c) => (
                        <button type="button" key={c.value} className={`aw-chip ${e.fields.category === c.value ? "on" : ""}`}
                          onClick={() => setField(e.id, "category", c.value)}>{c.label}</button>
                      ))}
                    </div>
                  )}
                  {e.error && <p className="up-err">{e.error}</p>}
                </div>
              </div>
            ))}
          </div>
        )}

        {error && <div className="aw-alert" role="alert">{error}</div>}
        {status === "saving" && <ProgressBar pct={pct} label={progressLabel(pct, Boolean(category))} />}
        {status === "saved" && <div className="aw-success">✓ Added to your wardrobe</div>}
        {batchDone && <div className="aw-success">✓ All {doneCount} items added to your wardrobe</div>}

        <div className="aw-modal-actions">
          {step === "photo" && <button type="button" className="aw-btn aw-btn-soft" onClick={onClose}>Cancel</button>}
          {step === "details" && (
            <>
              <button type="button" className="aw-btn aw-btn-ghost" onClick={() => { setEntries([]); setStep("photo"); setChoices([]); }} disabled={saving || status === "saved"}>Change photo</button>
              <button type="button" className="aw-btn" onClick={save} disabled={saving || status === "saved"}>
                {saving ? "Saving…" : "Add to Wardrobe"}
              </button>
            </>
          )}
          {step === "review" && !editingEntry && (
            <>
              <button type="button" className="aw-btn aw-btn-soft" onClick={onClose}>Cancel</button>
              <button type="button" className="aw-btn" onClick={() => { setStep("batch"); setError(""); }} disabled={preparing || !entries.length}>
                Next · {entries.length} photo{entries.length === 1 ? "" : "s"}
              </button>
            </>
          )}
          {step === "batch" && !batchRunning && !batchDone && (
            <>
              {doneCount === 0 && <button type="button" className="aw-btn aw-btn-ghost" onClick={() => setStep("review")}>Back</button>}
              {doneCount > 0 && <button type="button" className="aw-btn aw-btn-soft" onClick={finishBatch}>Finish ({doneCount} added)</button>}
              <button type="button" className="aw-btn" onClick={() => uploadAll(doneCount ? redo : null)}>
                {doneCount ? `Retry ${redo.length}` : `Upload ${entries.length} item${entries.length === 1 ? "" : "s"}`}
              </button>
            </>
          )}
          {step === "batch" && batchRunning && (
            <p className="up-count">Uploading {entries.filter((e) => e.status === "done").length + 1} of {entries.length}… keep the app open.</p>
          )}
          {batchDone && <button type="button" className="aw-btn" onClick={finishBatch}>Done</button>}
        </div>
      </div>
    </div>
  );
}

function EditItemModal({ item, sections, onClose, onSaved }) {
  const [category, setCategory] = useState(item.category || "");
  const [color, setColor] = useState(item.color || "");
  const [material, setMaterial] = useState(item.material || "");
  const [occasion, setOccasion] = useState(item.occasion || "");
  const [styling, setStyling] = useState(item.styling || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    setSaving(true);
    setError("");
    try {
      await axios.put(`${API_URL}/api/wardrobe/${item._id}`,
        { category, color, material, occasion, styling }, { headers: authHeaders() });
      onSaved();
    } catch (err) {
      setError(apiErrorMessage(err, "Saving"));
      setSaving(false);
    }
  };

  return (
    <div className="aw-overlay center" onClick={() => !saving && onClose()}>
      <div className="aw-modal aw-add" onClick={(e) => e.stopPropagation()}>
        <button type="button" className="aw-close" onClick={onClose}>×</button>
        <h2 className="aw-add-title">Edit item</h2>
        <div className="aw-details">
          <img src={assetUrl(item.image_path)} alt={item.display_name} className="aw-details-img" />
          <div className="aw-details-fields">
            <label className="aw-label">Category</label>
            <select className="aw-select" value={category} onChange={(e) => setCategory(e.target.value)}>
              <CategoryOptions sections={sections} current={category} />
            </select>
            <label className="aw-label">Colour</label>
            <input className="aw-input" value={color} onChange={(e) => setColor(e.target.value)} />
            {hasFlag(sections, category, "material") && (
              <>
                <label className="aw-label">Material</label>
                <input className="aw-input" value={material} onChange={(e) => setMaterial(e.target.value)} />
              </>
            )}
            {hasFlag(sections, category, "styling") && (
              <>
                <label className="aw-label">Styling</label>
                <select className="aw-select" value={styling} onChange={(e) => setStyling(e.target.value)}>
                  <option value="">Not specified</option>
                  <option value="Casual">Casual</option>
                  <option value="Wedding/Festive">Wedding / Festive</option>
                </select>
              </>
            )}
            <label className="aw-label">Also suitable for (optional)</label>
            <select className="aw-select" value={occasion} onChange={(e) => setOccasion(e.target.value)}>
              <option value="">Automatic (recommended)</option>
              {OCCASIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
        </div>
        {error && <div className="aw-alert">{error}</div>}
        <div className="aw-modal-actions">
          <button type="button" className="aw-btn aw-btn-soft" onClick={onClose} disabled={saving}>Cancel</button>
          <button type="button" className="aw-btn" onClick={save} disabled={saving}>{saving ? "Saving…" : "Save changes"}</button>
        </div>
      </div>
    </div>
  );
}

function Wardrobe() {
  const navigate = useNavigate();
  const location = useLocation();
  // Gender and categories come from the account on the server.
  const { sections, gender, error: categoryError } = useCategories();
  const [items, setItems] = useState([]);
  const [lastWorn, setLastWorn] = useState({});
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [autoCategory, setAutoCategory] = useState(false);
  const [search, setSearch] = useState("");
  const [group, setGroup] = useState("");
  const [colour, setColour] = useState("");
  const [occasion, setOccasion] = useState("");
  const [sortBy, setSortBy] = useState("recent");
  const [showAdd, setShowAdd] = useState(false);
  const [editing, setEditing] = useState(null);
  const [detail, setDetail] = useState(null);
  const [toast, setToast] = useState("");
  const [suggestion, setSuggestion] = useState(null);
  const [showFilters, setShowFilters] = useState(false);

  // The phone tab bar's big "+" lands here with { add: true }.
  useEffect(() => {
    if (location.state && location.state.add) {
      setShowAdd(true);
      navigate(location.pathname, { replace: true, state: {} });
    }
  }, [location.state, location.pathname, navigate]);

  const goLogin = useCallback(() => {
    localStorage.removeItem("token");
    navigate("/login");
  }, [navigate]);

  const fetchItems = useCallback(async () => {
    try {
      const data = await authGet("/api/wardrobe");
      setItems(data.items || []);
      // "Last worn 12 days ago" (Outfit Calendar). Optional - a failure
      // here must never stop the wardrobe from showing.
      authGet("/api/wardrobe/last-worn").then((d) => setLastWorn(d.last_worn || {})).catch(() => {});
      setLoadError("");
    } catch (err) {
      if (isAuthError(err)) goLogin();
      else setLoadError(apiErrorMessage(err, "Loading your wardrobe"));
    } finally {
      setLoaded(true);
    }
  }, [goLogin]);

  useEffect(() => {
    if (!localStorage.getItem("token")) {
      navigate("/login");
      return;
    }
    fetchItems();
    authGet("/api/wardrobe/capabilities")
      .then((d) => setAutoCategory(Boolean(d.auto_category)))
      .catch(() => setAutoCategory(false));
  }, [fetchItems, navigate]);

  const flash = (message) => {
    setToast(message);
    setTimeout(() => setToast(""), 3500);
  };

  const onSaved = (data, problem) => {
    if (problem === "auth") return goLogin();
    setShowAdd(false);
    fetchItems();
    if (data?.batch) {
      if (data.count) flash(`Added ${data.count} item${data.count === 1 ? "" : "s"} to your wardrobe.`);
      return;
    }
    if (data?.needs_confirmation && data.suggested_category) {
      setSuggestion({ itemId: data.item_id, saved: data.category, suggested: data.suggested_category });
    }
    // Only a colour the user chose is shown - never an auto-detected one.
    const chosenColour = data?.color && !data?.color_auto_detected ? ` (${data.color})` : "";
    const photoNote = data?.background_removed === false
      ? ` ${(data.image_warnings || [])[0] || "Kept your photo as it was."}`
      : data?.background_removed ? " Background removed." : "";
    flash(`Added to your wardrobe as ${data?.category || "a new item"}${chosenColour}.${photoNote}`);
  };

  const toggleFavourite = async (item) => {
    setItems((prev) => prev.map((x) => (x._id === item._id ? { ...x, favorite: !x.favorite } : x)));
    try {
      await axios.put(`${API_URL}/api/wardrobe/${item._id}`, { favorite: !item.favorite }, { headers: authHeaders() });
    } catch (err) {
      setItems((prev) => prev.map((x) => (x._id === item._id ? { ...x, favorite: item.favorite } : x)));
      flash(apiErrorMessage(err, "Saving favourite"));
    }
  };

  const remove = async (item) => {
    if (!window.confirm(`Delete ${item.display_name || item.category} from your wardrobe?`)) return;
    try {
      await axios.delete(`${API_URL}/api/wardrobe/${item._id}`, { headers: authHeaders() });
      setDetail(null);
      fetchItems();
      flash("Item deleted.");
    } catch (err) {
      flash(apiErrorMessage(err, "Delete"));
    }
  };

  const acceptSuggestion = async () => {
    try {
      await axios.put(`${API_URL}/api/wardrobe/${suggestion.itemId}`, { category: suggestion.suggested }, { headers: authHeaders() });
      fetchItems();
    } catch (err) {
      flash(apiErrorMessage(err, "Changing the category"));
    }
    setSuggestion(null);
  };

  // Straight to Virtual Try-On with this garment already selected.
  const tryOn = (item) => {
    navigate("/tryon", { state: { itemIds: [item._id], source: "wardrobe", label: item.display_name || item.category } });
  };
  const canTryOn = (item) => !["Shoes", "Accessories"].includes(item.group);

  const styleMe = (item) => {
    navigate("/recommend", { state: { occasion: (item.suitable_occasions || [])[0] || "casual", category: item.group } });
  };

  const colours = [...new Set(items.map((i) => (i.color || "").toLowerCase().trim()).filter(Boolean))].sort();
  const words = search.toLowerCase().split(/\s+/).filter(Boolean);
  const text = (i) => [i.display_name, i.category, i.group, i.color, i.style_label, i.material, i.styling,
    i.attributes && i.attributes.pattern, ...(i.suitable_occasions || []).map((o) => `${o} ${occasionLabel(o)}`)]
    .filter(Boolean).join(" ").toLowerCase();

  const shown = items
    .filter((i) => !group || i.group === group)
    .filter((i) => !colour || (i.color || "").toLowerCase().trim() === colour)
    .filter((i) => !occasion || (i.suitable_occasions || []).includes(occasion))
    .filter((i) => words.every((w) => text(i).includes(w) || text(i).includes(w.replace(/s$/, ""))))
    .sort((a, b) => {
      if (sortBy === "name") return (a.display_name || "").localeCompare(b.display_name || "");
      if (sortBy === "favourites") return (b.favorite ? 1 : 0) - (a.favorite ? 1 : 0);
      const ta = new Date(a.created_at || 0).getTime();
      const tb = new Date(b.created_at || 0).getTime();
      return sortBy === "oldest" ? ta - tb : tb - ta;
    });

  const filtersOn = search || group || colour || occasion;

  return (
    <Layout>
      <div className="aw-header">
        <div>
          <h1 className="aw-title">My Wardrobe</h1>
          <p className="aw-subtitle">Your personal digital wardrobe</p>
        </div>
        <div className="aw-header-actions">
          <ProfileChip />
          <div className="aw-count"><strong>{items.length}</strong> items</div>
          <button type="button" className="aw-btn" onClick={() => setShowAdd(true)}>
            <PlusIcon width={16} height={16} /> Add New Item
          </button>
        </div>
      </div>

      {toast && <div className="aw-toast" role="status">{toast}</div>}

      {suggestion && (
        <div className="aw-note">
          Saved as <strong>{suggestion.saved}</strong>, but the AI wasn't sure - it could also be <strong>{suggestion.suggested}</strong>.{" "}
          <button className="aw-btn aw-btn-sm" onClick={acceptSuggestion}>Change to {suggestion.suggested}</button>{" "}
          <button className="aw-btn aw-btn-soft aw-btn-sm" onClick={() => setSuggestion(null)}>Keep {suggestion.saved}</button>
        </div>
      )}

      <div className="wd-chips" role="group" aria-label="Show category">
        {["", ...groupsFor(gender)].map((g) => (
          <button type="button" key={g || "all"} className={`wd-chip ${group === g ? "on" : ""}`} onClick={() => setGroup(g)}>
            {g || "All"}
          </button>
        ))}
      </div>
      <div className={`aw-filters ${showFilters ? "open" : ""}`}>
        <div className="wd-searchrow">
          <label className="aw-search">
            <SearchIcon width={17} height={17} style={{ color: "#8c7b72" }} />
            <input placeholder="Search (e.g. black jeans, party, pink saree)" value={search} onChange={(e) => setSearch(e.target.value)} />
          </label>
          <button type="button" className={`wd-filter-btn ${showFilters || colour || occasion || sortBy !== "recent" ? "on" : ""}`}
            onClick={() => setShowFilters((v) => !v)} aria-expanded={showFilters}>Filters</button>
        </div>
        <select className="aw-select wd-group-select" value={group} onChange={(e) => setGroup(e.target.value)} aria-label="Category">
          <option value="">All categories</option>
          {groupsFor(gender).map((g) => <option key={g} value={g}>{g}</option>)}
        </select>
        <select className="aw-select wd-more" value={colour} onChange={(e) => setColour(e.target.value)} aria-label="Colour">
          <option value="">All colours</option>
          {colours.map((c) => <option key={c} value={c}>{c[0].toUpperCase() + c.slice(1)}</option>)}
        </select>
        <select className="aw-select wd-more" value={occasion} onChange={(e) => setOccasion(e.target.value)} aria-label="Occasion">
          <option value="">Any occasion</option>
          {OCCASIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select className="aw-select wd-more" value={sortBy} onChange={(e) => setSortBy(e.target.value)} aria-label="Sort">
          <option value="recent">Newest first</option>
          <option value="oldest">Oldest first</option>
          <option value="name">Name A–Z</option>
          <option value="favourites">Favourites first</option>
        </select>
      </div>
      {filtersOn && (
        <p className="aw-result-line">
          Showing {shown.length} of {items.length}
          <button type="button" className="aw-link" onClick={() => { setSearch(""); setGroup(""); setColour(""); setOccasion(""); }}>Clear filters</button>
        </p>
      )}

      {loadError && <div className="aw-alert">{loadError}</div>}

      {loaded && !loadError && items.length === 0 && (
        <div className="aw-empty">
          <h3>Your wardrobe is empty</h3>
          <p>Add a photo of any clothing item to get started.</p>
          <button className="aw-btn" style={{ marginTop: 14 }} onClick={() => setShowAdd(true)}>
            <CameraIcon width={18} height={18} /> Add your first item
          </button>
        </div>
      )}
      {items.length > 0 && shown.length === 0 && (
        <div className="aw-empty"><h3>Nothing matches</h3><p>Try another search or filter.</p></div>
      )}

      <div className="aw-grid">
        {shown.map((item) => (
          <article key={item._id} className="aw-card aw-wcard">
            <button type="button" className="aw-wcard-img" onClick={() => setDetail(item)} aria-label={`Open ${item.display_name}`}>
              {item.image_path
                ? <img src={assetUrl(item.image_path)} alt={item.display_name || item.category} loading="lazy" />
                : <span>👕</span>}
            </button>
            <button type="button" className={`wd-heart ${item.favorite ? "on" : ""}`} onClick={() => toggleFavourite(item)}
              aria-label={item.favorite ? "Remove from favourites" : "Add to favourites"}>
              <HeartIcon filled={item.favorite} width={18} height={18} />
            </button>
            <div className="aw-wcard-body">
              <div className="aw-wcard-top">
                <div>
                  <div className="aw-item-name">{item.display_name || item.category}</div>
                  <div className="aw-item-meta">{itemMeta(item)}</div>
                  <div className="aw-wcard-worn" data-testid="last-worn">
                    {lastWorn[item._id]
                      ? (lastWorn[item._id].days_ago === 0 ? "Worn today"
                        : `Last worn ${lastWorn[item._id].days_ago} day${lastWorn[item._id].days_ago === 1 ? "" : "s"} ago`)
                      : "Not worn yet"}
                  </div>
                </div>
                <span className="aw-dot" style={{ background: swatch(item.color) }} title={item.color} />
              </div>
              <div className="aw-wcard-actions">
                <button type="button" className="aw-icon-btn desk-only" onClick={() => setEditing(item)} title="Edit">Edit</button>
                <button type="button" className="aw-icon-btn" onClick={() => styleMe(item)} title="Style me">Style</button>
                {canTryOn(item) && (
                  <button type="button" className="aw-icon-btn" onClick={() => tryOn(item)} title="Try it on">Try on</button>
                )}
                <button type="button" className="aw-icon-btn danger desk-only" onClick={() => remove(item)} title="Delete">Delete</button>
              </div>
            </div>
          </article>
        ))}
      </div>

      {detail && (
        <div className="aw-overlay center" onClick={() => setDetail(null)}>
          <div className="aw-modal aw-add" onClick={(e) => e.stopPropagation()}>
            <button type="button" className="aw-close" onClick={() => setDetail(null)}>×</button>
            <div className="aw-details">
              <img src={assetUrl(detail.image_path)} alt={detail.display_name} className="aw-details-img" />
              <div className="aw-details-fields">
                <h2 className="aw-add-title" style={{ marginBottom: 4 }}>{detail.display_name || detail.category}</h2>
                <p className="aw-item-meta">{itemMeta(detail)}</p>
                <ul className="aw-why" style={{ marginTop: 12 }}>
                  <li>Category: {detail.category}</li>
                  <li>
                    Colour: {detail.color_display || detail.color || "not set"}
                    {detail.color_display &&
                      detail.color &&
                      detail.color_display.toLowerCase() !== detail.color.toLowerCase() && (
                        <span className="aw-hint"> ({detail.color})</span>
                      )}
                  </li>
                  {detail.attributes?.pattern && <li>Pattern: {detail.attributes.pattern}</li>}
                  {detail.material && <li>Material: {detail.material}</li>}
                  {detail.styling && <li>Styling: {detail.styling}</li>}
                  <li>Suits: {(detail.suitable_occasions || []).map(occasionLabel).join(", ") || "—"}</li>
                </ul>
                <div className="aw-actions-row">
                  <button className="aw-btn aw-btn-sm" onClick={() => styleMe(detail)}>✨ Style me</button>
                  {canTryOn(detail) && (
                    <button className="aw-btn aw-btn-ghost aw-btn-sm" onClick={() => tryOn(detail)}>Try it on</button>
                  )}
                  <button className="aw-btn aw-btn-soft aw-btn-sm" onClick={() => { setEditing(detail); setDetail(null); }}>Edit</button>
                  <button className="aw-btn aw-btn-soft aw-btn-sm" onClick={() => remove(detail)}>Delete</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {categoryError && <div className="aw-note" role="status">{categoryError}</div>}

      {showAdd && (
        <AddItemModal sections={sections} categoryError={categoryError} autoCategory={autoCategory} onClose={() => setShowAdd(false)} onSaved={onSaved} />
      )}
      {editing && (
        <EditItemModal item={editing} sections={sections} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); fetchItems(); flash("Changes saved."); }} />
      )}
    </Layout>
  );
}

export default Wardrobe;

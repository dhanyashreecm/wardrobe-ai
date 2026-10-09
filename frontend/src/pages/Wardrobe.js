import { useEffect, useRef, useState, useCallback } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import Cropper from "react-easy-crop";
import Layout from "../components/Layout";
import { ProfileChip } from "../components/PageHeader";
import { PlusIcon, SearchIcon } from "../components/Icons";
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

// Crop the selected region of an image into a JPEG File.
async function cropToFile(src, area, name) {
  const img = new Image();
  img.src = src;
  await new Promise((resolve, reject) => {
    img.onload = resolve;
    img.onerror = () => reject(new Error("This image can't be opened in the browser (HEIC photos need converting to JPG first)."));
  });
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(area.width));
  canvas.height = Math.max(1, Math.round(area.height));
  canvas.getContext("2d").drawImage(img, area.x, area.y, area.width, area.height, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
  if (!blob) throw new Error("Couldn't crop this image - try another photo.");
  const base = (name || "item").replace(/\.[^.]+$/, "") || "item";
  return new File([blob], `${base}.jpg`, { type: "image/jpeg" });
}

function AddItemModal({ onClose, onSaved, sections, autoCategory, categoryError }) {
  const [step, setStep] = useState("photo"); // photo | crop | details
  const [original, setOriginal] = useState(null);
  const [src, setSrc] = useState(null);
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [crop, setCrop] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  // Crop shape. Starts as the photo's OWN shape so the whole garment
  // (e.g. full-length jeans) fits; 3:4 and square are optional.
  const [natural, setNatural] = useState(3 / 4);
  const [aspectMode, setAspectMode] = useState("whole");
  const [area, setArea] = useState(null);
  const [category, setCategory] = useState("");
  const [color, setColor] = useState("");
  const [material, setMaterial] = useState("");
  const [styling, setStyling] = useState("");
  const [status, setStatus] = useState("idle"); // idle | saving | saved
  const [error, setError] = useState("");
  const busy = useRef(false);
  const [choices, setChoices] = useState([]);

  const pickFile = (e) => {
    const chosen = e.target.files && e.target.files[0];
    setError("");
    if (!chosen) return;
    if (!chosen.type.startsWith("image/")) {
      setError("Please choose an image file (JPG, PNG or WEBP).");
      return;
    }
    setOriginal(chosen);
    setSrc(URL.createObjectURL(chosen));
    setCrop({ x: 0, y: 0 });
    setZoom(1);
    setAspectMode("whole");
    setStep("crop");
  };

  const useCrop = async () => {
    try {
      const cropped = area ? await cropToFile(src, area, original?.name) : original;
      setFile(cropped);
      setPreview(URL.createObjectURL(cropped));
      setStep("details");
    } catch (err) {
      setError(err.message);
    }
  };

  const skipCrop = () => {
    setFile(original);
    setPreview(src);
    setStep("details");
  };

  const save = async () => {
    if (busy.current) return; // never two uploads at once
    if (!file) {
      setError("Please choose a photo first.");
      return;
    }
    if (!category && !autoCategory) {
      setError("Please choose a category.");
      return;
    }
    busy.current = true;
    setStatus("saving");
    setError("");
    const form = new FormData();
    form.append("image", file);
    form.append("category", category);
    form.append("category_explicit", category ? "true" : "false");
    if (color.trim()) form.append("color", color.trim());
    if (material.trim()) form.append("material", material.trim());
    if (styling) form.append("styling", styling);
    try {
      const res = await axios.post(`${API_URL}/api/wardrobe/add`, form, { headers: authHeaders() });
      setStatus("saved");
      setTimeout(() => onSaved(res.data), 900);
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

  const stepIndex = { photo: 0, crop: 1, details: 2 }[step];
  const saving = status === "saving";

  return (
    <div className="aw-overlay center" onClick={() => !saving && onClose()}>
      <div className="aw-modal aw-add" onClick={(e) => e.stopPropagation()}>
        <button type="button" className="aw-close" onClick={onClose} disabled={saving} aria-label="Close">×</button>
        <h2 className="aw-add-title">Add New Item</h2>
        <ol className="aw-steps">
          {["Photo", "Crop", "Details"].map((label, i) => (
            <li key={label} className={i === stepIndex ? "on" : i < stepIndex ? "done" : ""}>
              <span>{i < stepIndex ? "✓" : i + 1}</span>{label}
            </li>
          ))}
        </ol>

        {step === "photo" && (
          <>
            <label className="aw-drop">
              <input type="file" accept="image/*" onChange={pickFile} hidden />
              <PlusIcon width={28} height={28} />
              <strong>Choose a photo</strong>
              <span>JPG, PNG or WEBP · one piece of clothing per photo works best</span>
            </label>
            {/* Said plainly because people assume the opposite and go
                looking for a white wall. The background is removed
                automatically; the one thing that genuinely helps is
                contrast between the garment and whatever it is lying on. */}
            <p className="aw-hint">
              A photo on the floor, the bed or a chair is fine — so are
              wrinkles, shadows and ordinary room lighting. The background is
              removed for you. The only thing that trips it up is a garment
              the same colour as the surface under it, so put a white top on
              something darker.
            </p>
          </>
        )}

        {step === "crop" && src && (
          <>
            <div className="aw-cropbox">
              <Cropper image={src} crop={crop} zoom={zoom}
                aspect={aspectMode === "whole" ? natural : aspectMode === "square" ? 1 : 3 / 4}
                onMediaLoaded={(m) => m.naturalWidth && m.naturalHeight && setNatural(m.naturalWidth / m.naturalHeight)}
                onCropChange={setCrop} onCropComplete={(_, px) => setArea(px)} onZoomChange={setZoom} />
            </div>
            <div className="aw-crop-shapes" role="group" aria-label="Crop shape">
              {[["whole", "Whole photo"], ["portrait", "3:4"], ["square", "Square"]].map(([key, label]) => (
                <button type="button" key={key} aria-pressed={aspectMode === key}
                  className={`aw-btn aw-btn-sm ${aspectMode === key ? "" : "aw-btn-soft"}`}
                  onClick={() => { setAspectMode(key); setZoom(1); setCrop({ x: 0, y: 0 }); }}>
                  {label}
                </button>
              ))}
            </div>
            <label className="aw-zoom">
              Zoom
              <input type="range" min="1" max="3" step="0.05" value={zoom} onChange={(e) => setZoom(Number(e.target.value))} />
            </label>
          </>
        )}

        {step === "details" && (
          <div className="aw-details">
            <img src={preview} alt="Your item" className="aw-details-img" />
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
                <p className="aw-hint">Automatic recognition isn't set up on this computer yet, so please pick the category.</p>
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

        {error && <div className="aw-alert" role="alert">{error}</div>}
        {status === "saving" && (
          <div className="aw-progress">
            <span className="aw-spinner" />
            {category ? "Cleaning background & uploading…" : "Cleaning background & recognising your item…"}
          </div>
        )}
        {status === "saved" && <div className="aw-success">✓ Added to your wardrobe</div>}

        <div className="aw-modal-actions">
          <button type="button" className="aw-btn aw-btn-soft" onClick={onClose} disabled={saving}>Cancel</button>
          {step === "crop" && (
            <>
              <button type="button" className="aw-btn aw-btn-ghost" onClick={skipCrop}>Skip crop</button>
              <button type="button" className="aw-btn" onClick={useCrop}>Use this crop</button>
            </>
          )}
          {step === "details" && (
            <>
              <button type="button" className="aw-btn aw-btn-ghost" onClick={() => setStep("crop")} disabled={saving}>Back</button>
              <button type="button" className="aw-btn" onClick={save} disabled={saving || status === "saved"}>
                {saving ? "Saving…" : "Add to Wardrobe"}
              </button>
            </>
          )}
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

      <div className="aw-filters">
        <label className="aw-search">
          <SearchIcon width={17} height={17} style={{ color: "#8c7b72" }} />
          <input placeholder="Search (e.g. black jeans, party, pink saree)" value={search} onChange={(e) => setSearch(e.target.value)} />
        </label>
        <select className="aw-select" value={group} onChange={(e) => setGroup(e.target.value)} aria-label="Category">
          <option value="">All categories</option>
          {groupsFor(gender).map((g) => <option key={g} value={g}>{g}</option>)}
        </select>
        <select className="aw-select" value={colour} onChange={(e) => setColour(e.target.value)} aria-label="Colour">
          <option value="">All colours</option>
          {colours.map((c) => <option key={c} value={c}>{c[0].toUpperCase() + c.slice(1)}</option>)}
        </select>
        <select className="aw-select" value={occasion} onChange={(e) => setOccasion(e.target.value)} aria-label="Occasion">
          <option value="">Any occasion</option>
          {OCCASIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select className="aw-select" value={sortBy} onChange={(e) => setSortBy(e.target.value)} aria-label="Sort">
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
            <PlusIcon width={16} height={16} /> Add your first item
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
                <button type="button" className={`aw-icon-btn ${item.favorite ? "on" : ""}`} onClick={() => toggleFavourite(item)}
                  aria-label={item.favorite ? "Remove from favourites" : "Add to favourites"} title="Favourite">
                  {item.favorite ? "♥" : "♡"}
                </button>
                <button type="button" className="aw-icon-btn" onClick={() => setEditing(item)} title="Edit">Edit</button>
                <button type="button" className="aw-icon-btn" onClick={() => styleMe(item)} title="Style me">Style me</button>
                {canTryOn(item) && (
                  <button type="button" className="aw-icon-btn" onClick={() => tryOn(item)} title="Try it on">Try on</button>
                )}
                <button type="button" className="aw-icon-btn danger" onClick={() => remove(item)} title="Delete">Delete</button>
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

import { useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import Layout from "../components/Layout";
import { ProfileChip, useProfile } from "../components/PageHeader";
import { OutfitDrawer, useOutfitActions } from "../components/Outfit";
import StyleInspiration from "../components/Inspiration";
import { assetUrl } from "../config";
import "../styles/aw-v2.css";
import { authGet, apiErrorMessage, isAuthError, OCCASIONS, occasionLabel, outfitTags, swatch } from "../lib/api";

const STYLES = ["", "Casual", "Smart", "Formal", "Party", "Ethnic"];
const COLOURS = ["", "black", "white", "blue", "navy", "red", "pink", "green", "yellow", "beige", "brown", "grey", "purple", "gold"];
// Each tab is sent to the backend (?category=...). Single categories return
// ranked items of exactly that category; Full Looks returns complete outfits.
const TABS = ["All", "Full Looks", "Tops", "Bottoms", "Dresses", "Sarees", "Ethnic", "Outerwear", "Shoes", "Accessories"];

const ROLE_LABEL = {
  layer: "Layer", top: "Top", bottom: "Bottom", one_piece: "Outfit", set_part: "Blouse",
  footwear: "Shoes", accessory: "Accessory",
};
const ROLE_ORDER = ["layer", "top", "one_piece", "set_part", "bottom", "footwear", "accessory"];

function LookCard({ outfit, full, onOpen, actions }) {
  const roles = outfit.roles || {};
  const pieces = [...outfit.items].sort(
    (a, b) => ROLE_ORDER.indexOf(roles[a._id]) - ROLE_ORDER.indexOf(roles[b._id])
  );
  const saved = actions.feedbackOf(outfit) === "like";
  return (
    <article className="aw-card aw-look" onClick={() => onOpen(outfit)}>
      <div className="aw-look-head">
        <div>
          <span className="aw-kind">{full ? "Full Look" : "Outfit"}</span>
          <h3>{outfit.title}</h3>
          <div className="aw-item-meta">{outfitTags(outfit)}</div>
        </div>
        <button type="button" className={`aw-icon-btn ${saved ? "on" : ""}`} aria-label="Save look"
          onClick={(e) => { e.stopPropagation(); actions.act(outfit, "like"); }}>{saved ? "♥" : "♡"}</button>
      </div>
      <div className="aw-look-pieces">
        {pieces.map((item, i) => (
          <div key={item._id} className="aw-look-piece">
            {i > 0 && <span className="aw-plus">+</span>}
            <figure>
              <img src={assetUrl(item.image_path)} alt={item.display_name} />
              <figcaption>
                <b>{ROLE_LABEL[roles[item._id]] || "Item"}</b>
                {item.display_name}
              </figcaption>
            </figure>
          </div>
        ))}
      </div>
      <ul className="aw-why compact">
        {(outfit.why || []).filter((w) => !w.startsWith("Color:") && !w.startsWith("Style:")).slice(0, 3)
          .map((w, i) => <li key={i}>{w}</li>)}
      </ul>
    </article>
  );
}

function ItemCard({ rec }) {
  const item = rec.item;
  return (
    <article className="aw-card aw-wcard aw-single">
      <div className="aw-wcard-img static">
        <img src={assetUrl(item.image_path)} alt={item.display_name} />
        <span className="aw-kind floating">Single item</span>
      </div>
      <div className="aw-wcard-body">
        <div className="aw-wcard-top">
          <div>
            <div className="aw-item-name">{item.display_name}</div>
            <div className="aw-item-meta">{[rec.group, occasionLabel(rec.occasion), ...(rec.style_tags || [])].join(" • ")}</div>
          </div>
          <span className="aw-dot" style={{ background: swatch(item.color) }} title={item.color} />
        </div>
        <ul className="aw-why compact">{rec.why.slice(0, 4).map((w, i) => <li key={i}>{w}</li>)}</ul>
      </div>
    </article>
  );
}

function OutfitRecommendation() {
  const location = useLocation();
  const navigate = useNavigate();
  const profile = useProfile();
  const actions = useOutfitActions();

  const [occasion, setOccasion] = useState(location.state?.occasion || "casual");
  const [tab, setTab] = useState(TABS.includes(location.state?.category) ? location.state.category : "All");
  const [style, setStyle] = useState("");
  const [colour, setColour] = useState("");
  const [useWeather, setUseWeather] = useState(true);
  const [city, setCity] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(null);

  const load = useCallback(async (overrides = {}) => {
    if (!localStorage.getItem("token")) {
      navigate("/login");
      return;
    }
    const q = { occasion, tab, style, colour, useWeather, city, ...overrides };
    setLoading(true);
    setError("");
    try {
      const params = { occasion: q.occasion, category: q.tab };
      if (q.style) params.style = q.style;
      if (q.colour) params.colour = q.colour;
      if (!q.useWeather) params.use_weather = "false";
      else if (q.city.trim()) params.city = q.city.trim();
      setData(await authGet("/api/ai/recommend", params));
    } catch (err) {
      if (isAuthError(err)) {
        localStorage.removeItem("token");
        navigate("/login");
        return;
      }
      setError(apiErrorMessage(err, "Getting recommendations"));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [occasion, tab, style, colour, useWeather, city, navigate]);

  // Occasion and category change the results straight away; the other
  // filters apply on "Update".
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [occasion, tab]);

  const recs = data?.recommendations || [];
  const mode = data?.mode;
  const label = occasionLabel(occasion);
  const heading = data?.heading || (tab === "All" ? `Outfits for ${label}` : tab === "Full Looks" ? `Complete Looks for ${label}` : `${tab} for ${label}`);
  const weather = data?.weather;

  return (
    <Layout>
      <div className="aw-header">
        <div>
          <h1 className="aw-title">Outfit Recommendations</h1>
          <p className="aw-subtitle">Based on your wardrobe, occasion, style, colour &amp; weather</p>
        </div>
        <div className="aw-header-actions"><ProfileChip /></div>
      </div>

      <form className="aw-card aw-reco-filters" onSubmit={(e) => { e.preventDefault(); load(); }}>
        <label>
          <span>Occasion</span>
          <select className="aw-select" value={occasion} onChange={(e) => setOccasion(e.target.value)}>
            {OCCASIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label>
          <span>Style</span>
          <select className="aw-select" value={style} onChange={(e) => setStyle(e.target.value)}>
            {STYLES.map((s) => <option key={s} value={s}>{s || "Any style"}</option>)}
          </select>
        </label>
        <label>
          <span>Colour</span>
          <select className="aw-select" value={colour} onChange={(e) => setColour(e.target.value)}>
            {COLOURS.map((c) => <option key={c} value={c}>{c ? c[0].toUpperCase() + c.slice(1) : "Any colour"}</option>)}
          </select>
        </label>
        <label>
          <span>
            <input type="checkbox" checked={useWeather} onChange={(e) => setUseWeather(e.target.checked)} /> Weather
          </span>
          <input className="aw-input" placeholder={profile?.city ? `${profile.city} (saved)` : "City"}
            value={city} disabled={!useWeather} onChange={(e) => setCity(e.target.value)} />
        </label>
        <button type="submit" className="aw-btn" disabled={loading}>{loading ? "Updating…" : "Update"}</button>
      </form>

      {weather && (
        <p className="aw-result-line">
          🌤 {weather.city}: {Math.round(weather.temp_c)}°C, {weather.description || weather.condition}
          {data.used_saved_city ? " (your saved city)" : ""} - used in the ranking.
        </p>
      )}
      {data?.weather_error && useWeather && (
        <p className="aw-result-line">Weather unavailable ({data.weather_error}) - showing results without it.</p>
      )}

      <h2 className="aw-question">What are you looking for?</h2>
      <div className="aw-chips" role="tablist">
        {TABS.filter((t) => (profile?.gender || "").toLowerCase() !== "male" || (t !== "Dresses" && t !== "Sarees")).map((t) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t}
            className={`aw-chip ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>

      <div className="aw-row-head">
        <h2 className="aw-section-title" style={{ marginTop: 6 }}>{heading}</h2>
        {data?.outfit_mode === "traditional" && (
          <span className="aw-chip" title="Complete ethnic outfits with traditional footwear and accessories">Traditional mode</span>
        )}
        {!loading && data && recs.length > 0 && <span className="aw-result-line">{recs.length} result{recs.length === 1 ? "" : "s"}</span>}
      </div>

      {error && <div className="aw-alert">{error}</div>}
      {loading && <p className="aw-result-line"><span className="aw-spinner" /> Choosing from your wardrobe…</p>}

      {!loading && data && recs.length === 0 && (
        <div className="aw-empty">
          <h3>{(data.notes || [])[0] || `Nothing suitable for ${label.toLowerCase()} yet.`}</h3>
          {(data.notes || []).slice(1).map((n, i) => <p key={i}>{n}</p>)}
        </div>
      )}
      {!loading && recs.length > 0 && (data.notes || []).map((n, i) => <div key={i} className="aw-note">{n}</div>)}

      {!loading && mode === "items" && (
        <div className="aw-grid">
          {recs.map((rec) => <ItemCard key={rec.item._id} rec={rec} />)}
        </div>
      )}
      {!loading && (mode === "looks" || mode === "outfits") && (
        <div className="aw-looks">
          {recs.map((o) => (
            <LookCard key={o.outfit_key} outfit={o} full={mode === "looks" || Object.values(o.roles || {}).includes("footwear")}
              onOpen={setOpen} actions={actions} />
          ))}
        </div>
      )}

      <StyleInspiration occasion={occasion} label={label} />

      <OutfitDrawer outfit={open} onClose={() => setOpen(null)} actions={actions} />
    </Layout>
  );
}

export default OutfitRecommendation;

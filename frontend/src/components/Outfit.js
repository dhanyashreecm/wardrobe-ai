import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { assetUrl } from "../config";
import { authPost, outfitTags, swatch } from "../lib/api";

const MAIN_ROLES = ["layer", "top", "bottom", "one_piece", "set_part"];

// Split an outfit into its big "main" pieces and the small extras
// (shoes, bag, jewellery) for the collage.
export function splitOutfit(outfit) {
  const roles = outfit.roles || {};
  const main = [];
  const extras = [];
  (outfit.items || []).forEach((item) => {
    if (MAIN_ROLES.includes(roles[item._id])) main.push(item);
    else extras.push(item);
  });
  return { main: main.length ? main : outfit.items || [], extras };
}

export function Collage({ outfit, height }) {
  const { main, extras } = splitOutfit(outfit);
  const img = (item) => (
    <img
      key={item._id}
      src={assetUrl(item.image_path)}
      alt={item.display_name || item.category}
      onError={(e) => { e.currentTarget.style.visibility = "hidden"; }}
    />
  );
  return (
    <div className={`aw-collage ${extras.length ? "" : "solo"}`} style={height ? { height } : undefined}>
      <div className="main">{main.slice(0, 3).map(img)}</div>
      {extras.length > 0 && <div className="side">{extras.slice(0, 3).map(img)}</div>}
    </div>
  );
}

export function useOutfitActions() {
  const [status, setStatus] = useState({});

  const act = async (outfit, action) => {
    const key = outfit.outfit_key;
    const itemIds = outfit.key_item_ids || [];
    try {
      if (action === "wear") {
        const data = await authPost("/api/outfits/wear", { item_ids: itemIds, occasion: outfit.occasion });
        setStatus((prev) => ({ ...prev, [key]: { ...(prev[key] || {}), worn: true, message: data.message } }));
        return;
      }
      const current = status[key]?.feedback !== undefined ? status[key].feedback : outfit.liked ? "like" : null;
      const value = current === action ? null : action;
      await authPost("/api/outfits/feedback", { item_ids: itemIds, value });
      setStatus((prev) => ({
        ...prev,
        [key]: {
          ...(prev[key] || {}),
          feedback: value,
          message:
            value === "like" ? "Saved to your looks - similar outfits will rank higher."
              : value === "dislike" ? "Got it - this combination won't be suggested again."
                : "Removed.",
        },
      }));
    } catch (err) {
      setStatus((prev) => ({
        ...prev,
        [key]: { ...(prev[key] || {}), message: err.response?.data?.message || "Couldn't save - is the backend running?" },
      }));
    }
  };

  const feedbackOf = (outfit) => {
    const s = status[outfit.outfit_key] || {};
    return s.feedback !== undefined ? s.feedback : outfit.liked ? "like" : null;
  };

  return { status, act, feedbackOf };
}

export function OutfitCard({ outfit, onOpen, badge, actions }) {
  const { feedbackOf, act } = actions;
  const saved = feedbackOf(outfit) === "like";
  const colours = [...new Set((outfit.colours || []).map((c) => c.toLowerCase()))].slice(0, 4);
  return (
    <div className="aw-card aw-outfit" onClick={() => onOpen(outfit)}>
      <Collage outfit={outfit} />
      {badge && <span className="aw-badge-float">{badge}</span>}
      <button
        type="button"
        className={`aw-heart ${saved ? "on" : ""}`}
        onClick={(e) => { e.stopPropagation(); act(outfit, "like"); }}
        aria-label="Save look"
      >
        {saved ? "♥" : "♡"}
      </button>
      <div className="aw-outfit-body">
        <div className="aw-outfit-title">{outfit.title}</div>
        <div className="aw-tags">
          {outfitTags(outfit)}
        </div>
        <div className="aw-dots">
          {colours.map((c) => <span key={c} className="aw-dot" title={c} style={{ background: swatch(c) }} />)}
        </div>
      </div>
    </div>
  );
}

export function OutfitDrawer({ outfit, onClose, actions }) {
  const navigate = useNavigate();
  if (!outfit) return null;
  const { act, status, feedbackOf } = actions;
  const s = status[outfit.outfit_key] || {};
  const feedback = feedbackOf(outfit);

  return (
    <div className="aw-overlay" onClick={onClose}>
      <div className="aw-drawer" onClick={(e) => e.stopPropagation()}>
        <button type="button" className="aw-close" onClick={onClose} aria-label="Close">×</button>
        <Collage outfit={outfit} height={360} />
        <h2 style={{ fontSize: 26, margin: "18px 0 4px" }}>{outfit.title}</h2>
        <div className="aw-tags">
          {outfitTags(outfit)}
          {typeof outfit.score === "number" && ` • match score ${Math.round(outfit.score)}`}
        </div>

        <h3 style={{ fontSize: 17, marginTop: 20 }}>Items in this look</h3>
        <div className="aw-piece-row">
          {outfit.items.map((item) => (
            <div key={item._id} className="aw-piece">
              <img src={assetUrl(item.image_path)} alt={item.display_name} />
              <p>{item.display_name || item.category}</p>
              <small>{[item.group, item.style_label].filter(Boolean).join(" • ")}</small>
            </div>
          ))}
        </div>

        <h3 style={{ fontSize: 17 }}>Why this works</h3>
        <ul className="aw-why">
          {(outfit.why || []).map((line, i) => <li key={i}>{line}</li>)}
        </ul>

        {outfit.inspiration && (
          <div className="aw-inspo" style={{ marginBottom: 18 }}>
            <a href={outfit.inspiration.pinterest_url} target="_blank" rel="noreferrer">
              <span className="pin">P</span>
              <span>
                See similar looks on Pinterest
                <br />
                <small style={{ color: "#8c7b72" }}>{outfit.inspiration.query}</small>
              </span>
            </a>
          </div>
        )}

        <button type="button" className="aw-btn" style={{ width: "100%" }} onClick={() => act(outfit, "like")}>
          {feedback === "like" ? "♥ Saved to your looks" : "♡ Save to Wardrobe"}
        </button>
        <button
          type="button"
          className="aw-btn aw-btn-ghost"
          style={{ width: "100%", marginTop: 10 }}
          onClick={() => navigate("/tryon", { state: { outfit } })}
        >
          Try Virtual Try-On
        </button>
        <div className="aw-actions-row" style={{ justifyContent: "center" }}>
          <button type="button" className="aw-btn aw-btn-soft aw-btn-sm" disabled={s.worn} onClick={() => act(outfit, "wear")}>
            {s.worn ? "✓ Worn today" : "👕 I wore this"}
          </button>
          <button type="button" className="aw-btn aw-btn-soft aw-btn-sm" onClick={() => act(outfit, "dislike")}>
            {feedback === "dislike" ? "👎 Hidden" : "👎 Not for me"}
          </button>
        </div>
        {s.message && <p style={{ fontSize: 12.5, color: "#6b5b4d", textAlign: "center", marginTop: 10 }}>{s.message}</p>}
      </div>
    </div>
  );
}

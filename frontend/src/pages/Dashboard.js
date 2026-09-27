import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Layout from "../components/Layout";
import { OutfitCard, OutfitDrawer, useOutfitActions } from "../components/Outfit";
import { PlaneIcon, TryOnIcon, SearchIcon, SparkleIcon } from "../components/Icons";
import { assetUrl } from "../config";
import { authGet, swatch } from "../lib/api";

export function StyleEditStrip({ edits, onOpenEdit }) {
  return (
    <div className="aw-panel aw-edit-strip">
      <div className="aw-edit-intro">
        <div className="spark">✧</div>
        <h2>Your Style Edit</h2>
        <p className="aw-section-sub" style={{ margin: 0 }}>Curated from your wardrobe</p>
      </div>
      {edits.map((edit) => {
        const pieces = (edit.outfits[0]?.items || []).slice(0, 3);
        return (
          <button
            type="button"
            key={edit.key}
            className="aw-card aw-edit-card"
            onClick={() => onOpenEdit(edit)}
          >
            <div className={`aw-edit-img ${pieces.length === 1 ? "single" : ""}`}>
              {pieces.map((item) => (
                <img key={item._id} src={assetUrl(item.image_path)} alt={item.display_name} />
              ))}
            </div>
            <div className="aw-edit-body">
              <strong>{edit.icon} {edit.title}</strong>
              <span>
                {edit.count
                  ? `${edit.subtitle} · ${edit.count} look${edit.count === 1 ? "" : "s"}`
                  : "Add a few more pieces to unlock this edit"}
              </span>
              <span className="arrow">→</span>
            </div>
          </button>
        );
      })}
    </div>
  );
}

export function ItemStrip({ items }) {
  return (
    <div className="aw-strip">
      {items.map((item) => (
        <Link to="/wardrobe" key={item._id} className="aw-card aw-item" style={{ textDecoration: "none", color: "inherit" }}>
          <img className="aw-item-img" src={assetUrl(item.image_path)} alt={item.display_name} />
          <div className="aw-item-body">
            <div className="aw-item-name">{item.display_name}</div>
            <div className="aw-item-meta">{item.group}</div>
            <div className="aw-dots"><span className="aw-dot" style={{ background: swatch(item.color) }} /></div>
          </div>
        </Link>
      ))}
    </div>
  );
}

function Dashboard() {
  const navigate = useNavigate();
  const [home, setHome] = useState(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(null);
  const actions = useOutfitActions();

  useEffect(() => {
    if (!localStorage.getItem("token")) {
      navigate("/login");
      return;
    }
    authGet("/api/home")
      .then(setHome)
      .catch((err) => {
        if (err.response?.status === 401 || err.response?.status === 422) {
          localStorage.removeItem("token");
          navigate("/login");
        } else {
          setError("Couldn't load your wardrobe - is the backend running?");
        }
      });
  }, [navigate]);

  const heroImages = (home?.recent || []).slice(0, 3);
  const firstName = (home?.name || "").split(" ")[0];

  return (
    <Layout>
      <div className="aw-hero">
        <div className="aw-hero-text">
          <div className="script">Welcome to your{firstName ? `, ${firstName}` : ""}</div>
          <h1>AI Wardrobe</h1>
          <p style={{ fontSize: 17, color: "#3f3531", marginBottom: 14 }}>
            Your clothes. Your style. Your possibilities.
          </p>
          <p>
            Get personalised outfit recommendations, plan your looks for any
            occasion, explore travel-ready outfits and so much more — all from
            your own wardrobe.
          </p>
          <div style={{ marginTop: 24 }}>
            <Link to="/wardrobe" className="aw-btn">Explore Your Wardrobe →</Link>
          </div>
        </div>
        <div className="aw-hero-art">
          {heroImages.length >= 1 ? (
            <>
              {heroImages.map((item) => (
                <img key={item._id} src={assetUrl(item.image_path)} alt={item.display_name} />
              ))}
              <span className="aw-hero-script">Better outfits, brighter days ♡</span>
            </>
          ) : (
            <div className="aw-hero-placeholder">Your wardrobe starts here ✦</div>
          )}
        </div>
      </div>

      {error && <p className="aw-note" style={{ marginTop: 20 }}>{error}</p>}

      {home && (
        <>
          <div style={{ marginTop: 28 }}>
            <StyleEditStrip
              edits={home.edits}
              onOpenEdit={(edit) =>
                edit.outfits[0] ? setOpen(edit.outfits[0]) : navigate("/wardrobe")
              }
            />
          </div>

          <div className="aw-shortcuts" style={{ marginTop: 22 }}>
            <Link to="/recommend" className="aw-card aw-shortcut">
              <span className="ico"><SparkleIcon width={22} /></span>
              <div><strong>Style me</strong><span>Outfits for any occasion</span></div>
            </Link>
            <Link to="/trip" className="aw-card aw-shortcut">
              <span className="ico"><PlaneIcon width={22} /></span>
              <div>
                <strong>Trip Planner</strong>
                <span>
                  {home.weather
                    ? `${home.city}: ${Math.round(home.weather.temp_c)}°C, ${home.weather.description || home.weather.condition}`
                    : "Weather-ready packing"}
                </span>
              </div>
            </Link>
            <Link to="/tryon" className="aw-card aw-shortcut">
              <span className="ico"><TryOnIcon width={22} /></span>
              <div><strong>Virtual Try-On</strong><span>See a look put together</span></div>
            </Link>
            <Link to="/similar" className="aw-card aw-shortcut">
              <span className="ico"><SearchIcon width={22} /></span>
              <div><strong>Find Similar</strong><span>Match any clothing photo</span></div>
            </Link>
          </div>

          {home.top_pick && (
            <>
              <h2 className="aw-section-title">Recommended for you</h2>
              <p className="aw-section-sub">One look from each of your edits</p>
              <div className="aw-outfit-grid">
                {home.edits.filter((e) => e.outfits[0]).map((edit) => (
                  <OutfitCard
                    key={edit.key}
                    outfit={edit.outfits[0]}
                    badge={`${edit.icon} ${edit.title}`}
                    onOpen={setOpen}
                    actions={actions}
                  />
                ))}
              </div>
            </>
          )}

          <div className="aw-row-head">
            <h2 className="aw-section-title">Recently added</h2>
            <Link to="/wardrobe" className="aw-link">View all {home.item_count} items →</Link>
          </div>
          {home.recent.length ? (
            <ItemStrip items={home.recent} />
          ) : (
            <div className="aw-empty">
              <h3>Your wardrobe is empty</h3>
              <p>Add your first piece and the AI will recognise it for you.</p>
              <Link to="/wardrobe" className="aw-btn" style={{ marginTop: 14 }}>+ Add clothes</Link>
            </div>
          )}

          {home.favourites.length > 0 && (
            <>
              <h2 className="aw-section-title">Your favourites ♡</h2>
              <ItemStrip items={home.favourites} />
            </>
          )}
        </>
      )}

      {!home && !error && <p className="aw-section-sub" style={{ marginTop: 24 }}>Loading your wardrobe…</p>}

      <OutfitDrawer outfit={open} onClose={() => setOpen(null)} actions={actions} />
    </Layout>
  );
}

export default Dashboard;

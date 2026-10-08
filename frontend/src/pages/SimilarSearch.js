import { useEffect, useState } from "react";
import axios from "axios";
import Layout from "../components/Layout";
import "../App.css";
import "../styles/shop.css";
import { API_URL, assetUrl } from "../config";
import { authGet, apiErrorMessage } from "../lib/api";
import { useCategories } from "../lib/categories";

// Find Similar: one photo, two answers.
//   1. "Already in your wardrobe" - so the user doesn't buy a twin.
//   2. "Shop similar" - live store links built from what the AI saw.
//      Plain URLs (no dataset pictures stored on one laptop), so this
//      works for every account on every device, including the phone app.

const STORE_NOTES = {
  myntra: ["💃", "Trendy & ethnic"],
  ajio: ["🕶️", "Cool brands"],
  amazon: ["📦", "Lots of choice"],
  flipkart: ["🏷️", "Good prices"],
  meesho: ["💰", "Low budget"],
  google: ["🌐", "Compare all shops"],
};

// Budget buttons: [label, min, max] in rupees ("" = no limit).
const BUDGETS = [
  ["💫 Any price", "", ""],
  ["Under ₹500", "", "500"],
  ["₹500 – ₹1,000", "500", "1000"],
  ["₹1,000 – ₹2,000", "1000", "2000"],
  ["₹2,000+", "2000", ""],
];

function pct(similarity) {
  return Math.round((similarity || 0) * 100);
}

function SimilarSearch() {
  const [image, setImage] = useState(null);
  const [preview, setPreview] = useState("");
  const [wardrobeResults, setWardrobeResults] = useState([]);
  const [shopping, setShopping] = useState(null);
  const [searched, setSearched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // editable filters for the shop links
  const [category, setCategory] = useState("");
  const [color, setColor] = useState("");
  const [printed, setPrinted] = useState(false);
  const [query, setQuery] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [budget, setBudget] = useState(0); // index into BUDGETS

  const { sections } = useCategories();

  useEffect(() => {
    if (!image) {
      setPreview("");
      return undefined;
    }
    const url = URL.createObjectURL(image);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [image]);

  const applyShopping = (shop) => {
    setShopping(shop);
    setCategory(shop?.category || "");
    setColor(shop?.color || "");
    setPrinted(Boolean(shop?.patterned));
    setQuery(shop?.query || "");
  };

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!image) {
      setError("📷 Please add a photo first.");
      return;
    }
    setLoading(true);
    setError("");
    setWardrobeResults([]);
    setShopping(null);

    const formData = new FormData();
    formData.append("image", image);

    try {
      const res = await axios.post(`${API_URL}/api/ai/similar`, formData, {
        headers: {
          Authorization: `Bearer ${localStorage.getItem("token")}`,
          "Content-Type": "multipart/form-data",
        },
      });
      if (res.data.success) {
        setWardrobeResults(res.data.wardrobe_results || []);
        applyShopping(res.data.shopping || null);
        setBudget(0);
        setSearched(true);
      } else {
        setError(res.data.message || "Search failed");
      }
    } catch (err) {
      setError(apiErrorMessage(err, "Search"));
    } finally {
      setLoading(false);
    }
  };

  // Rebuild links from corrected category / colour, or a typed query.
  const refreshLinks = async ({ useTypedQuery, budgetIndex = budget } = {}) => {
    setRefreshing(true);
    const [, minPrice, maxPrice] = BUDGETS[budgetIndex] || BUDGETS[0];
    try {
      const data = await authGet("/api/shop/links", {
        min_price: minPrice || undefined,
        max_price: maxPrice || undefined,
        category: category || undefined,
        color: color || undefined,
        printed: printed ? "1" : undefined,
        q: useTypedQuery ? query : undefined,
        image_url: shopping?.image_url || undefined,
      });
      setShopping((old) => ({ ...(old || {}), ...data.shopping }));
      setQuery(data.shopping.query);
    } catch (err) {
      setError(apiErrorMessage(err, "Updating the shop links"));
    } finally {
      setRefreshing(false);
    }
  };

  const categoryOptions = (sections || []).flatMap((s) =>
    s.categories.map((c) => ({ ...c, section: s.name }))
  );
  const categoryKnown = categoryOptions.some((c) => c.value === category);

  return (
    <Layout>
      <div className="page-header">
        <div>
          <h1 className="page-title">Find Similar &amp; Shop ✨</h1>
          <p className="page-subtitle">
            Saw a nice outfit? Add a photo. We'll show you if you already have it,
            and where to buy it. 💕
          </p>
        </div>
      </div>

      <ol className="shop-steps" aria-label="How it works">
        <li><span>📸</span>Add a photo</li>
        <li><span>👀</span>We check your closet</li>
        <li><span>🛍️</span>Shop it online</li>
      </ol>

      <form className="shop-upload" onSubmit={handleSearch}>
        <label className="shop-drop">
          {preview ? (
            <img src={preview} alt="Your chosen clothing" />
          ) : (
            <span className="shop-drop-hint">
              <span className="shop-drop-emoji">📷</span>
              <strong>Tap to add a photo</strong>
              <small>Pick from gallery or use camera</small>
            </span>
          )}
          <input
            type="file"
            accept="image/*"
            onChange={(e) => {
              setImage(e.target.files[0] || null);
              setError("");
            }}
          />
        </label>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={loading || !image}
        >
          {loading ? "Searching… 🔎" : "Find it ✨"}
        </button>
      </form>

      {error && <p className="error" style={{ marginTop: 18 }}>{error}</p>}
      {loading && <p className="shop-muted">🔎 Looking at the colour and style… just a few seconds!</p>}

      {/* ---------------- ALREADY OWNED ---------------- */}
      {!loading && searched && (
        <section className="shop-section">
          <h2>👚 In your closet</h2>
          {wardrobeResults.length > 0 ? (
            <>
              <p className="shop-muted">
                {wardrobeResults.some((i) => i.exact_match)
                  ? "🎉 You already have this one!"
                  : "💡 You have something like this. Check it before you buy!"}
              </p>
              <div className="shop-owned-grid">
                {wardrobeResults.map((item, idx) => (
                  <div
                    className={`shop-owned${item.exact_match ? " shop-owned--exact" : ""}`}
                    key={item.item_id || idx}
                  >
                    {item.exact_match && <span className="shop-exact">✅ Same item</span>}
                    <img src={assetUrl(item.image)} alt="Your wardrobe item" />
                    <div>
                      <strong>{pct(item.similarity)}% same</strong>
                      {item.category && <span>{item.category}</span>}
                      {item.color && <span>{item.color}</span>}
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <p className="shop-muted">🙈 Nothing like this in your closet yet.</p>
          )}
        </section>
      )}

      {/* ---------------- SHOP SIMILAR ---------------- */}
      {!loading && shopping && (
        <section className="shop-section">
          <h2>🛍️ Buy something similar</h2>
          <p className="shop-muted">
            Tap a shop to see the latest styles and prices. 💸
          </p>

          {shopping.lens_url && (
            <a
              className="shop-lens"
              href={shopping.lens_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              <span className="shop-lens-icon" aria-hidden="true">🪄</span>
              <span>
                <strong>Find this exact look 🔍</strong>
                <small>Search the whole internet using your photo</small>
              </span>
              <span aria-hidden="true">↗</span>
            </a>
          )}

          <div className="shop-filters">
            <label>
              👕 What is it?
              {categoryOptions.length > 0 ? (
                <select value={category} onChange={(e) => setCategory(e.target.value)}>
                  {!categoryKnown && <option value={category}>{category || "Pick one"}</option>}
                  {(sections || []).map((s) => (
                    <optgroup key={s.name} label={s.name}>
                      {s.categories.map((c) => (
                        <option key={c.value} value={c.value}>{c.label}</option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              ) : (
                <input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="e.g. Kurta" />
              )}
            </label>
            <label>
              🎨 Colour
              <input value={color} onChange={(e) => setColor(e.target.value)} placeholder="e.g. Navy" />
            </label>
            <label className="shop-check">
              <input type="checkbox" checked={printed} onChange={(e) => setPrinted(e.target.checked)} />
              🌸 Has prints
            </label>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => refreshLinks()}
              disabled={refreshing}
            >
              {refreshing ? "Updating…" : "🔄 Update"}
            </button>
          </div>

          <form
            className="shop-query"
            onSubmit={(e) => {
              e.preventDefault();
              refreshLinks({ useTypedQuery: true });
            }}
          >
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Your own search"
              placeholder="✏️ Or type what you want…"
            />
            <button type="submit" className="btn btn-primary" disabled={refreshing || !query.trim()}>
              Search 🔎
            </button>
          </form>

          <div className="shop-budget" role="group" aria-label="Budget">
            <span className="shop-budget-label">💰 Budget</span>
            {BUDGETS.map(([label], idx) => (
              <button
                key={label}
                type="button"
                className={`shop-budget-chip${budget === idx ? " is-active" : ""}`}
                aria-pressed={budget === idx}
                disabled={refreshing}
                onClick={() => {
                  setBudget(idx);
                  refreshLinks({ useTypedQuery: true, budgetIndex: idx });
                }}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="shop-stores">
            {(shopping.links || []).map((link) => (
              <a
                key={link.store}
                className={`shop-store shop-store--${link.store}`}
                href={link.url}
                target="_blank"
                rel="noopener noreferrer"
              >
                <span className="shop-store-emoji" aria-hidden="true">
                  {(STORE_NOTES[link.store] || ["🛍️"])[0]}
                </span>
                <strong>{link.name}</strong>
                <small>{(STORE_NOTES[link.store] || ["", "Shop now"])[1]}</small>
                <span className="shop-go">Shop now →</span>
              </a>
            ))}
          </div>
        </section>
      )}

      {!loading && !searched && !error && (
        <p className="shop-muted" style={{ marginTop: 24 }}>
          💡 Tip: Take a clear photo of just the clothes, in the middle. It works best!
        </p>
      )}
    </Layout>
  );
}

export default SimilarSearch;

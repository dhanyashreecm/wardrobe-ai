import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import Layout from "../components/Layout";
import "../App.css";
import "../styles/aw-v2.css";
import "../styles/similar.css";
import { API_URL, assetUrl } from "../config";
import { authGet, authPost, apiErrorMessage, isAuthError } from "../lib/api";

// Find Similar = three parts on one page:
//   Your Search   - the photo (kept visible) and what was detected in it,
//                   editable so a wrong guess can be corrected
//   Your Wardrobe - the closest things the user already owns
//   Shop Similar  - real products from shops (exact match when Google
//                   Lens can verify it), or search links for each shop
//                   when product search isn't available
//
// Shop results are never invented: every card is a real listing from
// the backend, and when there are none the page says so.

export const MATCH_LABELS = {
  exact: "Exact product match",
  very_similar: "Very similar",
  similar_style: "Similar style",
  same_category: "Same category",
};
const MATCH_ORDER = ["exact", "very_similar", "similar_style", "same_category"];

const WARDROBE_LABELS = {
  very_close: "Very close match",
  similar: "Similar",
  loose: "Loosely similar",
};

const ATTRIBUTE_FIELDS = [
  ["category", "Type"],
  ["colour", "Colour"],
  ["pattern", "Pattern"],
  ["sleeve", "Sleeves"],
  ["neckline", "Neckline"],
  ["silhouette", "Cut / fit"],
  ["fabric", "Fabric"],
];

const SOURCE_LABELS = { photo: "from photo", "matched products": "from matches", you: "edited" };

const MAX_COMPARE = 3;

const EMPTY_ANALYSIS = {
  category: "", colour: "", pattern: "", sleeve: "", neckline: "", silhouette: "",
  fabric: "", audience: "", keywords: "", secondary_colours: [], sources: {}, uncertain: false,
};

function isWebLink(url) {
  return typeof url === "string" && /^https?:\/\//i.test(url);
}

export function formatPrice(product) {
  if (typeof product.price === "number" && product.currency === "INR") {
    return new Intl.NumberFormat("en-IN", {
      style: "currency", currency: "INR", maximumFractionDigits: 0,
    }).format(product.price);
  }
  return product.price_text || "";
}

function percent(similarity) {
  return `${(similarity * 100).toFixed(1)}%`;
}

function ProgressRow({ label, state, onRetry }) {
  return (
    <div className={`sim-progress-row is-${state}`}>
      {state === "loading" && <span className="aw-spinner" aria-hidden="true" />}
      {state === "done" && <span aria-hidden="true">✓</span>}
      {state === "error" && <span aria-hidden="true">!</span>}
      {state === "idle" && <span aria-hidden="true">·</span>}
      <span>{label}</span>
      {state === "error" && onRetry && (
        <button type="button" className="aw-icon-btn" onClick={onRetry}>Retry</button>
      )}
    </div>
  );
}

function ProductImage({ src, alt }) {
  const [broken, setBroken] = useState(false);
  if (!isWebLink(src) || broken) {
    return <span className="sim-noimg" aria-label="No image available">👗</span>;
  }
  return (
    <img src={src} alt={alt} loading="lazy" referrerPolicy="no-referrer"
         onError={() => setBroken(true)} />
  );
}

function ProductCard({ product, saved, onToggleSave, comparing, onToggleCompare, compareFull }) {
  return (
    <article className="aw-card sim-product" data-testid="product-card">
      <div className="sim-product-img">
        <ProductImage src={product.image} alt={product.title} />
        <span className={`sim-match sim-match-${product.match}`}>{MATCH_LABELS[product.match]}</span>
        <button
          type="button"
          className={`aw-heart${saved ? " on" : ""}`}
          aria-label={saved ? "Remove from wishlist" : "Save to wishlist"}
          aria-pressed={saved}
          onClick={() => onToggleSave(product)}
        >
          {saved ? "♥" : "♡"}
        </button>
      </div>
      <div className="sim-product-body">
        <div className="sim-platform">{product.platform || product.source || "Online shop"}</div>
        <div className="aw-item-name sim-title" title={product.title}>{product.title}</div>
        <div className="sim-price-row">
          {formatPrice(product) ? <strong>{formatPrice(product)}</strong> : <span className="sim-muted">Price on site</span>}
          {product.in_stock === true && <span className="sim-stock">In stock</span>}
          {product.in_stock === false && <span className="sim-stock out">Out of stock</span>}
        </div>
        {product.matched_attributes?.length > 0 && (
          <div className="sim-agree">
            Matches: {product.matched_attributes.join(", ")}
          </div>
        )}
        <div className="sim-product-actions">
          <a className="aw-btn aw-btn-sm sim-view" href={product.url} target="_blank" rel="noopener noreferrer">
            View Product ↗
          </a>
          <label className={`sim-compare${!comparing && compareFull ? " disabled" : ""}`}>
            <input
              type="checkbox"
              checked={comparing}
              disabled={!comparing && compareFull}
              onChange={() => onToggleCompare(product)}
            />
            Compare
          </label>
        </div>
      </div>
    </article>
  );
}

function SimilarSearch() {
  const navigate = useNavigate();

  const [image, setImage] = useState(null);
  const [previewUrl, setPreviewUrl] = useState("");

  const [wardrobeState, setWardrobeState] = useState("idle");
  const [wardrobeError, setWardrobeError] = useState("");
  const [wardrobeResults, setWardrobeResults] = useState([]);
  const [wardrobeStatus, setWardrobeStatus] = useState("");
  const [datasetResults, setDatasetResults] = useState([]);
  const [indofashionResults, setIndofashionResults] = useState([]);

  const [analysis, setAnalysis] = useState(EMPTY_ANALYSIS);

  const [shopState, setShopState] = useState("idle");
  const [shopError, setShopError] = useState("");
  const [shop, setShop] = useState(null);

  const [platformFilter, setPlatformFilter] = useState([]);
  const [matchFilter, setMatchFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [colourFilter, setColourFilter] = useState("");
  const [minPrice, setMinPrice] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [sortBy, setSortBy] = useState("best");

  const [compareIds, setCompareIds] = useState([]);
  const [wishlist, setWishlist] = useState([]);
  const [showWishlist, setShowWishlist] = useState(false);
  const [notice, setNotice] = useState("");

  const goLogin = useCallback(() => {
    localStorage.removeItem("token");
    navigate("/login");
  }, [navigate]);

  useEffect(() => {
    if (!localStorage.getItem("token")) {
      navigate("/login");
      return;
    }
    authGet("/api/wishlist")
      .then((data) => setWishlist(data.items || []))
      .catch((err) => { if (isAuthError(err)) goLogin(); });
  }, [navigate, goLogin]);

  useEffect(() => {
    if (!image) {
      setPreviewUrl("");
      return undefined;
    }
    const url = URL.createObjectURL(image);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [image]);

  const flash = (message) => {
    setNotice(message);
    setTimeout(() => setNotice(""), 3000);
  };

  const authHeader = () => ({ Authorization: `Bearer ${localStorage.getItem("token")}` });

  // ---------------------------------------------------------------
  // SHOP SEARCH
  // ---------------------------------------------------------------

  const runShop = useCallback(async (details, photo) => {
    const file = photo || image;
    if (!file) return;
    setShopState("loading");
    setShopError("");
    setCompareIds([]);

    const formData = new FormData();
    formData.append("image", file);
    formData.append("analysis", JSON.stringify(details || EMPTY_ANALYSIS));

    try {
      const res = await axios.post(`${API_URL}/api/shop/search`, formData, {
        headers: { ...authHeader(), "Content-Type": "multipart/form-data" },
      });
      setShop(res.data);
      if (res.data.analysis) {
        // Keep the user's own edits; take any details the matched
        // products filled in.
        setAnalysis((prev) => ({ ...res.data.analysis, keywords: prev.keywords }));
      }
      setShopState("done");
    } catch (err) {
      if (isAuthError(err)) return goLogin();
      setShopError(apiErrorMessage(err, "Shop search"));
      setShopState("error");
    }
  }, [image, goLogin]);

  // ---------------------------------------------------------------
  // WARDROBE SEARCH (the original Find Similar request)
  // ---------------------------------------------------------------

  const runWardrobe = async () => {
    if (!image) {
      setWardrobeError("Please select an image first.");
      return;
    }
    setWardrobeState("loading");
    setWardrobeError("");
    setWardrobeResults([]);
    setDatasetResults([]);
    setIndofashionResults([]);
    setWardrobeStatus("");
    setShop(null);
    setShopState("idle");
    setShopError("");

    const formData = new FormData();
    formData.append("image", image);

    let detected = EMPTY_ANALYSIS;
    let status = "none";
    try {
      const res = await axios.post(`${API_URL}/api/ai/similar`, formData, {
        headers: { ...authHeader(), "Content-Type": "multipart/form-data" },
      });
      if (!res.data.success) throw new Error(res.data.message || "Search failed");
      setWardrobeResults(res.data.wardrobe_results || []);
      setDatasetResults(res.data.dataset_results || []);
      setIndofashionResults(res.data.indofashion_results || []);
      status = res.data.wardrobe_status || ((res.data.wardrobe_results || []).length ? "similar" : "none");
      setWardrobeStatus(status);
      detected = { ...EMPTY_ANALYSIS, ...(res.data.analysis || {}) };
      setAnalysis(detected);
      setWardrobeState("done");
    } catch (err) {
      if (isAuthError(err)) return goLogin();
      setWardrobeError(err.response ? apiErrorMessage(err, "Wardrobe search") : (err.message || "Wardrobe search failed."));
      setWardrobeState("error");
      setAnalysis(EMPTY_ANALYSIS);
    }

    // Nothing suitable owned (or the wardrobe search failed): look in
    // shops straight away. When the user already owns something like
    // it, shopping is offered with a button instead.
    if (status === "none") runShop(detected, image);
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    runWardrobe();
  };

  const editAttribute = (field, value) => {
    setAnalysis((prev) => ({
      ...prev,
      [field]: value,
      sources: field === "keywords" ? prev.sources : { ...prev.sources, [field]: "you" },
    }));
  };

  // ---------------------------------------------------------------
  // WISHLIST + COMPARE
  // ---------------------------------------------------------------

  const savedByUrl = useMemo(() => new Map(wishlist.map((w) => [w.url, w])), [wishlist]);

  const toggleSave = async (product) => {
    const existing = savedByUrl.get(product.url);
    try {
      if (existing) {
        await axios.delete(`${API_URL}/api/wishlist/${existing.id}`, { headers: authHeader() });
        setWishlist((prev) => prev.filter((w) => w.id !== existing.id));
        flash("Removed from your wishlist.");
      } else {
        const data = await authPost("/api/wishlist", {
          title: product.title, url: product.url, image: product.image,
          platform: product.platform, price: product.price,
          price_text: product.price_text, currency: product.currency,
        });
        setWishlist((prev) => [data.item, ...prev.filter((w) => w.id !== data.item.id)]);
        flash("Saved to your wishlist.");
      }
    } catch (err) {
      if (isAuthError(err)) return goLogin();
      flash(apiErrorMessage(err, "Wishlist"));
    }
  };

  const removeSaved = async (item) => {
    try {
      await axios.delete(`${API_URL}/api/wishlist/${item.id}`, { headers: authHeader() });
      setWishlist((prev) => prev.filter((w) => w.id !== item.id));
    } catch (err) {
      if (isAuthError(err)) return goLogin();
      flash(apiErrorMessage(err, "Wishlist"));
    }
  };

  const toggleCompare = (product) => {
    setCompareIds((prev) => (prev.includes(product.id)
      ? prev.filter((id) => id !== product.id)
      : prev.length >= MAX_COMPARE ? prev : [...prev, product.id]));
  };

  // ---------------------------------------------------------------
  // FILTER + SORT (client side - no extra searches)
  // ---------------------------------------------------------------

  const products = useMemo(() => shop?.products || [], [shop]);
  const platforms = [...new Set(products.map((p) => p.platform).filter(Boolean))].sort();
  const categories = [...new Set(products.map((p) => p.title_category).filter(Boolean))].sort();
  const colours = [...new Set(products.flatMap((p) => p.title_colours || []))].sort();

  const shown = products
    .filter((p) => !platformFilter.length || platformFilter.includes(p.platform))
    .filter((p) => !matchFilter || MATCH_ORDER.indexOf(p.match) <= MATCH_ORDER.indexOf(matchFilter))
    .filter((p) => !categoryFilter || p.title_category === categoryFilter)
    .filter((p) => !colourFilter || (p.title_colours || []).includes(colourFilter))
    .filter((p) => minPrice === "" || (typeof p.price === "number" && p.price >= Number(minPrice)))
    .filter((p) => maxPrice === "" || (typeof p.price === "number" && p.price <= Number(maxPrice)))
    .sort((a, b) => {
      if (sortBy === "price_low" || sortBy === "price_high") {
        // Products without a known price always go last.
        const knownA = typeof a.price === "number";
        const knownB = typeof b.price === "number";
        if (knownA !== knownB) return knownA ? -1 : 1;
        if (knownA) return sortBy === "price_low" ? a.price - b.price : b.price - a.price;
      }
      return b.score - a.score;
    });

  const compared = products.filter((p) => compareIds.includes(p.id));
  const filtersActive = platformFilter.length || matchFilter || categoryFilter || colourFilter || minPrice || maxPrice;

  const clearFilters = () => {
    setPlatformFilter([]); setMatchFilter(""); setCategoryFilter("");
    setColourFilter(""); setMinPrice(""); setMaxPrice("");
  };

  const busy = wardrobeState === "loading" || shopState === "loading";
  const started = wardrobeState !== "idle";

  return (
    <Layout>
      <div className="page-header">
        <div>
          <h1 className="page-title">Find Similar Clothes</h1>
          <p className="page-subtitle">
            Upload a clothing photo to check your wardrobe, then find the same
            piece - or the closest alternatives - in online shops.
          </p>
        </div>
      </div>

      <div className="sim-layout">
        {/* ============================================= */}
        {/* YOUR SEARCH                                   */}
        {/* ============================================= */}
        <aside className="aw-card sim-search" aria-label="Your search">
          <h2 className="sim-h2">Your Search</h2>
          <form onSubmit={handleSubmit}>
            <label className="sim-drop">
              {previewUrl
                ? <img src={previewUrl} alt="Your uploaded clothing" className="sim-preview" />
                : <span className="sim-drop-hint">📷 Choose a clothing photo</span>}
              <input
                type="file"
                accept="image/*"
                aria-label="Clothing photo"
                onChange={(e) => {
                  setImage(e.target.files[0] || null);
                  setWardrobeError("");
                }}
              />
            </label>
            <button type="submit" className="aw-btn sim-full" disabled={busy || !image}>
              {wardrobeState === "loading" ? "Searching..." : "Find Similar"}
            </button>
          </form>

          {started && (
            <div className="sim-progress" aria-live="polite">
              <ProgressRow label="Checking your wardrobe" state={wardrobeState} onRetry={runWardrobe} />
              <ProgressRow
                label="Searching shops"
                state={shopState}
                onRetry={() => runShop(analysis)}
              />
            </div>
          )}

          {(wardrobeState === "done" || wardrobeState === "error") && (
            <div className="sim-attrs">
              <h3 className="sim-h3">Detected in your photo</h3>
              {analysis.uncertain && (
                <p className="sim-hint">
                  We're not sure about this photo - please check the type and colour
                  before searching shops.
                </p>
              )}
              {ATTRIBUTE_FIELDS.map(([field, label]) => (
                <label key={field} className="sim-attr">
                  <span>
                    {label}
                    {analysis.sources?.[field] && (
                      <em className="sim-source">{SOURCE_LABELS[analysis.sources[field]] || analysis.sources[field]}</em>
                    )}
                  </span>
                  <input
                    className="aw-input"
                    value={analysis[field] || ""}
                    placeholder="unknown"
                    maxLength={60}
                    onChange={(e) => editAttribute(field, e.target.value)}
                  />
                </label>
              ))}
              <label className="sim-attr">
                <span>Your keywords <em className="sim-source">optional</em></span>
                <input
                  className="aw-input"
                  value={analysis.keywords || ""}
                  placeholder="e.g. yellow anarkali mirror work"
                  maxLength={60}
                  onChange={(e) => editAttribute("keywords", e.target.value)}
                />
              </label>
              <button
                type="button"
                className="aw-btn aw-btn-ghost sim-full"
                disabled={busy || !image}
                onClick={() => runShop(analysis)}
              >
                {shopState === "done" ? "Search shops again" : "Search shops with these details"}
              </button>
            </div>
          )}
        </aside>

        <div className="sim-results">
          {wardrobeError && <div className="aw-alert">{wardrobeError}</div>}
          {notice && <div className="aw-success">{notice}</div>}

          {!started && (
            <div className="aw-card sim-empty">
              <p>Upload a clothing photo to find similar items in your wardrobe and in shops.</p>
            </div>
          )}

          {/* ============================================= */}
          {/* YOUR WARDROBE                                 */}
          {/* ============================================= */}
          {wardrobeState === "done" && (
            <section className="sim-section" aria-label="Your wardrobe">
              <h2 className="sim-h2">🧥 Available in Your Wardrobe</h2>
              {wardrobeStatus === "very_close" && (
                <p className="sim-sub">You probably own this already.</p>
              )}
              {wardrobeStatus === "similar" && (
                <p className="sim-sub">You have something similar.</p>
              )}
              {wardrobeStatus === "none" && (
                <p className="sim-sub">
                  Nothing in your wardrobe is a close match{wardrobeResults.length ? " - the nearest items are shown below" : ""}.
                </p>
              )}

              {wardrobeResults.length > 0 && (
                <div className="aw-grid sim-grid">
                  {wardrobeResults.map((item, idx) => (
                    <article key={item.item_id || idx} className="aw-card sim-product">
                      <div className="sim-product-img">
                        <img src={assetUrl(item.image)} alt={item.category || "Your wardrobe item"} />
                        <span className={`sim-match sim-wardrobe-${item.match_level || "loose"}`}>
                          {WARDROBE_LABELS[item.match_level] || "Similar"}
                        </span>
                      </div>
                      <div className="sim-product-body">
                        <div className="aw-item-name">{item.category || "Wardrobe item"}</div>
                        <div className="sim-muted">{percent(item.similarity)} visual similarity</div>
                        {item.color && <div className="sim-muted">Colour: {item.color}</div>}
                        {item.occasion && <div className="sim-muted">Occasion: {item.occasion}</div>}
                        {item.item_id && (
                          <button
                            type="button"
                            className="aw-icon-btn"
                            onClick={() => navigate("/wardrobe", { state: { openItem: item.item_id } })}
                          >
                            View in wardrobe
                          </button>
                        )}
                      </div>
                    </article>
                  ))}
                </div>
              )}

              {wardrobeStatus !== "none" && shopState === "idle" && (
                <div className="sim-offer">
                  <span>
                    {wardrobeStatus === "very_close"
                      ? "Want alternatives anyway?"
                      : "Want this exact design?"}
                  </span>
                  <button type="button" className="aw-btn aw-btn-sm" onClick={() => runShop(analysis)}>
                    {wardrobeStatus === "very_close" ? "Show online alternatives" : "Shop this look"}
                  </button>
                </div>
              )}
            </section>
          )}

          {/* ============================================= */}
          {/* SHOP SIMILAR                                  */}
          {/* ============================================= */}
          {shopState !== "idle" && (
            <section className="sim-section" aria-label="Shop similar">
              <h2 className="sim-h2">🛍️ Shop This Look</h2>

              {shopState === "loading" && (
                <div className="aw-progress"><span className="aw-spinner" /> Looking for this piece in shops...</div>
              )}

              {shopState === "error" && (
                <div className="aw-alert sim-row">
                  <span>{shopError}</span>
                  <button type="button" className="aw-icon-btn" onClick={() => runShop(analysis)}>Retry</button>
                </div>
              )}

              {shopState === "done" && shop && (
                <>
                  {shop.status === "exact_found" && (
                    <p className="sim-sub">Found the exact product in at least one shop, plus similar options.</p>
                  )}
                  {shop.message && (
                    <p className={`sim-sub${shop.status === "provider_error" ? " sim-warn" : ""}`}>{shop.message}</p>
                  )}
                  {(shop.status === "no_results" || shop.status === "provider_error") && (
                    <button type="button" className="aw-icon-btn" onClick={() => runShop(analysis)}>Try again</button>
                  )}

                  {products.length > 0 && (
                    <>
                      <div className="aw-card sim-filters" aria-label="Filter shop results">
                        <div className="sim-filter-group">
                          <span className="aw-label">Shop</span>
                          <div className="sim-chips">
                            {platforms.map((name) => (
                              <button
                                key={name}
                                type="button"
                                className={`aw-chip${platformFilter.includes(name) ? " on" : ""}`}
                                aria-pressed={platformFilter.includes(name)}
                                onClick={() => setPlatformFilter((prev) => (prev.includes(name)
                                  ? prev.filter((x) => x !== name) : [...prev, name]))}
                              >
                                {name}
                              </button>
                            ))}
                          </div>
                        </div>
                        <label className="sim-filter-group">
                          <span className="aw-label">Similarity</span>
                          <select className="aw-input" value={matchFilter} onChange={(e) => setMatchFilter(e.target.value)}>
                            <option value="">Any</option>
                            <option value="exact">Exact only</option>
                            <option value="very_similar">Very similar or better</option>
                            <option value="similar_style">Similar style or better</option>
                          </select>
                        </label>
                        {categories.length > 0 && (
                          <label className="sim-filter-group">
                            <span className="aw-label">Type</span>
                            <select className="aw-input" value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
                              <option value="">Any</option>
                              {categories.map((c) => <option key={c} value={c}>{c}</option>)}
                            </select>
                          </label>
                        )}
                        {colours.length > 0 && (
                          <label className="sim-filter-group">
                            <span className="aw-label">Colour</span>
                            <select className="aw-input" value={colourFilter} onChange={(e) => setColourFilter(e.target.value)}>
                              <option value="">Any</option>
                              {colours.map((c) => <option key={c} value={c}>{c}</option>)}
                            </select>
                          </label>
                        )}
                        <div className="sim-filter-group">
                          <span className="aw-label">Price (₹)</span>
                          <div className="sim-price-inputs">
                            <input className="aw-input" type="number" min="0" placeholder="Min" aria-label="Minimum price"
                                   value={minPrice} onChange={(e) => setMinPrice(e.target.value)} />
                            <input className="aw-input" type="number" min="0" placeholder="Max" aria-label="Maximum price"
                                   value={maxPrice} onChange={(e) => setMaxPrice(e.target.value)} />
                          </div>
                        </div>
                        <label className="sim-filter-group">
                          <span className="aw-label">Sort</span>
                          <select className="aw-input" value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
                            <option value="best">Best match</option>
                            <option value="price_low">Price: low to high</option>
                            <option value="price_high">Price: high to low</option>
                          </select>
                        </label>
                        {filtersActive ? (
                          <button type="button" className="aw-icon-btn" onClick={clearFilters}>Clear filters</button>
                        ) : null}
                      </div>

                      <p className="sim-muted sim-count">
                        Showing {shown.length} of {products.length} products
                        {shop.cached ? " (saved results)" : ""}. Labels show how much each one has in
                        common with your photo; prices and stock can change on the shop's site.
                      </p>

                      {shown.length === 0 && (
                        <p className="sim-sub">No products match these filters.</p>
                      )}

                      <div className="aw-grid sim-grid">
                        {shown.map((product) => (
                          <ProductCard
                            key={product.id}
                            product={product}
                            saved={savedByUrl.has(product.url)}
                            onToggleSave={toggleSave}
                            comparing={compareIds.includes(product.id)}
                            onToggleCompare={toggleCompare}
                            compareFull={compareIds.length >= MAX_COMPARE}
                          />
                        ))}
                      </div>
                    </>
                  )}

                  {shop.links?.length > 0 && (
                    <div className="sim-links">
                      <h3 className="sim-h3">
                        {products.length ? "Search for more on each shop" : "Search for this look on each shop"}
                      </h3>
                      <p className="sim-muted">Opens each shop's own search for "{shop.query}".</p>
                      <div className="sim-chips">
                        {shop.links.filter((l) => isWebLink(l.url)).map((link) => (
                          <a key={link.platform} className="aw-chip sim-link" href={link.url}
                             target="_blank" rel="noopener noreferrer">
                            {link.platform} ↗
                          </a>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}
            </section>
          )}

          {/* ============================================= */}
          {/* COMPARE                                       */}
          {/* ============================================= */}
          {compared.length > 0 && (
            <section className="aw-card sim-compare-panel" aria-label="Compare products">
              <div className="sim-row">
                <h3 className="sim-h3">Compare ({compared.length}/{MAX_COMPARE})</h3>
                <button type="button" className="aw-icon-btn" onClick={() => setCompareIds([])}>Clear</button>
              </div>
              <div className="sim-table-wrap">
                <table className="sim-table">
                  <tbody>
                    <tr>
                      <th scope="row">Product</th>
                      {compared.map((p) => (
                        <td key={p.id}>
                          <div className="sim-compare-img"><ProductImage src={p.image} alt={p.title} /></div>
                          {p.title}
                        </td>
                      ))}
                    </tr>
                    <tr><th scope="row">Shop</th>{compared.map((p) => <td key={p.id}>{p.platform}</td>)}</tr>
                    <tr><th scope="row">Price</th>{compared.map((p) => <td key={p.id}>{formatPrice(p) || "On site"}</td>)}</tr>
                    <tr><th scope="row">Match</th>{compared.map((p) => <td key={p.id}>{MATCH_LABELS[p.match]}</td>)}</tr>
                    <tr>
                      <th scope="row">In common</th>
                      {compared.map((p) => <td key={p.id}>{(p.matched_attributes || []).join(", ") || "-"}</td>)}
                    </tr>
                    <tr>
                      <th scope="row">Stock</th>
                      {compared.map((p) => (
                        <td key={p.id}>{p.in_stock === true ? "In stock" : p.in_stock === false ? "Out of stock" : "Unknown"}</td>
                      ))}
                    </tr>
                    <tr>
                      <th scope="row" aria-label="Link" />
                      {compared.map((p) => (
                        <td key={p.id}>
                          <a className="aw-btn aw-btn-sm" href={p.url} target="_blank" rel="noopener noreferrer">View ↗</a>
                        </td>
                      ))}
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* ============================================= */}
          {/* WISHLIST                                      */}
          {/* ============================================= */}
          <section className="sim-section" aria-label="Your wishlist">
            <button
              type="button"
              className="aw-btn aw-btn-soft"
              aria-expanded={showWishlist}
              onClick={() => setShowWishlist((v) => !v)}
            >
              ♥ Your shopping wishlist ({wishlist.length}) {showWishlist ? "▲" : "▼"}
            </button>
            {showWishlist && (
              wishlist.length === 0 ? (
                <p className="sim-sub">Tap ♡ on a product to save it here.</p>
              ) : (
                <div className="aw-grid sim-grid">
                  {wishlist.map((item) => (
                    <article key={item.id} className="aw-card sim-product">
                      <div className="sim-product-img"><ProductImage src={item.image} alt={item.title} /></div>
                      <div className="sim-product-body">
                        <div className="sim-platform">{item.platform}</div>
                        <div className="aw-item-name sim-title">{item.title}</div>
                        {formatPrice(item) && (
                          <div className="sim-muted">
                            {formatPrice(item)}
                            {item.saved_at && ` when saved on ${new Date(item.saved_at).toLocaleDateString()}`}
                          </div>
                        )}
                        <div className="sim-product-actions">
                          {isWebLink(item.url) && (
                            <a className="aw-btn aw-btn-sm" href={item.url} target="_blank" rel="noopener noreferrer">
                              View Product ↗
                            </a>
                          )}
                          <button type="button" className="aw-icon-btn" onClick={() => removeSaved(item)}>Remove</button>
                        </div>
                      </div>
                    </article>
                  ))}
                </div>
              )
            )}
          </section>

          {/* ============================================= */}
          {/* MORE IDEAS - the original dataset results     */}
          {/* ============================================= */}
          {wardrobeState === "done" && (datasetResults.length > 0 || indofashionResults.length > 0) && (
            <section className="sim-section" aria-label="More ideas">
              <h2 className="sim-h2">✨ More Ideas from the AI Fashion Datasets</h2>
              <p className="sim-sub">Visually similar clothes found by the AI models (not for sale).</p>
              <div className="aw-grid sim-grid sim-grid-small">
                {datasetResults.map((item, idx) => (
                  <div key={`d${idx}`} className="aw-card sim-idea">
                    <img
                      src={`${API_URL}/api/dataset/${item.image.replace(/^dataset\/deepfashion\//, "")}`}
                      alt="Similar clothing"
                    />
                    <span className="sim-muted">{percent(item.similarity)} match</span>
                  </div>
                ))}
                {indofashionResults.map((item, idx) => (
                  <div key={`i${idx}`} className="aw-card sim-idea">
                    <img
                      src={`${API_URL}/api/indofashion/${item.image.replace(/^.*dataset\/indofashion\/processed\//, "")}`}
                      alt="Similar Indian clothing"
                      onError={(e) => { e.currentTarget.style.display = "none"; }}
                    />
                    <span className="sim-muted">{percent(item.similarity)} match · IndoFashion</span>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
    </Layout>
  );
}

export default SimilarSearch;

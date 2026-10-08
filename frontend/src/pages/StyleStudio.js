import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Layout from "../components/Layout";
import PageHeader from "../components/PageHeader";
import { assetUrl } from "../config";
import { authGet, authPost, apiErrorMessage, isAuthError } from "../lib/api";
import axios from "axios";
import { API_URL } from "../config";
import "../styles/aw-v2.css";
import "../styles/studio.css";

/*
 * STYLE & TRENDS - personal stylist.
 * Three things are always visibly separate:
 *   Fashion Inspiration  (trend cards: published sources, never your clothes)
 *   Your Wardrobe        (the real pieces, with their real photos)
 *   Your Outfit          (what the stylist built from your wardrobe)
 */

const STATUS = {
  yes: { icon: "✓", cls: "yes" },
  partly: { icon: "◐", cls: "partly" },
  no: { icon: "＋", cls: "no" },
  inspiration: { icon: "✦", cls: "insp" },
};

function fmtDate(value) {
  if (!value) return "";
  try {
    return new Date(value).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  } catch {
    return value;
  }
}

function Pieces({ pieces }) {
  return (
    <div className="st-pieces">
      {pieces.map((p) => (
        <figure key={p._id} className="st-piece">
          {p.image_path ? <img src={assetUrl(p.image_path)} alt={p.display_name || p.category} loading="lazy" /> : <span>👕</span>}
          <figcaption>
            {p.display_name || p.category}
            {p.color_display || p.color ? <small> · {p.color_display || p.color}</small> : null}
          </figcaption>
        </figure>
      ))}
    </div>
  );
}

export function OutfitCard({ outfit, onSave, onTry, onWear, saved, worn }) {
  return (
    <article className="st-outfit" data-testid="studio-outfit">
      <header>
        <span className="st-tag">Your Outfit</span>
        <h3>✨ {outfit.name}</h3>
        <p className="st-meta">
          <strong>Best for:</strong> {outfit.best_for.join(" · ")} &nbsp;|&nbsp; <strong>Style:</strong> {outfit.style_label}
        </p>
      </header>
      <p className="st-sub">From your wardrobe</p>
      <Pieces pieces={outfit.pieces} />
      <div className="st-why">
        <p className="st-label">Why it works</p>
        <ul>{outfit.why.map((line) => <li key={line}>{line}</li>)}</ul>
        <p><strong>💡 Styling tip:</strong> {outfit.styling_tip}</p>
        {outfit.fresh_note && <p className="st-fresh">🌱 {outfit.fresh_note}</p>}
        {outfit.notes.map((n) => <p key={n} className="st-note">{n}</p>)}
      </div>
      <div className="st-actions">
        <button type="button" className="aw-btn aw-btn-sm" onClick={() => onTry(outfit)}>👗 Try This Outfit</button>
        <button type="button" className="aw-btn aw-btn-soft aw-btn-sm" onClick={() => onSave(outfit)} disabled={saved}>
          {saved ? "💾 Saved" : "💾 Save"}
        </button>
        <button type="button" className="aw-btn aw-btn-ghost aw-btn-sm" onClick={() => onWear(outfit)} disabled={worn}>
          {worn ? "📅 Logged today" : "📅 Wore it today"}
        </button>
      </div>
    </article>
  );
}

function StyleStudio() {
  const navigate = useNavigate();
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ occasion: "casual", color: "", style: "", trend_id: "" });
  const [created, setCreated] = useState(null);
  const [creating, setCreating] = useState(false);
  const [ideas, setIdeas] = useState(null);
  const [shopping, setShopping] = useState(null);
  const [savedList, setSavedList] = useState([]);
  const [flags, setFlags] = useState({});
  const [toast, setToast] = useState("");

  const fail = useCallback((err, what) => {
    if (isAuthError(err) && err?.response?.status === 401) navigate("/login");
    else setError(apiErrorMessage(err, what));
  }, [navigate]);

  const loadSaved = useCallback(() => {
    authGet("/api/style/saved").then((d) => setSavedList(d.saved || [])).catch(() => {});
  }, []);

  useEffect(() => {
    if (!localStorage.getItem("token")) { navigate("/login"); return; }
    authGet("/api/style/overview").then(setOverview).catch((e) => fail(e, "Loading trends"));
    authGet("/api/style/ideas").then((d) => setIdeas(d.ideas || [])).catch(() => setIdeas([]));
    authGet("/api/style/shopping").then(setShopping).catch(() => setShopping(null));
    loadSaved();
  }, [navigate, fail, loadSaved]);

  const create = async (overrides = {}) => {
    const body = { ...form, ...overrides };
    setCreating(true);
    setError("");
    try {
      setCreated(await authPost("/api/style/outfits", body));
      setTimeout(() => document.getElementById("studio-create")?.scrollIntoView?.({ behavior: "smooth" }), 50);
    } catch (err) {
      fail(err, "Creating outfits");
    } finally {
      setCreating(false);
    }
  };

  const myVersion = (trend) => {
    setForm((f) => ({ ...f, trend_id: trend.id, occasion: "" }));
    create({ trend_id: trend.id, occasion: "" });
  };

  const flash = (msg) => { setToast(msg); setTimeout(() => setToast(""), 3500); };

  const save = async (outfit) => {
    try {
      await authPost("/api/style/saved", {
        name: outfit.name, occasion: outfit.occasion_label, item_ids: outfit.item_ids,
        style_tags: outfit.style_tags, style_label: outfit.style_label,
        trend_id: outfit.trends[0]?.id, trend_name: outfit.trends[0]?.name,
        why: outfit.why, styling_tip: outfit.styling_tip,
      });
      setFlags((f) => ({ ...f, [`s-${outfit.id}`]: true }));
      flash("Saved to My Saved Outfits 💾");
      loadSaved();
    } catch (err) { fail(err, "Saving"); }
  };

  const wear = async (outfit) => {
    try {
      const d = await authPost("/api/calendar", { item_ids: outfit.key_item_ids.length ? outfit.key_item_ids : outfit.item_ids, name: outfit.name, occasion: outfit.occasion });
      setFlags((f) => ({ ...f, [`w-${outfit.id}`]: true }));
      flash(d.warning || "Logged in your Outfit Calendar 📅");
    } catch (err) { fail(err, "Logging"); }
  };

  // Hands the outfit to the EXISTING Virtual Try-On page; nothing is
  // generated (and no try-on is used) until you press Try On there.
  const tryOn = (outfit) => navigate("/tryon", {
    state: { itemIds: outfit.item_ids, source: "style_studio", occasion: outfit.occasion, label: outfit.name },
  });

  const removeSaved = async (id) => {
    try {
      await axios.delete(`${API_URL}/api/style/saved/${id}`, { headers: { Authorization: `Bearer ${localStorage.getItem("token")}` } });
      loadSaved();
    } catch (err) { fail(err, "Deleting"); }
  };

  const outfitProps = (o) => ({
    outfit: o, onSave: save, onTry: tryOn, onWear: wear,
    saved: flags[`s-${o.id}`], worn: flags[`w-${o.id}`],
  });

  const live = overview?.live || {};
  const liveOn = Object.values(live).some((v) => v && v.ok);

  return (
    <Layout>
      <PageHeader title="Style & Trends" subtitle="Your personal style intelligence - learn from fashion, style your own wardrobe." />
      {error && <div className="aw-alert" role="alert">{error}</div>}
      {toast && <div className="st-toast" role="status">{toast}</div>}

      {/* A. WHAT'S TRENDING */}
      <section className="st-section">
        <div className="st-head">
          <h2>🔥 What's Trending</h2>
          <span className="st-tag insp">Fashion Inspiration</span>
        </div>
        <p className="st-hint">
          {liveOn
            ? "Trends from published fashion sources, confirmed by live signals."
            : `From published 2026 fashion sources (curated ${fmtDate(overview?.curated_on)}). Live trend signals aren't switched on yet.`}
          {" "}Inspiration only - nothing here is added to your wardrobe.
        </p>
        {!overview && !error && <p className="st-hint">Reading the trends…</p>}
        <div className="st-trends">
          {(overview?.trends || []).map((t) => {
            const w = t.your_wardrobe;
            const s = STATUS[w.status] || STATUS.partly;
            return (
              <article key={t.id} className="st-trend" data-testid="trend-card">
                <h3>{t.emoji} {t.name}</h3>
                <p>{t.summary}</p>
                <p className="st-label">👀 What it means</p>
                <ul>{t.meaning.map((m) => <li key={m}>{m}</li>)}</ul>
                <p className="st-label">Why it's trending</p>
                <p className="st-small">{t.why}</p>
                <p className="st-small"><strong>Best for:</strong> {t.occasions.map((o) => overview.occasions.find((x) => x.value === o)?.label || o).join(", ")}</p>
                {t.colors.length > 0 && <p className="st-small"><strong>Colours:</strong> {t.colors.join(", ")}</p>}
                <details className="st-sources">
                  <summary>Sources · {t.confidence} confidence{t.freshness === "live" ? " · live" : ""}</summary>
                  <ul>
                    {t.sources.map((src) => (
                      <li key={src.id}><a href={src.url} target="_blank" rel="noopener noreferrer">{src.name}</a> - {src.title}{src.published ? ` (${fmtDate(src.published)})` : ""}</li>
                    ))}
                    {t.live_signals.map((sig, i) => (
                      <li key={i}>{sig.provider}: {sig.keyword || sig.title}{sig.growth_mom != null ? ` (+${sig.growth_mom}% month on month)` : ""}</li>
                    ))}
                  </ul>
                </details>
                <div className={`st-can ${s.cls}`}>
                  <p className="st-label">👗 Can you do it?</p>
                  <p>{s.icon} {w.message}</p>
                  {t.rule_note && w.status !== "inspiration" && <p className="st-small">{t.rule_note}</p>}
                </div>
                {w.status === "yes" && (
                  <button type="button" className="aw-btn aw-btn-sm" onClick={() => myVersion(t)}>✨ Create My Version</button>
                )}
              </article>
            );
          })}
        </div>
      </section>

      {/* B. CREATE AN OUTFIT */}
      <section className="st-section" id="studio-create">
        <div className="st-head"><h2>👗 Create an Outfit</h2><span className="st-tag">Your Wardrobe</span></div>
        <div className="st-form">
          <label>Occasion
            <select className="aw-input" value={form.occasion} onChange={(e) => setForm({ ...form, occasion: e.target.value })}>
              <option value="">Any (or the trend's)</option>
              {(overview?.occasions || []).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
          <label>Colour
            <input className="aw-input" placeholder="e.g. black" value={form.color} onChange={(e) => setForm({ ...form, color: e.target.value })} />
          </label>
          <label>Style
            <select className="aw-input" value={form.style} onChange={(e) => setForm({ ...form, style: e.target.value })}>
              <option value="">Any</option>
              {(overview?.styles || []).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
          <label>Trend
            <select className="aw-input" value={form.trend_id} onChange={(e) => setForm({ ...form, trend_id: e.target.value })}>
              <option value="">None</option>
              {(overview?.trends || []).filter((t) => t.your_wardrobe.status === "yes").map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </label>
          <button type="button" className="aw-btn" onClick={() => create()} disabled={creating}>{creating ? "Styling…" : "✨ Create Outfits"}</button>
        </div>
        <p className="st-hint">Wardrobe-only: every outfit uses clothes you own.</p>
        {created && (
          <>
            {created.notes.map((n) => <p key={n} className="st-note">{n}</p>)}
            <div className="st-outfits">{created.outfits.map((o) => <OutfitCard key={o.id} {...outfitProps(o)} />)}</div>
          </>
        )}
      </section>

      {/* C. IDEAS */}
      <section className="st-section">
        <div className="st-head"><h2>✨ From Your Wardrobe</h2><span className="st-tag">Your Wardrobe</span></div>
        <p className="st-hint">Combinations you own but haven't worn together yet.</p>
        {ideas === null ? <p className="st-hint">Looking through your wardrobe…</p>
          : ideas.length === 0 ? <p className="st-hint">Add a few more pieces to unlock new ideas.</p>
          : <div className="st-outfits">{ideas.map((o) => <OutfitCard key={o.id} {...outfitProps(o)} />)}</div>}
      </section>

      {/* D. SHOPPING */}
      <section className="st-section">
        <div className="st-head"><h2>🛍 What Should I Shop For?</h2><span className="st-tag">Buy less · Style more</span></div>
        {!shopping ? <p className="st-hint">Checking your wardrobe for gaps…</p>
          : shopping.no_purchase_needed ? <div className="st-nobuy">✅ {shopping.message}</div>
          : (
            <>
              <p className="st-hint">{shopping.message}</p>
              <div className="st-gaps">
                {shopping.gaps.map((g, i) => (
                  <article key={g.name} className={`st-gap ${i === 0 ? "top" : ""}`}>
                    {i === 0 && <span className="st-tag">One useful purchase</span>}
                    <h3>{g.name}</h3>
                    <p>{g.why}</p>
                    <p className="st-small"><strong>It can create:</strong> {g.unlocks.map((u) => `${u.count} ${u.occasion.toLowerCase()}`).join(" · ")}</p>
                    {g.trends.length > 0 && <p className="st-small"><strong>Helps recreate:</strong> {g.trends.join(", ")}</p>}
                    {g.works_with.length > 0 && (
                      <>
                        <p className="st-label">Works with what you own</p>
                        <div className="st-mini">{g.works_with.map((p) => p.image_path && <img key={p._id} src={assetUrl(p.image_path)} alt={p.display_name} title={p.display_name} />)}</div>
                      </>
                    )}
                    <div className="st-shops">
                      {(g.shop?.links || []).slice(0, 4).map((l) => <a key={l.store} href={l.url} target="_blank" rel="noopener noreferrer">{l.name} ↗</a>)}
                    </div>
                  </article>
                ))}
              </div>
            </>
          )}
      </section>

      {/* E. SAVED */}
      <section className="st-section">
        <div className="st-head"><h2>💾 My Saved Outfits</h2></div>
        {savedList.length === 0 ? <p className="st-hint">Save an outfit you like and it'll appear here.</p> : (
          <div className="st-outfits">
            {savedList.map((s) => (
              <article key={s.id} className="st-outfit" data-testid="saved-outfit">
                <header>
                  <h3>💾 {s.name}</h3>
                  <p className="st-meta">{[s.occasion, s.style_label, s.trend_name].filter(Boolean).join(" · ")} · saved {fmtDate(s.created_at)}</p>
                </header>
                <Pieces pieces={s.pieces} />
                {s.missing_pieces > 0 && <p className="st-note">{s.missing_pieces} piece(s) were removed from your wardrobe.</p>}
                <div className="st-actions">
                  <button type="button" className="aw-btn aw-btn-sm" disabled={!s.item_ids.length}
                    onClick={() => navigate("/tryon", { state: { itemIds: s.item_ids, source: "style_studio", label: s.name } })}>👗 Try This Outfit</button>
                  <button type="button" className="aw-btn aw-btn-ghost aw-btn-sm" onClick={() => removeSaved(s.id)}>Delete</button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </Layout>
  );
}

export default StyleStudio;

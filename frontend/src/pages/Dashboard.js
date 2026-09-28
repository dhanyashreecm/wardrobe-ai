import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Layout from "../components/Layout";
import { useProfile } from "../components/PageHeader";
import { SparkleIcon } from "../components/Icons";
import { assetUrl } from "../config";
import { authGet, isAuthError, occasionLabel } from "../lib/api";
import "../styles/home.css";

// HOME - a calm personal wardrobe dashboard. Everything shown comes from
// the signed-in cloud account: the profile (/api/user/profile), the
// wardrobe (/api/wardrobe) and the outfits actually marked "I wore this"
// (/api/outfits/history). Nothing is invented; missing data is simply not
// shown. Navigation lives in the sidebar only - Home does not repeat it.

const MAX_RECENT = 6;
const MAX_ADDED = 4;
const NOT_MAIN = new Set(["Shoes", "Accessories"]);
const WEEK_MS = 7 * 86400000;

function greeting(now = new Date()) {
  const hour = now.getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

// The name saved on the account (first word). If the account has no
// name, the server's email for it; otherwise a neutral "there".
export function displayName(profile) {
  const name = (profile?.name || "").trim();
  if (name) return name.split(/\s+/)[0];
  const email = (profile?.email || "").trim();
  if (email.includes("@")) return email.split("@")[0];
  return "there";
}

function dayLabel(iso) {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return "";
  const today = new Date();
  const days = Math.floor((today.setHours(0, 0, 0, 0) - new Date(when).setHours(0, 0, 0, 0)) / 86400000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return when.toLocaleDateString(undefined, { weekday: "long" });
}

// One picture per worn outfit: its main garment (not the shoes or bag).
export function recentOutfits(history, items) {
  const byId = new Map(items.map((item) => [String(item._id), item]));
  const out = [];
  for (const entry of history || []) {
    const pieces = (entry.item_ids || []).map((id) => byId.get(String(id))).filter(Boolean);
    if (!pieces.length) continue; // every piece since deleted
    const cover = pieces.find((p) => !NOT_MAIN.has(p.group)) || pieces[0];
    out.push({ key: `${entry.outfit_key}-${entry.worn_at}`, cover, entry });
    if (out.length === MAX_RECENT) break;
  }
  return out;
}

function addedAt(item) {
  const t = Date.parse(item.created_at || "");
  return Number.isNaN(t) ? null : t;
}

// Newest pieces first (only items that carry a real upload date).
export function recentlyAdded(items, limit = MAX_ADDED) {
  return (items || [])
    .filter((item) => addedAt(item) !== null)
    .sort((a, b) => addedAt(b) - addedAt(a))
    .slice(0, limit);
}

function Dashboard() {
  const navigate = useNavigate();
  const profile = useProfile();
  const [items, setItems] = useState(null);
  const [history, setHistory] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!localStorage.getItem("token")) {
      navigate("/login");
      return;
    }
    const onError = (err) => {
      if (isAuthError(err)) {
        localStorage.removeItem("token");
        navigate("/login");
      } else {
        setError("Couldn't reach the server - is the backend running?");
      }
    };
    authGet("/api/wardrobe").then((d) => setItems(d.items || [])).catch(onError);
    authGet("/api/outfits/history")
      .then((d) => setHistory(d.history || []))
      .catch(() => setHistory([]));
  }, [navigate]);

  // Blank until the profile arrives, so no placeholder name flashes.
  const name = profile ? displayName(profile) : "";
  const gender = (profile?.gender || "").toLowerCase();
  const recent = useMemo(
    () => (items && history ? recentOutfits(history, items) : []),
    [items, history]
  );
  const added = useMemo(() => recentlyAdded(items), [items]);
  const addedThisWeek = (items || []).filter((i) => (addedAt(i) || 0) > Date.now() - WEEK_MS).length;
  const loading = items === null || history === null;
  const initial = (name || "·").charAt(0).toUpperCase();

  return (
    <Layout>
      <div className="hm">
        <section className="hm-hero">
          <div className="hm-hero-text">
            <div className="hm-eyebrow">{greeting()},</div>
            <h1 className="hm-name">{name} <span className="hm-leaf" aria-hidden="true">❦</span></h1>
            <p className="hm-lede">
              Welcome back to your wardrobe.
              <br />
              Let's create something beautiful today.
            </p>
            <Link to="/recommend" className="hm-cta">
              <SparkleIcon width={17} height={17} /> Get Outfit Recommendations <span aria-hidden="true">→</span>
            </Link>
          </div>
          <div className="hm-hero-img" role="img" aria-label="A calm wardrobe corner with a clothing rack" />
        </section>

        <aside className="hm-profile" aria-label="Your profile">
          <div className="hm-profile-head">
            {profile?.profile_picture ? (
              <img className="hm-avatar" src={assetUrl(profile.profile_picture)} alt="" />
            ) : (
              <span className="hm-avatar">{initial}</span>
            )}
            <div>
              <div className="hm-profile-name">{profile?.name || name}</div>
              {profile?.email && <div className="hm-muted">{profile.email}</div>}
            </div>
          </div>
          <dl className="hm-stats">
            <div>
              <dt>Wardrobe</dt>
              <dd>{items === null ? "…" : `${items.length} item${items.length === 1 ? "" : "s"}`}</dd>
            </div>
            {gender && (
              <div>
                <dt>Wardrobe for</dt>
                <dd>{gender === "male" ? "Men" : gender === "female" ? "Women" : gender}</dd>
              </div>
            )}
            {items !== null && (
              <div>
                <dt>Added this week</dt>
                <dd>{addedThisWeek}</dd>
              </div>
            )}
          </dl>
          <div className="hm-script">Better outfits, brighter days ♡</div>
        </aside>

        <section className="hm-recent" aria-label="Your wardrobe this week">
          <h2>Your wardrobe this week</h2>
          <p className="hm-muted">Outfits you've marked as worn.</p>
          {error && <p className="hm-note">{error}</p>}
          {!error && loading && <p className="hm-muted">Loading…</p>}
          {!error && !loading && recent.length === 0 && (
            <div className="hm-empty">
              <p className="hm-empty-title">Your wardrobe story starts here.</p>
              <p>Wear a recommended outfit and press "I wore this" - it will appear here.</p>
            </div>
          )}
          {recent.length > 0 && (
            <div className="hm-recent-row">
              {recent.map(({ key, cover, entry }) => (
                <figure key={key} className="hm-outfit">
                  <img src={assetUrl(cover.image_path)} alt={cover.display_name || cover.category} />
                  <figcaption>
                    <strong>{dayLabel(entry.worn_at)}</strong>
                    {entry.occasion && <span>{occasionLabel(entry.occasion)}</span>}
                  </figcaption>
                </figure>
              ))}
            </div>
          )}
        </section>

        <aside className="hm-added" aria-label="Recently added">
          <h2>Recently added</h2>
          {!loading && added.length === 0 && !error && (
            <p className="hm-muted">New pieces you add will show up here.</p>
          )}
          {added.length > 0 && (
            <ul className="hm-added-list">
              {added.map((item) => (
                <li key={item._id}>
                  <img src={assetUrl(item.image_path)} alt="" />
                  <span>
                    <strong>{item.display_name || item.category}</strong>
                    <span className="hm-muted">{dayLabel(item.created_at)}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <footer className="hm-quote">
          <span className="hm-leaf" aria-hidden="true">❦</span>
          <div>
            <strong>Style is a way to say who you are</strong>
            <span className="hm-muted">Same wardrobe. New possibilities.</span>
          </div>
        </footer>
      </div>
    </Layout>
  );
}

export default Dashboard;

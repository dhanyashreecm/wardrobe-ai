import { useEffect, useState } from "react";
import axios from "axios";
import { useNavigate, Link } from "react-router-dom";
import Layout from "../components/Layout";
import "../App.css";

// =========================================================
// CATEGORY BUCKETS
//
// The wardrobe stores fine-grained categories (Shirt, Men
// Kurta, Palazzos, ...); the dashboard groups them into a
// handful of tiles so the home page reads as an overview,
// not a wall of 24 categories.
// =========================================================

const CATEGORY_BUCKETS = [
  {
    key: "tops",
    label: "Tops",
    tint: "tile-tint-1",
    match: ["Shirt", "Blouse", "Women Kurta", "Men Kurta"],
  },
  {
    key: "bottoms",
    label: "Bottoms",
    tint: "tile-tint-3",
    match: [
      "Pant",
      "Skirt",
      "Leggings & Salwars",
      "Palazzos",
      "Dhoti Pants",
    ],
  },
  {
    key: "dresses",
    label: "Dresses & Sets",
    tint: "tile-tint-4",
    match: ["Dress", "Gown", "Lehenga"],
  },
  {
    key: "outerwear",
    label: "Outerwear",
    tint: "tile-tint-5",
    match: ["Jacket", "Nehru Jacket", "Sherwani"],
  },
  {
    key: "footwear",
    label: "Footwear",
    tint: "tile-tint-2",
    match: ["Mojaris Men", "Mojaris Women"],
  },
  {
    key: "ethnic",
    label: "Ethnic Wear",
    tint: "tile-tint-6",
    match: ["Saree", "Dupatta", "Petticoat"],
  },
  {
    key: "accessories",
    label: "Accessories",
    tint: "tile-tint-1",
    match: ["Bag", "Watch", "Belt", "Jewelry"],
  },
];

const ONE_WEEK_MS = 7 * 24 * 60 * 60 * 1000;

function Dashboard() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    const token = localStorage.getItem("token");

    if (!token) {
      navigate("/login");
      return;
    }

    axios
      .get("http://localhost:5001/api/wardrobe", {
        headers: { Authorization: `Bearer ${token}` },
      })
      .then((res) => setItems(res.data.items || []))
      .catch(() => navigate("/login"))
      .finally(() => setLoading(false));
  }, [navigate]);

  // -----------------------------------------------------
  // STATS
  // -----------------------------------------------------

  const totalItems = items.length;

  const categoryCount = new Set(
    items.map((item) => item.category).filter(Boolean)
  ).size;

  const favoriteCount = items.filter(
    (item) => item.favorite
  ).length;

  const recentCount = items.filter((item) => {
    if (!item.created_at) return false;
    const created = new Date(item.created_at).getTime();
    return !Number.isNaN(created) && Date.now() - created < ONE_WEEK_MS;
  }).length;

  // -----------------------------------------------------
  // CATEGORY TILES
  // -----------------------------------------------------

  const tiles = CATEGORY_BUCKETS.map((bucket) => {
    const bucketItems = items.filter((item) =>
      bucket.match.includes(item.category)
    );

    const cover = bucketItems.find((item) => item.image_path);

    return {
      ...bucket,
      count: bucketItems.length,
      cover,
    };
  }).filter((bucket) => bucket.count > 0);

  return (
    <Layout>
      <div className="page-header">
        <div>
          <h1 className="page-title">My Digital Wardrobe</h1>
          <p className="page-subtitle">
            Your clothes, your style, all in one place.
          </p>
        </div>
      </div>

      {!loading && totalItems === 0 && (
        <p style={{ color: "#8a7a6d", marginBottom: "24px" }}>
          Your wardrobe is empty so far —{" "}
          <Link to="/wardrobe" style={{ color: "#c1694f", fontWeight: 600 }}>
            add your first item
          </Link>{" "}
          to see it here.
        </p>
      )}

      {/* STAT CARDS */}

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-icon tone-primary">👗</div>
          <div>
            <div className="stat-value">{totalItems}</div>
            <div className="stat-label">Total Items</div>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon tone-sage">🗂️</div>
          <div>
            <div className="stat-value">{categoryCount}</div>
            <div className="stat-label">Categories</div>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon tone-blue">❤️</div>
          <div>
            <div className="stat-value">{favoriteCount}</div>
            <div className="stat-label">Favorites</div>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon tone-lavender">🕓</div>
          <div>
            <div className="stat-value">{recentCount}</div>
            <div className="stat-label">Added This Week</div>
          </div>
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "2fr 1fr",
          gap: "24px",
          alignItems: "start",
        }}
      >
        <div>
          {/* CATEGORY TILES */}

          {tiles.length > 0 && (
            <>
              <h2 className="section-title" style={{ marginTop: 0 }}>
                Browse by category
              </h2>

              <div className="tile-grid">
                {tiles.map((tile) => (
                  <Link
                    key={tile.key}
                    to="/wardrobe"
                    className={`category-tile ${
                      tile.cover ? "" : tile.tint
                    }`}
                  >
                    {tile.cover && (
                      <>
                        <img
                          src={`http://localhost:5001${tile.cover.image_path}`}
                          alt={tile.label}
                        />
                        <div className="tile-overlay" />
                      </>
                    )}

                    <span className="tile-label">{tile.label}</span>

                    <div>
                      <span className="tile-count">
                        {tile.count} item
                        {tile.count === 1 ? "" : "s"}
                      </span>
                    </div>
                  </Link>
                ))}
              </div>
            </>
          )}
        </div>

        {/* QUICK ACTIONS */}

        <div className="side-panel">
          <h3>Quick Actions</h3>

          <ul className="quick-actions">
            <li>
              <Link to="/wardrobe">
                <span className="qa-icon">＋</span>
                Add New Item
              </Link>
            </li>
            <li>
              <Link to="/recommend">
                <span className="qa-icon">✨</span>
                Get Outfit Recommendation
              </Link>
            </li>
            <li>
              <Link to="/trip">
                <span className="qa-icon">🧳</span>
                Plan a Trip
              </Link>
            </li>
            <li>
              <Link to="/similar">
                <span className="qa-icon">🔍</span>
                Find Similar Clothes
              </Link>
            </li>
          </ul>
        </div>
      </div>
    </Layout>
  );
}

export default Dashboard;

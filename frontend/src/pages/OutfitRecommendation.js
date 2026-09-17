import { useState } from "react";
import axios from "axios";
import Layout from "../components/Layout";
import "../App.css";

// Matches backend.outfit_recommendation.CANONICAL_OCCASIONS.
// Recommendations are filtered STRICTLY by this value - asking for
// "Party" only ever returns items tagged Party (or a known alias),
// never casual items mixed in.
const OCCASIONS = [
  ["casual", "Casual"],
  ["day_outing", "Day Outing"],
  ["college", "College"],
  ["office", "Office"],
  ["interview", "Interview"],
  ["date", "Date"],
  ["party", "Party"],
  ["wedding", "Wedding"],
  ["traditional", "Traditional"]
];

// Set at registration/login (see Register.js / Login.js). Shown here
// purely as a label so it's clear whose wardrobe these recommendations
// were built from - it never changes which items are eligible.
const GENDER_LABELS = {
  male: "Men's Wear",
  female: "Women's Wear"
};

function OutfitRecommendation() {
  const [occasion, setOccasion] = useState("casual");
  const [city, setCity] = useState("");
  const [useWeather, setUseWeather] = useState(false);
  const [weather, setWeather] = useState(null);
  const [weatherError, setWeatherError] = useState("");
  const [recommendations, setRecommendations] = useState([]);
  const [notes, setNotes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [searched, setSearched] = useState(false);

  const genderKey = (localStorage.getItem("gender") || "").toLowerCase();
  const genderLabel = GENDER_LABELS[genderKey];

  const getRecommendations = async () => {
    setLoading(true);
    setError("");
    setWeather(null);
    setWeatherError("");
    setRecommendations([]);
    setNotes([]);
    setSearched(true);

    const token = localStorage.getItem("token");

    let url = `http://localhost:5001/api/ai/recommend?occasion=${occasion}`;

    if (useWeather && city.trim()) {
      url += `&city=${encodeURIComponent(city.trim())}`;
    }

    try {
      const res = await axios.get(
        url,
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

      if (res.data.success) {
        setRecommendations(
          res.data.recommendations || []
        );

        // Honest "missing item" messaging (see backend
        // describe_missing_pieces) - e.g. "Your wardrobe does not
        // contain a suitable bottom to pair with your casual tops."
        // Shown even when recommendations ARE returned (they may
        // just be accessory-only or one-piece outfits).
        setNotes(res.data.notes || []);

        setWeather(res.data.weather || null);
        setWeatherError(res.data.weather_error || "");
      } else {
        setError(
          res.data.message ||
            "Could not generate recommendations."
        );
      }
    } catch (err) {
      console.error(
        "Recommendation error:",
        err
      );

      setError(
        err.response?.data?.message ||
          "Failed to generate outfit recommendations."
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <Layout>
      <div className="page-header">
        <div>
          <h1 className="page-title">Recommend an Outfit</h1>
          <p className="page-subtitle">
            Get outfit ideas using clothes already available in
            your wardrobe.
            {genderLabel && ` Showing ${genderLabel}.`}
          </p>
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "300px 1fr",
          gap: "28px",
          alignItems: "start",
        }}
      >
        <div className="side-panel">
          {/* OCCASION */}

          <label className="field-label">Choose occasion</label>

          <select
            value={occasion}
            onChange={(e) =>
              setOccasion(e.target.value)
            }
          >
            {OCCASIONS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>

          {/* WEATHER */}

          <label
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              fontSize: "13px",
              fontWeight: 600,
              marginBottom: "10px",
            }}
          >
            <input
              type="checkbox"
              checked={useWeather}
              onChange={(e) =>
                setUseWeather(e.target.checked)
              }
            />
            Consider today's weather
          </label>

          {useWeather && (
            <input
              placeholder="City (e.g. Bengaluru)"
              value={city}
              onChange={(e) =>
                setCity(e.target.value)
              }
            />
          )}

          <button
            className="btn btn-primary"
            onClick={getRecommendations}
            disabled={loading}
            style={{ width: "100%" }}
          >
            {loading
              ? "Generating..."
              : "Recommend Outfits"}
          </button>

          {/* ERROR */}

          {error && <p className="error">{error}</p>}

          {/* WEATHER STATUS */}

          {!loading && weather && (
            <p
              style={{
                marginTop: "15px",
                color: "#c1694f",
                fontSize: "13px",
              }}
            >
              {weather.city}: {weather.temp_c}°C,{" "}
              {weather.description}
            </p>
          )}

          {!loading && weatherError && (
            <p
              style={{
                marginTop: "15px",
                color: "#8a7a6d",
                fontSize: "12px",
              }}
            >
              Weather not applied: {weatherError}
            </p>
          )}
        </div>

        <div>
          {/* MISSING-PIECE NOTES */}
          {/* Honest disclosure, per spec section 10: never fabricate
              wardrobe contents - if a piece is genuinely missing,
              say so plainly instead of just showing fewer results. */}

          {!loading && notes.length > 0 && (
            <div
              style={{
                background: "#fdf3e7",
                border: "1px solid #f3ddb8",
                borderRadius: "10px",
                padding: "12px 16px",
                marginBottom: "18px",
              }}
            >
              {notes.map((note, i) => (
                <p
                  key={i}
                  style={{
                    color: "#8a5a1f",
                    fontSize: "13px",
                    margin: i === 0 ? 0 : "6px 0 0",
                  }}
                >
                  {note}
                </p>
              ))}
            </div>
          )}

          {/* RESULTS */}

          {!loading &&
            recommendations.length > 0 && (
              <div>
                <h2 className="section-title" style={{ marginTop: 0 }}>
                  👗 Recommended Outfits
                </h2>

                <div className="panel-grid">
                  {recommendations.map(
                    (outfit, index) => (
                      <div
                        key={index}
                        className="panel"
                      >
                        <h3>
                          Outfit {index + 1}
                        </h3>

                        {outfit.items.map(
                          (item, itemIndex) => (
                            <div
                              key={itemIndex}
                              className="mini-item"
                            >
                              {item.image_path && (
                                <img
                                  src={`http://localhost:5001${item.image_path}`}
                                  alt={
                                    item.category ||
                                    "Clothing item"
                                  }
                                  onError={(e) => {
                                    e.currentTarget.style.display =
                                      "none";
                                  }}
                                />
                              )}

                              <p className="item-title">
                                {item.category ||
                                  "Item"}
                              </p>

                              {item.color && (
                                <p className="item-subtitle">
                                  {item.color}
                                </p>
                              )}

                              {item.material && (
                                <p className="item-meta">
                                  {item.material}
                                </p>
                              )}
                            </div>
                          )
                        )}

                        <span className="badge">
                          {outfit.occasion}
                        </span>

                        {/* SUITABILITY */}

                        <span
                          className="badge"
                          style={{
                            marginLeft: "6px",
                            background: outfit.flagged
                              ? "#f3e0c9"
                              : "#dcefe0",
                            color: outfit.flagged
                              ? "#8a5a1f"
                              : "#2f6b45",
                          }}
                          title={
                            outfit.flagged
                              ? "One or more items here aren't a typical fit for this occasion - double check the item's category/occasion tags if this looks wrong."
                              : "Every item is a typical fit for this occasion."
                          }
                        >
                          {outfit.flagged
                            ? "⚠ Unusual pairing"
                            : "✓ Good fit"}
                        </span>

                        {typeof outfit.score === "number" && (
                          <span
                            style={{
                              marginLeft: "6px",
                              fontSize: "11px",
                              color: "#8a7a6d",
                            }}
                          >
                            score: {outfit.score}
                          </span>
                        )}

                        {/* WHY THIS WORKS - spec section 10. Built
                            server-side from the same color/style
                            reasons used to score the outfit, never
                            invented client-side. */}

                        {Array.isArray(outfit.why) &&
                          outfit.why.length > 0 && (
                            <div
                              style={{
                                marginTop: "10px",
                                paddingTop: "8px",
                                borderTop: "1px solid #eee0d4",
                              }}
                            >
                              <p
                                style={{
                                  fontSize: "11px",
                                  fontWeight: 700,
                                  color: "#6b5b4d",
                                  margin: "0 0 4px",
                                  textTransform: "uppercase",
                                  letterSpacing: "0.03em",
                                }}
                              >
                                Why this works
                              </p>
                              <ul
                                style={{
                                  margin: 0,
                                  paddingLeft: "16px",
                                  fontSize: "12px",
                                  color: "#8a7a6d",
                                }}
                              >
                                {outfit.why.map((line, i) => (
                                  <li key={i}>{line}</li>
                                ))}
                              </ul>
                            </div>
                          )}
                      </div>
                    )
                  )}
                </div>
              </div>
            )}

          {/* NO RESULTS */}

          {!loading &&
            !error &&
            recommendations.length === 0 &&
            (searched ? (
              <div>
                <p style={{ color: "#8a7a6d", marginBottom: "4px" }}>
                  No suitable outfits found for this occasion.
                </p>
                <p style={{ color: "#8a7a6d", fontSize: "13px" }}>
                  Add a few wardrobe items tagged "
                  {OCCASIONS.find(([value]) => value === occasion)?.[1] ||
                    occasion}
                  " (or edit existing ones in My Wardrobe) and try again.
                </p>
              </div>
            ) : (
              <p style={{ color: "#8a7a6d" }}>
                Choose your preferences and click "Recommend
                Outfits".
              </p>
            ))}
        </div>
      </div>
    </Layout>
  );
}

export default OutfitRecommendation;

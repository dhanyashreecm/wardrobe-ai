import { useState, useEffect } from "react";
import axios from "axios";
import Layout from "../components/Layout";
import "../App.css";
import { API_URL, assetUrl } from "../config";

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

// Matches backend.outfit_recommendation.CANONICAL_ACTIVITIES. Purely
// an optional ranking nudge (never a filter, unlike occasion) - so
// "None" is a perfectly normal choice, not a missing answer.
const ACTIVITIES = [
  ["", "None / not specific"],
  ["sports", "Sports / workout"],
  ["outdoor", "Outdoor"],
  ["formal_event", "Formal event"],
  ["travel", "Travel"],
];

function OutfitRecommendation() {
  const [occasion, setOccasion] = useState("casual");
  const [activity, setActivity] = useState("");
  const [city, setCity] = useState("");
  // Defaults to on once a saved profile city loads (see the
  // fetchDefaultCity effect below) - weather is meant to apply
  // automatically app-wide per the spec, not require re-opting-in
  // on every visit. Unchecking it tells the backend NOT to fall back
  // to the saved city either (?use_weather=false), so it's a real
  // opt-out, not just "don't bother filling the box for me".
  const [useWeather, setUseWeather] = useState(false);
  const [usedSavedCity, setUsedSavedCity] = useState(false);
  const [weather, setWeather] = useState(null);
  const [weatherError, setWeatherError] = useState("");
  const [recommendations, setRecommendations] = useState([]);
  const [notes, setNotes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [searched, setSearched] = useState(false);

  const genderKey = (localStorage.getItem("gender") || "").toLowerCase();
  const genderLabel = GENDER_LABELS[genderKey];

  // On first load, pull the user's saved default city (Profile page)
  // so weather-aware recommendations work automatically without
  // making them retype a city every visit - still fully editable/
  // overridable below, and harmless (silently does nothing) if the
  // profile fetch fails or no city has been saved yet.
  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      return;
    }

    axios
      .get(`${API_URL}/api/user/profile`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      .then((res) => {
        const savedCity = res.data?.profile?.city;
        if (savedCity) {
          setCity(savedCity);
          setUseWeather(true);
        }
      })
      .catch((err) => {
        // Non-fatal - the page works fine with weather simply off
        // by default, same as before this default-city lookup existed.
        console.error("Could not load default city:", err);
      });
  }, []);

  const getRecommendations = async () => {
    setLoading(true);
    setError("");
    setWeather(null);
    setWeatherError("");
    setUsedSavedCity(false);
    setRecommendations([]);
    setNotes([]);
    setSearched(true);

    const token = localStorage.getItem("token");

    let url = `${API_URL}/api/ai/recommend?occasion=${occasion}`;

    if (activity) {
      url += `&activity=${encodeURIComponent(activity)}`;
    }

    if (useWeather) {
      if (city.trim()) {
        url += `&city=${encodeURIComponent(city.trim())}`;
      }
      // else: leave city unset so the backend can fall back to the
      // saved profile city on its own (see /api/ai/recommend).
    } else {
      // Explicit opt-out - without this the backend would still
      // fall back to the saved profile city on its own.
      url += "&use_weather=false";
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
        setUsedSavedCity(!!res.data.used_saved_city);
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
            onChange={(e) => {
              setOccasion(e.target.value);
              // Results are only fetched when the button is pressed,
              // so changing the occasion used to leave the PREVIOUS
              // occasion's outfits on screen - which reads exactly
              // like "every occasion gives me the same outfits", even
              // when the engine would have returned something
              // different. Clearing them makes the stale state
              // impossible to mistake for a result.
              setRecommendations([]);
              setNotes([]);
              setSearched(false);
            }}
          >
            {OCCASIONS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>

          {/* ACTIVITY (optional, additive only - see ACTIVITIES) */}

          <label className="field-label">Activity (optional)</label>

          <select
            value={activity}
            onChange={(e) => setActivity(e.target.value)}
          >
            {ACTIVITIES.map(([value, label]) => (
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
            <div style={{ marginTop: "15px" }}>
              <p
                style={{
                  color: "#c1694f",
                  fontSize: "13px",
                  margin: 0,
                }}
              >
                {weather.city}: {weather.temp_c}°C,{" "}
                {weather.description}
              </p>
              <p
                style={{
                  color: "#8a7a6d",
                  fontSize: "12px",
                  margin: "3px 0 0",
                }}
              >
                {weather.humidity_pct != null &&
                  `Humidity ${weather.humidity_pct}%`}
                {weather.humidity_pct != null &&
                  weather.wind_kph != null &&
                  " · "}
                {weather.wind_kph != null &&
                  `Wind ${weather.wind_kph} km/h`}
              </p>
              {usedSavedCity && (
                <p
                  style={{
                    color: "#8a7a6d",
                    fontSize: "11px",
                    margin: "3px 0 0",
                    fontStyle: "italic",
                  }}
                >
                  Using your saved default city (change it in My
                  Profile, or type a different city here for a
                  one-off check).
                </p>
              )}
            </div>
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
                                  src={assetUrl(item.image_path)}
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

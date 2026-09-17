import { useState } from "react";
import axios from "axios";
import Layout from "../components/Layout";
import "../App.css";

function OutfitRecommendation() {
  const [occasion, setOccasion] = useState("casual");
  const [city, setCity] = useState("");
  const [useWeather, setUseWeather] = useState(false);
  const [weather, setWeather] = useState(null);
  const [weatherError, setWeatherError] = useState("");
  const [recommendations, setRecommendations] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const getRecommendations = async () => {
    setLoading(true);
    setError("");
    setWeather(null);
    setWeatherError("");
    setRecommendations([]);

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
            <option value="casual">Casual</option>
            <option value="formal">Formal</option>
            <option value="party">Party</option>
            <option value="traditional">Traditional</option>
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
                      </div>
                    )
                  )}
                </div>
              </div>
            )}

          {/* NO RESULTS */}

          {!loading &&
            !error &&
            recommendations.length === 0 && (
              <p style={{ color: "#8a7a6d" }}>
                Choose your preferences and click "Recommend
                Outfits".
              </p>
            )}
        </div>
      </div>
    </Layout>
  );
}

export default OutfitRecommendation;

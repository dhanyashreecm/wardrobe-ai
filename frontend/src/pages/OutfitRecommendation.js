import { useState } from "react";
import axios from "axios";
import "../App.css";

function OutfitRecommendation() {
  const [occasion, setOccasion] = useState("casual");
  const [recommendations, setRecommendations] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const getRecommendations = async () => {
    setLoading(true);
    setError("");
    setRecommendations([]);

    const token = localStorage.getItem("token");

    try {
      const res = await axios.get(
        `http://localhost:5001/api/ai/recommend?occasion=${occasion}`,
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
    <div className="page-container">
      <div
        className="auth-card"
        style={{
          maxWidth: "900px",
          width: "100%",
        }}
      >
        <div className="logo">
          Outfit Recommendation
        </div>

        <p
          style={{
            color: "#777",
            marginBottom: "20px",
          }}
        >
          Get outfit ideas using clothes already
          available in your wardrobe.
        </p>

        {/* OCCASION */}

        <div
          style={{
            marginBottom: "20px",
          }}
        >
          <label>
            <strong>Choose occasion:</strong>
          </label>

          <br />

          <select
            value={occasion}
            onChange={(e) =>
              setOccasion(e.target.value)
            }
            style={{
              marginTop: "10px",
              padding: "10px",
              borderRadius: "8px",
              border: "1px solid #ddd",
            }}
          >
            <option value="casual">
              Casual
            </option>

            <option value="formal">
              Formal
            </option>

            <option value="party">
              Party
            </option>

            <option value="traditional">
              Traditional
            </option>
          </select>
        </div>

        {/* BUTTON */}

        <button
          onClick={getRecommendations}
          disabled={loading}
        >
          {loading
            ? "Generating..."
            : "Recommend Outfits"}
        </button>

        {/* ERROR */}

        {error && (
          <p
            className="error"
            style={{
              marginTop: "20px",
            }}
          >
            {error}
          </p>
        )}

        {/* RESULTS */}

        {!loading &&
          recommendations.length > 0 && (
            <div
              style={{
                marginTop: "35px",
                textAlign: "left",
              }}
            >
              <h2>
                👗 Recommended Outfits
              </h2>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns:
                    "repeat(auto-fill, minmax(220px, 1fr))",
                  gap: "20px",
                  marginTop: "20px",
                }}
              >
                {recommendations.map(
                  (outfit, index) => (
                    <div
                      key={index}
                      style={{
                        border:
                          "1px solid #eee",
                        borderRadius: "12px",
                        padding: "15px",
                        background:
                          "#fafafa",
                      }}
                    >
                      <h3>
                        Outfit {index + 1}
                      </h3>

                      {outfit.items.map(
                        (item, itemIndex) => (
                          <div
                            key={itemIndex}
                            style={{
                              marginBottom:
                                "12px",
                            }}
                          >
                            {item.image_path && (
                              <img
                                src={`http://localhost:5001${item.image_path}`}
                                alt={
                                  item.category ||
                                  "Clothing item"
                                }
                                style={{
                                  width:
                                    "100%",
                                  height:
                                    "180px",
                                  objectFit:
                                    "cover",
                                  borderRadius:
                                    "8px",
                                }}
                                onError={(e) => {
                                  e.currentTarget.style.display =
                                    "none";
                                }}
                              />
                            )}

                            <p
                              style={{
                                margin:
                                  "6px 0 0",
                                fontSize:
                                  "14px",
                              }}
                            >
                              <strong>
                                {item.category ||
                                  "Item"}
                              </strong>
                            </p>

                            {item.color && (
                              <p
                                style={{
                                  margin:
                                    "3px 0",
                                  color:
                                    "#777",
                                  fontSize:
                                    "13px",
                                }}
                              >
                                {item.color}
                              </p>
                            )}
                          </div>
                        )
                      )}

                      <p
                        style={{
                          color: "#777",
                          fontSize: "13px",
                        }}
                      >
                        Occasion:{" "}
                        {outfit.occasion}
                      </p>
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
            <p
              style={{
                color: "#888",
                marginTop: "25px",
              }}
            >
              Select an occasion and click
              "Recommend Outfits".
            </p>
          )}
      </div>
    </div>
  );
}

export default OutfitRecommendation;

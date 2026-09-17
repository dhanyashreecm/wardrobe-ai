import { useState } from "react";
import axios from "axios";
import Layout from "../components/Layout";
import "../App.css";

function SimilarSearch() {
  const [image, setImage] = useState(null);

  const [wardrobeResults, setWardrobeResults] = useState([]);
  const [datasetResults, setDatasetResults] = useState([]);
  const [indofashionResults, setIndofashionResults] = useState([]);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const token = localStorage.getItem("token");

  const handleSearch = async (e) => {
    e.preventDefault();

    if (!image) {
      setError("Please select an image first.");
      return;
    }

    setLoading(true);
    setError("");

    setWardrobeResults([]);
    setDatasetResults([]);
    setIndofashionResults([]);

    const formData = new FormData();
    formData.append("image", image);

    try {
      const res = await axios.post(
        "http://localhost:5001/api/ai/similar",
        formData,
        {
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "multipart/form-data",
          },
        }
      );

      if (res.data.success) {
        setWardrobeResults(res.data.wardrobe_results || []);
        setDatasetResults(res.data.dataset_results || []);
        setIndofashionResults(res.data.indofashion_results || []);
      } else {
        setError(res.data.message || "Search failed");
      }
    } catch (err) {
      console.error("Similarity search error:", err);

      setError(
        err.response?.data?.message ||
          "Search failed. Please try again."
      );
    } finally {
      setLoading(false);
    }
  };

  const getSimilarityPercentage = (similarity) => {
    return (similarity * 100).toFixed(1);
  };

  return (
    <Layout>
      <div className="page-header">
        <div>
          <h1 className="page-title">Find Similar Clothes</h1>
          <p className="page-subtitle">
            Upload a clothing photo to check your wardrobe and
            find visually similar clothes.
          </p>
        </div>
      </div>

      <div className="side-panel" style={{ maxWidth: "420px" }}>
        {/* UPLOAD */}

        <form onSubmit={handleSearch}>
          <input
            type="file"
            accept="image/*"
            onChange={(e) => {
              setImage(e.target.files[0]);
              setError("");
            }}
          />

          <button
            type="submit"
            className="btn btn-primary"
            disabled={loading || !image}
            style={{ width: "100%" }}
          >
            {loading ? "Searching..." : "Find Similar"}
          </button>
        </form>
      </div>

      <div style={{ marginTop: "28px" }}>

        {/* ERROR */}

        {error && (
          <p
            className="error"
            style={{
              marginBottom: "20px",
            }}
          >
            {error}
          </p>
        )}

        {/* LOADING */}

        {loading && (
          <p
            style={{
              textAlign: "center",
              color: "#777",
              marginTop: "25px",
            }}
          >
            Analyzing your clothing image...
          </p>
        )}

        {/* USER'S OWN WARDROBE */}
        {/* ================================================= */}

        {!loading && wardrobeResults.length > 0 && (
          <div
            style={{
              marginTop: "30px",
              textAlign: "left",
            }}
          >
            <h2>🧥 Already in Your Wardrobe</h2>

            <p
              style={{
                color: "#777",
                marginBottom: "18px",
              }}
            >
              You already have similar item
              {wardrobeResults.length > 1 ? "s" : ""} in your wardrobe.
            </p>

            <div
              style={{
                display: "grid",
                gridTemplateColumns:
                  "repeat(auto-fill, minmax(180px, 1fr))",
                gap: "18px",
              }}
            >
              {wardrobeResults.map((item, idx) => (
                <div
                  key={item.item_id || idx}
                  style={{
                    background: "#fafafa",
                    borderRadius: "12px",
                    overflow: "hidden",
                    border: "2px solid #e8e8e8",
                    textAlign: "center",
                    paddingBottom: "12px",
                  }}
                >
                  <img
                    src={`http://localhost:5001${item.image}`}
                    alt="Your wardrobe item"
                    style={{
                      width: "100%",
                      height: "180px",
                      objectFit: "cover",
                    }}
                  />

                  <p
                    style={{
                      margin: "10px 5px 4px",
                      fontSize: "15px",
                      fontWeight: "600",
                    }}
                  >
                    {getSimilarityPercentage(item.similarity)}% match
                  </p>

                  {item.category && (
                    <p
                      style={{
                        margin: "3px",
                        fontSize: "13px",
                        color: "#777",
                      }}
                    >
                      Category: {item.category}
                    </p>
                  )}

                  {item.color && (
                    <p
                      style={{
                        margin: "3px",
                        fontSize: "13px",
                        color: "#777",
                      }}
                    >
                      Color: {item.color}
                    </p>
                  )}

                  {item.occasion && (
                    <p
                      style={{
                        margin: "3px",
                        fontSize: "13px",
                        color: "#777",
                      }}
                    >
                      Occasion: {item.occasion}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ================================================= */}
        {/* NO WARDROBE MATCH */}
        {/* ================================================= */}

        {!loading &&
          wardrobeResults.length === 0 &&
          (datasetResults.length > 0 ||
            indofashionResults.length > 0) && (
            <div
              style={{
                marginTop: "30px",
                padding: "15px",
                background: "#fafafa",
                borderRadius: "10px",
                textAlign: "left",
              }}
            >
              <p
                style={{
                  margin: 0,
                  color: "#777",
                }}
              >
                You don't appear to have a similar item in your
                wardrobe.
              </p>
            </div>
          )}               

        {/* ================================================= */}
        {/* DEEPFASHION */}
        {/* ================================================= */}

        {!loading && datasetResults.length > 0 && (
          <div
            style={{
              marginTop: "35px",
              textAlign: "left",
            }}
          >
            <h2>👗 Similar Clothes</h2>

            <p
              style={{
                color: "#777",
                marginBottom: "18px",
              }}
            >
              Visually similar clothing found by the AI model.
            </p>

            <div
              style={{
                display: "grid",
                gridTemplateColumns:
                  "repeat(auto-fill, minmax(160px, 1fr))",
                gap: "16px",
              }}
            >
              {datasetResults.map((item, idx) => (
                <div
                  key={idx}
                  style={{
                    background: "#fafafa",
                    borderRadius: "12px",
                    overflow: "hidden",
                    border: "1px solid #eee",
                    textAlign: "center",
                    paddingBottom: "10px",
                  }}
                >
                  <img
                    src={`http://localhost:5001/api/dataset/${item.image.replace(
                      /^dataset\/deepfashion\//,
                      ""
                    )}`}
                    alt="Similar clothing"
                    style={{
                      width: "100%",
                      height: "150px",
                      objectFit: "cover",
                    }}
                  />

                  <p
                    style={{
                      margin: "9px 0 0",
                      fontSize: "14px",
                      color: "#777",
                    }}
                  >
                    {getSimilarityPercentage(item.similarity)}% match
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ================================================= */}
        {/* INDOFASHION DATASET */}
        {/* ================================================= */}

        {!loading && indofashionResults.length > 0 && (
          <div
            style={{
              marginTop: "35px",
              textAlign: "left",
            }}
          >
            <h2
              style={{
                marginBottom: "8px",
              }}
            >
              🇮🇳 Similar Indian Clothes
            </h2>

            <p
              style={{
                color: "#777",
                marginBottom: "18px",
              }}
            >
              Similar Indian clothing found using the IndoFashion dataset.
            </p>

            <div
              style={{
                display: "grid",
                gridTemplateColumns:
                  "repeat(auto-fill, minmax(160px, 1fr))",
                gap: "16px",
              }}
            >
              {indofashionResults.map((item, idx) => {
                const imagePath = item.image.replace(
                  /^.*dataset\/indofashion\/processed\//,
                  ""
                );

                return (
                  <div
                    key={idx}
                    style={{
                      background: "#fafafa",
                      borderRadius: "12px",
                      overflow: "hidden",
                      border: "1px solid #eee",
                      textAlign: "center",
                      paddingBottom: "10px",
                    }}
                  >
                    <img
                      src={`http://localhost:5001/api/indofashion/${imagePath}`}
                      alt="Similar Indian clothing"
                      style={{
                        width: "100%",
                        height: "150px",
                        objectFit: "cover",
                      }}
                      onError={(e) => {
                        e.currentTarget.style.display = "none";
                      }}
                    />

                    <p
                      style={{
                        margin: "9px 0 0",
                        fontSize: "14px",
                        color: "#777",
                      }}
                    >
                      {getSimilarityPercentage(item.similarity)}
                      % match
                    </p>

                    <p
                      style={{
                        margin: "4px 0 0",
                        fontSize: "12px",
                        color: "#999",
                      }}
                    >
                      IndoFashion
                    </p>
                  </div>
                );
              })}
            </div>
          </div>
        )}
        {/* ================================================= */}
        {/* NO RESULTS */}
        {/* ================================================= */}

        {!loading &&
          !error &&
          wardrobeResults.length === 0 &&
          datasetResults.length === 0 &&
          indofashionResults.length === 0 && (
            <p
              style={{
                color: "#888",
                marginTop: "25px",
              }}
            >
              Upload a clothing photo to find similar items.
            </p>
          )}
      </div>
    </Layout>
  );
}

export default SimilarSearch;

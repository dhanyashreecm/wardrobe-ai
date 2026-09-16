import { useState, useEffect } from "react";
import axios from "axios";
import { useNavigate, Link } from "react-router-dom";
import Cropper from "react-easy-crop";
import "../App.css";

function Wardrobe() {
  const [items, setItems] = useState([]);

  const [category, setCategory] = useState("Shirt");
  const [color, setColor] = useState("");
  const [image, setImage] = useState(null);

  const [loading, setLoading] = useState(false);

  const [filterCategory, setFilterCategory] = useState("All");

  // =========================================================
  // CROP STATES
  // =========================================================

  const [imagePreview, setImagePreview] = useState(null);
  const [cropMode, setCropMode] = useState(false);

  const [crop, setCrop] = useState({
    x: 0,
    y: 0
  });

  const [zoom, setZoom] = useState(1);

  const [croppedAreaPixels, setCroppedAreaPixels] = useState(null);

  const navigate = useNavigate();

  const token = localStorage.getItem("token");

  // =========================================================
  // FETCH WARDROBE
  // =========================================================

  const fetchItems = async () => {
    try {
      const res = await axios.get(
        "http://localhost:5001/api/wardrobe",
        {
          headers: {
            Authorization: `Bearer ${token}`
          }
        }
      );

      setItems(res.data.items);
    } catch (err) {
      console.error("Failed to fetch wardrobe:", err);
      navigate("/login");
    }
  };

  // =========================================================
  // LOAD WARDROBE
  // =========================================================

  useEffect(() => {
    if (!token) {
      navigate("/login");
      return;
    }

    fetchItems();
  }, []);

  // =========================================================
  // IMAGE SELECTION
  // =========================================================

  const handleImageSelect = (e) => {
    const selectedFile = e.target.files[0];

    if (!selectedFile) {
      return;
    }

    if (!selectedFile.type.startsWith("image/")) {
      alert("Please select an image file.");
      return;
    }

    setImage(selectedFile);

    const previewUrl = URL.createObjectURL(selectedFile);

    setImagePreview(previewUrl);

    // Reset crop settings
    setCrop({
      x: 0,
      y: 0
    });

    setZoom(1);

    setCropMode(true);
  };

  // =========================================================
  // CROP COMPLETE
  // =========================================================

  const onCropComplete = (croppedArea, croppedAreaPixelsValue) => {
    setCroppedAreaPixels(croppedAreaPixelsValue);
  };

  // =========================================================
  // CREATE CROPPED IMAGE
  // =========================================================

  const createCroppedImage = async () => {
    if (!imagePreview || !croppedAreaPixels) {
      return null;
    }

    const imageElement = new Image();

    imageElement.src = imagePreview;

    await new Promise((resolve, reject) => {
      imageElement.onload = resolve;
      imageElement.onerror = reject;
    });

    const canvas = document.createElement("canvas");

    const ctx = canvas.getContext("2d");

    canvas.width = croppedAreaPixels.width;
    canvas.height = croppedAreaPixels.height;

    ctx.drawImage(
      imageElement,
      croppedAreaPixels.x,
      croppedAreaPixels.y,
      croppedAreaPixels.width,
      croppedAreaPixels.height,
      0,
      0,
      croppedAreaPixels.width,
      croppedAreaPixels.height
    );

    return new Promise((resolve) => {
      canvas.toBlob(
        (blob) => {
          if (!blob) {
            resolve(null);
            return;
          }

          const croppedFile = new File(
            [blob],
            image?.name || "cropped-clothing.jpg",
            {
              type: "image/jpeg"
            }
          );

          resolve(croppedFile);
        },
        "image/jpeg",
        0.95
      );
    });
  };

  // =========================================================
  // CONFIRM CROP
  // =========================================================

  const handleCropDone = async () => {
    try {
      const croppedFile = await createCroppedImage();

      if (!croppedFile) {
        alert("Could not crop image.");
        return;
      }

      setImage(croppedFile);

      const newPreview = URL.createObjectURL(croppedFile);

      setImagePreview(newPreview);

      setCropMode(false);

      setZoom(1);

      alert(
        "Crop completed. The cropped clothing image is ready to upload."
      );
    } catch (error) {
      console.error("Crop failed:", error);
      alert("Could not crop the image.");
    }
  };

  // =========================================================
  // CANCEL CROP
  // =========================================================

  const handleCropCancel = () => {
    setImage(null);
    setImagePreview(null);
    setCropMode(false);

    setCrop({
      x: 0,
      y: 0
    });

    setZoom(1);

    setCroppedAreaPixels(null);

    const fileInput = document.getElementById("fileInput");

    if (fileInput) {
      fileInput.value = "";
    }
  };

  // =========================================================
  // UPLOAD ITEM
  // =========================================================

  const handleUpload = async (e) => {
    e.preventDefault();

    if (!category) {
      alert("Please select a category.");
      return;
    }

    if (!image) {
      alert("Please select a clothing image.");
      return;
    }

    setLoading(true);

    const formData = new FormData();

    formData.append("category", category);

    /*
     * Color is optional now.
     *
     * using OpenCV.
     */
    if (color) {
      formData.append("color", color);
    }

    formData.append("image", image);

    try {
      const response = await axios.post(
        "http://localhost:5001/api/wardrobe/add",
        formData,
        {
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "multipart/form-data"
          }
        }
      );

      console.log(
        "Wardrobe item added:",
        response.data
      );

      // Reset form

      setColor("");

      setImage(null);

      setImagePreview(null);

      setCropMode(false);

      setCrop({
        x: 0,
        y: 0
      });

      setZoom(1);

      setCroppedAreaPixels(null);

      const fileInput =
        document.getElementById("fileInput");

      if (fileInput) {
        fileInput.value = "";
      }

      // Refresh wardrobe

      fetchItems();

      alert(
        `Item added successfully!\nDetected color: ${
          response.data.color || "Unknown"
        }`
      );
    } catch (err) {
      console.error(
        "Upload failed:",
        err
      );

      alert(
        err.response?.data?.message ||
          "Upload failed."
      );
    } finally {
      setLoading(false);
    }
  };

  // =========================================================
  // DELETE ITEM
  // =========================================================

  const handleDelete = async (id) => {
    try {
      await axios.delete(
        `http://localhost:5001/api/wardrobe/${id}`,
        {
          headers: {
            Authorization: `Bearer ${token}`
          }
        }
      );

      fetchItems();
    } catch (err) {
      console.error(
        "Delete failed:",
        err
      );

      alert("Could not delete item.");
    }
  };

  // =========================================================
  // FILTER ITEMS
  // =========================================================

  const filteredItems =
    filterCategory === "All"
      ? items
      : items.filter(
          (item) =>
            item.category === filterCategory
        );

  // =========================================================
  // CATEGORY OPTIONS
  // =========================================================

  const categories = [
    ["Shirt", "Shirt"],
    ["Pant", "Pant"],
    ["Skirt", "Skirt"],
    ["Saree", "Saree"],
    ["Dress", "Dress"],
    ["Jacket", "Jacket"],
    ["Blouse", "Blouse"],
    ["Dhoti Pants", "Dhoti Pants"],
    ["Dupatta", "Dupatta"],
    ["Gown", "Gown"],
    ["Men Kurta", "Men Kurta"],
    [
      "Leggings & Salwars",
      "Leggings & Salwars"
    ],
    ["Lehenga", "Lehenga"],
    ["Mojaris Men", "Mojaris Men"],
    ["Mojaris Women", "Mojaris Women"],
    ["Nehru Jacket", "Nehru Jacket"],
    ["Palazzos", "Palazzos"],
    ["Petticoat", "Petticoat"],
    ["Sherwani", "Sherwani"],
    ["Women Kurta", "Women Kurta"]
  ];

  // =========================================================
  // UI
  // =========================================================

  return (
    <div className="page-container">

      <div
        className="auth-card"
        style={{
          maxWidth: "720px"
        }}
      >

        {/* ================================================= */}
        {/* TITLE */}
        {/* ================================================= */}

        <div className="logo">
          👗 My Digital Wardrobe
        </div>

        {/* ================================================= */}
        {/* SIMILAR SEARCH */}
        {/* ================================================= */}

        <Link
          to="/similar"
          style={{
            display: "block",
            marginBottom: "16px",
            color: "#764ba2"
          }}
        >
          Find Similar Clothes →
        </Link>

        {/* ================================================= */}
        {/* ADD ITEM */}
        {/* ================================================= */}

        <form
          onSubmit={handleUpload}
          style={{
            marginBottom: "10px"
          }}
        >

          {/* CATEGORY */}

          <select
            value={category}
            onChange={(e) =>
              setCategory(e.target.value)
            }
            style={{
              width: "100%",
              padding: "12px 14px",
              marginBottom: "14px",
              border: "1px solid #ddd",
              borderRadius: "8px",
              fontSize: "15px",
              background: "white"
            }}
          >

            {categories.map(
              ([value, label]) => (
                <option
                  key={value}
                  value={value}
                >
                  {label}
                </option>
              )
            )}

          </select>

          {/* OPTIONAL MANUAL COLOR */}

          <input
            placeholder="Color"
            value={color}
            onChange={(e) =>
              setColor(e.target.value)
            }
            style={{
              width: "100%",
              boxSizing: "border-box",
              marginBottom: "14px"
            }}
          />

          {/* IMAGE */}

          <input
            id="fileInput"
            type="file"
            accept="image/*"
            onChange={handleImageSelect}
            style={{
              marginBottom: "14px"
            }}
          />

          {/* IMAGE PREVIEW */}

          {imagePreview &&
            !cropMode && (
              <div
                style={{
                  marginBottom: "15px",
                  textAlign: "center"
                }}
              >

                <p
                  style={{
                    fontWeight: "600",
                    color: "#4a3f8a"
                  }}
                >
                  Cropped Image Preview
                </p>

                <img
                  src={imagePreview}
                  alt="Cropped clothing preview"
                  style={{
                    maxWidth: "100%",
                    maxHeight: "250px",
                    borderRadius: "10px",
                    border:
                      "1px solid #ddd"
                  }}
                />

                <br />

                <button
                  type="button"
                  onClick={() =>
                    setCropMode(true)
                  }
                  style={{
                    marginTop: "10px",
                    width: "auto"
                  }}
                >
                  ✂️ Crop Again
                </button>

              </div>
            )}

          {/* ================================================= */}
          {/* CROP AREA */}
          {/* ================================================= */}

          {cropMode &&
            imagePreview && (
              <div
                style={{
                  position: "relative",
                  width: "100%",
                  height: "400px",
                  background: "#222",
                  borderRadius: "12px",
                  overflow: "hidden",
                  marginBottom: "15px"
                }}
              >

                <Cropper
                  image={imagePreview}
                  crop={crop}
                  zoom={zoom}
                  aspect={3 / 4}
                  onCropChange={setCrop}
                  onCropComplete={
                    onCropComplete
                  }
                  onZoomChange={setZoom}
                />

              </div>
            )}

          {/* ================================================= */}
          {/* CROP CONTROLS */}
          {/* ================================================= */}

          {cropMode && (
            <div
              style={{
                marginBottom: "20px",
                textAlign: "center"
              }}
            >

              <label
                style={{
                  display: "block",
                  marginBottom: "8px",
                  fontWeight: "600"
                }}
              >
                Zoom
              </label>

              <input
                type="range"
                min="1"
                max="3"
                step="0.1"
                value={zoom}
                onChange={(e) =>
                  setZoom(
                    Number(
                      e.target.value
                    )
                  )
                }
                style={{
                  width: "80%"
                }}
              />

              <div
                style={{
                  marginTop: "12px"
                }}
              >

                <button
                  type="button"
                  onClick={handleCropDone}
                  style={{
                    width: "auto",
                    marginRight: "10px"
                  }}
                >
                  ✓ Use This Crop
                </button>

                <button
                  type="button"
                  onClick={handleCropCancel}
                  style={{
                    width: "auto",
                    background: "#777"
                  }}
                >
                  Cancel
                </button>

              </div>

            </div>
          )}

          {/* ================================================= */}
          {/* UPLOAD */}
          {/* ================================================= */}

          {!cropMode && (
            <button
              type="submit"
              disabled={
                loading || !image
              }
            >
              {loading
                ? "Uploading..."
                : "Add Item"}
            </button>
          )}

        </form>

        {/* ================================================= */}
        {/* CATEGORY FILTER */}
        {/* ================================================= */}

        <div
          style={{
            marginTop: "20px",
            marginBottom: "10px"
          }}
        >

          <label
            style={{
              display: "block",
              marginBottom: "6px",
              fontWeight: "600",
              color: "#4a3f8a"
            }}
          >
            Organize by Category
          </label>

          <select
            value={filterCategory}
            onChange={(e) =>
              setFilterCategory(
                e.target.value
              )
            }
            style={{
              width: "100%",
              padding: "12px 14px",
              border: "1px solid #ddd",
              borderRadius: "8px",
              fontSize: "15px",
              background: "white"
            }}
          >

            <option value="All">
              All Items
            </option>

            {categories.map(
              ([value, label]) => (
                <option
                  key={value}
                  value={value}
                >
                  {label}
                </option>
              )
            )}

          </select>

        </div>

        {/* ================================================= */}
        {/* WARDROBE ITEMS */}
        {/* ================================================= */}

        <div
          style={{
            display: "grid",
            gridTemplateColumns:
              "repeat(auto-fill, minmax(140px, 1fr))",
            gap: "16px",
            marginTop: "24px",
            textAlign: "left"
          }}
        >

          {filteredItems.length === 0 && (
            <p
              style={{
                color: "#888",
                gridColumn: "1 / -1"
              }}
            >
              No items found in this category.
            </p>
          )}

          {filteredItems.map(
            (item) => (

              <div
                key={item._id}
                style={{
                  background: "#fafafa",
                  borderRadius: "12px",
                  overflow: "hidden",
                  border:
                    "1px solid #eee",
                  textAlign: "center",
                  paddingBottom: "10px"
                }}
              >

                {/* IMAGE */}

                {item.image_path ? (

                  <img
                    src={`http://localhost:5001${item.image_path}`}
                    alt={item.category}
                    style={{
                      width: "100%",
                      height: "120px",
                      objectFit: "cover"
                    }}
                  />

                ) : (

                  <div
                    style={{
                      width: "100%",
                      height: "120px",
                      display: "flex",
                      alignItems:
                        "center",
                      justifyContent:
                        "center",
                      background: "#eee",
                      fontSize: "36px"
                    }}
                  >
                    👕
                  </div>

                )}

                {/* CATEGORY */}

                <p
                  style={{
                    margin:
                      "8px 0 2px",
                    fontWeight: "600",
                    fontSize: "14px",
                    color: "#4a3f8a"
                  }}
                >
                  {item.category}
                </p>

                {/* COLOR */}

                <p
                  style={{
                    margin:
                      "0 0 8px",
                    fontSize: "13px",
                    color: "#777"
                  }}
                >
                  {item.color ||
                    "Color not detected"}
                </p>

                {/* DELETE */}

                <button
                  onClick={() =>
                    handleDelete(
                      item._id
                    )
                  }
                  style={{
                    width: "auto",
                    padding:
                      "5px 12px",
                    fontSize: "12px",
                    background:
                      "#e74c3c"
                  }}
                >
                  Delete
                </button>

              </div>

            )
          )}

        </div>

      </div>

    </div>
  );
}

export default Wardrobe;

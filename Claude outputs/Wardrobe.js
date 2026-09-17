import { useState, useEffect } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import Cropper from "react-easy-crop";
import Layout from "../components/Layout";
import "../App.css";

function Wardrobe() {
  const [items, setItems] = useState([]);

  const [category, setCategory] = useState("Shirt");
  const [color, setColor] = useState("");
  const [material, setMaterial] = useState("");
  const [image, setImage] = useState(null);

  const [loading, setLoading] = useState(false);

  const [filterCategory, setFilterCategory] = useState("All");

  // =========================================================
  // EDIT ITEM STATE
  // =========================================================

  const [editingId, setEditingId] = useState(null);
  const [editCategory, setEditCategory] = useState("");
  const [editColor, setEditColor] = useState("");
  const [editMaterial, setEditMaterial] = useState("");
  const [editSaving, setEditSaving] = useState(false);

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

    if (material) {
      formData.append("material", material);
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

      setMaterial("");

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
  // EDIT ITEM
  // =========================================================

  const handleEditStart = (item) => {
    setEditingId(item._id);
    setEditCategory(item.category || "");
    setEditColor(item.color || "");
    setEditMaterial(item.material || "");
  };

  const handleEditCancel = () => {
    setEditingId(null);
    setEditCategory("");
    setEditColor("");
    setEditMaterial("");
  };

  const handleEditSave = async (id) => {
    setEditSaving(true);

    try {
      await axios.put(
        `http://localhost:5001/api/wardrobe/${id}`,
        {
          category: editCategory,
          color: editColor,
          material: editMaterial
        },
        {
          headers: {
            Authorization: `Bearer ${token}`
          }
        }
      );

      setEditingId(null);

      fetchItems();
    } catch (err) {
      console.error("Update failed:", err);

      alert(
        err.response?.data?.message ||
          "Could not update item."
      );
    } finally {
      setEditSaving(false);
    }
  };

  // =========================================================
  // FAVORITE TOGGLE
  // =========================================================

  const handleToggleFavorite = async (item) => {
    // Optimistic update so the heart feels instant.
    setItems((prev) =>
      prev.map((existing) =>
        existing._id === item._id
          ? { ...existing, favorite: !existing.favorite }
          : existing
      )
    );

    try {
      await axios.put(
        `http://localhost:5001/api/wardrobe/${item._id}`,
        {
          favorite: !item.favorite
        },
        {
          headers: {
            Authorization: `Bearer ${token}`
          }
        }
      );
    } catch (err) {
      console.error("Favorite toggle failed:", err);

      // Roll back on failure
      setItems((prev) =>
        prev.map((existing) =>
          existing._id === item._id
            ? { ...existing, favorite: item.favorite }
            : existing
        )
      );
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

  // Kept deliberately short. Each category is an umbrella for
  // every variant of that garment (e.g. "Shirt" covers formal,
  // casual, printed - any shirt), instead of a long list of
  // near-duplicate options that just makes setting up a wardrobe
  // feel tedious. Ethnic wear is limited to the two categories the
  // AI can actually tell apart with confidence: Saree and Lehenga.
  const categories = [
    ["Shirt", "Shirt"],
    ["T-Shirt", "T-Shirt"],
    ["Pant", "Pant"],
    ["Shorts", "Shorts"],
    ["Skirt", "Skirt"],
    ["Jacket", "Jacket"],
    ["Dress", "Dress"],
    ["Saree", "Saree"],
    ["Lehenga", "Lehenga"],
    ["Bag", "Bag"],
    ["Watch", "Watch"],
    ["Belt", "Belt"],
    ["Jewelry", "Jewelry"]
  ];

  const ACCESSORY_CATEGORIES = [
    "Bag",
    "Watch",
    "Belt",
    "Jewelry"
  ];

  // =========================================================
  // UI
  // =========================================================

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

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "300px 1fr",
          gap: "28px",
          alignItems: "start"
        }}
      >

        {/* ================================================= */}
        {/* ADD ITEM */}
        {/* ================================================= */}

        <div className="side-panel">

          <h3>Add New Item</h3>

          <form onSubmit={handleUpload}>

            {/* CATEGORY */}

            <select
              value={category}
              onChange={(e) =>
                setCategory(e.target.value)
              }
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
            />

            {/* MATERIAL (accessories only) */}

            {ACCESSORY_CATEGORIES.includes(
              category
            ) && (
              <input
                placeholder="Material (e.g. leather, gold, metal)"
                value={material}
                onChange={(e) =>
                  setMaterial(e.target.value)
                }
              />
            )}

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
                      fontSize: "13px",
                      color: "#8a7a6d"
                    }}
                  >
                    Cropped Image Preview
                  </p>

                  <img
                    src={imagePreview}
                    alt="Cropped clothing preview"
                    style={{
                      maxWidth: "100%",
                      maxHeight: "200px",
                      borderRadius: "10px",
                      border:
                        "1px solid #ece1d6"
                    }}
                  />

                  <br />

                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() =>
                      setCropMode(true)
                    }
                    style={{
                      marginTop: "10px"
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
                    height: "260px",
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
                    fontWeight: "600",
                    fontSize: "13px"
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
                    className="btn btn-primary btn-sm"
                    onClick={handleCropDone}
                    style={{
                      marginRight: "10px"
                    }}
                  >
                    ✓ Use This Crop
                  </button>

                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={handleCropCancel}
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
                style={{ width: "100%" }}
              >
                {loading
                  ? "Uploading..."
                  : "Add Item"}
              </button>
            )}

          </form>

        </div>

        <div>

          {/* ================================================= */}
          {/* CATEGORY FILTER */}
          {/* ================================================= */}

          <div
            style={{
              marginBottom: "8px",
              maxWidth: "320px"
            }}
          >

            <label className="field-label">
              Organize by Category
            </label>

            <select
              value={filterCategory}
              onChange={(e) =>
                setFilterCategory(
                  e.target.value
                )
              }
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

          <div className="item-grid">

            {filteredItems.length === 0 && (
              <p
                style={{
                  color: "#8a7a6d",
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
                  className="item-card"
                >

                  {/* FAVORITE */}

                  <button
                    type="button"
                    className={`favorite-btn ${
                      item.favorite ? "active" : ""
                    }`}
                    onClick={() =>
                      handleToggleFavorite(item)
                    }
                    aria-label={
                      item.favorite
                        ? "Remove from favorites"
                        : "Add to favorites"
                    }
                  >
                    {item.favorite ? "♥" : "♡"}
                  </button>

                  {/* IMAGE */}

                  {item.image_path ? (

                    <img
                      src={`http://localhost:5001${item.image_path}`}
                      alt={item.category}
                    />

                  ) : (

                    <div className="item-placeholder">
                      👕
                    </div>

                  )}

                  {editingId === item._id ? (

                    /* ============================= */
                    /* EDIT MODE */
                    /* ============================= */

                    <div
                      className="item-edit-form"
                      style={{
                        padding: "0 8px"
                      }}
                    >

                      <select
                        value={editCategory}
                        onChange={(e) =>
                          setEditCategory(
                            e.target.value
                          )
                        }
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

                      <input
                        placeholder="Color"
                        value={editColor}
                        onChange={(e) =>
                          setEditColor(
                            e.target.value
                          )
                        }
                      />

                      {ACCESSORY_CATEGORIES.includes(
                        editCategory
                      ) && (
                        <input
                          placeholder="Material"
                          value={editMaterial}
                          onChange={(e) =>
                            setEditMaterial(
                              e.target.value
                            )
                          }
                        />
                      )}

                      <div className="item-actions">

                        <button
                          className="btn btn-primary btn-sm"
                          onClick={() =>
                            handleEditSave(
                              item._id
                            )
                          }
                          disabled={editSaving}
                        >
                          {editSaving
                            ? "Saving..."
                            : "Save"}
                        </button>

                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          onClick={handleEditCancel}
                        >
                          Cancel
                        </button>

                      </div>

                    </div>

                  ) : (

                    <>

                      {/* CATEGORY */}

                      <p className="item-title">
                        {item.category}
                      </p>

                      {/* COLOR */}

                      <p className="item-subtitle">
                        {item.color ||
                          "Color not detected"}
                      </p>

                      {/* MATERIAL */}

                      {item.material && (
                        <p className="item-meta">
                          {item.material}
                        </p>
                      )}

                      <div className="item-actions">

                        {/* EDIT */}

                        <button
                          className="btn btn-secondary btn-sm"
                          onClick={() =>
                            handleEditStart(item)
                          }
                        >
                          Edit
                        </button>

                        {/* DELETE */}

                        <button
                          className="btn btn-danger btn-sm"
                          onClick={() =>
                            handleDelete(
                              item._id
                            )
                          }
                        >
                          Delete
                        </button>

                      </div>

                    </>

                  )}

                </div>

              )
            )}

          </div>

        </div>

      </div>

    </Layout>
  );
}

export default Wardrobe;

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

  // Set at registration/login (see Register.js / Login.js) and used
  // purely to trim the category dropdown to the categories relevant
  // to the signed-in user - "Male" hides Skirt/Dress/Saree/Lehenga.
  // Nothing is enforced server-side; an account with no gender on
  // file (older accounts) just sees every category.
  const userGender = (localStorage.getItem("gender") || "").toLowerCase();

  // =========================================================
  // EDIT ITEM STATE
  // =========================================================

  const [editingId, setEditingId] = useState(null);
  const [editCategory, setEditCategory] = useState("");
  const [editColor, setEditColor] = useState("");
  const [editMaterial, setEditMaterial] = useState("");
  // "" = automatic (no manual override) - the default and normal
  // case now. Only set to a real occasion value when deliberately
  // forcing one extra occasion on top of what the category implies.
  const [editOccasion, setEditOccasion] = useState("");
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
      // Clear the stale/invalid token before redirecting - same fix
      // as Dashboard.js. Without this, Login.js's "already logged
      // in?" check still sees this token and immediately bounces
      // straight back here, which fails again, in a fast loop that
      // trips the browser's history.replaceState rate limit (the
      // "Attempt to use history.replaceState() more than 100 times
      // per 10 seconds" crash).
      localStorage.removeItem("token");
      localStorage.removeItem("gender");
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

    // No occasion field here on purpose - the whole point of this
    // app is that the occasion(s) an item fits get worked out
    // automatically from its (AI-detected, or manually chosen)
    // category. See the "suitable_occasions" the backend sends
    // back below, and Edit on an item afterwards if you ever want
    // to force a specific occasion on top of that.

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

      const detectedOccasions =
        (response.data.suitable_occasions || [])
          .map(
            (value) =>
              OCCASIONS.find(([v]) => v === value)?.[1] || value
          )
          .join(", ");

      alert(
        `Item added successfully!\n` +
          `Detected color: ${response.data.color || "Unknown"}\n` +
          `Category: ${response.data.category}\n` +
          `Automatically suitable for: ${
            detectedOccasions || "every occasion"
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
    setEditOccasion(item.occasion || "");
  };

  const handleEditCancel = () => {
    setEditingId(null);
    setEditCategory("");
    setEditColor("");
    setEditMaterial("");
    setEditOccasion("");
  };

  const handleEditSave = async (id) => {
    setEditSaving(true);

    try {
      await axios.put(
        `http://localhost:5001/api/wardrobe/${id}`,
        {
          category: editCategory,
          color: editColor,
          material: editMaterial,
          occasion: editOccasion
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

  // Every category is an umbrella for every variant of that garment
  // (e.g. "Shirt" covers formal, casual, printed - any shirt),
  // instead of a long list of near-duplicate options. The ethnic
  // categories here match the AI classifier's actual 16 trained
  // classes 1:1 (see dataset/indofashion/class_names.json and
  // backend.category_gender, which is the single source of truth
  // this list mirrors) - so every one of these can also be reliably
  // auto-detected, not just Saree/Lehenga as before.
  //
  // "audience" drives the filter below: "unisex" always shows,
  // "men"/"women" only shows for a matching account. This is now
  // SYMMETRIC - a Male account gets its own explicit category set
  // (Kurta (Men), Sherwani, Nehru Jacket, Dhoti Pants, Mojaris
  // (Men)) instead of "whatever's left after hiding women's items".
  // This is a UI filter based on what the user chose at signup, not
  // a retrained model - there's no separate AI per gender. An
  // account with no gender on file sees every category.
  const ALL_CATEGORIES = [
    // ---- unisex Western basics ----
    ["Shirt", "Shirt", "unisex"],
    ["T-Shirt", "T-Shirt", "unisex"],
    ["Pant", "Pant", "unisex"],
    ["Shorts", "Shorts", "unisex"],
    ["Jacket", "Jacket", "unisex"],
    ["Bag", "Bag", "unisex"],
    ["Watch", "Watch", "unisex"],
    ["Belt", "Belt", "unisex"],
    ["Jewelry", "Jewelry", "unisex"],
    // ---- men's ----
    ["Kurta (Men)", "Kurta (Men)", "men"],
    ["Sherwani", "Sherwani", "men"],
    ["Nehru Jacket", "Nehru Jacket", "men"],
    ["Dhoti Pants", "Dhoti Pants", "men"],
    ["Mojaris (Men)", "Mojaris (Men)", "men"],
    // ---- women's ----
    ["Kurta (Women)", "Kurta (Women)", "women"],
    ["Skirt", "Skirt", "women"],
    ["Dress", "Dress", "women"],
    ["Saree", "Saree", "women"],
    ["Lehenga", "Lehenga", "women"],
    ["Blouse", "Blouse", "women"],
    ["Gown", "Gown", "women"],
    ["Petticoat", "Petticoat", "women"],
    ["Dupatta", "Dupatta", "women"],
    ["Palazzos", "Palazzos", "women"],
    ["Leggings & Salwars", "Leggings & Salwars", "women"],
    ["Mojaris (Women)", "Mojaris (Women)", "women"]
  ];

  const categories = ALL_CATEGORIES
    .filter(([, , audience]) => {
      if (audience === "unisex") return true;
      if (!userGender) return true; // no gender on file - show everything
      return audience === (userGender === "male" ? "men" : "women");
    })
    .map(([value, label]) => [value, label]);

  const ACCESSORY_CATEGORIES = [
    "Bag",
    "Watch",
    "Belt",
    "Jewelry"
  ];

  // =========================================================
  // OCCASION OPTIONS
  //
  // Matches backend.outfit_recommendation.CANONICAL_OCCASIONS.
  // Occasion eligibility is AUTOMATIC now, worked out from an
  // item's category (see backend/outfit_recommendation.py's
  // infer_occasions_for_category) - nothing here is required at
  // upload. This list is only used to (a) label the
  // auto-detected occasions shown after upload / on each item
  // card, and (b) let Edit optionally FORCE one extra occasion on
  // top of whatever the category already implies, for the rare
  // case where a specific item needs it (e.g. "this exact shirt is
  // my interview shirt").
  // =========================================================

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
            {userGender === "male" && " Showing Men's Wear categories."}
            {userGender === "female" && " Showing Women's Wear categories."}
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

            {/* No occasion picker here - it's detected
                automatically from the category above once the
                item's added. See the alert after Add Item, or the
                badges on each item card below; Edit an item if you
                ever want to force a specific occasion on top of
                that. */}

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

                      <label className="field-label">
                        Force an occasion (optional)
                      </label>

                      <select
                        value={editOccasion}
                        onChange={(e) =>
                          setEditOccasion(
                            e.target.value
                          )
                        }
                      >
                        <option value="">
                          Automatic (recommended)
                        </option>

                        {OCCASIONS.map(
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

                      {/* OCCASION - auto-detected from category,
                          not something you tagged when adding this
                          item. Shown as a short list of badges; a
                          "+ forced: X" note appears only when Edit
                          was used to add an occasion on top of
                          that. */}

                      <p
                        className="item-meta"
                        style={{
                          display: "flex",
                          flexWrap: "wrap",
                          gap: "4px"
                        }}
                      >
                        {(item.suitable_occasions &&
                        item.suitable_occasions.length > 0
                          ? item.suitable_occasions
                          : ["casual"]
                        ).map((value) => (
                          <span key={value} className="badge">
                            {OCCASIONS.find(
                              ([v]) => v === value
                            )?.[1] || value}
                          </span>
                        ))}
                      </p>

                      {item.occasion && (
                        <p
                          style={{
                            fontSize: "11px",
                            color: "#8a7a6d"
                          }}
                        >
                          + manually forced:{" "}
                          {OCCASIONS.find(
                            ([v]) => v === item.occasion
                          )?.[1] || item.occasion}
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

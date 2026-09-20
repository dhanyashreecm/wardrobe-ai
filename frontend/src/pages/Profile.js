import { useState, useEffect } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import Layout from "../components/Layout";
import "../App.css";

// Matches backend.auth.get_user_profile()'s "gender" values - shown
// read-only here since gender is permanently locked at registration
// (see Register.js/Login.js migration screen) and there is no route
// anywhere that lets it change after that.
const GENDER_LABELS = {
  Male: "Men's Wear",
  Female: "Women's Wear",
};

function Profile() {
  const navigate = useNavigate();
  const token = localStorage.getItem("token");

  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // -----------------------------------------------------
  // EDITABLE FIELDS (name, phone) - email and gender are shown but
  // never editable, see backend.auth.update_user_profile().
  // -----------------------------------------------------

  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");

  // -----------------------------------------------------
  // PROFILE PICTURE
  // -----------------------------------------------------

  const [pictureFile, setPictureFile] = useState(null);
  const [picturePreview, setPicturePreview] = useState(null);
  const [uploadingPicture, setUploadingPicture] = useState(false);

  // -----------------------------------------------------
  // DELETE ACCOUNT
  // -----------------------------------------------------

  const [deleting, setDeleting] = useState(false);

  // =========================================================
  // LOAD PROFILE
  // =========================================================

  const fetchProfile = async () => {
    try {
      const res = await axios.get(
        "http://localhost:5001/api/user/profile",
        { headers: { Authorization: `Bearer ${token}` } }
      );

      if (res.data.success) {
        setProfile(res.data.profile);
        setName(res.data.profile.name || "");
        setPhone(res.data.profile.phone || "");
      } else {
        setError(res.data.message || "Could not load profile.");
      }
    } catch (err) {
      console.error("Failed to fetch profile:", err);
      // Same stale-token cleanup as Dashboard.js/Wardrobe.js - an
      // expired/invalid token here should send the user back to
      // login, not leave them stuck on a broken profile page.
      localStorage.removeItem("token");
      localStorage.removeItem("gender");
      navigate("/login");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!token) {
      navigate("/login");
      return;
    }

    fetchProfile();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // =========================================================
  // EDIT NAME / PHONE
  // =========================================================

  const handleEditStart = () => {
    setSaveMessage("");
    setEditing(true);
  };

  const handleEditCancel = () => {
    setName(profile.name || "");
    setPhone(profile.phone || "");
    setEditing(false);
  };

  const handleEditSave = async () => {
    if (!name.trim()) {
      alert("Name can't be empty.");
      return;
    }

    setSaving(true);
    setSaveMessage("");

    try {
      const res = await axios.put(
        "http://localhost:5001/api/user/profile",
        { name, phone },
        { headers: { Authorization: `Bearer ${token}` } }
      );

      if (res.data.success) {
        setProfile(res.data.profile);
        setEditing(false);
        setSaveMessage("Saved.");
      } else {
        alert(res.data.message || "Could not save changes.");
      }
    } catch (err) {
      console.error("Profile update failed:", err);
      alert(
        err.response?.data?.message || "Could not save changes."
      );
    } finally {
      setSaving(false);
    }
  };

  // =========================================================
  // PROFILE PICTURE
  // =========================================================

  const handlePictureSelect = (e) => {
    const selectedFile = e.target.files[0];

    if (!selectedFile) {
      return;
    }

    if (!selectedFile.type.startsWith("image/")) {
      alert("Please select an image file.");
      return;
    }

    setPictureFile(selectedFile);
    setPicturePreview(URL.createObjectURL(selectedFile));
  };

  const handlePictureUpload = async () => {
    if (!pictureFile) {
      return;
    }

    setUploadingPicture(true);

    const formData = new FormData();
    formData.append("image", pictureFile);

    try {
      const res = await axios.post(
        "http://localhost:5001/api/user/profile/picture",
        formData,
        {
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "multipart/form-data",
          },
        }
      );

      if (res.data.success) {
        setProfile((prev) => ({
          ...prev,
          profile_picture: res.data.profile_picture,
        }));
        setPictureFile(null);
        setPicturePreview(null);

        const fileInput = document.getElementById("profilePictureInput");
        if (fileInput) {
          fileInput.value = "";
        }
      } else {
        alert(res.data.message || "Could not upload picture.");
      }
    } catch (err) {
      console.error("Profile picture upload failed:", err);
      alert(
        err.response?.data?.message || "Could not upload picture."
      );
    } finally {
      setUploadingPicture(false);
    }
  };

  // =========================================================
  // LOGOUT
  // =========================================================

  const handleLogout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("gender");
    navigate("/login");
  };

  // =========================================================
  // DELETE ACCOUNT
  // =========================================================

  const handleDeleteAccount = async () => {
    const confirmed = window.confirm(
      "Delete your account? This permanently removes your profile, " +
        "your entire wardrobe, and every saved trip. This can't be undone."
    );

    if (!confirmed) {
      return;
    }

    // A second, more deliberate confirmation - this is irreversible
    // and deletes real data, so one click alone shouldn't be enough.
    const typed = window.prompt(
      'Type DELETE (all caps) to permanently delete your account.'
    );

    if (typed !== "DELETE") {
      return;
    }

    setDeleting(true);

    try {
      const res = await axios.delete(
        "http://localhost:5001/api/user/account",
        { headers: { Authorization: `Bearer ${token}` } }
      );

      if (res.data.success) {
        localStorage.removeItem("token");
        localStorage.removeItem("gender");
        navigate("/login");
      } else {
        alert(res.data.message || "Could not delete account.");
        setDeleting(false);
      }
    } catch (err) {
      console.error("Account deletion failed:", err);
      alert(
        err.response?.data?.message || "Could not delete account."
      );
      setDeleting(false);
    }
  };

  // =========================================================
  // UI
  // =========================================================

  if (loading) {
    return (
      <Layout>
        <p style={{ color: "#8a7a6d" }}>Loading your profile...</p>
      </Layout>
    );
  }

  if (error || !profile) {
    return (
      <Layout>
        <p className="error">{error || "Profile unavailable."}</p>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="page-header">
        <div>
          <h1 className="page-title">My Profile</h1>
          <p className="page-subtitle">
            Your account details, in one place.
          </p>
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "260px 1fr",
          gap: "28px",
          alignItems: "start",
        }}
      >
        {/* ================================================= */}
        {/* PROFILE PICTURE */}
        {/* ================================================= */}

        <div className="side-panel" style={{ textAlign: "center" }}>
          <div
            style={{
              width: "140px",
              height: "140px",
              borderRadius: "50%",
              overflow: "hidden",
              margin: "0 auto 16px",
              border: "2px solid #ece1d6",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: "#fdf3e7",
              fontSize: "56px",
            }}
          >
            {picturePreview || profile.profile_picture ? (
              <img
                src={
                  picturePreview ||
                  `http://localhost:5001${profile.profile_picture}`
                }
                alt="Profile"
                style={{
                  width: "100%",
                  height: "100%",
                  objectFit: "cover",
                }}
              />
            ) : (
              <span>👤</span>
            )}
          </div>

          <input
            id="profilePictureInput"
            type="file"
            accept="image/*"
            onChange={handlePictureSelect}
            style={{ marginBottom: "10px", fontSize: "12px" }}
          />

          {pictureFile && (
            <button
              className="btn btn-primary btn-sm"
              onClick={handlePictureUpload}
              disabled={uploadingPicture}
              style={{ width: "100%" }}
            >
              {uploadingPicture ? "Uploading..." : "Save Photo"}
            </button>
          )}
        </div>

        {/* ================================================= */}
        {/* DETAILS */}
        {/* ================================================= */}

        <div className="side-panel">
          <h3>Account Details</h3>

          {!editing ? (
            <>
              <p className="item-meta">
                <strong>Name:</strong> {profile.name}
              </p>

              <p className="item-meta">
                <strong>Email:</strong> {profile.email}
              </p>

              <p className="item-meta">
                <strong>Phone:</strong>{" "}
                {profile.phone || "Not added yet"}
              </p>

              <p className="item-meta">
                <strong>Wardrobe:</strong>{" "}
                {GENDER_LABELS[profile.gender] ||
                  "Not set"}
              </p>

              {saveMessage && (
                <p style={{ color: "#2f6b45", fontSize: "13px" }}>
                  {saveMessage}
                </p>
              )}

              <button
                className="btn btn-secondary btn-sm"
                onClick={handleEditStart}
                style={{ marginTop: "10px" }}
              >
                Edit Name / Phone
              </button>
            </>
          ) : (
            <>
              <label className="field-label">Name</label>
              <input
                placeholder="Your name"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />

              <label className="field-label">Phone number</label>
              <input
                placeholder="Phone number (optional)"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
              />

              <p
                style={{
                  fontSize: "12px",
                  color: "#8a7a6d",
                  marginBottom: "12px",
                }}
              >
                Email and Wardrobe (gender) can't be changed here.
              </p>

              <div className="item-actions">
                <button
                  className="btn btn-primary btn-sm"
                  onClick={handleEditSave}
                  disabled={saving}
                >
                  {saving ? "Saving..." : "Save"}
                </button>

                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={handleEditCancel}
                  disabled={saving}
                >
                  Cancel
                </button>
              </div>
            </>
          )}

          <hr
            style={{
              margin: "22px 0",
              border: "none",
              borderTop: "1px solid #ece1d6",
            }}
          />

          <button
            className="btn btn-secondary btn-sm"
            onClick={handleLogout}
            style={{ marginRight: "10px" }}
          >
            ⎋ Logout
          </button>

          <button
            className="btn btn-danger btn-sm"
            onClick={handleDeleteAccount}
            disabled={deleting}
          >
            {deleting ? "Deleting..." : "Delete My Account"}
          </button>
        </div>
      </div>
    </Layout>
  );
}

export default Profile;
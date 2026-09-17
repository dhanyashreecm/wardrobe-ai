import { useState } from "react";
import axios from "axios";
import { useNavigate, Link } from "react-router-dom";
import "../App.css";

// Single source of truth for the gender picker - shared with
// Login.js's pre-fill picker (both read/write the same
// "genderPreference" localStorage key, so a choice made on either
// screen carries over to the other instead of the two silently
// disagreeing).
const GENDER_OPTIONS = [
  { value: "Female", label: "Women", icon: "👗" },
  { value: "Male", label: "Men", icon: "👔" }
];

function Register() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  // Pre-filled from whatever was picked on the Login page (if
  // anything), but this field - not Login's - is the one that
  // actually gets submitted. No default: an empty string means
  // "not chosen yet" and blocks submission, since gender is now
  // mandatory and can never be changed after this form is submitted.
  const [gender, setGender] = useState(
    () => localStorage.getItem("genderPreference") || ""
  );

  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const chooseGender = (value) => {
    setGender(value);
    localStorage.setItem("genderPreference", value);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");

    if (!name || !email || !password) {
      setError("All fields are required");
      return;
    }

    if (gender !== "Male" && gender !== "Female") {
      setError("Please choose Men or Women to continue - this can't be changed later.");
      return;
    }

    setLoading(true);
    try {
      const res = await axios.post("http://localhost:5001/api/register", {
        name, email, password, gender
      });
      if (res.data.success) {
        // Done its job - clear it so a later visit to Login/Register
        // for a DIFFERENT new account doesn't silently inherit it.
        localStorage.removeItem("genderPreference");
        navigate("/login");
      } else {
        setError(res.data.message || "Registration failed");
      }
    } catch (err) {
      setError(err.response?.data?.message || "Registration failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-shell">
      <div className="auth-hero">
        <div className="auth-hero-brand">
          <span role="img" aria-label="hanger">👚</span> WardrobeAI
          <span className="tagline">Your Style · Your Wardrobe · Smarter Choices</span>
        </div>

        <div>
          <h1>
            Build Your
            <br />
            Digital <em>Wardrobe</em>
          </h1>

          <p className="subtitle">
            Catalog your clothes once, then let WardrobeAI put
            together outfits, plan your trips, and dress you for
            the weather.
          </p>

          <div className="auth-hero-features">
            <div className="feature">
              <span className="icon">👗</span>
              Organize every category
            </div>
            <div className="feature">
              <span className="icon">🤖</span>
              AI-assisted categorization
            </div>
            <div className="feature">
              <span className="icon">❤️</span>
              Save your favorites
            </div>
          </div>
        </div>

        <p className="auth-hero-quote">
          "Small choices create big style stories."
        </p>
      </div>

      <div className="auth-panel">
        <div className="auth-card">
          <h2>Create Account</h2>
          <p className="auth-subtitle">
            Start building your digital wardrobe today.
          </p>

          <form onSubmit={handleSubmit}>
            <input
              placeholder="Name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <input
              placeholder="Email address"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <input
              placeholder="Password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />

            {/* ================================================= */}
            {/* GENDER - mandatory, permanent */}
            {/* ================================================= */}

            <label className="field-label">
              Your wardrobe *
            </label>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: "10px",
                marginBottom: "8px"
              }}
            >
              {GENDER_OPTIONS.map((opt) => {
                const selected = gender === opt.value;

                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => chooseGender(opt.value)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: "8px",
                      padding: "12px 10px",
                      borderRadius: "12px",
                      border: selected
                        ? "2px solid #c1694f"
                        : "2px solid #ece1d6",
                      background: selected ? "#fdf1ea" : "#fffaf5",
                      cursor: "pointer",
                      fontFamily: "inherit",
                      fontWeight: selected ? 700 : 500
                    }}
                  >
                    <span style={{ fontSize: "18px" }}>{opt.icon}</span>
                    {opt.label}
                  </button>
                );
              })}
            </div>

            <p
              style={{
                fontSize: "12px",
                color: "#8a7a6d",
                margin: "-2px 0 14px"
              }}
            >
              Required, and <strong>permanent</strong> - it sets your
              wardrobe's category list (e.g. Kurta/Sherwani/Dhoti
              Pants for Men, Saree/Lehenga/Blouse for Women) and
              keeps recommendations and AI detection scoped to it.
              It cannot be changed after your account is created.
            </p>

            <button
              type="submit"
              disabled={loading || (gender !== "Male" && gender !== "Female")}
            >
              {loading ? "Creating account..." : "Create Account →"}
            </button>
          </form>

          {error && <p className="error">{error}</p>}

          <p className="switch-link">
            Already have an account? <Link to="/login">Login →</Link>
          </p>
        </div>
      </div>
    </div>
  );
}

export default Register;

import { useState, useEffect } from "react";
import axios from "axios";
import { useNavigate, Link } from "react-router-dom";
import "../App.css";

// Shown on the Login page purely as a convenience PRE-FILL for the
// Register screen (this is where a NEW account's choice is actually
// submitted - see Register.js, which reads/writes this same
// localStorage key so the two screens can't disagree). It does
// nothing to an account that already exists.
const GENDER_OPTIONS = [
  { value: "Female", label: "Women", icon: "👗" },
  { value: "Male", label: "Men", icon: "👔" }
];

function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const [genderPreference, setGenderPreference] = useState(
    () => localStorage.getItem("genderPreference") || ""
  );

  // -----------------------------------------------------
  // ONE-TIME MIGRATION for an account that logged in
  // successfully but has NO gender on file yet (it was created
  // before gender became mandatory). We never silently assign one -
  // the account owner has to make an explicit, permanent choice
  // before continuing on to the dashboard.
  // -----------------------------------------------------
  const [needsMigration, setNeedsMigration] = useState(false);
  const [pendingToken, setPendingToken] = useState(null);
  const [migrationChoice, setMigrationChoice] = useState("");
  const [migrationError, setMigrationError] = useState("");
  const [migrationSaving, setMigrationSaving] = useState(false);

  // A returning, already-logged-in visitor shouldn't see the login
  // form at all - straight to the dashboard.
  useEffect(() => {
    if (localStorage.getItem("token")) {
      navigate("/dashboard", { replace: true });
    }
  }, [navigate]);

  const chooseGender = (value) => {
    setGenderPreference(value);
    localStorage.setItem("genderPreference", value);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const res = await axios.post("http://localhost:5001/api/login", {
        email, password
      });
      if (res.data.success) {
        if (res.data.gender) {
          localStorage.setItem("token", res.data.token);
          localStorage.setItem("gender", res.data.gender);
          navigate("/dashboard");
        } else {
          // Pre-existing, gender-less account - hold the token in
          // memory only (not localStorage yet) until the one-time
          // choice below is saved, so a half-finished migration
          // can't leave a "logged in but no gender" state behind.
          setPendingToken(res.data.token);
          setNeedsMigration(true);
        }
      }
    } catch (err) {
      setError(err.response?.data?.message || "Login failed");
    } finally {
      setLoading(false);
    }
  };

  const handleMigrationSave = async () => {
    if (migrationChoice !== "Male" && migrationChoice !== "Female") {
      setMigrationError("Please choose Men or Women to continue.");
      return;
    }

    setMigrationSaving(true);
    setMigrationError("");

    try {
      const res = await axios.post(
        "http://localhost:5001/api/user/gender/migrate",
        { gender: migrationChoice },
        { headers: { Authorization: `Bearer ${pendingToken}` } }
      );

      if (res.data.success) {
        localStorage.setItem("token", pendingToken);
        localStorage.setItem("gender", res.data.gender);
        navigate("/dashboard");
      } else {
        setMigrationError(res.data.message || "Could not save your choice.");
      }
    } catch (err) {
      setMigrationError(
        err.response?.data?.message || "Could not save your choice."
      );
    } finally {
      setMigrationSaving(false);
    }
  };

  // =========================================================
  // ONE-TIME MIGRATION SCREEN
  // =========================================================

  if (needsMigration) {
    return (
      <div className="auth-shell">
        <div className="auth-hero">
          <div className="auth-hero-brand">
            <span role="img" aria-label="hanger">👚</span> WardrobeAI
          </div>
          <div>
            <h1>
              One Last <em>Step</em>
            </h1>
            <p className="subtitle">
              Your account was created before wardrobe gender
              existed. Pick one now to finish setting it up - this
              is a one-time choice and can't be changed afterward.
            </p>
          </div>
        </div>

        <div className="auth-panel">
          <div className="auth-card">
            <h2>Choose Your Wardrobe</h2>
            <p className="auth-subtitle">
              This decides your category list (e.g. Kurta/Sherwani/
              Dhoti Pants for Men, Saree/Lehenga/Blouse for Women)
              and scopes recommendations and AI detection to it.
            </p>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: "10px",
                marginBottom: "16px"
              }}
            >
              {GENDER_OPTIONS.map((opt) => {
                const selected = migrationChoice === opt.value;

                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setMigrationChoice(opt.value)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: "8px",
                      padding: "14px 10px",
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

            <button
              type="button"
              disabled={migrationSaving || (migrationChoice !== "Male" && migrationChoice !== "Female")}
              onClick={handleMigrationSave}
              style={{ width: "100%" }}
            >
              {migrationSaving ? "Saving..." : "Confirm & Continue →"}
            </button>

            {migrationError && <p className="error">{migrationError}</p>}
          </div>
        </div>
      </div>
    );
  }

  // =========================================================
  // NORMAL LOGIN SCREEN
  // =========================================================

  return (
    <div className="auth-shell">
      <div className="auth-hero">
        <div className="auth-hero-brand">
          <span role="img" aria-label="hanger">👚</span> WardrobeAI
          <span className="tagline">Your Style · Your Wardrobe · Smarter Choices</span>
        </div>

        <div>
          <h1>
            Dress Better,
            <br />
            Live <em>Smarter</em>
          </h1>

          <p className="subtitle">
            Your personal AI-powered wardrobe for outfit
            recommendations, trip planning, weather-based
            suggestions and more.
          </p>

          <div className="auth-hero-features">
            <div className="feature">
              <span className="icon">✨</span>
              Smart Recommendations
            </div>
            <div className="feature">
              <span className="icon">☁️</span>
              Weather-Ready Outfits
            </div>
            <div className="feature">
              <span className="icon">🧳</span>
              Trip Planner
            </div>
            <div className="feature">
              <span className="icon">🔍</span>
              Similar Search
            </div>
          </div>
        </div>

        <p className="auth-hero-quote">
          "Good outfits build good days."
        </p>
      </div>

      <div className="auth-panel">
        <div className="auth-card">
          <h2>Welcome Back</h2>
          <p className="auth-subtitle">
            Login to continue your fashion journey.
          </p>

          {/* ================================================= */}
          {/* GENDER PRE-FILL (for creating a NEW account - see
              GENDER_OPTIONS comment above) */}
          {/* ================================================= */}

          <div style={{ marginBottom: "18px" }}>
            <label className="field-label">
              Creating a new account?
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
                const selected = genderPreference === opt.value;

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
                marginTop: "8px"
              }}
            >
              Pick this now to save a step on Register - you'll
              confirm it there and it can't be changed afterward.
              Has no effect on an account you already have.
            </p>
          </div>

          <form onSubmit={handleSubmit}>
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
            <button type="submit" disabled={loading}>
              {loading ? "Logging in..." : "Login →"}
            </button>
          </form>

          {error && <p className="error">{error}</p>}

          <p className="switch-link">
            Don't have an account? <Link to="/register">Create one →</Link>
          </p>
        </div>
      </div>
    </div>
  );
}

export default Login;

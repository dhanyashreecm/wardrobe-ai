import { useState } from "react";
import axios from "axios";
import { useNavigate, Link } from "react-router-dom";
import "../App.css";

function Register() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");

    if (!name || !email || !password) {
      setError("All fields are required");
      return;
    }

    setLoading(true);
    try {
      const res = await axios.post("http://localhost:5001/api/register", {
        name, email, password
      });
      if (res.data.success) {
        navigate("/login");
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
            <button type="submit" disabled={loading}>
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

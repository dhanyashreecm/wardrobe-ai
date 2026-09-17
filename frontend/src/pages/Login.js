import { useState } from "react";
import axios from "axios";
import { useNavigate, Link } from "react-router-dom";
import "../App.css";

function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const res = await axios.post("http://localhost:5001/api/login", {
        email, password
      });
      if (res.data.success) {
        localStorage.setItem("token", res.data.token);

        if (res.data.gender) {
          localStorage.setItem("gender", res.data.gender);
        } else {
          localStorage.removeItem("gender");
        }

        navigate("/dashboard");
      }
    } catch (err) {
      setError(err.response?.data?.message || "Login failed");
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

import { useState } from "react";
import axios from "axios";
import { useNavigate, Link } from "react-router-dom";
import "../App.css";
import { API_URL } from "../config";

// Two steps on one screen:
//   1. enter email  -> backend emails a 6-digit code
//   2. enter code + new password -> password is changed
function ForgotPassword() {
  const [step, setStep] = useState(1);
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [info, setInfo] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const requestCode = async (e) => {
    if (e) e.preventDefault();
    setError("");
    setInfo("");
    if (!email.trim()) {
      setError("Enter your email address");
      return;
    }
    setLoading(true);
    try {
      const res = await axios.post(`${API_URL}/api/password/forgot`, {
        email: email.trim().toLowerCase()
      });
      setInfo(res.data.message);
      setStep(2);
    } catch (err) {
      setError(err.response?.data?.message || "Could not reach the server");
    } finally {
      setLoading(false);
    }
  };

  const resetPassword = async (e) => {
    e.preventDefault();
    setError("");
    if (!/^\d{6}$/.test(code.trim())) {
      setError("Enter the 6-digit code from the email");
      return;
    }
    if (password.length < 6) {
      setError("New password must be at least 6 characters");
      return;
    }
    if (password !== confirm) {
      setError("Passwords don't match");
      return;
    }
    setLoading(true);
    try {
      const res = await axios.post(`${API_URL}/api/password/reset`, {
        email: email.trim().toLowerCase(),
        code: code.trim(),
        new_password: password
      });
      setInfo(res.data.message);
      setTimeout(() => navigate("/login"), 1500);
    } catch (err) {
      setError(err.response?.data?.message || "Could not reach the server");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-shell">
      <div className="auth-hero">
        <div className="auth-hero-brand">
          <span role="img" aria-label="hanger">👚</span> WardrobeAI
        </div>
        <div>
          <h1>
            Forgot Your <em>Password?</em>
          </h1>
          <p className="subtitle">
            We'll email you a 6-digit code so you can choose a new one.
          </p>
        </div>
      </div>

      <div className="auth-panel">
        <div className="auth-card">
          <h2>Reset Password</h2>

          {step === 1 ? (
            <>
              <p className="auth-subtitle">
                Enter the email you registered with.
              </p>
              <form onSubmit={requestCode}>
                <input
                  placeholder="Email address"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
                <button type="submit" disabled={loading}>
                  {loading ? "Sending..." : "Send Code →"}
                </button>
              </form>
            </>
          ) : (
            <>
              <p className="auth-subtitle">
                Code sent to <strong>{email}</strong>. It expires in 15 minutes.
              </p>
              <form onSubmit={resetPassword}>
                <input
                  placeholder="6-digit code"
                  inputMode="numeric"
                  maxLength={6}
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                />
                <input
                  placeholder="New password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <input
                  placeholder="Confirm new password"
                  type="password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                />
                <button type="submit" disabled={loading}>
                  {loading ? "Saving..." : "Change Password →"}
                </button>
              </form>
              <p className="switch-link">
                Didn't get it?{" "}
                <button
                  type="button"
                  onClick={requestCode}
                  disabled={loading}
                  style={{
                    background: "none", border: "none", padding: 0,
                    color: "#c1694f", fontWeight: 700, cursor: "pointer",
                    width: "auto", fontFamily: "inherit", fontSize: "inherit"
                  }}
                >
                  Send again
                </button>{" "}
                (wait a minute between requests)
              </p>
            </>
          )}

          {info && <p style={{ color: "#3f7a4f", marginTop: "10px" }}>{info}</p>}
          {error && <p className="error">{error}</p>}

          <p className="switch-link">
            Remembered it? <Link to="/login">Back to login →</Link>
          </p>
        </div>
      </div>
    </div>
  );
}

export default ForgotPassword;

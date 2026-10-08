import { useState } from "react";
import axios from "axios";
import { useNavigate, Link } from "react-router-dom";
import "../App.css";
import { API_URL } from "../config";

// Forgot Password - plain email code, nothing else (no passkeys,
// security keys or authenticator apps):
//   1. enter the registered email -> backend emails a 6-digit code
//   2. enter the code             -> backend checks it
//   3. choose a new password      -> saved, then log in with it
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[a-z]{2,}$/i;

// The backend's own message when it answered; otherwise say WHICH
// server could not be reached - the usual cause is that the backend
// isn't running, or REACT_APP_API_URL points somewhere else.
function errorMessage(err) {
  if (err.response?.data?.message) return err.response.data.message;
  if (err.response) return `Server error (${err.response.status}). Please try again.`;
  return `Could not reach the server at ${API_URL}. Is the backend running?`;
}

const linkButton = {
  background: "none", border: "none", padding: 0,
  color: "#c1694f", fontWeight: 700, cursor: "pointer",
  width: "auto", fontFamily: "inherit", fontSize: "inherit"
};

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

  const cleanEmail = () => email.trim().toLowerCase();

  // Step 1 (and "Send again" on step 2)
  const requestCode = async (e) => {
    if (e) e.preventDefault();
    setError("");
    setInfo("");
    if (!email.trim()) {
      setError("Enter your email address");
      return;
    }
    if (!EMAIL_PATTERN.test(email.trim())) {
      setError("Please enter a valid email address");
      return;
    }
    setLoading(true);
    try {
      const res = await axios.post(`${API_URL}/api/password/forgot`, {
        email: cleanEmail()
      });
      setInfo(res.data.message);
      setCode("");
      setStep(2);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  // Step 2
  const verifyCode = async (e) => {
    e.preventDefault();
    setError("");
    setInfo("");
    if (!/^\d{6}$/.test(code.trim())) {
      setError("Enter the 6-digit code from the email");
      return;
    }
    setLoading(true);
    try {
      const res = await axios.post(`${API_URL}/api/password/verify-code`, {
        email: cleanEmail(),
        code: code.trim()
      });
      setInfo(res.data.message);
      setStep(3);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  // Step 3
  const resetPassword = async (e) => {
    e.preventDefault();
    setError("");
    setInfo("");
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
        email: cleanEmail(),
        code: code.trim(),
        new_password: password
      });
      setInfo(res.data.message);
      setTimeout(() => navigate("/login"), 1500);
    } catch (err) {
      const message = errorMessage(err);
      setError(message);
      // Code expired or used up while on this screen: start over at the code step.
      if (/code/i.test(message)) setStep(2);
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

          {step === 1 && (
            <>
              <p className="auth-subtitle">
                Enter the email you registered with.
              </p>
              <form onSubmit={requestCode} noValidate>
                <input
                  placeholder="Email address"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
                <button type="submit" disabled={loading}>
                  {loading ? "Sending..." : "Send Code →"}
                </button>
              </form>
            </>
          )}

          {step === 2 && (
            <>
              <p className="auth-subtitle">
                Enter the 6-digit code sent to <strong>{email.trim()}</strong>.
                It expires in 15 minutes.
              </p>
              <form onSubmit={verifyCode}>
                <input
                  placeholder="6-digit code"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                />
                <button type="submit" disabled={loading}>
                  {loading ? "Checking..." : "Verify Code →"}
                </button>
              </form>
              <p className="switch-link">
                Didn't get it? Check Spam, or{" "}
                <button type="button" onClick={requestCode} disabled={loading} style={linkButton}>
                  send again
                </button>{" "}
                (wait a minute between requests)
              </p>
              <p className="switch-link">
                Wrong email?{" "}
                <button
                  type="button"
                  onClick={() => { setStep(1); setCode(""); setInfo(""); setError(""); }}
                  style={linkButton}
                >
                  Change it
                </button>
              </p>
            </>
          )}

          {step === 3 && (
            <>
              <p className="auth-subtitle">
                Choose a new password for <strong>{email.trim()}</strong>.
              </p>
              <form onSubmit={resetPassword}>
                <input
                  placeholder="New password"
                  type="password"
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <input
                  placeholder="Confirm new password"
                  type="password"
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                />
                <button type="submit" disabled={loading}>
                  {loading ? "Saving..." : "Change Password →"}
                </button>
              </form>
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

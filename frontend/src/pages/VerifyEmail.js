import { useEffect, useState } from "react";
import axios from "axios";
import { useLocation, useNavigate, Link } from "react-router-dom";
import "../App.css";
import { API_URL } from "../config";

const RESEND_WAIT_SECONDS = 60;

// Shown after registering (and when an unverified account tries to
// log in). The user types the 6-digit code from their inbox; until
// they do, the backend refuses to issue a login token.
function VerifyEmail() {
  const location = useLocation();
  const navigate = useNavigate();

  const initialEmail =
    location.state?.email ||
    new URLSearchParams(location.search).get("email") ||
    "";

  const [email, setEmail] = useState(initialEmail);
  const [code, setCode] = useState("");
  const [info, setInfo] = useState(location.state?.notice || "");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [wait, setWait] = useState(initialEmail ? RESEND_WAIT_SECONDS : 0);

  useEffect(() => {
    if (wait <= 0) return undefined;
    const timer = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(timer);
  }, [wait]);

  const verify = async (e) => {
    e.preventDefault();
    setError("");
    setInfo("");

    if (!email.trim()) {
      setError("Enter the email address you registered with");
      return;
    }
    if (!/^\d{6}$/.test(code.trim())) {
      setError("Enter the 6-digit code from the email");
      return;
    }

    setLoading(true);
    try {
      const res = await axios.post(`${API_URL}/api/verify-email`, {
        email: email.trim().toLowerCase(),
        code: code.trim(),
      });
      navigate("/login", {
        replace: true,
        state: { notice: res.data.message, email: email.trim().toLowerCase() },
      });
    } catch (err) {
      setError(err.response?.data?.message || "Could not reach the server");
    } finally {
      setLoading(false);
    }
  };

  const resend = async () => {
    setError("");
    setInfo("");
    if (!email.trim()) {
      setError("Enter your email address first");
      return;
    }
    setLoading(true);
    try {
      const res = await axios.post(`${API_URL}/api/verify-email/resend`, {
        email: email.trim().toLowerCase(),
      });
      setInfo(res.data.message);
      setWait(RESEND_WAIT_SECONDS);
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
            Check Your <em>Inbox</em>
          </h1>
          <p className="subtitle">
            We emailed you a 6-digit code to confirm the address is
            yours. Your account activates as soon as you enter it.
          </p>
        </div>
      </div>

      <div className="auth-panel">
        <div className="auth-card">
          <h2>Verify Your Email</h2>
          <p className="auth-subtitle">
            {initialEmail ? (
              <>Code sent to <strong>{initialEmail}</strong>. It expires in 15 minutes.</>
            ) : (
              "Enter your email and the code we sent you."
            )}
          </p>

          <form onSubmit={verify}>
            {!initialEmail && (
              <input
                placeholder="Email address"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            )}
            <input
              placeholder="6-digit code"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            />
            <button type="submit" disabled={loading}>
              {loading ? "Checking..." : "Verify Email →"}
            </button>
          </form>

          <p className="switch-link">
            Didn't get it? Check spam, or{" "}
            <button
              type="button"
              onClick={resend}
              disabled={loading || wait > 0}
              style={{
                background: "none", border: "none", padding: 0,
                color: wait > 0 ? "#b3a497" : "#c1694f", fontWeight: 700,
                cursor: wait > 0 ? "default" : "pointer",
                width: "auto", fontFamily: "inherit", fontSize: "inherit"
              }}
            >
              {wait > 0 ? `send again in ${wait}s` : "send a new code"}
            </button>
          </p>

          {info && <p style={{ color: "#3f7a4f", marginTop: "10px" }}>{info}</p>}
          {error && <p className="error">{error}</p>}

          <p className="switch-link">
            Already verified? <Link to="/login">Back to login →</Link>
          </p>
        </div>
      </div>
    </div>
  );
}

export default VerifyEmail;

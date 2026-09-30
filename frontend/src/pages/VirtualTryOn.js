import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import axios from "axios";

import Layout from "../components/Layout";
import PageHeader from "../components/PageHeader";
import { API_URL, assetUrl } from "../config";
import "../styles/aw-v2.css";
import "../styles/tryon.css";

/*
 * VIRTUAL TRY-ON
 *
 * The user's own photo + a garment from their own wardrobe, sent to the
 * configured AI try-on service by the backend (backend/virtual_tryon.py).
 * Nothing here composes images: the result shown is exactly the image
 * the service generated. When no service is configured the page says so
 * instead of offering a form that can't work.
 *
 * Which garments can be tried on is decided by the BACKEND
 * (GET /api/tryon/garments labels every item) - this page keeps no
 * category list of its own.
 */

// Generation takes 20-60 s per garment. Poll gently and back off.
const FIRST_POLL_MS = 2000;
const MAX_POLL_MS = 5000;
// Give up waiting on the page after this long; the backend has its own
// per-garment timeout and will normally report failure well before.
const CLIENT_TIMEOUT_MS = 12 * 60 * 1000;

// Job error codes that mean the SERVICE was the problem (not the photo or
// garment) - a later retry can work, so a Retry button is offered.
const PROVIDER_ERROR_CODES = new Set([
  "QUOTA_EXHAUSTED", "RATE_LIMITED", "QUEUE_FULL", "PROVIDER_SLEEPING",
  "TEMPORARILY_UNAVAILABLE", "TIMEOUT", "AUTH_ERROR", "CONFIGURATION_ERROR",
]);

const SLOT_GROUPS = [
  { slot: "one_piece", label: "Dresses & one-pieces" },
  { slot: "top", label: "Tops" },
  { slot: "bottom", label: "Bottoms" },
  { slot: "outerwear", label: "Jackets & layers" },
];

function friendlyError(err, fallback) {
  if (!err || !err.response) {
    return "Can't reach the server right now. Check your connection and try again.";
  }
  if (err.response.status === 401 || err.response.status === 422) {
    return "Your session has expired - please log in again.";
  }
  const data = err.response.data;
  if (data && typeof data === "object" && typeof data.message === "string") {
    return data.message;
  }
  return fallback;
}

function authHeaders() {
  const token = localStorage.getItem("token");
  return token ? { Authorization: `Bearer ${token}` } : null;
}

// Selection rules: one item per slot; a one-piece is worn alone; a
// provider that only wears one garment gets exactly one.
export function applySelection(current, item, garments, maxGarments) {
  const slot = item.tryon.slot;
  const slotOf = (id) => garments.find((g) => g._id === id)?.tryon.slot;

  if (current.includes(item._id)) return current.filter((id) => id !== item._id);
  if (maxGarments <= 1) return [item._id];

  let next = current.filter((id) => slotOf(id) !== slot);
  if (slot === "one_piece") next = next.filter((id) => !["top", "bottom"].includes(slotOf(id)));
  if (slot === "top" || slot === "bottom") next = next.filter((id) => slotOf(id) !== "one_piece");
  next = [...next, item._id];
  return next.slice(-maxGarments);
}

function VirtualTryOn() {
  const navigate = useNavigate();
  const location = useLocation();
  const incoming = useMemo(() => location.state || {}, [location.state]);

  const [capability, setCapability] = useState(null);
  const [garments, setGarments] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [selected, setSelected] = useState([]);
  const [incomingNotes, setIncomingNotes] = useState([]);

  const [photoUrl, setPhotoUrl] = useState("");
  const [localPreview, setLocalPreview] = useState("");
  const [uploading, setUploading] = useState(false);
  const [photoProblems, setPhotoProblems] = useState([]);

  const [job, setJob] = useState(null);
  const [besides, setBesides] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showOriginal, setShowOriginal] = useState(false);
  const [history, setHistory] = useState([]);
  // A try-on that failed because of the service, not the input.
  const [canRetry, setCanRetry] = useState(false);
  const [checking, setChecking] = useState(false);

  const fileInput = useRef(null);
  const pollTimer = useRef(null);
  // Set synchronously, so two quick clicks can never start two try-ons.
  const submitting = useRef(false);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, []);

  // Revoke the local object URL when it is replaced.
  useEffect(() => () => {
    if (localPreview) URL.revokeObjectURL(localPreview);
  }, [localPreview]);

  const loadHistory = useCallback(async () => {
    const headers = authHeaders();
    if (!headers) return;
    try {
      const res = await axios.get(`${API_URL}/api/tryon/results`, { headers });
      if (alive.current) setHistory(res.data.results || []);
    } catch (err) {
      // History is secondary: never block a new try-on over it.
    }
  }, []);

  // Re-asks the backend which provider (if any) is usable now. Never
  // submits anything, so it costs no try-on allowance.
  const refreshCapability = useCallback(async () => {
    const headers = authHeaders();
    if (!headers) return null;
    try {
      const res = await axios.get(`${API_URL}/api/tryon/capability`, { headers });
      if (!alive.current) return null;
      setCapability(res.data);
      return res.data;
    } catch (err) {
      return null;
    }
  }, []);

  useEffect(() => {
    const headers = authHeaders();
    if (!headers) {
      navigate("/login");
      return;
    }
    (async () => {
      try {
        const [cap, list] = await Promise.all([
          axios.get(`${API_URL}/api/tryon/capability`, { headers }),
          axios.get(`${API_URL}/api/tryon/garments`, { headers }),
        ]);
        if (!alive.current) return;
        setCapability(cap.data);
        setPhotoUrl(cap.data.photo_url || "");
        setGarments(list.data.items || []);
      } catch (err) {
        if (!alive.current) return;
        if (err?.response?.status === 401 || err?.response?.status === 422) {
          navigate("/login");
          return;
        }
        setError(friendlyError(err, "Couldn't load Virtual Try-On. Please refresh the page."));
      } finally {
        if (alive.current) setLoaded(true);
      }
    })();
    loadHistory();
  }, [navigate, loadHistory]);

  const maxGarments = capability?.max_garments || 1;

  // A garment (from My Wardrobe) or an outfit (from a recommendation)
  // handed to this page: pre-select what can be worn, and say plainly
  // what can't.
  useEffect(() => {
    const ids = incoming.itemIds || [];
    if (!ids.length || !garments.length || !capability) return;
    let next = [];
    const notes = [];
    ids.forEach((id) => {
      const item = garments.find((g) => g._id === id);
      if (!item) return;
      if (item.tryon.supported) {
        next = applySelection(next, item, garments, maxGarments);
      } else if (!item.tryon.shown_beside) {
        notes.push(`${item.display_name}: ${item.tryon.reason}`);
      }
    });
    setSelected(next);
    setIncomingNotes(notes);
  }, [incoming.itemIds, garments, capability, maxGarments]);

  const wearable = garments.filter((g) => g.tryon.supported);
  const unavailable = garments.filter((g) => !g.tryon.supported && !g.tryon.shown_beside);
  const selectedItems = selected.map((id) => garments.find((g) => g._id === id)).filter(Boolean);
  const serviceUp = capability ? capability.available !== false : false;
  const inputsReady = Boolean(photoUrl) && selected.length > 0 && !busy && !uploading;
  // The backend is the only authority on how many attempts are left;
  // this just displays what it reported. Nothing here is trusted by
  // the server - the limit is enforced again on every request.
  const usage = capability?.usage || null;
  const attemptsLeft = usage ? usage.remaining : null;
  const outOfAttempts = usage ? usage.remaining <= 0 : false;

  const resetsAt = usage?.resets_at
    ? new Date(usage.resets_at).toLocaleString(undefined, {
        weekday: "short", hour: "numeric", minute: "2-digit",
      })
    : null;

  const canTry = serviceUp && inputsReady && !outOfAttempts;

  // A try-on that fails is refunded by the backend, so once a job
  // reaches a terminal state the page asks for the real figure again
  // rather than assuming the attempt was spent.
  const jobStatus = job?.status;
  useEffect(() => {
    if (jobStatus === "done" || jobStatus === "failed") {
      refreshCapability();
    }
  }, [jobStatus, refreshCapability]);

  // ---------------- photo ----------------

  const choosePhoto = () => fileInput.current && fileInput.current.click();

  const uploadPhoto = async (event) => {
    const file = event.target.files && event.target.files[0];
    if (fileInput.current) fileInput.current.value = "";
    if (!file) return;
    const headers = authHeaders();
    if (!headers) return navigate("/login");

    setPhotoProblems([]);
    setError("");

    if (!file.type.startsWith("image/")) {
      setPhotoProblems(["Please choose a photo (JPEG, PNG or WebP)."]);
      return;
    }
    const limit = (capability?.max_upload_mb || 8) * 1024 * 1024;
    if (file.size > limit) {
      setPhotoProblems([`That photo is larger than ${capability?.max_upload_mb || 8} MB. Please choose a smaller copy.`]);
      return;
    }

    setLocalPreview(URL.createObjectURL(file));
    setUploading(true);
    const form = new FormData();
    form.append("image", file);
    try {
      const res = await axios.post(`${API_URL}/api/tryon/photo`, form, { headers });
      if (!alive.current) return;
      setPhotoUrl(res.data.photo_url);
      setJob(null);
    } catch (err) {
      if (!alive.current) return;
      const problems = err?.response?.data?.problems;
      if (problems && problems.length) setPhotoProblems(problems);
      else setError(friendlyError(err, "Couldn't upload that photo. Please try again."));
    } finally {
      if (alive.current) {
        setUploading(false);
        setLocalPreview("");
      }
    }
  };

  const removePhoto = async () => {
    const headers = authHeaders();
    if (!headers) return navigate("/login");
    try {
      await axios.delete(`${API_URL}/api/tryon/photo`, { headers });
      setPhotoUrl("");
      setJob(null);
    } catch (err) {
      setError(friendlyError(err, "Couldn't remove your photo. Please try again."));
    }
  };

  // ---------------- generation ----------------

  const poll = useCallback((jobId, delay, startedAt) => {
    pollTimer.current = setTimeout(async () => {
      if (!alive.current) return;
      if (Date.now() - startedAt > CLIENT_TIMEOUT_MS) {
        setBusy(false);
        setError("This is taking much longer than usual. Please try again in a few minutes.");
        return;
      }
      const headers = authHeaders();
      if (!headers) return;
      try {
        const res = await axios.get(`${API_URL}/api/tryon/status/${jobId}`, { headers });
        if (!alive.current) return;
        const current = res.data.job;
        setJob(current);
        if (current.status === "done") {
          setBusy(false);
          setShowOriginal(false);
          loadHistory();
          return;
        }
        if (current.status === "failed") {
          setBusy(false);
          setError(current.error || "The try-on couldn't be completed. Please try again.");
          if (PROVIDER_ERROR_CODES.has(current.error_code)) {
            setCanRetry(true);
            refreshCapability();
          }
          return;
        }
        poll(jobId, Math.min(delay * 1.5, MAX_POLL_MS), startedAt);
      } catch (err) {
        if (!alive.current) return;
        setBusy(false);
        setError(friendlyError(err, "Lost contact with the server while creating your look."));
      }
    }, delay);
  }, [loadHistory, refreshCapability]);

  // `afterCheck` is set only by retry(), which has just confirmed with
  // the backend that a provider is available.
  const startTryOn = async (options) => {
    const afterCheck = Boolean(options && options.afterCheck === true);
    if (!(afterCheck ? inputsReady : canTry)) return;
    if (submitting.current) return;
    const headers = authHeaders();
    if (!headers) return navigate("/login");
    submitting.current = true;
    if (pollTimer.current) clearTimeout(pollTimer.current);

    setError("");
    setCanRetry(false);
    setJob(null);
    setBesides([]);
    setBusy(true);

    // Shoes/accessories from a recommended outfit travel along so they
    // can be shown beside the result - the backend never "wears" them.
    const extras = (incoming.itemIds || []).filter((id) => {
      const item = garments.find((g) => g._id === id);
      return item && item.tryon.shown_beside;
    });

    try {
      const res = await axios.post(
        `${API_URL}/api/tryon/generate`,
        {
          item_ids: [...selected, ...extras],
          source: incoming.source || "manual",
          occasion: incoming.occasion || "",
          label: incoming.label || "",
        },
        { headers }
      );
      // The response carries the count AFTER this attempt, so the
      // figure on screen drops immediately rather than after a poll.
      if (res.data.usage) {
        setCapability((current) => (current ? { ...current, usage: res.data.usage } : current));
      }
      setBesides(res.data.not_applied || []);
      setJob({ job_id: res.data.job_id, status: "pending", progress: "", step: 0, total_steps: res.data.total_steps });
      poll(res.data.job_id, FIRST_POLL_MS, Date.now());
    } catch (err) {
      setBusy(false);
      setError(friendlyError(err, "Couldn't start the try-on. Please try again."));
      if (err?.response?.status === 503) {
        setCanRetry(true);
        refreshCapability();
      }
      // 429 = the day's attempts are gone. Not something to retry, so
      // no retry button - just the real figure back from the server.
      if (err?.response?.status === 429) {
        setCanRetry(false);
        if (err.response.data?.usage) {
          setCapability((current) => (
            current ? { ...current, usage: err.response.data.usage } : current
          ));
        }
      }
    } finally {
      submitting.current = false;
    }
  };

  // Retry = ask whether a provider is usable, then (only if one is)
  // start ONE new try-on. The button is disabled while this runs, so a
  // double click can't submit twice.
  const retry = async () => {
    if (checking || busy || submitting.current) return;
    submitting.current = true;
    setChecking(true);
    const cap = await refreshCapability();
    submitting.current = false;
    if (!alive.current) return;
    setChecking(false);
    if (cap && cap.available) {
      startTryOn({ afterCheck: true });
    } else if (cap) {
      setError(cap.message);
    }
  };

  const checkAgain = async () => {
    if (checking) return;
    setChecking(true);
    await refreshCapability();
    if (alive.current) setChecking(false);
  };

  const tryAnother = () => {
    setJob(null);
    setBesides([]);
    setSelected([]);
    setError("");
    setCanRetry(false);
    const picker = document.getElementById("tryon-step-2");
    if (picker && picker.scrollIntoView) picker.scrollIntoView({ behavior: "smooth" });
  };

  const saveResult = async (entry) => {
    const url = assetUrl(entry.image_url);
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error("download failed");
      const blob = await res.blob();
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `my-virtual-look-${(entry.job_id || "").slice(0, 8)}.png`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    } catch (err) {
      window.open(url, "_blank", "noopener");
    }
  };

  const deleteResult = async (jobId) => {
    const headers = authHeaders();
    if (!headers) return navigate("/login");
    try {
      await axios.delete(`${API_URL}/api/tryon/result/${jobId}`, { headers });
      setHistory((list) => list.filter((entry) => entry.job_id !== jobId));
      if (job && job.job_id === jobId) setJob(null);
    } catch (err) {
      setError(friendlyError(err, "Couldn't delete that look. Please try again."));
    }
  };

  // ---------------- render ----------------

  const header = (
    <PageHeader title="Virtual Try-On" subtitle="See how your wardrobe looks on you." sparkle />
  );

  if (!loaded) {
    return (
      <Layout>
        {header}
        <div className="aw-progress"><span className="aw-spinner" /> Loading…</div>
      </Layout>
    );
  }

  // Only "nothing is configured" hides the page. A provider that is
  // merely busy or out of quota leaves the page usable (photo, garment
  // choice, recent try-ons) with a banner explaining the wait.
  const notConfigured = capability && !capability.available
    && (capability.status === "not_configured" || !capability.status);

  if (notConfigured) {
    const missing = capability.missing_configuration || [];
    return (
      <Layout>
        {header}
        <section className="aw-panel tryon-unconfigured" data-testid="tryon-not-configured">
          <h3>Virtual Try-On is not configured yet.</h3>
          <p>
            Trying clothes on your photo needs an AI try-on service connected to this app.
            Until it is, everything else in AI Wardrobe works as normal.
          </p>
          {missing.length > 0 && (
            <div className="aw-note">
              <strong>For whoever runs this server - still missing:</strong>
              <ul>
                {missing.map((name) => <li key={name}><code>{name}</code></li>)}
              </ul>
              Add these to the backend's <code>.env</code> and restart it.
            </div>
          )}
        </section>
      </Layout>
    );
  }

  const result = job && job.status === "done" && job.image_url ? job : null;

  return (
    <Layout>
      {header}

      {capability && capability.status && capability.status !== "not_configured" && (
        <div
          className={`tryon-status tryon-status-${capability.status}`}
          data-testid="tryon-status"
          role={capability.available ? "status" : "alert"}
        >
          <span className="tryon-status-dot" aria-hidden="true" />
          <div>
            <p>{capability.message}</p>
            {!capability.available && capability.reason && <p className="aw-hint">{capability.reason}</p>}
          </div>
          {!capability.available && (
            <button type="button" className="aw-btn aw-btn-soft aw-btn-sm" onClick={checkAgain} disabled={checking}>
              {checking ? "Checking…" : "Check again"}
            </button>
          )}
        </div>
      )}
      {incoming.label && (
        <div className="aw-note">
          Trying on <strong>{incoming.label}</strong>
          {incoming.source === "recommendation" ? " from your recommendations" : ""} - it's already selected below.
        </div>
      )}
      {incomingNotes.map((note) => <div key={note} className="aw-note">{note}</div>)}
      {error && (
        <div className="aw-alert" role="alert">
          {capability && !capability.available && capability.message && error.startsWith(capability.message)
            ? "Your last try-on couldn't be completed."
            : error}
          {canRetry && (
            <button
              type="button"
              className="aw-btn aw-btn-soft aw-btn-sm tryon-retry"
              onClick={retry}
              disabled={checking || busy}
            >
              {checking ? "Checking…" : "Retry"}
            </button>
          )}
        </div>
      )}

      <div className="tryon-steps">
        {/* 1. PHOTO */}
        <section className="aw-panel tryon-step" aria-labelledby="tryon-step-1-title">
          <h3 id="tryon-step-1-title"><span className="tryon-num">1</span> Your Photo</h3>

          {photoUrl || localPreview ? (
            <div className="tryon-photo">
              <img src={localPreview || assetUrl(photoUrl)} alt="You, for the try-on" data-testid="photo-preview" />
              <div className="aw-actions-row">
                <button type="button" className="aw-btn aw-btn-soft aw-btn-sm" onClick={choosePhoto} disabled={uploading || busy}>
                  Replace
                </button>
                <button type="button" className="aw-btn aw-btn-soft aw-btn-sm" onClick={removePhoto} disabled={uploading || busy || !photoUrl}>
                  Remove
                </button>
              </div>
              {uploading && <div className="aw-progress"><span className="aw-spinner" /> Checking your photo…</div>}
            </div>
          ) : (
            <button type="button" className="tryon-drop" onClick={choosePhoto} disabled={uploading}>
              <span className="tryon-drop-icon">＋</span>
              <span>Upload Photo</span>
              <small>JPEG, PNG or WebP, up to {capability?.max_upload_mb || 8} MB</small>
            </button>
          )}

          <input
            ref={fileInput}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={uploadPhoto}
            style={{ display: "none" }}
            data-testid="photo-input"
            aria-label="Upload your photo"
          />

          {photoProblems.length > 0 && (
            <div className="aw-alert" role="alert">
              <strong>That photo won't work:</strong>
              <ul>{photoProblems.map((p) => <li key={p}>{p}</li>)}</ul>
            </div>
          )}

          <div className="tryon-tips">
            <p>Works best with:</p>
            <ul>
              {(capability?.photo_guidance || []).map((line) => <li key={line}>{line}</li>)}
            </ul>
            <p className="aw-hint">Your photo is private to your account. Remove it any time.</p>
          </div>
        </section>

        {/* 2. GARMENT */}
        <section className="aw-panel tryon-step" id="tryon-step-2" aria-labelledby="tryon-step-2-title">
          <h3 id="tryon-step-2-title"><span className="tryon-num">2</span> Choose an item</h3>
          <p className="aw-hint" style={{ marginTop: -4 }}>
            {maxGarments > 1
              ? "Pick one item, or build a look: a top, a bottom and a jacket - or a single dress."
              : "Pick one item from your wardrobe."}
          </p>

          {garments.length === 0 ? (
            <div className="aw-empty tryon-empty">
              <p>Your wardrobe is empty.</p>
              <button type="button" className="aw-btn aw-btn-sm" onClick={() => navigate("/wardrobe")}>Add clothes</button>
            </div>
          ) : wearable.length === 0 ? (
            <p className="aw-hint">None of your items can be tried on yet - see below for why.</p>
          ) : (
            SLOT_GROUPS.map(({ slot, label }) => {
              const items = wearable.filter((g) => g.tryon.slot === slot);
              if (!items.length) return null;
              return (
                <div key={slot} className="tryon-group">
                  <p className="aw-label">{label}</p>
                  <div className="tryon-items">
                    {items.map((item) => {
                      const on = selected.includes(item._id);
                      return (
                        <button
                          type="button"
                          key={item._id}
                          className={`tryon-item ${on ? "on" : ""}`}
                          aria-pressed={on}
                          onClick={() => setSelected((cur) => applySelection(cur, item, garments, maxGarments))}
                          disabled={busy}
                          title={item.display_name}
                        >
                          <img src={assetUrl(item.image_path)} alt={item.display_name} loading="lazy" />
                          <span>{item.display_name}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })
          )}

          {unavailable.length > 0 && (
            <details className="tryon-unavailable">
              <summary>Not available for try-on ({unavailable.length})</summary>
              <ul>
                {unavailable.map((item) => (
                  <li key={item._id}>
                    <img src={assetUrl(item.image_path)} alt="" />
                    <div>
                      <strong>{item.display_name}</strong>
                      <span>{item.tryon.reason}</span>
                    </div>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </section>

        {/* 3. TRY ON */}
        <section className="aw-panel tryon-step" aria-labelledby="tryon-step-3-title">
          <h3 id="tryon-step-3-title"><span className="tryon-num">3</span> Try It On</h3>

          {selectedItems.length > 0 ? (
            <div className="tryon-selected">
              {selectedItems.map((item) => (
                <div key={item._id} className="tryon-chip">
                  <img src={assetUrl(item.image_path)} alt="" />
                  <span>{item.display_name}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="aw-hint">
              {!photoUrl ? "Add your photo, then choose an item." : "Choose an item to try on."}
            </p>
          )}

          {usage && (
            <p className="aw-hint tryon-attempts" aria-live="polite">
              {attemptsLeft} of {usage.limit} attempts remaining today
            </p>
          )}

          <button type="button" className="aw-btn tryon-go" onClick={startTryOn} disabled={!canTry}>
            {busy ? "Creating…" : "Try On"}
          </button>

          {outOfAttempts && (
            <div className="tryon-status tryon-status-unavailable" role="status">
              <div>
                <p>
                  You've reached your daily Virtual Try-On limit of {usage.limit}{" "}
                  attempts. Your attempts will reset tomorrow.
                </p>
                {resetsAt && <p className="aw-hint">Resets {resetsAt}.</p>}
              </div>
            </div>
          )}
          {capability && !serviceUp && (
            <p className="aw-hint">Try On is paused until a try-on service is available.</p>
          )}

          {busy && (
            <div className="tryon-loading" role="status" aria-live="polite">
              <div className="tryon-orbit" aria-hidden="true" />
              <p className="tryon-loading-title">Creating your virtual look...</p>
              <p className="aw-hint">
                {job?.total_steps > 1 && job?.step
                  ? `Garment ${job.step} of ${job.total_steps}. `
                  : ""}
                This usually takes under a minute. You can keep browsing this page.
              </p>
            </div>
          )}
        </section>
      </div>

      {/* 4. RESULT */}
      {result && (
        <section className="aw-panel tryon-result" aria-labelledby="tryon-result-title" data-testid="tryon-result">
          <h2 id="tryon-result-title" className="aw-section-title" style={{ marginTop: 0 }}>Your Virtual Look</h2>
          <div className="tryon-result-body">
            <figure>
              <img src={assetUrl(showOriginal ? photoUrl : result.image_url)} alt={showOriginal ? "Your original photo" : "Your virtual look"} />
              <figcaption className="aw-hint">{showOriginal ? "Original photo" : "AI-generated preview"}</figcaption>
              {result.notice && <p className="aw-hint" data-testid="tryon-notice">{result.notice}</p>}
            </figure>
            <div className="tryon-result-side">
              {besides.length > 0 && (
                <div>
                  <p className="aw-label">Goes with</p>
                  <div className="tryon-selected">
                    {besides.map((entry) => (
                      <div key={entry.item_id} className="tryon-chip">
                        <img src={assetUrl(entry.image_url)} alt="" />
                        <span>{entry.category}</span>
                      </div>
                    ))}
                  </div>
                  <p className="aw-hint">Shoes and accessories are shown alongside - the try-on can't put them on.</p>
                </div>
              )}
              <div className="tryon-result-actions">
                <button type="button" className="aw-btn" onClick={() => saveResult(result)}>Save Result</button>
                <button type="button" className="aw-btn aw-btn-ghost" onClick={tryAnother}>Try Another</button>
                <button type="button" className="aw-btn aw-btn-soft aw-btn-sm" onClick={() => setShowOriginal((v) => !v)}>
                  {showOriginal ? "Show my look" : "Compare with original"}
                </button>
                <button type="button" className="aw-btn aw-btn-soft aw-btn-sm" onClick={() => deleteResult(result.job_id)}>Delete</button>
              </div>
              <p className="aw-hint">Kept in Recent Try-Ons on every device you sign in to.</p>
            </div>
          </div>
        </section>
      )}

      {/* 5. RECENT */}
      {history.length > 0 && (
        <section>
          <h2 className="aw-section-title">Recent Try-Ons</h2>
          <div className="tryon-history">
            {history.map((entry) => (
              <div key={entry.job_id} className="aw-card tryon-history-card">
                <button type="button" onClick={() => { setJob(entry); setBesides(entry.not_applied || []); setShowOriginal(false); }}>
                  <img src={assetUrl(entry.image_url)} alt={entry.label || "Earlier virtual look"} loading="lazy" />
                </button>
                <div className="tryon-history-meta">
                  <span>{entry.label || (entry.worn || []).map((w) => w.category).join(" + ") || "Virtual look"}</span>
                  <button type="button" className="aw-link" onClick={() => deleteResult(entry.job_id)}>Delete</button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </Layout>
  );
}

export default VirtualTryOn;

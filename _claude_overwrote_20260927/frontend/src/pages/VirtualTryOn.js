import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import axios from "axios";

import Layout from "../components/Layout";
import { API_URL, assetUrl } from "../config";

// Polled rather than held open: a generation takes 20-60 seconds, and
// a full outfit is two passes, so the backend answers straight away
// with a job id and this asks how it is going. See
// backend/virtual_tryon.py for why the model runs elsewhere.
const POLL_MS = 1500;

// Roles the model can actually wear, in the order they read best in
// the picker. Footwear and accessories are deliberately absent from
// this list and handled separately - no current try-on model can put
// shoes or jewellery on a person, and pretending otherwise would be
// the dishonest option.
const WEARABLE_GROUPS = [
  { key: "one_piece", label: "Dresses, sarees and gowns" },
  { key: "top", label: "Tops" },
  { key: "bottom", label: "Bottoms" },
  { key: "outerwear", label: "Jackets and coats" },
];

// Mirrors backend/garment_taxonomy.py closely enough to group the
// picker. The backend remains the authority - it re-plans the outfit
// and refuses anything impossible - so a disagreement here shows up
// as a clear message, never as a wrong image.
const ONE_PIECE = /saree|lehenga|gown|dress|anarkali|jumpsuit|sherwani/i;
const BOTTOM = /jean|trouser|pant|skirt|short|palazzo|salwar|legging|dhoti|churidar/i;
const OUTERWEAR = /jacket|coat|blazer|cardigan|sweater|hoodie|shrug|nehru/i;
const FOOTWEAR = /shoe|sneaker|sandal|heel|boot|mojari|flip|slipper|flat/i;
const ACCESSORY = /watch|bag|belt|scarf|dupatta|jewel|earring|necklace|cap|hat|sunglass/i;

function groupFor(category) {
  const name = category || "";

  if (FOOTWEAR.test(name)) return "footwear";
  if (ACCESSORY.test(name)) return "accessory";
  if (ONE_PIECE.test(name)) return "one_piece";
  if (OUTERWEAR.test(name)) return "outerwear";
  if (BOTTOM.test(name)) return "bottom";

  return "top";
}

function VirtualTryOn() {
  const navigate = useNavigate();
  const location = useLocation();

  const [capability, setCapability] = useState(null);
  const [wardrobe, setWardrobe] = useState([]);
  const [selected, setSelected] = useState([]);

  const [photoUrl, setPhotoUrl] = useState("");
  const [uploading, setUploading] = useState(false);
  const [photoProblems, setPhotoProblems] = useState([]);

  const [job, setJob] = useState(null);
  const [notApplied, setNotApplied] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showOriginal, setShowOriginal] = useState(false);

  const [history, setHistory] = useState([]);

  // Where the request came from, so the saved result can say "the
  // Party outfit the AI suggested" rather than just "a try-on".
  const incoming = location.state || {};

  const pollTimer = useRef(null);
  const fileInput = useRef(null);

  const authHeader = useCallback(() => {
    const token = localStorage.getItem("token");

    if (!token) {
      navigate("/login");
      return null;
    }

    return { Authorization: `Bearer ${token}` };
  }, [navigate]);

  const loadHistory = useCallback(async () => {
    const headers = authHeader();
    if (!headers) return;

    try {
      const response = await axios.get(`${API_URL}/api/tryon/results`, {
        headers,
      });
      setHistory(response.data.results || []);
    } catch (problem) {
      // A failed history load must not stop someone generating a new
      // try-on, so this is deliberately silent.
    }
  }, [authHeader]);

  useEffect(() => {
    const headers = authHeader();
    if (!headers) return;

    let cancelled = false;

    (async () => {
      try {
        const [capabilityResponse, wardrobeResponse] = await Promise.all([
          axios.get(`${API_URL}/api/tryon/capability`, { headers }),
          axios.get(`${API_URL}/api/wardrobe`, { headers }),
        ]);

        if (cancelled) return;

        setCapability(capabilityResponse.data);
        setPhotoUrl(capabilityResponse.data.photo_url || "");
        setWardrobe(wardrobeResponse.data.items || []);
      } catch (problem) {
        if (!cancelled) {
          setError(
            "Couldn't load the try-on page. Check the backend is running."
          );
        }
      }
    })();

    loadHistory();

    return () => {
      cancelled = true;
    };
  }, [authHeader, loadHistory]);

  // An outfit handed over from the Recommend or Trip page. Selecting
  // it automatically is the entire point of that button: the user
  // should never have to pick the same clothes twice.
  useEffect(() => {
    if (incoming.itemIds && incoming.itemIds.length) {
      setSelected(incoming.itemIds);
    }
  }, [incoming.itemIds]);

  useEffect(
    () => () => {
      if (pollTimer.current) clearTimeout(pollTimer.current);
    },
    []
  );

  const pollJob = useCallback(
    async (jobId) => {
      const headers = authHeader();
      if (!headers) return;

      try {
        const response = await axios.get(
          `${API_URL}/api/tryon/status/${jobId}`,
          { headers }
        );

        const current = response.data.job;

        setJob(current);

        if (current.status === "done") {
          setBusy(false);
          setShowOriginal(false);
          loadHistory();
          return;
        }

        if (current.status === "failed") {
          setBusy(false);
          setError(current.error || "The try-on didn't finish.");
          return;
        }

        pollTimer.current = setTimeout(() => pollJob(jobId), POLL_MS);
      } catch (problem) {
        setBusy(false);
        setError("Lost contact with the server while generating.");
      }
    },
    [authHeader, loadHistory]
  );

  const uploadPhoto = async (event) => {
    const file = event.target.files && event.target.files[0];
    if (!file) return;

    const headers = authHeader();
    if (!headers) return;

    setUploading(true);
    setPhotoProblems([]);
    setError("");

    const form = new FormData();
    form.append("image", file);

    try {
      const response = await axios.post(`${API_URL}/api/tryon/photo`, form, {
        headers,
      });

      setPhotoUrl(response.data.photo_url);
    } catch (problem) {
      const data = (problem.response && problem.response.data) || {};

      // The backend checks the photo before storing it and returns
      // specific, fixable reasons - show those rather than a generic
      // failure.
      setPhotoProblems(data.problems || []);

      if (!data.problems) {
        setError(data.message || "Couldn't upload that photo.");
      }
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const removePhoto = async () => {
    const headers = authHeader();
    if (!headers) return;

    try {
      await axios.delete(`${API_URL}/api/tryon/photo`, { headers });
      setPhotoUrl("");
      setJob(null);
    } catch (problem) {
      setError("Couldn't remove your photo.");
    }
  };

  const toggleItem = (itemId) => {
    setSelected((current) =>
      current.includes(itemId)
        ? current.filter((value) => value !== itemId)
        : [...current, itemId]
    );
  };

  // Swapping one garment without rebuilding the outfit: pick another
  // item of the same kind and it replaces the current one.
  const chooseForGroup = (item) => {
    const group = groupFor(item.category);

    setSelected((current) => {
      const withoutGroup = current.filter((id) => {
        const existing = wardrobe.find((entry) => entry._id === id);
        return !existing || groupFor(existing.category) !== group;
      });

      return current.includes(item._id)
        ? withoutGroup
        : [...withoutGroup, item._id];
    });
  };

  const startTryOn = async () => {
    const headers = authHeader();
    if (!headers) return;

    setError("");
    setJob(null);
    setNotApplied([]);
    setBusy(true);

    try {
      const response = await axios.post(
        `${API_URL}/api/tryon/generate`,
        {
          item_ids: selected,
          source: incoming.source || "manual",
          occasion: incoming.occasion || "",
          label: incoming.label || "",
        },
        { headers }
      );

      setNotApplied(response.data.not_applied || []);

      setJob({
        job_id: response.data.job_id,
        status: "pending",
        progress: "Waking up the try-on service",
        total_steps: response.data.total_steps,
        step: 0,
      });

      pollJob(response.data.job_id);
    } catch (problem) {
      setBusy(false);
      const data = (problem.response && problem.response.data) || {};
      setError(data.message || "Couldn't start the try-on.");
    }
  };

  const deleteResult = async (jobId) => {
    const headers = authHeader();
    if (!headers) return;

    try {
      await axios.delete(`${API_URL}/api/tryon/result/${jobId}`, { headers });
      setHistory((current) => current.filter((entry) => entry.job_id !== jobId));

      if (job && job.job_id === jobId) setJob(null);
    } catch (problem) {
      setError("Couldn't delete that try-on.");
    }
  };

  const selectedItems = wardrobe.filter((item) =>
    selected.includes(item._id)
  );

  const unwearableSelected = selectedItems.filter((item) =>
    ["footwear", "accessory"].includes(groupFor(item.category))
  );

  const ready = photoUrl && selected.length > 0 && !busy;

  // ==========================================================

  if (capability && !capability.available) {
    return (
      <Layout>
        <div className="page-header">
          <h1 className="page-title">Virtual Try-On</h1>
          <p className="page-subtitle">
            See your own clothes on your own photo.
          </p>
        </div>

        <div className="panel" style={{ maxWidth: "620px" }}>
          <h3 style={{ marginTop: 0 }}>Not set up on this server yet</h3>
          <p style={{ color: "#8a7a6d", lineHeight: 1.6 }}>
            Virtual try-on needs a GPU, so the model runs on a hosted
            service that has to be configured once by whoever runs this
            backend. Everything else in Wardrobe-AI works normally in the
            meantime.
          </p>
          <p style={{ color: "#8a7a6d", fontSize: "13px" }}>
            Setup instructions are in <code>spaces/tryon/README.md</code>.
          </p>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="page-header">
        <div>
          <h1 className="page-title">Virtual Try-On</h1>
          <p className="page-subtitle">
            See your own clothes on your own photo before you wear them.
          </p>
        </div>
      </div>

      {incoming.label && (
        <div
          className="panel"
          style={{ marginBottom: "16px", borderLeft: "3px solid #c9a227" }}
        >
          <strong>From your recommendations:</strong> {incoming.label}
          {incoming.occasion ? ` (${incoming.occasion})` : ""}
          <span style={{ color: "#8a7a6d" }}>
            {" "}
            — already selected below.
          </span>
        </div>
      )}

      {error && <p className="error">{error}</p>}

      <div className="panel-grid">
        {/* ---------------- A. YOUR PHOTO ---------------- */}
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>1. Your photo</h3>

          {photoUrl ? (
            <div>
              <img
                src={assetUrl(photoUrl)}
                alt="You"
                style={{
                  width: "100%",
                  maxWidth: "240px",
                  borderRadius: "8px",
                  display: "block",
                  marginBottom: "10px",
                }}
              />

              <div style={{ display: "flex", gap: "8px" }}>
                <button
                  className="btn"
                  onClick={() => fileInput.current && fileInput.current.click()}
                  disabled={uploading}
                >
                  Replace
                </button>
                <button className="btn" onClick={removePhoto}>
                  Remove
                </button>
              </div>
            </div>
          ) : (
            <div>
              <button
                className="btn btn-primary"
                onClick={() => fileInput.current && fileInput.current.click()}
                disabled={uploading}
              >
                {uploading ? "Uploading…" : "Upload a photo"}
              </button>
            </div>
          )}

          <input
            ref={fileInput}
            type="file"
            accept="image/*"
            onChange={uploadPhoto}
            style={{ display: "none" }}
          />

          {photoProblems.length > 0 && (
            <div
              style={{
                marginTop: "10px",
                padding: "10px",
                background: "#fdf3f3",
                borderRadius: "6px",
              }}
            >
              <strong style={{ fontSize: "13px" }}>
                That photo won't work:
              </strong>
              <ul style={{ margin: "6px 0 0", paddingLeft: "18px", fontSize: "13px" }}>
                {photoProblems.map((problem, index) => (
                  <li key={index}>{problem}</li>
                ))}
              </ul>
            </div>
          )}

          {capability && (
            <div style={{ marginTop: "14px" }}>
              <p
                style={{
                  fontSize: "12px",
                  color: "#8a7a6d",
                  marginBottom: "4px",
                }}
              >
                For the best result:
              </p>
              <ul
                style={{
                  margin: 0,
                  paddingLeft: "18px",
                  fontSize: "12px",
                  color: "#8a7a6d",
                  lineHeight: 1.6,
                }}
              >
                {capability.photo_guidance.map((line, index) => (
                  <li key={index}>{line}</li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* ---------------- B. CHOOSE CLOTHES ---------------- */}
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>2. Choose clothes</h3>

          {wardrobe.length === 0 ? (
            <p style={{ color: "#8a7a6d" }}>
              Your wardrobe is empty — add a few items first.
            </p>
          ) : (
            WEARABLE_GROUPS.map((group) => {
              const items = wardrobe.filter(
                (item) => groupFor(item.category) === group.key
              );

              if (items.length === 0) return null;

              return (
                <div key={group.key} style={{ marginBottom: "14px" }}>
                  <p className="field-label">{group.label}</p>

                  <div
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      gap: "8px",
                    }}
                  >
                    {items.map((item) => {
                      const isSelected = selected.includes(item._id);

                      return (
                        <button
                          key={item._id}
                          onClick={() => chooseForGroup(item)}
                          title={item.category}
                          style={{
                            border: isSelected
                              ? "2px solid #c9a227"
                              : "1px solid #e5ded5",
                            borderRadius: "8px",
                            padding: "2px",
                            background: "#fff",
                            cursor: "pointer",
                            lineHeight: 0,
                          }}
                        >
                          <img
                            src={assetUrl(item.image_path)}
                            alt={item.category}
                            style={{
                              width: "58px",
                              height: "72px",
                              objectFit: "cover",
                              borderRadius: "6px",
                            }}
                          />
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })
          )}

          <p
            style={{
              fontSize: "12px",
              color: "#8a7a6d",
              marginTop: "10px",
              lineHeight: 1.6,
            }}
          >
            Picking another item of the same kind swaps it, so you can
            change one garment without starting again. Shoes and
            accessories aren't shown here — no try-on model can put
            them on a person yet.
          </p>
        </div>

        {/* ---------------- C. GENERATE ---------------- */}
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>3. Try it on</h3>

          {selectedItems.length > 0 && (
            <div
              style={{
                display: "flex",
                gap: "6px",
                flexWrap: "wrap",
                marginBottom: "12px",
              }}
            >
              {selectedItems.map((item) => (
                <img
                  key={item._id}
                  src={assetUrl(item.image_path)}
                  alt={item.category}
                  title={item.category}
                  style={{
                    width: "44px",
                    height: "56px",
                    objectFit: "cover",
                    borderRadius: "6px",
                    opacity: unwearableSelected.includes(item) ? 0.45 : 1,
                  }}
                />
              ))}
            </div>
          )}

          <button
            className="btn btn-primary"
            onClick={startTryOn}
            disabled={!ready}
          >
            {busy ? "Generating…" : "Try On Outfit"}
          </button>

          {!photoUrl && (
            <p style={{ fontSize: "12px", color: "#8a7a6d", marginTop: "8px" }}>
              Upload a photo of yourself first.
            </p>
          )}

          {photoUrl && selected.length === 0 && (
            <p style={{ fontSize: "12px", color: "#8a7a6d", marginTop: "8px" }}>
              Pick at least one garment.
            </p>
          )}

          {/* Progress. Says which garment and which pass, because a
              full outfit is two generations and silence for a minute
              reads as a hung app. */}
          {busy && job && (
            <div style={{ marginTop: "14px" }}>
              <p style={{ fontSize: "13px", marginBottom: "6px" }}>
                {job.progress || "Working…"}
              </p>

              {job.total_steps > 1 && (
                <p style={{ fontSize: "12px", color: "#8a7a6d" }}>
                  A full outfit takes {job.total_steps} passes — one garment
                  at a time. This is normal.
                </p>
              )}

              <div
                style={{
                  height: "6px",
                  background: "#f0ebe4",
                  borderRadius: "3px",
                  overflow: "hidden",
                  marginTop: "8px",
                }}
              >
                <div
                  style={{
                    height: "100%",
                    width: `${
                      job.total_steps
                        ? Math.max(
                            8,
                            (job.step / job.total_steps) * 100
                          )
                        : 8
                    }%`,
                    background: "#c9a227",
                    transition: "width .4s",
                  }}
                />
              </div>
            </div>
          )}

          {notApplied.length > 0 && (
            <div style={{ marginTop: "14px" }}>
              <p className="field-label">Shown, but not worn</p>

              <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
                {notApplied.map((entry) => (
                  <img
                    key={entry.item_id}
                    src={assetUrl(entry.image_url)}
                    alt={entry.category}
                    title={`${entry.category} — ${entry.reason}`}
                    style={{
                      width: "44px",
                      height: "56px",
                      objectFit: "cover",
                      borderRadius: "6px",
                      border: "1px dashed #d8cfc4",
                    }}
                  />
                ))}
              </div>

              <p
                style={{
                  fontSize: "12px",
                  color: "#8a7a6d",
                  marginTop: "6px",
                  lineHeight: 1.5,
                }}
              >
                {notApplied[0].reason}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* ---------------- D. RESULT ---------------- */}
      {job && job.status === "done" && job.image_url && (
        <div style={{ marginTop: "22px" }}>
          <h2 className="section-title">Your try-on</h2>

          <div className="panel" style={{ maxWidth: "760px" }}>
            <div style={{ display: "flex", gap: "16px", flexWrap: "wrap" }}>
              <div>
                <p className="field-label">
                  {showOriginal ? "Your photo" : "With the outfit on"}
                </p>
                <img
                  src={assetUrl(showOriginal ? photoUrl : job.image_url)}
                  alt={showOriginal ? "Your photo" : "Try-on result"}
                  style={{
                    width: "100%",
                    maxWidth: "320px",
                    borderRadius: "10px",
                    display: "block",
                  }}
                />
              </div>

              <div style={{ flex: 1, minWidth: "220px" }}>
                <div
                  style={{
                    display: "flex",
                    gap: "8px",
                    flexWrap: "wrap",
                    marginBottom: "12px",
                  }}
                >
                  <button
                    className="btn"
                    onMouseDown={() => setShowOriginal(true)}
                    onMouseUp={() => setShowOriginal(false)}
                    onMouseLeave={() => setShowOriginal(false)}
                    onClick={() => setShowOriginal((value) => !value)}
                  >
                    {showOriginal ? "Show result" : "Compare with original"}
                  </button>

                  <button className="btn" onClick={startTryOn}>
                    Regenerate
                  </button>

                  <a
                    className="btn"
                    href={assetUrl(job.image_url)}
                    download={`tryon-${job.job_id}.png`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Download
                  </a>

                  <button
                    className="btn"
                    onClick={() => deleteResult(job.job_id)}
                  >
                    Delete
                  </button>
                </div>

                <p style={{ fontSize: "12px", color: "#8a7a6d", lineHeight: 1.6 }}>
                  Saved to your account, so it's here when you log in from
                  another computer. Generated by {job.model} ({job.model_license}).
                </p>

                {job.passes > 1 && (
                  <p style={{ fontSize: "12px", color: "#8a7a6d" }}>
                    Built in {job.passes} passes, one garment at a time.
                  </p>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ---------------- E. EARLIER TRY-ONS ---------------- */}
      {history.length > 0 && (
        <div style={{ marginTop: "22px" }}>
          <h2 className="section-title">Earlier try-ons</h2>

          <div style={{ display: "flex", gap: "12px", flexWrap: "wrap" }}>
            {history.map((entry) => (
              <div
                key={entry.job_id}
                className="panel"
                style={{ width: "180px", padding: "10px" }}
              >
                <img
                  src={assetUrl(entry.image_url)}
                  alt="Earlier try-on"
                  style={{
                    width: "100%",
                    borderRadius: "8px",
                    display: "block",
                    marginBottom: "8px",
                  }}
                />

                {entry.occasion && (
                  <span className="badge">{entry.occasion}</span>
                )}

                <div style={{ display: "flex", gap: "6px", marginTop: "8px" }}>
                  <button
                    className="btn"
                    style={{ fontSize: "12px", padding: "4px 8px" }}
                    onClick={() => {
                      setJob(entry);
                      setShowOriginal(false);
                      window.scrollTo({ top: 0, behavior: "smooth" });
                    }}
                  >
                    View
                  </button>
                  <button
                    className="btn"
                    style={{ fontSize: "12px", padding: "4px 8px" }}
                    onClick={() => deleteResult(entry.job_id)}
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </Layout>
  );
}

export default VirtualTryOn;

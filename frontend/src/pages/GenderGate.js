import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import "../App.css";

// =========================================================
// GENDER GATE
//
// Shown once, before login/signup, to a browser that hasn't
// picked a wardrobe preference yet. The choice is saved to
// localStorage immediately (so it survives the trip through
// Register.js -> POST /api/register -> stored on the user
// document) and is used ONLY to trim which categories show up
// in the wardrobe's "Add Item" dropdown - see Wardrobe.js. It
// never limits or changes clothing classification or outfit
// recommendations themselves; those are driven by each item's
// own category/occasion metadata, not by gender.
//
// A returning visitor who already has a token (still logged in)
// or has already made this choice before skips straight past it.
// =========================================================

function GenderGate() {
  const navigate = useNavigate();

  useEffect(() => {
    if (localStorage.getItem("token")) {
      navigate("/dashboard", { replace: true });
      return;
    }

    if (localStorage.getItem("genderPreference")) {
      navigate("/login", { replace: true });
    }
  }, [navigate]);

  const choose = (value) => {
    localStorage.setItem("genderPreference", value);
    navigate("/login");
  };

  const options = [
    {
      value: "Female",
      label: "Women",
      blurb: "Western basics, dresses, sarees & lehengas",
      icon: "👗"
    },
    {
      value: "Male",
      label: "Men",
      blurb: "Shirts, t-shirts, pants & jackets",
      icon: "👔"
    }
  ];

  return (
    <div className="auth-shell">
      <div className="auth-hero">
        <div className="auth-hero-brand">
          <span role="img" aria-label="hanger">👚</span> WardrobeAI
          <span className="tagline">Your Style · Your Wardrobe · Smarter Choices</span>
        </div>

        <div>
          <h1>
            Let's Set Up
            <br />
            Your <em>Wardrobe</em>
          </h1>

          <p className="subtitle">
            One quick question so we can show you the right
            categories from the start. You can change this later.
          </p>
        </div>

        <p className="auth-hero-quote">
          "Small choices create big style stories."
        </p>
      </div>

      <div className="auth-panel">
        <div className="auth-card">
          <h2>Who's shopping their closet?</h2>
          <p className="auth-subtitle">
            This only trims the category list you'll see when
            adding clothes - it never limits how your outfits get
            recommended.
          </p>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: "14px",
              margin: "22px 0 18px"
            }}
          >
            {options.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => choose(opt.value)}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  gap: "8px",
                  padding: "26px 14px",
                  borderRadius: "16px",
                  border: "2px solid #ece1d6",
                  background: "#fffaf5",
                  cursor: "pointer",
                  fontFamily: "inherit"
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = "#c1694f";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = "#ece1d6";
                }}
              >
                <span style={{ fontSize: "34px" }}>{opt.icon}</span>
                <span style={{ fontWeight: 700, fontSize: "16px" }}>
                  {opt.label}
                </span>
                <span
                  style={{
                    fontSize: "12px",
                    color: "#8a7a6d",
                    textAlign: "center"
                  }}
                >
                  {opt.blurb}
                </span>
              </button>
            ))}
          </div>

          <button
            type="button"
            className="btn btn-secondary"
            style={{ width: "100%" }}
            onClick={() => choose("")}
          >
            Prefer not to say
          </button>

          <p
            style={{
              fontSize: "12px",
              color: "#8a7a6d",
              marginTop: "14px",
              textAlign: "center"
            }}
          >
            "Prefer not to say" just shows every category - nothing
            is hidden.
          </p>
        </div>
      </div>
    </div>
  );
}

export default GenderGate;

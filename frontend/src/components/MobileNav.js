import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { clearProfileCache } from "./PageHeader";
import { clearCategoryCache } from "../lib/categories";

// Phone navigation (shown below 760px, where the sidebar is hidden):
// a slim top bar + a bottom tab bar with the five main places, and a
// "More" sheet for everything else.
const TABS = [
  { to: "/dashboard", label: "Home", icon: "🏠" },
  { to: "/wardrobe", label: "Wardrobe", icon: "👚" },
  { to: "/style", label: "Style", icon: "✨" },
  { to: "/tryon", label: "Try-On", icon: "🪞" },
];
const MORE = [
  { to: "/recommend", label: "Outfit Ideas", icon: "💡" },
  { to: "/calendar", label: "Outfit Calendar", icon: "📅" },
  { to: "/similar", label: "Find Similar & Shop", icon: "🛍️" },
  { to: "/trip", label: "Trip Planner", icon: "🧳" },
  { to: "/profile", label: "Settings", icon: "⚙️" },
];

export default function MobileNav() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const [sheet, setSheet] = useState(false);
  const moreActive = MORE.some((m) => m.to === pathname);

  const logout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("gender");
    clearProfileCache();
    clearCategoryCache();
    navigate("/login");
  };

  return (
    <>
      <header className="m-topbar">
        <Link to="/dashboard" className="m-brand">👗 <span>AI Wardrobe</span></Link>
        <Link to="/profile" className="m-top-btn" aria-label="Settings">⚙️</Link>
      </header>

      <nav className="m-tabbar" aria-label="Main">
        {TABS.map((t) => (
          <Link key={t.to} to={t.to} className={pathname === t.to ? "on" : ""} onClick={() => setSheet(false)}>
            <span className="m-ico">{t.icon}</span>{t.label}
          </Link>
        ))}
        <button type="button" className={moreActive || sheet ? "on" : ""} onClick={() => setSheet((s) => !s)}
          aria-expanded={sheet}>
          <span className="m-ico">☰</span>More
        </button>
      </nav>

      {sheet && (
        <div className="m-sheet-wrap" onClick={() => setSheet(false)} role="presentation">
          <div className="m-sheet" role="dialog" aria-label="More" onClick={(e) => e.stopPropagation()}>
            <div className="m-grip" />
            {MORE.map((m) => (
              <Link key={m.to} to={m.to} className={pathname === m.to ? "on" : ""} onClick={() => setSheet(false)}>
                <span>{m.icon}</span>{m.label}
              </Link>
            ))}
            <button type="button" onClick={logout}><span>🚪</span>Log Out</button>
          </div>
        </div>
      )}
    </>
  );
}

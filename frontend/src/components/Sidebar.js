import { useNavigate, useLocation, Link } from "react-router-dom";
import "../App.css";

const NAV_ITEMS = [
  { to: "/dashboard", label: "Home", icon: "🏠" },
  { to: "/wardrobe", label: "My Wardrobe", icon: "👗" },
  { to: "/recommend", label: "Recommend Outfit", icon: "✨" },
  { to: "/trip", label: "Trip Planner", icon: "🧳" },
  { to: "/similar", label: "Similar Search", icon: "🔍" },
];

function Sidebar() {
  const navigate = useNavigate();
  const location = useLocation();

  const handleLogout = () => {
    localStorage.removeItem("token");
    navigate("/login");
  };

  return (
    <div className="sidebar">
      <div className="sidebar-brand">
        <span role="img" aria-label="hanger">
          👚
        </span>
        WardrobeAI
      </div>

      <nav className="sidebar-nav">
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.to}
            to={item.to}
            className={
              location.pathname === item.to ? "active" : ""
            }
          >
            <span className="icon">{item.icon}</span>
            {item.label}
          </Link>
        ))}
      </nav>

      <div className="sidebar-footer-card">
        "Good outfits build good days."
      </div>

      <button
        className="sidebar-logout"
        onClick={handleLogout}
      >
        ⎋ Logout
      </button>
    </div>
  );
}

export default Sidebar;

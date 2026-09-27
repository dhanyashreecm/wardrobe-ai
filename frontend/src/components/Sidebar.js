import { useNavigate, useLocation, Link } from "react-router-dom";
import {
  HangerIcon, HomeIcon, SparkleIcon, PlaneIcon, TryOnIcon, SearchIcon,
  GearIcon, LogoutIcon,
} from "./Icons";
import { clearProfileCache } from "./PageHeader";

const NAV_ITEMS = [
  { to: "/dashboard", label: "Home", Icon: HomeIcon },
  { to: "/wardrobe", label: "My Wardrobe", Icon: HangerIcon },
  { to: "/recommend", label: "Outfit Recommendations", Icon: SparkleIcon },
  { to: "/trip", label: "Trip Planner", Icon: PlaneIcon },
  { to: "/tryon", label: "Virtual Try-On", Icon: TryOnIcon },
  { to: "/similar", label: "Find Similar Clothes", Icon: SearchIcon },
];

function Sidebar() {
  const navigate = useNavigate();
  const location = useLocation();

  const handleLogout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("gender");
    clearProfileCache();
    navigate("/login");
  };

  return (
    <aside className="aw-sidebar">
      <Link to="/dashboard" className="aw-brand">
        <HangerIcon width={34} height={34} />
        <div>
          <div className="aw-brand-name">AI Wardrobe</div>
          <div className="aw-brand-tag">Dress Smarter. Live Better.</div>
        </div>
      </Link>

      <nav className="aw-nav">
        {NAV_ITEMS.map(({ to, label, Icon }) => (
          <Link
            key={to}
            to={to}
            className={location.pathname === to ? "active" : ""}
          >
            <Icon />
            {label}
          </Link>
        ))}
      </nav>

      <div className="aw-quote">
        <span className="leaf">❦</span>
        Good style
        <br />
        is a form of
        <br />
        self care ♡
      </div>

      <div className="aw-nav aw-nav-bottom">
        <Link
          to="/profile"
          className={location.pathname === "/profile" ? "active" : ""}
        >
          <GearIcon />
          Settings
        </Link>
        <button type="button" onClick={handleLogout}>
          <LogoutIcon width={19} height={19} />
          Log Out
        </button>
      </div>
    </aside>
  );
}

export default Sidebar;

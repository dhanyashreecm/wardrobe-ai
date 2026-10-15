import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { clearProfileCache } from "./PageHeader";
import { clearCategoryCache } from "../lib/categories";
import {
  HomeIcon, HangerIcon, TryOnIcon, MenuIcon, PlusIcon, SparkleIcon, CalendarIcon, SearchIcon,
  PlaneIcon, GearIcon, LogoutIcon, TrendIcon,
} from "./Icons";

// Phone navigation (below 760px, where the sidebar is hidden): a slim
// top bar and a thumb-friendly bottom tab bar - Home, Wardrobe, a big
// "+" in the middle to add clothes, Try-On, and More for the rest.
const LEFT = [
  { to: "/dashboard", label: "Home", Icon: HomeIcon },
  { to: "/wardrobe", label: "Wardrobe", Icon: HangerIcon },
];
const RIGHT = [
  { to: "/tryon", label: "Try-On", Icon: TryOnIcon },
];
const MORE = [
  { to: "/style", label: "Style & Trends", hint: "Outfit Studio and saved looks", Icon: TrendIcon },
  { to: "/recommend", label: "Outfit Ideas", hint: "What to wear today", Icon: SparkleIcon },
  { to: "/calendar", label: "Outfit Calendar", hint: "What you wore, and when", Icon: CalendarIcon },
  { to: "/similar", label: "Find Similar & Shop", hint: "Match a look you like", Icon: SearchIcon },
  { to: "/trip", label: "Trip Planner", hint: "Pack outfits for a trip", Icon: PlaneIcon },
  { to: "/profile", label: "Settings", hint: "Profile, account, server", Icon: GearIcon },
];

export default function MobileNav() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const [sheet, setSheet] = useState(false);
  const moreActive = MORE.some((m) => m.to === pathname);

  useEffect(() => { setSheet(false); }, [pathname]);

  const logout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("gender");
    clearProfileCache();
    clearCategoryCache();
    navigate("/login");
  };

  const tab = ({ to, label, Icon }) => (
    <Link key={to} to={to} className={pathname === to ? "on" : ""} aria-current={pathname === to ? "page" : undefined}>
      <span className="m-ico"><Icon width={23} height={23} /></span>{label}
    </Link>
  );

  return (
    <>
      <header className="m-topbar">
        <Link to="/dashboard" className="m-brand"><span className="m-logo" aria-hidden="true">W</span><span>Wardrobe AI</span></Link>
        <Link to="/profile" className="m-top-btn" aria-label="Settings"><GearIcon width={22} height={22} /></Link>
      </header>

      <nav className="m-tabbar" aria-label="Main">
        {LEFT.map(tab)}
        <button type="button" className="m-add" aria-label="Add clothes"
          onClick={() => navigate("/wardrobe", { state: { add: true } })}>
          <span><PlusIcon width={26} height={26} /></span>
        </button>
        {RIGHT.map(tab)}
        <button type="button" className={moreActive || sheet ? "on" : ""} onClick={() => setSheet((s) => !s)}
          aria-expanded={sheet}>
          <span className="m-ico"><MenuIcon width={23} height={23} /></span>More
        </button>
      </nav>

      {sheet && (
        <div className="m-sheet-wrap" onClick={() => setSheet(false)} role="presentation">
          <div className="m-sheet" role="dialog" aria-label="More" onClick={(e) => e.stopPropagation()}>
            <div className="m-grip" />
            {MORE.map(({ to, label, hint, Icon }) => (
              <Link key={to} to={to} className={pathname === to ? "on" : ""} onClick={() => setSheet(false)}>
                <span className="m-sheet-ico"><Icon width={22} height={22} /></span>
                <span className="m-sheet-text"><strong>{label}</strong><small>{hint}</small></span>
              </Link>
            ))}
            <button type="button" onClick={logout}>
              <span className="m-sheet-ico"><LogoutIcon width={22} height={22} /></span>
              <span className="m-sheet-text"><strong>Log out</strong></span>
            </button>
          </div>
        </div>
      )}
    </>
  );
}

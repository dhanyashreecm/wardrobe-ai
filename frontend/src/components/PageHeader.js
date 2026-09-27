import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { authGet } from "../lib/api";
import { assetUrl } from "../config";

// One profile fetch shared by every page header.
let profileCache = null;
let profilePromise = null;

export function clearProfileCache() {
  profileCache = null;
  profilePromise = null;
}

export function useProfile() {
  const [profile, setProfile] = useState(profileCache);
  useEffect(() => {
    if (profileCache) return;
    if (!profilePromise) {
      profilePromise = authGet("/api/user/profile")
        .then((data) => {
          profileCache = data.profile || data;
          return profileCache;
        })
        .catch(() => null);
    }
    profilePromise.then((value) => value && setProfile(value));
  }, []);
  return profile;
}

export function ProfileChip({ itemCount }) {
  const profile = useProfile();
  const name = profile?.name || "";
  const gender = profile?.gender || localStorage.getItem("gender") || "";
  const initial = (name || "?").trim().charAt(0).toUpperCase();

  return (
    <Link to="/profile" className="aw-profile">
      {profile?.profile_picture ? (
        <img className="aw-avatar" src={assetUrl(profile.profile_picture)} alt={name} />
      ) : (
        <div className="aw-avatar">{initial}</div>
      )}
      <div>
        <div className="aw-profile-name">{name || "Your profile"}</div>
        <div className="aw-profile-meta">
          {gender}
          {typeof itemCount === "number" && ` • ${itemCount} items`}
        </div>
      </div>
    </Link>
  );
}

function PageHeader({ title, subtitle, sparkle, itemCount, actions }) {
  return (
    <div className="aw-header">
      <div>
        <h1 className="aw-title">
          {title}
          {sparkle && <span className="sparkle">✦</span>}
        </h1>
        {subtitle && <p className="aw-subtitle">{subtitle}</p>}
      </div>
      <div className="aw-header-actions">
        <ProfileChip itemCount={itemCount} />
        {actions}
      </div>
    </div>
  );
}

export default PageHeader;

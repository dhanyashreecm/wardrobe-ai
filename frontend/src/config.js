// ONE place that knows where the backend is.
//
// Every page used to contain the literal string "http://localhost:5001"
// - 34 of them across the app - so pointing the frontend anywhere else
// meant editing dozens of files and hoping none were missed. Now each
// page imports API_URL from here, and the address itself comes from an
// environment variable, so a different backend needs one line in
// frontend/.env and nothing else.
//
// REACT_APP_ prefix: Create React App only exposes variables that start
// with it, and the value is read at BUILD time, not at run time - so
// after changing frontend/.env you must stop and restart `npm start`
// for the new value to take effect.
//
// The localhost default is what both developers run day to day: React
// on this machine talking to Flask on this machine. That is fine even
// for multi-device use, because what actually has to be shared is the
// DATABASE and the IMAGE STORAGE (both configured in the backend's own
// .env), not the backend process itself.

export const API_URL =
  process.env.REACT_APP_API_URL || "http://localhost:5001";

// Builds a loadable <img src> from whatever the backend stored.
//
// There are two shapes in the database and both must keep working:
//
//   * "https://res.cloudinary.com/..." - anything uploaded since images
//     moved to Cloudinary. Already absolute, and loads from any
//     computer, so it is returned untouched.
//
//   * "/api/uploads/ganga_digital_wardrobe/shirt.jpg" - an older item,
//     served by the backend from that machine's disk. It needs the API
//     address in front of it.
//
// Deciding by looking at the value (rather than by a flag somewhere)
// is what lets a wardrobe hold a mix of old and new items and display
// both correctly, which is exactly the state a part-migrated account
// is in.
export function assetUrl(path) {
  if (!path) {
    return "";
  }

  if (path.startsWith("http://") || path.startsWith("https://")) {
    return path;
  }

  const url = `${API_URL}${path.startsWith("/") ? "" : "/"}${path}`;

  // Images served from the backend's own disk now require a token,
  // because the folder name is derived from the email and was
  // therefore guessable by anyone. An <img> tag cannot send an
  // Authorization header, so the token goes in the query string -
  // the backend accepts it there for this route only.
  //
  // Cloudinary URLs returned above never reach this line: they are
  // absolute, and their paths are hashed rather than guessable.
  const token = localStorage.getItem("token");

  if (token && url.includes("/api/uploads/")) {
    return `${url}${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}`;
  }

  return url;
}

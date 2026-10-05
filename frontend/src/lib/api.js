import axios from "axios";
import { API_URL } from "../config";

// Small helpers so every page sends the JWT the same way. The backend
// always works out WHO the user is from this token - pages never send
// a user id of their own.
function headers() {
  const token = localStorage.getItem("token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function authGet(path, params) {
  const res = await axios.get(`${API_URL}${path}`, { headers: headers(), params });
  return res.data;
}

export async function authPost(path, body) {
  const res = await axios.post(`${API_URL}${path}`, body, { headers: headers() });
  return res.data;
}

export async function authPut(path, body) {
  const res = await axios.put(`${API_URL}${path}`, body, { headers: headers() });
  return res.data;
}

export const OCCASIONS = [
  ["casual", "Casual"],
  ["day_outing", "Day Outing"],
  ["college", "College"],
  ["office", "Office"],
  ["interview", "Interview"],
  ["date", "Date Night"],
  ["party", "Party"],
  ["wedding", "Wedding"],
  ["traditional", "Traditional"],
  ["sports", "Sports / Workout"],
];

// A message the user can act on, from any failed API call. Never a bare
// "failed": says whether the server is down, the session expired, or
// what the backend reported.
export function apiErrorMessage(err, action = "That") {
  if (!err || !err.response) {
    return `${action} failed: can't reach the server. Is the backend running (python -m backend.app)?`;
  }
  const data = err.response.data || {};
  if (err.response.status === 401) {
    return data.message || "Your session has expired - please log in again.";
  }
  if (typeof data === "object") {
    if (data.message) return data.message;
    if (data.error) return data.error;
    if (data.msg) return data.msg;
  }
  return `${action} failed (server error ${err.response.status}).`;
}

export function isAuthError(err) {
  return err?.response?.status === 401 || err?.response?.status === 422;
}

export const occasionLabel = (value) =>
  OCCASIONS.find(([v]) => v === value)?.[1] || value;

// Colour words -> swatch colours for the little dots on cards.
const SWATCH = {
  black: "#1f1f1f", white: "#f7f7f5", grey: "#9a9a9a", gray: "#9a9a9a", charcoal: "#3f3f42",
  silver: "#c8c8cc", beige: "#e3d3bb", cream: "#f3ead6", ivory: "#f6f0e1", tan: "#c9a57d",
  brown: "#7a5236", camel: "#c19a6b", nude: "#e0bfa5", navy: "#23324f", blue: "#4f78b8",
  denim: "#5a7fa8", sky: "#9cc4e4", teal: "#2f8584", turquoise: "#3fb8b2", green: "#4f7a4a",
  olive: "#7b7a3d", mint: "#a8dcc0", sage: "#a3b18a", emerald: "#1f7a55", yellow: "#e9c64a",
  mustard: "#c99a2e", gold: "#c9a24a", orange: "#e0823d", peach: "#f2bf9e", coral: "#ef8a73",
  rust: "#b45a34", red: "#c0392b", maroon: "#6d1f2a", wine: "#6b2436", burgundy: "#6b2436",
  pink: "#e8a1b4", rose: "#d98a96", blush: "#f0c9c5", magenta: "#c2378a", purple: "#7a4f9a",
  lavender: "#b9a6d8", lilac: "#c8a2c8", plum: "#6d3a5c", mauve: "#b98a9e",
};

export function swatch(colour) {
  const words = (colour || "").toLowerCase().split(/[^a-z]+/);
  for (let i = words.length - 1; i >= 0; i -= 1) {
    if (SWATCH[words[i]]) return SWATCH[words[i]];
  }
  return "#d9cfc7";
}

// "Party • Party • Smart" -> "Party • Smart"
export function outfitTags(outfit) {
  const tags = [occasionLabel(outfit.occasion), ...(outfit.style_tags || [])];
  const seen = new Set();
  return tags.filter((tag) => {
    const key = tag.toLowerCase().split(" ")[0];
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).join(" • ");
}

// Style labels mean nothing for shoes and accessories.
export function itemMeta(item) {
  const showStyle = !["Shoes", "Accessories"].includes(item.group);
  // color_display is the everyday word for the measured shade ("rose"
  // becomes "Pink"); the exact shade is still on item.color for search
  // and colour matching.
  const colour = item.color_display || item.color;
  return [item.group, showStyle ? item.style_label : null, colour].filter(Boolean).join(" • ");
}

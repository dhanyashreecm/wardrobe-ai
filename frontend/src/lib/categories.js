import { useEffect, useState } from "react";
import { authGet } from "./api";

// Wardrobe categories come from ONE place: the backend catalogue
// (backend/category_catalog.py), already filtered to the signed-in
// account's saved gender by GET /api/wardrobe/categories. The browser
// keeps no list of its own, so a men's wardrobe can never offer a
// saree and a women's wardrobe can never offer a sherwani.

export const GENDER_REQUIRED =
  "Gender information is required to load wardrobe categories - set Men or Women in your Profile.";

let cache = null;
let pending = null;
let cacheToken = null; // the list belongs to one signed-in account

export function clearCategoryCache() {
  cache = null;
  pending = null;
  cacheToken = null;
}

function currentToken() {
  try { return localStorage.getItem("token"); } catch { return null; }
}

export function useCategories() {
  if (cacheToken !== currentToken()) clearCategoryCache(); // another account signed in
  const [state, setState] = useState(cache || { sections: [], gender: null, error: "" });
  useEffect(() => {
    if (cache) return;
    if (!pending) {
      cacheToken = currentToken();
      pending = authGet("/api/wardrobe/categories")
        .then((data) => {
          if (!data.gender || !(data.sections || []).length) {
            // Never fall back to "every category": without the account's
            // gender the selector stays empty and says why.
            pending = null;
            return { sections: [], gender: null, error: GENDER_REQUIRED };
          }
          cache = { sections: data.sections, gender: data.gender, error: "" };
          return cache;
        })
        .catch((err) => {
          pending = null;
          const status = err?.response?.status;
          return {
            sections: [], gender: null,
            error: status === 409 ? GENDER_REQUIRED
              : err?.response?.data?.message || "Couldn't load your categories - is the backend running?",
          };
        });
    }
    let alive = true;
    pending.then((value) => alive && setState(value));
    return () => { alive = false; };
  }, []);
  return state;
}

export function findCategory(sections, value) {
  for (const section of sections || []) {
    const hit = section.categories.find((c) => c.value === value);
    if (hit) return hit;
  }
  return null;
}

export function hasFlag(sections, value, flag) {
  return (findCategory(sections, value)?.flags || []).includes(flag);
}

// Wardrobe page tabs (item groups the backend assigns for display).
export const WARDROBE_GROUPS = [
  "Tops", "Bottoms", "Dresses", "Sarees", "Ethnic", "Outerwear", "Shoes", "Accessories",
];

export function groupsFor(gender) {
  return gender === "male"
    ? WARDROBE_GROUPS.filter((g) => g !== "Dresses" && g !== "Sarees")
    : WARDROBE_GROUPS;
}

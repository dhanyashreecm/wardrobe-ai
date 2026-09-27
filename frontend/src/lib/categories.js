// The wardrobe categories a user can pick, with who they are for.
// Names map onto the backend's garment taxonomy (outfit_builder.kind_for),
// which is what recommendations actually use.
export const ALL_CATEGORIES = [
  // ---- unisex western ----
  ["Shirt", "Shirt", "unisex"],
  ["T-Shirt", "T-Shirt", "unisex"],
  ["Tank Top", "Tank Top", "unisex"],
  ["Denims", "Jeans / Denims", "unisex"],
  ["Pant", "Trousers / Pants", "unisex"],
  ["Track Pants", "Track Pants", "unisex"],
  ["Shorts", "Shorts", "unisex"],
  ["Jacket", "Jacket", "unisex"],
  ["Blazer", "Blazer", "unisex"],
  ["Coat", "Coat", "unisex"],
  ["Cardigan", "Cardigan / Sweater", "unisex"],
  // ---- footwear ----
  ["Sneakers", "Sneakers", "unisex"],
  ["Footwear", "Shoes (other)", "unisex"],
  ["Sandals", "Sandals", "unisex"],
  ["Boots", "Boots", "unisex"],
  ["Heels", "Heels", "women"],
  ["Flats", "Flats", "women"],
  // ---- accessories ----
  ["Bag", "Bag", "unisex"],
  ["Handbag", "Handbag", "women"],
  ["Watch", "Watch", "unisex"],
  ["Belt", "Belt", "unisex"],
  ["Jewelry", "Jewellery (other)", "unisex"],
  ["Earrings", "Earrings", "unisex"],
  ["Neck Chain", "Necklace / Chain", "unisex"],
  ["Finger Ring", "Ring", "unisex"],
  ["Hand Cuff", "Bracelet / Bangles", "unisex"],
  ["Head Accessory", "Head Accessory", "unisex"],
  // ---- men's ethnic ----
  ["Kurta (Men)", "Kurta (Men)", "men"],
  ["Sherwani", "Sherwani", "men"],
  ["Nehru Jacket", "Nehru Jacket", "men"],
  ["Dhoti Pants", "Dhoti Pants", "men"],
  ["Mojaris (Men)", "Mojaris (Men)", "men"],
  // ---- women's ----
  ["Top", "Top", "women"],
  ["Crop Top", "Crop Top", "women"],
  ["Skirt", "Skirt", "women"],
  ["Leggings", "Leggings", "women"],
  ["Dress", "Dress", "women"],
  ["Gown", "Gown", "women"],
  ["Saree", "Saree", "women"],
  ["Lehenga", "Lehenga", "women"],
  ["Blouse", "Blouse (for saree / lehenga)", "women"],
  ["Kurta (Women)", "Kurta / Kurti (Women)", "women"],
  ["Anarkali", "Anarkali", "women"],
  ["Palazzos", "Palazzos", "women"],
  ["Leggings & Salwars", "Salwar / Churidar", "women"],
  ["Dupatta", "Dupatta", "women"],
  ["Petticoat", "Petticoat", "women"],
  ["Mojaris (Women)", "Mojaris (Women)", "women"],
];

export function categoriesFor(gender) {
  const g = (gender || "").toLowerCase();
  return ALL_CATEGORIES.filter(([, , audience]) => {
    if (audience === "unisex" || !g) return true;
    return audience === (g === "male" ? "men" : "women");
  }).map(([value, label]) => [value, label]);
}

// Material matters for accessories and for warm layers (weather).
export const MATERIAL_CATEGORIES = [
  "Bag", "Handbag", "Watch", "Belt", "Jewelry", "Earrings", "Neck Chain",
  "Finger Ring", "Hand Cuff", "Head Accessory", "Coat", "Jacket", "Cardigan",
];

// The AI knows "saree" but not how formal a particular saree is.
export const STYLING_CATEGORIES = ["Saree", "Lehenga", "Kurta (Men)", "Kurta (Women)", "Anarkali"];

export const WARDROBE_GROUPS = [
  "Tops", "Bottoms", "Dresses", "Sarees", "Ethnic", "Outerwear", "Shoes", "Accessories",
];

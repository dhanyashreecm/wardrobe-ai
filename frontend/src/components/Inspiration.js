import { useEffect, useState } from "react";
import { assetUrl } from "../config";
import { authGet } from "../lib/api";

// STYLE INSPIRATION - reference pictures for the chosen occasion, for
// the account's own gender only (the server decides both). Pictures
// only: no source site, no links. Kept clearly apart from "Your
// Outfits", which always come from the user's own wardrobe.
export default function StyleInspiration({ occasion, label }) {
  const [images, setImages] = useState([]);

  useEffect(() => {
    let alive = true;
    setImages([]);
    authGet("/api/inspiration", { occasion })
      .then((d) => alive && setImages(d.images || []))
      .catch(() => alive && setImages([]));
    return () => { alive = false; };
  }, [occasion]);

  if (!images.length) return null;

  return (
    <section className="aw-inspiration" aria-label="Style inspiration">
      <h2 className="aw-section-title">{label} Inspiration</h2>
      <p className="aw-section-sub">Reference looks for ideas - not items from your wardrobe.</p>
      <div className="aw-inspiration-grid">
        {images.map((img) => (
          <figure key={img.id}>
            <img
              src={assetUrl(img.url)}
              alt={img.caption || `${label} inspiration`}
              loading="lazy"
              onError={(e) => { e.currentTarget.closest("figure").style.display = "none"; }}
            />
            {img.caption && <figcaption>{img.caption}</figcaption>}
          </figure>
        ))}
      </div>
    </section>
  );
}

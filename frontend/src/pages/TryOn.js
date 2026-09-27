import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import Layout from "../components/Layout";
import PageHeader from "../components/PageHeader";
import { Collage, useOutfitActions } from "../components/Outfit";
import { assetUrl } from "../config";
import { authGet, OCCASIONS, outfitTags } from "../lib/api";

/*
 * VIRTUAL TRY-ON (flat-lay board)
 *
 * Lays the outfit's real wardrobe photos out the way it would be worn:
 * layer and top above the bottom (or the one-piece in the centre),
 * shoes below, accessories at the sides. A photo-realistic "on your
 * body" try-on needs an external paid AI service; this project uses
 * the flat-lay board instead, which works offline and never needs a
 * photo of the user.
 */
function Board({ outfit }) {
  const roles = outfit.roles || {};
  const by = (role) => outfit.items.filter((item) => roles[item._id] === role);
  const layer = by("layer");
  const top = by("top");
  const bottom = by("bottom");
  const onePiece = by("one_piece");
  const blouse = by("set_part");
  const shoes = by("footwear");
  const acc = by("accessory");

  const pic = (item, cls = "") => (
    <img key={item._id} className={cls} src={assetUrl(item.image_path)} alt={item.display_name || item.category} />
  );

  return (
    <div className="aw-flatlay">
      <div className="col side">
        {blouse.map((item) => pic(item))}
        {acc.slice(0, 1).map((item) => pic(item))}
        {[...blouse, ...acc.slice(0, 1)].length === 0 && layer.map((item) => pic(item))}
      </div>
      <div className="col center">
        {onePiece.length ? onePiece.map((item) => pic(item, "tall")) : (
          <>
            {top.map((item) => pic(item))}
            {bottom.map((item) => pic(item))}
          </>
        )}
      </div>
      <div className="col side">
        {(blouse.length || acc.length) ? layer.map((item) => pic(item)) : null}
        {acc.slice(1).map((item) => pic(item))}
        {shoes.map((item) => pic(item))}
      </div>
    </div>
  );
}

function TryOn() {
  const location = useLocation();
  const navigate = useNavigate();
  const { act, feedbackOf } = useOutfitActions();
  const [outfit, setOutfit] = useState(location.state?.outfit || null);
  const [occasion, setOccasion] = useState(location.state?.outfit?.occasion || "casual");
  const [choices, setChoices] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!localStorage.getItem("token")) {
      navigate("/login");
      return;
    }
    setLoading(true);
    authGet("/api/ai/recommend", { occasion })
      .then((data) => {
        const list = data.recommendations || [];
        setChoices(list);
        if (!location.state?.outfit || location.state.outfit.occasion !== occasion) {
          setOutfit((current) => (current && current.occasion === occasion ? current : list[0] || null));
        }
      })
      .catch(() => setChoices([]))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [occasion]);

  return (
    <Layout>
      <PageHeader
        title="Virtual Try-On"
        subtitle="See a complete look laid out together, before you get dressed."
      />

      <div className="aw-toolbar" style={{ marginBottom: 18 }}>
        <div className="aw-field">
          Occasion
          <select value={occasion} onChange={(e) => setOccasion(e.target.value)}>
            {OCCASIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>
        {outfit && (
          <>
            <button type="button" className="aw-btn" onClick={() => act(outfit, "like")}>
              {feedbackOf(outfit) === "like" ? "♥ Saved" : "♡ Save this look"}
            </button>
            <button type="button" className="aw-btn aw-btn-soft" onClick={() => window.print()}>
              Print / save as PDF
            </button>
          </>
        )}
      </div>

      {outfit ? (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 2.2fr) minmax(220px, 1fr)", gap: 22 }}>
          <div>
            <Board outfit={outfit} />
            <p className="aw-section-sub" style={{ marginTop: 10 }}>
              Built from your own photos. A photo-realistic try-on on your body needs an external AI
              service, which isn't connected to this app.
            </p>
          </div>
          <div>
            <div className="aw-card" style={{ padding: 18 }}>
              <h3 style={{ fontSize: 22, marginBottom: 2 }}>{outfit.title}</h3>
              <div className="aw-tags">{outfitTags(outfit)}</div>
              <ul className="aw-why">
                {outfit.items.map((item) => <li key={item._id}>{item.display_name || item.category}</li>)}
              </ul>
            </div>
            <h3 style={{ fontSize: 18, margin: "20px 0 10px" }}>Try another look</h3>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              {choices.filter((c) => c.outfit_key !== outfit.outfit_key).slice(0, 6).map((c) => (
                <button
                  key={c.outfit_key}
                  type="button"
                  className="aw-card"
                  style={{ padding: 0, overflow: "hidden", background: "#fff", width: "auto" }}
                  onClick={() => setOutfit(c)}
                >
                  <Collage outfit={c} height={120} />
                  <div style={{ padding: "6px 8px", fontSize: 11.5, color: "#4a3f3a" }}>{c.title}</div>
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="aw-empty">
          <h3>{loading ? "Finding a look…" : "No outfit to try on yet"}</h3>
          {!loading && <p>Add a few more clothes for this occasion, or pick another one.</p>}
        </div>
      )}
    </Layout>
  );
}

export default TryOn;

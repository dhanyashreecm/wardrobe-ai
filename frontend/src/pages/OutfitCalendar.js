import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import Layout from "../components/Layout";
import PageHeader from "../components/PageHeader";
import { API_URL, assetUrl } from "../config";
import { authGet, authPost, apiErrorMessage } from "../lib/api";
import "../styles/aw-v2.css";
import "../styles/studio.css";

// OUTFIT CALENDAR - what you wore each day. Built on the same wear log
// the recommendations already read, so logged outfits aren't suggested
// again straight away.

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function monthKey(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function OutfitCalendar() {
  const navigate = useNavigate();
  const [cursor, setCursor] = useState(() => new Date());
  const [data, setData] = useState({ entries: [], today: "" });
  const [items, setItems] = useState([]);
  const [day, setDay] = useState("");
  const [picked, setPicked] = useState([]);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(() => {
    authGet("/api/calendar", { month: monthKey(cursor) })
      .then((d) => { setData(d); setDay((cur) => cur || d.today); })
      .catch((e) => setError(apiErrorMessage(e, "Loading your calendar")));
  }, [cursor]);

  useEffect(() => {
    if (!localStorage.getItem("token")) { navigate("/login"); return; }
    load();
  }, [load, navigate]);

  useEffect(() => {
    authGet("/api/wardrobe").then((d) => setItems(d.items || [])).catch(() => {});
  }, []);

  const byDay = useMemo(() => {
    const map = {};
    (data.entries || []).forEach((e) => { (map[e.date] = map[e.date] || []).push(e); });
    return map;
  }, [data]);

  const cells = useMemo(() => {
    const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
    const lead = (first.getDay() + 6) % 7;
    const days = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0).getDate();
    const out = Array(lead).fill(null);
    for (let n = 1; n <= days; n += 1) out.push(`${monthKey(cursor)}-${String(n).padStart(2, "0")}`);
    return out;
  }, [cursor]);

  const log = async () => {
    setMsg(""); setError("");
    try {
      const d = await authPost("/api/calendar", { item_ids: picked, date: day });
      setMsg(d.warning || "Logged 📅");
      setPicked([]);
      load();
    } catch (e) { setError(apiErrorMessage(e, "Logging")); }
  };

  const remove = async (id) => {
    try {
      await axios.delete(`${API_URL}/api/calendar/${id}`, { headers: { Authorization: `Bearer ${localStorage.getItem("token")}` } });
      load();
    } catch (e) { setError(apiErrorMessage(e, "Deleting")); }
  };

  const shift = (n) => setCursor((c) => new Date(c.getFullYear(), c.getMonth() + n, 1));
  const future = day && data.today && day > data.today;

  return (
    <Layout>
      <PageHeader title="Outfit Calendar" subtitle="Log what you wore - your stylist won't repeat it too soon." />
      {error && <div className="aw-alert" role="alert">{error}</div>}
      <section className="st-section">
        <div className="st-cal-head">
          <button type="button" className="aw-btn aw-btn-soft aw-btn-sm" onClick={() => shift(-1)}>‹</button>
          <h2>📅 {cursor.toLocaleDateString(undefined, { month: "long", year: "numeric" })}</h2>
          <button type="button" className="aw-btn aw-btn-soft aw-btn-sm" onClick={() => shift(1)}>›</button>
        </div>
        <div className="st-cal">
          {WEEKDAYS.map((w) => <div key={w} className="st-cal-wd">{w}</div>)}
          {cells.map((date, i) => date ? (
            <button type="button" key={date} data-testid="cal-day"
              className={`st-cal-day ${date === day ? "on" : ""} ${date === data.today ? "today" : ""}`}
              onClick={() => setDay(date)}>
              <span>{Number(date.slice(8))}</span>
              {(byDay[date] || []).slice(0, 1).map((e) => e.pieces[0]?.image_path &&
                <img key={e.id} src={assetUrl(e.pieces[0].image_path)} alt="" />)}
              {(byDay[date] || []).length > 1 && <small>+{byDay[date].length - 1}</small>}
            </button>
          ) : <div key={`b${i}`} />)}
        </div>
      </section>

      {day && (
        <section className="st-section">
          <h2>{new Date(`${day}T12:00:00`).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}</h2>
          {(byDay[day] || []).length === 0 ? <p className="st-hint">Nothing logged for this day.</p> : (
            (byDay[day] || []).map((e) => (
              <div key={e.id} className="st-cal-entry">
                <div className="st-mini">{e.pieces.map((p) => <img key={p._id} src={assetUrl(p.image_path)} alt={p.category} title={p.category} />)}</div>
                <span>{e.name || e.pieces.map((p) => p.category).join(" + ")}</span>
                <button type="button" className="aw-link" onClick={() => remove(e.id)}>Remove</button>
              </div>
            ))
          )}
          {!future && (
            <>
              <p className="st-label" style={{ marginTop: 16 }}>Log an outfit for this day - tap the pieces you wore</p>
              <div className="st-pick">
                {items.map((it) => (
                  <button type="button" key={it._id} className={picked.includes(it._id) ? "on" : ""}
                    onClick={() => setPicked((p) => (p.includes(it._id) ? p.filter((x) => x !== it._id) : [...p, it._id]))}>
                    <img src={assetUrl(it.image_path)} alt={it.display_name || it.category} />
                    <small>{it.display_name || it.category}</small>
                  </button>
                ))}
              </div>
              <button type="button" className="aw-btn" disabled={!picked.length} onClick={log}>📅 Log {picked.length || ""} piece{picked.length === 1 ? "" : "s"}</button>
              {msg && <p className="st-note">{msg}</p>}
            </>
          )}
        </section>
      )}
    </Layout>
  );
}

export default OutfitCalendar;

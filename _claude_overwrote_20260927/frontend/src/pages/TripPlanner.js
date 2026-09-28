import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Layout from "../components/Layout";
import PageHeader from "../components/PageHeader";
import { OutfitCard, OutfitDrawer, useOutfitActions } from "../components/Outfit";
import { assetUrl } from "../config";
import { authPost, OCCASIONS } from "../lib/api";

const WEATHER_ICON = (w) => {
  const text = `${w?.condition || ""} ${w?.description || ""}`.toLowerCase();
  if (text.includes("rain") || text.includes("drizzle") || text.includes("thunder")) return "🌧";
  if (text.includes("cloud")) return "⛅";
  if (text.includes("snow")) return "❄️";
  if (text.includes("mist") || text.includes("fog") || text.includes("haze")) return "🌫";
  return "☀️";
};

function shortDay(iso) {
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { weekday: "short", day: "numeric" });
}

function TripPlanner() {
  const navigate = useNavigate();
  const actions = useOutfitActions();
  const [destination, setDestination] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [occasion, setOccasion] = useState("casual");
  const [trip, setTrip] = useState(null);
  const [weather, setWeather] = useState(null);
  const [weatherError, setWeatherError] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(null);

  const handlePlanTrip = async (e) => {
    e.preventDefault();
    if (!localStorage.getItem("token")) {
      navigate("/login");
      return;
    }
    if (!destination || !startDate || !endDate) {
      setError("Please fill in destination, start date and end date.");
      return;
    }
    setLoading(true);
    setError("");
    setTrip(null);
    try {
      const data = await authPost("/api/trips", {
        destination, start_date: startDate, end_date: endDate, occasion,
      });
      setTrip(data.trip);
      setWeather(data.weather || null);
      setWeatherError(data.weather_error || "");
    } catch (err) {
      setError(err.response?.data?.message || "Couldn't plan this trip - is the backend running?");
    } finally {
      setLoading(false);
    }
  };

  const forecastDays = (trip?.schedule || []).filter((d) => d.weather).slice(0, 5);
  const rainyDays = forecastDays.filter((d) => d.weather.is_rainy || (d.weather.rain_chance_pct || 0) >= 40);

  return (
    <Layout>
      <PageHeader title="Trip Planner" subtitle="Weather-based outfit recommendations for your next trip" />

      <form className="aw-card aw-filterbar" onSubmit={handlePlanTrip}>
        <div className="cell" style={{ flex: 2 }}>
          <label>Destination</label>
          <input placeholder="e.g. Goa, India" value={destination} onChange={(e) => setDestination(e.target.value)} />
        </div>
        <div className="cell">
          <label>From</label>
          <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        </div>
        <div className="cell">
          <label>To</label>
          <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        </div>
        <div className="cell">
          <label>Main occasion</label>
          <select value={occasion} onChange={(e) => setOccasion(e.target.value)}>
            {OCCASIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>
        <div className="go">
          <button type="submit" className="aw-btn" disabled={loading}>
            {loading ? "Planning…" : "Get Outfit Suggestions"}
          </button>
        </div>
      </form>

      {error && <div className="aw-note" style={{ marginTop: 16 }}>{error}</div>}

      {trip && (
        <>
          <div className="aw-weather-hero" style={{ marginTop: 24 }}>
            <div>
              <h2>{weather?.city || trip.destination}</h2>
              <div style={{ opacity: 0.9, marginTop: 4, textTransform: "capitalize" }}>
                {weather ? weather.description || weather.condition : "Weather unavailable"}
              </div>
            </div>
            {weather && (
              <div className="temp">
                {WEATHER_ICON(weather)} {Math.round(weather.temp_c)}°C
                <div style={{ fontFamily: "Inter", fontSize: 13, opacity: 0.9, marginTop: 6 }}>
                  feels like {Math.round(weather.feels_like_c ?? weather.temp_c)}°C
                  {weather.humidity_pct != null && ` · humidity ${weather.humidity_pct}%`}
                </div>
              </div>
            )}
            {forecastDays.length > 0 && (
              <div className="aw-forecast">
                {forecastDays.map((d) => (
                  <div key={d.date}>
                    {shortDay(d.date)}
                    <strong>{WEATHER_ICON(d.weather)}</strong>
                    {d.weather.temp_min_c !== undefined && d.weather.temp_max_c !== undefined
                      ? `${Math.round(d.weather.temp_min_c)}°/${Math.round(d.weather.temp_max_c)}°`
                      : `${Math.round(d.weather.temp_c)}°`}
                  </div>
                ))}
              </div>
            )}
          </div>
          {weatherError && <p className="aw-section-sub" style={{ marginTop: 10 }}>Weather couldn't be loaded ({weatherError}) - outfits are planned without it.</p>}
          {rainyDays.length > 0 && (
            <div className="aw-note" style={{ marginTop: 12 }}>
              ☔ Rain likely on {rainyDays.map((d) => shortDay(d.date)).join(", ")} - pack closed footwear or a layer.
            </div>
          )}

          <div className="aw-row-head">
            <h2 className="aw-section-title">Recommended Outfits for {trip.destination}</h2>
          </div>
          {(trip.looks || []).length ? (
            <div className="aw-outfit-grid">
              {trip.looks.map((look) => (
                <OutfitCard key={look.outfit_key} outfit={look} onOpen={setOpen} actions={actions} />
              ))}
            </div>
          ) : (
            <div className="aw-empty">
              <h3>Not enough pieces for trip looks yet</h3>
              <p>Add a few more clothes and they'll appear here.</p>
            </div>
          )}

          <h2 className="aw-section-title">Day by day · {trip.duration_days} day{trip.duration_days > 1 ? "s" : ""}</h2>
          {trip.schedule.map((day) => (
            <div key={day.day_number} className="aw-card aw-day">
              <div>
                <strong>Day {day.day_number}</strong>
                <div className="aw-tags">{shortDay(day.date)}</div>
                {day.weather && (
                  <div className="aw-tags">
                    {WEATHER_ICON(day.weather)} {Math.round(day.weather.temp_c)}°C
                    {day.weather_estimated ? " (est.)" : ""}
                  </div>
                )}
              </div>
              <div className="aw-day-pieces">
                {day.outfit ? (
                  day.outfit.items.map((item) => (
                    <div key={item._id} style={{ textAlign: "center" }}>
                      <img src={assetUrl(item.image_path)} alt={item.category} />
                      <div className="aw-tags" style={{ fontSize: 11 }}>{item.color} {item.category}</div>
                    </div>
                  ))
                ) : (
                  <span className="aw-tags">No suitable outfit for this day.</span>
                )}
              </div>
            </div>
          ))}

          <h2 className="aw-section-title">Packing checklist</h2>
          <div className="aw-card" style={{ padding: "8px 20px" }}>
            {trip.packing_list.map((item) => (
              <label key={item._id} style={{ display: "flex", gap: 10, alignItems: "center", padding: "10px 0", borderBottom: "1px solid #f0e6dd", fontSize: 14 }}>
                <input type="checkbox" style={{ width: "auto", margin: 0 }} />
                {item.color ? `${item.color} ` : ""}{item.category}
              </label>
            ))}
          </div>
        </>
      )}

      {!trip && !loading && (
        <div className="aw-panel" style={{ marginTop: 24, display: "flex", alignItems: "center", gap: 18 }}>
          <span style={{ fontSize: 40 }}>🌴</span>
          <div>
            <strong className="aw-serif" style={{ fontSize: 20 }}>Let your wardrobe take you places</strong>
            <p className="aw-section-sub" style={{ margin: "4px 0 0" }}>
              Weather + your style + your wardrobe = perfect travel outfits.
            </p>
          </div>
        </div>
      )}

      <OutfitDrawer outfit={open} onClose={() => setOpen(null)} actions={actions} />
    </Layout>
  );
}

export default TripPlanner;

import { useState } from "react";
import axios from "axios";
import Layout from "../components/Layout";
import "../App.css";

function TripPlanner() {
  const [destination, setDestination] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [occasion, setOccasion] = useState("casual");

  const [trip, setTrip] = useState(null);
  const [weather, setWeather] = useState(null);
  const [weatherError, setWeatherError] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const token = localStorage.getItem("token");

  const handlePlanTrip = async (e) => {
    e.preventDefault();

    if (!destination || !startDate || !endDate) {
      alert("Please fill in destination, start date and end date.");
      return;
    }

    setLoading(true);
    setError("");
    setTrip(null);
    setWeather(null);
    setWeatherError("");

    try {
      const res = await axios.post(
        "http://localhost:5001/api/trips",
        {
          destination,
          start_date: startDate,
          end_date: endDate,
          occasion,
        },
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

      if (res.data.success) {
        setTrip(res.data.trip);
        setWeather(res.data.weather || null);
        setWeatherError(res.data.weather_error || "");
      } else {
        setError(
          res.data.message || "Could not create trip plan."
        );
      }
    } catch (err) {
      console.error("Trip planning failed:", err);

      setError(
        err.response?.data?.message ||
          "Could not create trip plan."
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <Layout>
      <div className="page-header">
        <div>
          <h1 className="page-title">Trip Planner</h1>
          <p className="page-subtitle">
            Plan day-by-day outfits and a packing list from your
            own wardrobe.
          </p>
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "300px 1fr",
          gap: "28px",
          alignItems: "start",
        }}
      >
        <div className="side-panel">
          <form onSubmit={handlePlanTrip}>
            <label className="field-label">Destination</label>
            <input
              placeholder="e.g. Bengaluru"
              value={destination}
              onChange={(e) => setDestination(e.target.value)}
            />

            <label className="field-label">Start date</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />

            <label className="field-label">End date</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />

            <label className="field-label">Trip style</label>

            <select
              value={occasion}
              onChange={(e) => setOccasion(e.target.value)}
            >
              <option value="casual">Casual</option>
              <option value="formal">Formal</option>
              <option value="party">Party</option>
              <option value="traditional">Traditional</option>
            </select>

            <button
              type="submit"
              className="btn btn-primary"
              disabled={loading}
              style={{ width: "100%" }}
            >
              {loading ? "Planning..." : "Plan Trip"}
            </button>
          </form>

          {error && <p className="error">{error}</p>}

          {!loading && weather && (
            <p
              style={{
                marginTop: "15px",
                color: "#c1694f",
                fontSize: "13px",
              }}
            >
              {weather.city}: {weather.temp_c}°C, {weather.description}
            </p>
          )}

          {!loading && weatherError && (
            <p
              style={{
                marginTop: "15px",
                color: "#8a7a6d",
                fontSize: "12px",
              }}
            >
              Weather not applied: {weatherError}
            </p>
          )}
        </div>

        <div>
          {/* TRIP RESULTS */}

          {!loading && trip && (
            <div>
              <h2 className="section-title" style={{ marginTop: 0 }}>
                {trip.destination} · {trip.duration_days} day
                {trip.duration_days > 1 ? "s" : ""}
              </h2>

              {/* DAY-BY-DAY SCHEDULE */}

              {trip.schedule.map((day) => (
                <div
                  key={day.day_number}
                  className="panel"
                  style={{ marginTop: "16px" }}
                >
                  <h3>
                    Day {day.day_number} — {day.date}
                  </h3>

                  <div
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      gap: "14px",
                    }}
                  >
                    {day.outfit.items.map((item, itemIndex) => (
                      <div
                        key={itemIndex}
                        className="day-item"
                      >
                        {item.image_path && (
                          <img
                            src={`http://localhost:5001${item.image_path}`}
                            alt={item.category || "Clothing item"}
                            onError={(e) => {
                              e.currentTarget.style.display = "none";
                            }}
                          />
                        )}
                        <p className="item-title">{item.category}</p>
                        {item.color && (
                          <p className="item-subtitle">{item.color}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ))}

              {/* PACKING CHECKLIST */}

              <h2 className="section-title">Packing checklist</h2>

              <ul className="checklist">
                {trip.packing_list.map((item) => (
                  <li key={item._id}>
                    {item.category}
                    {item.color ? ` — ${item.color}` : ""}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {!loading && !error && !trip && (
            <p style={{ color: "#8a7a6d" }}>
              Fill in your trip details and click "Plan Trip".
            </p>
          )}
        </div>
      </div>
    </Layout>
  );
}

export default TripPlanner;

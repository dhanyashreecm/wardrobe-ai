import { useEffect, useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import "../App.css";

function Dashboard() {
  const [message, setMessage] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      navigate("/login");
      return;
    }
    axios.get("http://localhost:5001/api/dashboard", {
      headers: { Authorization: `Bearer ${token}` }
    }).then(res => setMessage(res.data.message))
      .catch(() => navigate("/login"));
  }, [navigate]);

  const handleLogout = () => {
    localStorage.removeItem("token");
    navigate("/login");
  };

  return (
    <div className="page-container">
      <div className="auth-card">
        <div className="logo">WardrobeAI</div>
        <h2>Dashboard</h2>
        <p style={{marginBottom: "20px", color: "#555"}}>{message}</p>
        <button onClick={handleLogout}>Logout</button>
      </div>
    </div>
  );
}

export default Dashboard;

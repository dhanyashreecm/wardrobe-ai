import { useNavigate } from "react-router-dom";
import "../App.css";

const categories = [
  { name: "Shirts", emoji: "👕" },
  { name: "Pants", emoji: "👖" },
  { name: "Dresses", emoji: "👗" },
  { name: "Shoes", emoji: "👟" },
  { name: "Accessories", emoji: "👜" },
];

function Categories() {
  const navigate = useNavigate();

  const handleLogout = () => {
    localStorage.removeItem("token");
    navigate("/login");
  };

  return (
    <div className="page-container">
      <div className="auth-card" style={{maxWidth: "480px"}}>
        <div className="logo">👗 WardrobeAI</div>
        <h2>Choose a Category</h2>
        <div style={{
          display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginTop: "20px"
        }}>
          {categories.map(cat => (
            <button
              key={cat.name}
              style={{
                background: "white", color: "#4a3f8a", border: "2px solid #eee",
                borderRadius: "12px", padding: "18px 10px", fontSize: "15px", fontWeight: "600"
              }}
              onClick={() => alert(cat.name + " selected")}
            >
              <div style={{fontSize: "26px", marginBottom: "6px"}}>{cat.emoji}</div>
              {cat.name}
            </button>
          ))}
        </div>
        <button onClick={handleLogout} style={{marginTop: "20px"}}>Logout</button>
      </div>
    </div>
  );
}

export default Categories;
